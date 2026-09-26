import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://127.0.0.1:8080/v1").rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "Qwen3-30B-A3B-Instruct-2507-Q4_K_M.gguf")
LLM_API_KEY = os.getenv("LLM_API_KEY", "none")
LLM_PARALLEL = int(os.getenv("LLM_PARALLEL", "8"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "2048"))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.6"))
SEARXNG_URL = os.getenv("SEARXNG_URL", "").strip()
CYCLE_SECONDS = float(os.getenv("CYCLE_SECONDS", "20"))

DATA_DIR = Path(os.getenv("DATA_DIR", "./data")).resolve()
WORKSPACE_DIR = Path(os.getenv("WORKSPACE_DIR", str(DATA_DIR / "workspace"))).resolve()
NOTES_DIR = DATA_DIR / "notes"
DB_PATH = DATA_DIR / "stevecan.db"
LOG_PATH = DATA_DIR / "agents.log"

for d in (DATA_DIR, WORKSPACE_DIR, NOTES_DIR):
    d.mkdir(parents=True, exist_ok=True)

# Directorios de código propio que los agentes deben conocer (separados por ':')
CODE_DIRS = [Path(p).expanduser().resolve() for p in os.getenv("CODE_DIRS", "").split(":") if p.strip()]

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
EXPERT_DOMAINS = [d.strip() for d in (os.getenv("EXPERT_DOMAINS") or _DEFAULT_DOMAINS).split(";") if d.strip()]
SKILLS_DIR = DATA_DIR / "skills"
PROPOSALS_DIR = DATA_DIR / "proposals"
KATAS_DIR = WORKSPACE_DIR / "katas"
for d in (SKILLS_DIR, PROPOSALS_DIR, KATAS_DIR):
    d.mkdir(parents=True, exist_ok=True)

# Proyectos que los agentes mejoran (separados por ':'), p. ej. Astur OS y Astur APK
PROJECT_DIRS = [Path(p).expanduser().resolve() for p in os.getenv("PROJECT_DIRS", "").split(":") if p.strip()]
AUTO_IMPROVE = os.getenv("AUTO_IMPROVE", "1") == "1"   # el agente developer busca mejoras por sí solo
AUTO_APPLY = os.getenv("AUTO_APPLY", "0") == "1"       # 1 = fusiona mejoras aprobadas por los tests en tu rama; 0 = deja rama stevecan/* para revisar
BACKUP_KEEP = int(os.getenv("BACKUP_KEEP", "30"))
MAX_CHANGE_LINES = int(os.getenv("MAX_CHANGE_LINES", "400"))
SKILLS_LIB_DIR = DATA_DIR / "skills-lib"
BACKUPS_DIR = DATA_DIR / "backups"
WORKTREES_DIR = DATA_DIR / "worktrees"
IMPROVEMENTS_DIR = DATA_DIR / "improvements"
for d in (BACKUPS_DIR, WORKTREES_DIR, IMPROVEMENTS_DIR):
    d.mkdir(parents=True, exist_ok=True)
CODE_DIRS = list(dict.fromkeys(CODE_DIRS + PROJECT_DIRS))
