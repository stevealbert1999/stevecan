"""Documentación y código de referencia oficial por lenguaje (docs-sources.txt) -> data/docs-lib -> memoria.
  python -m stevecan.docs sync     # clona (sparse, shallow) o actualiza e indexa todo
  python -m stevecan.docs stats
"""
import logging
import subprocess
import sys
from pathlib import Path
from . import config, memory
from .ingest import index_dir

log = logging.getLogger("docs")
ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "docs-sources.txt"
GIT_ENV = {"GIT_LFS_SKIP_SMUDGE": "1", "PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(Path.home())}


def _sources():
    out = []
    if SOURCES.exists():
        for line in SOURCES.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            name, repo = parts[0], parts[1]
            paths = parts[2].split(",") if len(parts) > 2 else []
            out.append((name, repo, paths))
    return out


def _git(args, cwd=None, timeout=1800):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout, env=GIT_ENV)


def sync_one(name: str, repo: str, paths: list[str]) -> dict:
    dest = config.DOCS_LIB_DIR / name
    url = f"https://github.com/{repo}"
    if (dest / ".git").is_dir():
        r = _git(["pull", "-q", "--ff-only", "--depth", "1"], cwd=dest)
        status = "actualizado" if r.returncode == 0 else f"pull falló: {r.stderr.strip()[-200:]}"
    else:
        if paths:
            r = _git(["clone", "-q", "--depth", "1", "--filter=blob:none", "--sparse", url, str(dest)])
            if r.returncode == 0:
                r = _git(["sparse-checkout", "set", "--no-cone", *paths], cwd=dest)
        else:
            r = _git(["clone", "-q", "--depth", "1", url, str(dest)])
        status = "clonado" if r.returncode == 0 else f"clone falló: {r.stderr.strip()[-200:]}"
    res = {"name": name, "source": repo, "status": status}
    if (dest / ".git").is_dir():
        res |= {k: v for k, v in index_dir(dest, repo_name=f"docs:{name}").items() if k != "repo"}
    log.info("%s", res)
    return res


def sync() -> list[dict]:
    config.DOCS_LIB_DIR.mkdir(parents=True, exist_ok=True)
    return [sync_one(*src) for src in _sources()]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    a = sys.argv[1:]
    if a and a[0] == "sync":
        for r in sync():
            print(r)
    elif a and a[0] == "stats":
        for k, v in memory.code_stats().items():
            if k.startswith("docs:"):
                print(f"{k:<24} {v['files']:>7} ficheros")
    else:
        sys.exit(__doc__)
