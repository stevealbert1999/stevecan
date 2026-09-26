"""Mejora proyectos propios sin destrozarlos: backup verificado -> rama/worktree aislado -> cambio ->
sintaxis + tests -> commit. Si algo falla, no toca tu rama. Con AUTO_APPLY=1 fusiona en tu rama tras pasar tests.
CLI:
  python -m stevecan.developer /ruta/proyecto "instrucción"        # encola para el agente developer (24/7)
  python -m stevecan.developer /ruta/proyecto "instrucción" --now  # lo ejecuta ahora mismo (necesita el modelo)
"""
import asyncio
import json
import logging
import shutil
import sys
import time
from pathlib import Path
from . import config, llm, memory, projects
from .ingest import index_dir

log = logging.getLogger("developer")


def _git(project, *args, timeout=300):
    return projects._sh(["git", *args], project, timeout)


def ensure_git(project: Path) -> str:
    """Garantiza repo git con al menos un commit. Devuelve la rama actual."""
    if not projects.is_git(project):
        _git(project, "init", "-q")
        _git(project, "-c", "user.name=stevecan", "-c", "user.email=agents@stevecan.local", "add", "-A")
        _git(project, "-c", "user.name=stevecan", "-c", "user.email=agents@stevecan.local",
             "commit", "-q", "-m", "estado inicial (creado por stevecan antes de mejorar)", "--allow-empty")
    if _git(project, "rev-parse", "--verify", "HEAD")[0] != 0:
        _git(project, "-c", "user.name=stevecan", "-c", "user.email=agents@stevecan.local", "add", "-A")
        _git(project, "-c", "user.name=stevecan", "-c", "user.email=agents@stevecan.local",
             "commit", "-q", "-m", "estado inicial (creado por stevecan antes de mejorar)", "--allow-empty")
    code, out, _ = _git(project, "rev-parse", "--abbrev-ref", "HEAD")
    return out.strip() or "HEAD"


def _context(project: Path, instruction: str) -> str:
    repo = project.name
    hits = memory.search_code(instruction, 8)
    hits = [h for h in hits if h["repo"] == repo] or hits[:4]
    tree = "\n".join(sorted(r["path"] for r in memory.rows("SELECT path FROM code_files WHERE repo=? LIMIT 400", (repo,))))
    summaries = "\n".join(f"- {r['path']}: {r['summary'][:200]}" for r in memory.rows(
        "SELECT path, summary FROM code_files WHERE repo=? AND summary IS NOT NULL LIMIT 40", (repo,)))
    code = "\n\n".join(f"### {h['path']} (líneas {h['start_line']}-{h['end_line']})\n```\n{h['content'][:2500]}\n```" for h in hits)
    skills = "\n\n".join(f"### skill {s['name']} ({s['source']})\n{s['content'][:1500]}" for s in memory.search_skills(instruction, 2))
    return f"Árbol:\n{tree[:6000]}\n\nResúmenes:\n{summaries[:4000]}\n\nCódigo relevante:\n{code}\n\nSkills aplicables:\n{skills}"


async def propose_goal(project: Path) -> str | None:
    """Con AUTO_IMPROVE: el modelo elige la mejora más valiosa y pequeña para el proyecto."""
    done = "\n".join(p.read_text(encoding="utf-8")[:300] for p in sorted(config.IMPROVEMENTS_DIR.glob(f"{project.name}-*.md"))[-8:])
    data = await llm.ask_json(
        "Eres el ingeniero responsable de este proyecto. Elige UNA mejora concreta, pequeña y segura "
        "(bug real, robustez, rendimiento, tests que faltan, legibilidad), no un rediseño. Sin inventar ficheros.",
        f"{_context(project, project.name)}\n\nMejoras ya hechas:\n{done}\n"
        'Devuelve {"goal":"instrucción precisa de 1-3 frases con los ficheros implicados"}', max_tokens=500)
    return (data or {}).get("goal")


async def improve(project: Path, instruction: str, agent: str = "developer") -> dict:
    project = project.resolve()
    if not project.is_dir():
        return {"ok": False, "reason": f"no existe {project}"}
    ts = time.strftime("%Y%m%d-%H%M%S")
    report = {"project": str(project), "instruction": instruction, "ts": ts, "ok": False}
    # 1) backup real y verificado
    archive = projects.backup(project, reason=f"pre-improve:{instruction[:40]}")
    report["backup"] = str(archive)
    # 2) repo git + rama aislada en un worktree (tu directorio de trabajo no se toca)
    base_branch = ensure_git(project)
    branch = f"stevecan/{ts}"
    wt = config.WORKTREES_DIR / f"{project.name}-{ts}"
    code, _, err = _git(project, "worktree", "add", "-q", "-b", branch, str(wt), "HEAD")
    if code != 0:
        report["reason"] = f"worktree: {err}"
        return _finish(report)
    try:
        index_dir(project)
        test_cmd = projects.detect_test_cmd(wt)
        baseline = await projects.run_tests(wt, test_cmd) if test_cmd else None
        report["test_cmd"] = test_cmd
        report["baseline_ok"] = baseline["ok"] if baseline else None
        feedback = ""
        for attempt in range(1, 4):
            data = await llm.ask_json(
                "Eres un ingeniero senior que mejora un proyecto existente con cambios pequeños, seguros y completos. "
                "Devuelve el contenido COMPLETO de cada fichero que cambies (máximo 4 ficheros), respetando el estilo "
                "del proyecto. No borres funcionalidad. No inventes APIs.",
                f"Proyecto: {project.name}\nObjetivo: {instruction}\n\n{_context(project, instruction)}\n{feedback}\n"
                'Devuelve {"summary":"qué y por qué","files":[{"path":"ruta/relativa","content":"contenido completo"}]}',
                max_tokens=6000)
            files = [f for f in (data or {}).get("files", []) if isinstance(f, dict) and f.get("path") and "content" in f]
            if not files:
                feedback = "La respuesta anterior no contenía ficheros válidos."
                continue
            changed = []
            for f in files[:4]:
                rel = Path(f["path"])
                if rel.is_absolute() or ".." in rel.parts:
                    continue
                dst = wt / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(f["content"], encoding="utf-8")
                changed.append(rel.as_posix())
            _, stat, _ = _git(wt, "diff", "--shortstat")
            lines = sum(int(x) for x in stat.replace(",", "").split() if x.isdigit()) if stat.strip() else 0
            if lines > config.MAX_CHANGE_LINES:
                _git(wt, "checkout", "-q", "--", "."); _git(wt, "clean", "-qfd")
                feedback = f"El cambio era demasiado grande ({lines} líneas > {config.MAX_CHANGE_LINES}). Hazlo más pequeño."
                continue
            errors = projects.syntax_check(wt, changed)
            if errors:
                feedback = "Errores de sintaxis:\n" + "\n".join(errors)
                continue
            result = await projects.run_tests(wt, test_cmd) if test_cmd else {"ok": True, "output": "sin tests; sintaxis OK"}
            if not result["ok"] and (baseline is None or baseline["ok"]):
                feedback = f"Los tests fallan tras el cambio (intento {attempt}):\n{result['output'][-2500:]}\nCorrígelo sin eliminar tests."
                continue
            report.update({"ok": True, "summary": (data or {}).get("summary", ""), "files": changed,
                           "tests": result["output"][-1500:], "attempts": attempt})
            break
        if not report["ok"]:
            report["reason"] = feedback[-1500:] or "sin cambio válido"
            return _finish(report, project, wt, branch, keep_branch=False)
        # 3) commit en la rama aislada
        _git(wt, "add", "-A")
        _git(wt, "-c", "user.name=stevecan-developer", "-c", "user.email=agents@stevecan.local",
             "commit", "-q", "-m", f"mejora: {instruction[:70]}\n\n{report.get('summary', '')}\n\nBackup: {archive}")
        report["branch"] = branch
        # 4) fusión en tu rama solo si AUTO_APPLY=1 y el árbol de trabajo está limpio
        if config.AUTO_APPLY and base_branch != "HEAD":
            _, status, _ = _git(project, "status", "--porcelain")
            if status.strip():
                report["applied"] = False
                report["note"] = "árbol de trabajo con cambios sin confirmar: no se fusiona; revisa la rama"
            else:
                code, _, err = _git(project, "merge", "-q", "--no-edit", branch)
                report["applied"] = code == 0
                if code != 0:
                    _git(project, "merge", "--abort")
                    report["note"] = f"conflicto al fusionar: {err[-300:]}"
        else:
            report["applied"] = False
        return _finish(report, project, wt, branch, keep_branch=True)
    except Exception as e:  # noqa: BLE001
        report["reason"] = repr(e)
        return _finish(report, project, wt, branch, keep_branch=False)


def _finish(report, project=None, wt=None, branch=None, keep_branch=True):
    if wt is not None and project is not None:
        _git(project, "worktree", "remove", "--force", str(wt))
        shutil.rmtree(wt, ignore_errors=True)
        if not keep_branch and branch:
            _git(project, "branch", "-D", branch)
    name = f"{Path(report['project']).name}-{report['ts']}.md"
    body = [f"# Mejora {report['ts']} — {Path(report['project']).name}", "",
            f"**Objetivo:** {report['instruction']}", f"**Resultado:** {'OK' if report['ok'] else 'DESCARTADA'}",
            f"**Backup:** `{report.get('backup', '')}`", f"**Rama:** `{report.get('branch', '-')}`",
            f"**Aplicada en tu rama:** {report.get('applied', False)}", f"**Tests:** `{report.get('test_cmd')}` baseline={report.get('baseline_ok')}", ""]
    if report["ok"]:
        body += [report.get("summary", ""), "", "Ficheros: " + ", ".join(report.get("files", [])), "", "```", report.get("tests", ""), "```"]
    else:
        body += ["Motivo: " + str(report.get("reason", ""))]
    if report.get("note"):
        body += ["", "Nota: " + report["note"]]
    (config.IMPROVEMENTS_DIR / name).write_text("\n".join(body) + "\n", encoding="utf-8")
    memory.log_event("developer", "improve", json.dumps(report, ensure_ascii=False, default=str)[:2000])
    log.info("%s: %s", "OK" if report["ok"] else "DESCARTADA", report["instruction"][:80])
    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    args = [a for a in sys.argv[1:] if a != "--now"]
    if len(args) < 2:
        sys.exit(__doc__)
    path, instr = Path(args[0]), " ".join(args[1:])
    if "--now" in sys.argv:
        r = asyncio.run(improve(path, instr, agent="cli"))
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
        sys.exit(0 if r["ok"] else 1)
    tid = memory.add_task("improve", {"project": str(path.resolve()), "instruction": instr}, "cli", priority=1)
    print(f"tarea {tid} encolada para el agente developer: {path} -> {instr}")
