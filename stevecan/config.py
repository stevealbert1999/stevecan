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
    "ingeniería de software y arquitectura;sistemas embebidos, microcontroladores y bus CAN;"
    "electrónica y electricidad;redes, Linux y ciberseguridad;ciencia de datos y aprendizaje automático;"
    "matemáticas y física aplicadas;DevOps, cloud y contenedores;mecánica, automoción y diagnosis")
EXPERT_DOMAINS = [d.strip() for d in (os.getenv("EXPERT_DOMAINS") or _DEFAULT_DOMAINS).split(";") if d.strip()]
SKILLS_DIR = DATA_DIR / "skills"
PROPOSALS_DIR = DATA_DIR / "proposals"
KATAS_DIR = WORKSPACE_DIR / "katas"
for d in (SKILLS_DIR, PROPOSALS_DIR, KATAS_DIR):
    d.mkdir(parents=True, exist_ok=True)
