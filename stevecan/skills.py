"""Biblioteca de skills de GitHub para los agentes locales.
  python -m stevecan.skills sync              # clona/actualiza skills-sources.txt en data/skills-lib e indexa
  python -m stevecan.skills search "<texto>"  # busca skills por contenido
  python -m stevecan.skills enable <nombre>   # copia un skill a .claude/skills/ (Claude Code lo carga)
  python -m stevecan.skills stats
"""
import hashlib
import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from . import config, memory

log = logging.getLogger("skills")
ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "skills-sources.txt"


def _sources():
    out = []
    if SOURCES.exists():
        for line in SOURCES.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(line.split()[0])
    return out


def _frontmatter(text: str):
    m = re.match(r"^---\s*\n(.*?)\n---", text, flags=re.S)
    name = desc = ""
    if m:
        lines = m.group(1).splitlines()
        for i, line in enumerate(lines):
            if line.lower().startswith("name:"):
                name = line.split(":", 1)[1].strip().strip("'\"")
            elif line.lower().startswith("description:"):
                desc = line.split(":", 1)[1].strip().strip("'\"")
                if desc in (">", ">-", "|", "|-", ""):
                    folded = []
                    for nxt in lines[i + 1:]:
                        if nxt.startswith((" ", "\t")):
                            folded.append(nxt.strip())
                        else:
                            break
                    desc = " ".join(folded)
    return name, desc


def sync(update: bool = True) -> dict:
    config.SKILLS_LIB_DIR.mkdir(parents=True, exist_ok=True)
    cloned = updated = 0
    for repo in _sources():
        dest = config.SKILLS_LIB_DIR / repo.replace("/", "__")
        if dest.is_dir():
            if update:
                subprocess.run(["git", "-C", str(dest), "pull", "-q", "--ff-only"], capture_output=True, timeout=600)
                updated += 1
        else:
            r = subprocess.run(["git", "clone", "-q", "--depth", "1", f"https://github.com/{repo}", str(dest)],
                               capture_output=True, text=True, timeout=900, env={"GIT_LFS_SKIP_SMUDGE": "1", "PATH": "/usr/bin:/bin:/usr/local/bin"})
            if r.returncode == 0:
                cloned += 1
            else:
                log.warning("no se pudo clonar %s: %s", repo, r.stderr.strip()[-300:])
    res = index() | {"cloned": cloned, "updated": updated}
    log.info("%s", res)
    return res


def _skill_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        if "SKILL.md" in filenames:
            yield Path(dirpath) / "SKILL.md"


def index() -> dict:
    n = 0
    seen = set()
    for f in _skill_files(config.SKILLS_LIB_DIR):
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = f.relative_to(config.SKILLS_LIB_DIR)
        source = rel.parts[0].replace("__", "/")
        name, desc = _frontmatter(text)
        name = name or f.parent.name
        key = f"{source}:{rel.parent.as_posix()}"
        seen.add(key)
        sha = hashlib.sha256(text.encode()).hexdigest()
        if memory.skill_sha(key) != sha:
            memory.upsert_skill(key, name, source, str(f.parent), desc, text[:60000], sha)
            n += 1
    memory.remove_skills_not_in(seen)
    return {"skills": len(seen), "reindexed": n}


def search(query: str, limit: int = 8):
    return memory.search_skills(query, limit)


def enable(name: str) -> Path:
    rows = memory.rows("SELECT * FROM skills_lib WHERE name=? ORDER BY key LIMIT 5", (name,))
    if not rows:
        raise SystemExit(f"skill '{name}' no encontrado; usa: python -m stevecan.skills search \"{name}\"")
    if len(rows) > 1:
        log.info("varios skills con ese nombre; se usa %s", rows[0]["key"])
    src = Path(rows[0]["path"])
    dst = ROOT / ".claude" / "skills" / name
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    log.info("habilitado %s -> %s", rows[0]["key"], dst)
    return dst


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    if a[0] == "sync":
        print(sync())
    elif a[0] == "search" and len(a) > 1:
        for r in search(" ".join(a[1:])):
            print(f"{r['name']:<40} {r['source']:<32} {r['description'][:90]}")
    elif a[0] == "enable" and len(a) > 1:
        print(enable(a[1]))
    elif a[0] == "stats":
        print(memory.rows("SELECT source, COUNT(*) n FROM skills_lib GROUP BY source ORDER BY n DESC"))
    else:
        sys.exit(__doc__)
