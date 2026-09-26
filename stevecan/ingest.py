"""Indexa código propio en la memoria compartida (troceado por líneas + FTS5).
Uso: python -m stevecan.ingest /ruta/al/proyecto [/otra/ruta ...]"""
import hashlib
import logging
import sys
from pathlib import Path
from . import memory

log = logging.getLogger("ingest")
SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", ".venv", "venv", "env", "__pycache__", "dist", "build",
             "target", ".idea", ".vscode", ".mypy_cache", ".pytest_cache", ".next", ".cache", "vendor", "data"}
TEXT_EXT = {".py", ".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs", ".vue", ".svelte", ".html", ".css", ".scss",
            ".c", ".h", ".cpp", ".hpp", ".cc", ".cs", ".java", ".kt", ".go", ".rs", ".rb", ".php", ".swift",
            ".m", ".sh", ".bash", ".zsh", ".ps1", ".sql", ".lua", ".dart", ".scala", ".r", ".jl", ".ex", ".exs",
            ".ino", ".pde", ".s", ".asm", ".v", ".sv", ".vhd",
            ".md", ".rst", ".txt", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env.example",
            ".xml", ".proto", ".graphql", ".dockerfile", ".gradle", ".cmake", ".mk"}
TEXT_NAMES = {"Dockerfile", "Makefile", "CMakeLists.txt", "requirements.txt", "package.json", "Cargo.toml"}
MAX_BYTES = 1_000_000
CHUNK_LINES = 120
OVERLAP = 10


def _is_text(p: Path) -> bool:
    return p.suffix.lower() in TEXT_EXT or p.name in TEXT_NAMES


def _chunks(text: str):
    lines = text.splitlines()
    if not lines:
        return []
    out, i = [], 0
    while i < len(lines):
        j = min(i + CHUNK_LINES, len(lines))
        out.append((i + 1, j, "\n".join(lines[i:j])))
        if j == len(lines):
            break
        i = j - OVERLAP
    return out


def index_dir(root: Path) -> dict:
    root = root.resolve()
    repo = root.name
    seen, added, unchanged = set(), 0, 0
    for p in root.rglob("*"):
        if any(part in SKIP_DIRS for part in p.relative_to(root).parts[:-1]):
            continue
        if not p.is_file() or not _is_text(p) or p.stat().st_size > MAX_BYTES:
            continue
        rel = p.relative_to(root).as_posix()
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        sha = hashlib.sha256(text.encode()).hexdigest()
        seen.add(rel)
        if memory.code_file_sha(repo, rel) == sha:
            unchanged += 1
            continue
        memory.replace_code_file(repo, rel, sha, _chunks(text))
        added += 1
    memory.remove_code_files_not_in(repo, seen)
    res = {"repo": repo, "files": len(seen), "indexed": added, "unchanged": unchanged}
    log.info("%s", res)
    return res


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for arg in sys.argv[1:]:
        print(index_dir(Path(arg)))
    print(memory.code_stats())
