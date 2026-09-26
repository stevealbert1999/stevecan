"""Proyectos propios: copias de seguridad reales (verificadas y restaurables), detección de tests y checks.
CLI:
  python -m stevecan.projects backup  /ruta/proyecto
  python -m stevecan.projects restore /ruta/backup.tar.gz [/ruta/destino]
  python -m stevecan.projects list    [/ruta/proyecto]
"""
import asyncio
import json
import logging
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path
from . import config

log = logging.getLogger("projects")
EXCLUDE_DIRS = {"node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".gradle",
                "build", "dist", "target", ".next", ".cache", ".tox", "Pods", "DerivedData"}


def _meta_path(archive: Path) -> Path:
    return archive.with_name(archive.name.removesuffix(".tar.gz") + ".json")


def _archive_path(meta: Path) -> Path:
    return meta.with_name(meta.name.removesuffix(".json") + ".tar.gz")


def _sh(cmd, cwd, timeout=600):
    p = subprocess.run(cmd, cwd=str(cwd), shell=isinstance(cmd, str), capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout or "")[-8000:], (p.stderr or "")[-4000:]


def is_git(project: Path) -> bool:
    return _sh(["git", "rev-parse", "--is-inside-work-tree"], project)[0] == 0


# ---- copias de seguridad -------------------------------------------------
def backup(project: Path, reason: str = "manual") -> Path:
    """tar.gz completo del proyecto (sin caches regenerables), verificado tras escribirse.
    Si es repo git, además crea el tag backup/<ts>. Devuelve la ruta del archivo."""
    project = project.resolve()
    if not project.is_dir():
        raise FileNotFoundError(project)
    ts = time.strftime("%Y%m%d-%H%M%S")
    dest_dir = config.BACKUPS_DIR / project.name
    dest_dir.mkdir(parents=True, exist_ok=True)
    archive = dest_dir / f"{ts}.tar.gz"
    n = 1
    while archive.exists():
        n += 1
        archive = dest_dir / f"{ts}-{n}.tar.gz"

    def _filter(ti: tarfile.TarInfo):
        parts = Path(ti.name).parts
        return None if any(p in EXCLUDE_DIRS for p in parts[1:]) else ti

    with tarfile.open(archive, "w:gz") as tar:
        tar.add(project, arcname=project.name, filter=_filter)
    # Verificación real: el archivo se abre y lista completo
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
    files = sum(1 for m in members if m.isfile())
    if files == 0:
        archive.unlink()
        raise RuntimeError(f"backup vacío de {project}")
    meta = {"project": str(project), "created": ts, "reason": reason, "files": files,
            "bytes": archive.stat().st_size, "git_tag": None}
    if is_git(project):
        tag = f"backup/{ts}"
        if _sh(["git", "tag", "-f", tag], project)[0] == 0:
            meta["git_tag"] = tag
    _meta_path(archive).write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    _rotate(dest_dir)
    log.info("backup %s: %d ficheros, %.1f MB", archive.name, files, meta["bytes"] / 1e6)
    return archive


def _rotate(dest_dir: Path):
    archives = sorted(dest_dir.glob("*.tar.gz"))
    for old in archives[:-config.BACKUP_KEEP]:
        old.unlink(missing_ok=True)
        _meta_path(old).unlink(missing_ok=True)


def restore(archive: Path, dest: Path | None = None) -> Path:
    """Restaura un backup. Antes hace un backup de seguridad del estado actual del destino."""
    archive = Path(archive).resolve()
    meta = json.loads(_meta_path(archive).read_text()) if _meta_path(archive).exists() else {}
    dest = Path(dest or meta.get("project") or ".").resolve()
    with tarfile.open(archive, "r:gz") as tar:
        top = {Path(m.name).parts[0] for m in tar.getmembers()}
        if len(top) != 1:
            raise RuntimeError("archivo con varias raíces")
        root = top.pop()
        for m in tar.getmembers():
            if m.name.startswith("/") or ".." in Path(m.name).parts:
                raise RuntimeError(f"ruta insegura en el archivo: {m.name}")
        if dest.exists() and any(dest.iterdir()):
            backup(dest, reason="pre-restore")
        tmp = dest.parent / f".{dest.name}.restore-{int(time.time())}"
        tar.extractall(tmp)
        extracted = tmp / root
        if dest.exists():
            trash = dest.parent / f".{dest.name}.replaced-{int(time.time())}"
            dest.rename(trash)
        else:
            trash = None
        extracted.rename(dest)
        shutil.rmtree(tmp, ignore_errors=True)
        if trash is not None:
            shutil.rmtree(trash, ignore_errors=True)
    log.info("restaurado %s en %s", archive.name, dest)
    return dest


def list_backups(project: Path | None = None):
    base = config.BACKUPS_DIR / project.resolve().name if project else config.BACKUPS_DIR
    out = []
    for j in sorted(base.rglob("*.json")):
        try:
            out.append(json.loads(j.read_text()) | {"archive": str(_archive_path(j))})
        except json.JSONDecodeError:
            pass
    return out


# ---- detección de tests y comprobaciones --------------------------------
def detect_test_cmd(project: Path) -> str | None:
    p = project
    if (p / "package.json").exists():
        try:
            scripts = json.loads((p / "package.json").read_text()).get("scripts", {})
            if "test" in scripts and "no test specified" not in scripts["test"]:
                return "npm test --silent"
        except json.JSONDecodeError:
            pass
    if (p / "pyproject.toml").exists() or (p / "pytest.ini").exists() or (p / "tests").is_dir() or list(p.glob("test_*.py")):
        return f"{sys.executable} -m pytest -q -x --no-header -p no:cacheprovider"
    if (p / "gradlew").exists():
        return "./gradlew test --quiet"
    if (p / "pom.xml").exists():
        return "mvn -q test"
    if (p / "Cargo.toml").exists():
        return "cargo test --quiet"
    if (p / "go.mod").exists():
        return "go test ./..."
    if (p / "Makefile").exists() and "test:" in (p / "Makefile").read_text(errors="ignore"):
        return "make test"
    return None


def syntax_check(project: Path, files: list[str]) -> list[str]:
    """Comprueba sintaxis de los ficheros cambiados. Devuelve lista de errores."""
    errors = []
    for rel in files:
        f = project / rel
        if not f.exists():
            continue
        ext = f.suffix.lower()
        if ext == ".py":
            code, _, err = _sh([sys.executable, "-m", "py_compile", str(f)], project, 60)
        elif ext in (".js", ".mjs", ".cjs") and shutil.which("node"):
            code, _, err = _sh(["node", "--check", str(f)], project, 60)
        elif ext == ".json":
            try:
                json.loads(f.read_text(encoding="utf-8")); code, err = 0, ""
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                code, err = 1, str(e)
        elif ext in (".sh", ".bash") and shutil.which("bash"):
            code, _, err = _sh(["bash", "-n", str(f)], project, 60)
        elif ext in (".yml", ".yaml"):
            try:
                import yaml  # type: ignore
                yaml.safe_load(f.read_text(encoding="utf-8")); code, err = 0, ""
            except ImportError:
                code, err = 0, ""
            except Exception as e:  # noqa: BLE001
                code, err = 1, str(e)
        else:
            continue
        if code != 0:
            errors.append(f"{rel}: {err.strip()[-500:]}")
    return errors


async def run_tests(project: Path, cmd: str, timeout: int = 900) -> dict:
    proc = await asyncio.create_subprocess_shell(cmd, cwd=str(project),
                                                 stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return {"ok": False, "output": f"timeout {timeout}s", "cmd": cmd}
    return {"ok": proc.returncode == 0, "output": (out.decode(errors="ignore") + err.decode(errors="ignore"))[-6000:], "cmd": cmd}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    if args[0] == "backup" and len(args) >= 2:
        print(backup(Path(args[1])))
    elif args[0] == "restore" and len(args) >= 2:
        print(restore(Path(args[1]), Path(args[2]) if len(args) > 2 else None))
    elif args[0] == "list":
        for b in list_backups(Path(args[1]) if len(args) > 1 else None):
            print(f"{b['created']}  {b['files']:>6} ficheros  {b['bytes']/1e6:7.1f} MB  {b['reason']:<12} {b['archive']}")
    else:
        sys.exit(__doc__)
