import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def _env(name, default=None):
    """getenv saneado: recorta espacios y comentarios inline ('VALOR # nota' o '# nota' = vacío)."""
    v = os.environ.get(name)
    if v is None:
        return default
    v = v.strip()
    if v.startswith("#"):
        v = ""
    v = v.split(" #", 1)[0].strip()
    return v if v != "" else default

LLM_BASE_URL = _env("LLM_BASE_URL", "http://127.0.0.1:8080/v1").rstrip("/")
LLM_MODEL = _env("LLM_MODEL", "Qwen3-30B-A3B-Instruct-2507-Q4_K_M.gguf")
LLM_API_KEY = _env("LLM_API_KEY", "none")
LLM_PARALLEL = int(_env("LLM_PARALLEL", "8"))
LLM_MAX_TOKENS = int(_env("LLM_MAX_TOKENS", "2048"))
LLM_TEMPERATURE = float(_env("LLM_TEMPERATURE", "0.6"))
SEARXNG_URL = _env("SEARXNG_URL", "").strip()
CYCLE_SECONDS = float(_env("CYCLE_SECONDS", "20"))

DATA_DIR = Path(_env("DATA_DIR", "./data")).resolve()
WORKSPACE_DIR = Path(_env("WORKSPACE_DIR", str(DATA_DIR / "workspace"))).resolve()
NOTES_DIR = DATA_DIR / "notes"
DB_PATH = DATA_DIR / "stevecan.db"
LOG_PATH = DATA_DIR / "agents.log"

for d in (DATA_DIR, WORKSPACE_DIR, NOTES_DIR):
    d.mkdir(parents=True, exist_ok=True)

# Directorios de código propio que los agentes deben conocer (separados por ':')
CODE_DIRS = [Path(p).expanduser().resolve() for p in _env("CODE_DIRS", "").split(":") if p.strip()]

# Dominios en los que habrá un agente experto dedicado (separados por ';')
_DEFAULT_DOMAINS = (
    # Sistemas operativos
    "Linux: administración, kernel, systemd, shell y rendimiento;"
    "macOS: sistema, Homebrew, launchd, Swift/Objective-C y herramientas de desarrollo;"
    "Windows: administración, PowerShell, WSL, registro y desarrollo Win32/.NET;"
    # Lenguajes de programación
    "Python: lenguaje, librería estándar, asyncio, empaquetado y buenas prácticas;"
    "JavaScript y TypeScript: lenguaje, Node.js, navegador, frameworks y tooling;"
    "C y C++: lenguaje moderno, memoria, STL, CMake, rendimiento y sistemas;"
    "Java y JVM: lenguaje, Spring, concurrencia, Maven/Gradle y Kotlin;"
    "C# y .NET: lenguaje, ASP.NET, Entity Framework y ecosistema;"
    "Go: lenguaje, concurrencia, herramientas y servicios;"
    "Rust: ownership, async, cargo y sistemas seguros;"
    "PHP, Ruby y Perl: lenguajes, frameworks web (Laravel, Rails) y scripting;"
    "Swift y Kotlin: desarrollo móvil iOS/Android;"
    "SQL y bases de datos: PostgreSQL, MySQL, SQLite, NoSQL, modelado y optimización;"
    "Shell scripting: Bash, Zsh, PowerShell, sed/awk y automatización;"
    # Paradigmas y modelos de programación
    "paradigmas: orientado a objetos, funcional, reactivo, lógico y concurrente;"
    "algoritmos, estructuras de datos y complejidad;"
    "patrones de diseño, arquitectura de software y sistemas distribuidos;"
    "testing, TDD, depuración y calidad de código;"
    "web: HTML, CSS, HTTP, REST, GraphQL, seguridad web y navegadores;"
    "DevOps: Git, CI/CD, Docker, Kubernetes y cloud;"
    "bases de datos: diseño, SQL avanzado, índices, replicación, NoSQL, migraciones y rendimiento;"
    "redes sociales: APIs (Meta, X, TikTok, YouTube, Telegram, Discord), bots, automatización y analítica;"
    "Android: Kotlin/Java, Gradle, SDK, APK, arquitectura de apps y publicación;"
    "sistemas operativos: diseño de SO, kernels, bootloaders, drivers, distribuciones y empaquetado")
EXPERT_DOMAINS = [d.strip() for d in (_env("EXPERT_DOMAINS") or _DEFAULT_DOMAINS).split(";") if d.strip()]
SKILLS_DIR = DATA_DIR / "skills"
PROPOSALS_DIR = DATA_DIR / "proposals"
KATAS_DIR = WORKSPACE_DIR / "katas"
for d in (SKILLS_DIR, PROPOSALS_DIR, KATAS_DIR):
    d.mkdir(parents=True, exist_ok=True)

# Proyectos que los agentes mejoran (separados por ':'), p. ej. Astur OS y Astur APK
PROJECT_DIRS = [Path(p).expanduser().resolve() for p in _env("PROJECT_DIRS", "").split(":") if p.strip()]
AUTO_IMPROVE = _env("AUTO_IMPROVE", "1") == "1"   # el agente developer busca mejoras por sí solo
AUTO_APPLY = _env("AUTO_APPLY", "0") == "1"       # 1 = fusiona mejoras aprobadas por los tests en tu rama; 0 = deja rama stevecan/* para revisar
BACKUP_KEEP = int(_env("BACKUP_KEEP", "30"))
MAX_CHANGE_LINES = int(_env("MAX_CHANGE_LINES", "400"))
SKILLS_LIB_DIR = DATA_DIR / "skills-lib"
DOCS_LIB_DIR = DATA_DIR / "docs-lib"
BACKUPS_DIR = DATA_DIR / "backups"
WORKTREES_DIR = DATA_DIR / "worktrees"
IMPROVEMENTS_DIR = DATA_DIR / "improvements"
for d in (BACKUPS_DIR, WORKTREES_DIR, IMPROVEMENTS_DIR):
    d.mkdir(parents=True, exist_ok=True)
CODE_DIRS = list(dict.fromkeys(CODE_DIRS + PROJECT_DIRS))

# API HTTP del sistema unificado
API_HOST = _env("API_HOST", "0.0.0.0")
API_PORT = int(_env("API_PORT", "8765"))
API_TOKEN = _env("API_TOKEN", "").strip()

# Entrenamiento en CPU (modelo pequeño con LoRA; sirve de borrador especulativo para el 30B)
DATASETS = [Path(p).expanduser().resolve() for p in _env("DATASETS", "").split(":") if p.strip()]
DATASETS_DIR = DATA_DIR / "datasets"
MODELS_DIR = DATA_DIR / "models"
TRAIN_BASE_MODEL = _env("TRAIN_BASE_MODEL", "Qwen/Qwen3-0.6B")
TRAIN_STEPS = int(_env("TRAIN_STEPS", "300"))
TRAIN_MAX_LEN = int(_env("TRAIN_MAX_LEN", "1024"))
TRAIN_LORA_R = int(_env("TRAIN_LORA_R", "16"))
TRAIN_THREADS = int(_env("TRAIN_THREADS") or (os.cpu_count() or 4))
TRAIN_MIN_EXAMPLES = int(_env("TRAIN_MIN_EXAMPLES", "200"))
AUTO_TRAIN = _env("AUTO_TRAIN", "0") == "1"
AUTO_TRAIN_EVERY_HOURS = float(_env("AUTO_TRAIN_EVERY_HOURS", "24"))
LLAMA_CPP_DIR = Path(_env("LLAMA_CPP_DIR")).expanduser().resolve() if _env("LLAMA_CPP_DIR") else None
for d in (DATASETS_DIR, MODELS_DIR):
    d.mkdir(parents=True, exist_ok=True)

# Inteligencia: razonamiento en dos pasos, autocrítica, mejor-de-N y embeddings
REASONING = _env("REASONING", "1") == "1"            # borrador -> crítica -> revisión en tareas difíciles
BEST_OF = int(_env("BEST_OF", "1"))                  # muestras en paralelo + juez (1 = desactivado)
LLM_THINK_BASE_URL = _env("LLM_THINK_BASE_URL", "").rstrip("/")   # servidor opcional con modelo *Thinking* para tareas difíciles
LLM_THINK_MODEL = _env("LLM_THINK_MODEL", "")
EMBED_BASE_URL = _env("EMBED_BASE_URL", "").rstrip("/")           # llama-server --embeddings (p. ej. Qwen3-Embedding-0.6B)
EMBED_MODEL = _env("EMBED_MODEL", "embedding")
