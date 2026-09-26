# stevecan — 37 agentes de aprendizaje 24/7 sobre Qwen3-30B-A3B local

Todos los agentes comparten un único `llama-server` con 8 slots paralelos y batching continuo:
sin límites de peticiones ni de tokens más allá de tu hardware.

| Agente | Función |
|---|---|
| curriculum | decide qué aprender (huecos, temas débiles) |
| researcher | busca en la web, lee fuentes reales, extrae hechos con cita |
| critic | verifica cada hecho contra su fuente; corrige o borra |
| coder | escribe y **ejecuta** experimentos en Python |
| synthesizer | consolida notas Markdown en `data/notes/` |
| examiner | examina al modelo sin contexto y detecta huecos |
| curator | limpia duplicados, baja confianza, tareas atascadas |
| orchestrator | vigila el modelo y escribe `data/status.json` |
| librarian | indexa y resume **tu código** (`CODE_DIRS`) para que los agentes lo conozcan |
| trainer | katas de programación con tests reales contra reloj: mide velocidad y tasa de acierto |
| skillsmith | convierte lo aprendido en skills `SKILL.md` (`data/skills/`) para tus agentes y Claude Code |
| reviewer | revisa el código de los propios agentes y deja propuestas con parche en `data/proposals/` |
| developer | mejora **tus proyectos** (`PROJECT_DIRS`, p. ej. Astur OS y Astur APK) por orden tuya o por iniciativa propia, siempre con backup verificado y tests |
| expert × 24 | un experto por dominio (`EXPERT_DOMAINS`): Linux, macOS, Windows, Python, JS/TS, C/C++, Java/JVM, C#/.NET, Go, Rust, PHP/Ruby/Perl, Swift/Kotlin, SQL, shell, paradigmas, algoritmos, arquitectura, testing, web, DevOps, bases de datos, redes sociales, Android/APK, sistemas operativos |

## Requisitos
- `llama-server` (llama.cpp) en el PATH, o Docker con GPU NVIDIA.
- ~20 GB de VRAM/RAM para el Q4_K_M + KV cache de 8×8192 (q8_0). Baja `CTX_PER_SLOT` si falta memoria.
- Python 3.11+.

## Instalación (systemd, arranque automático y reinicio infinito)
```bash
cp .env.example .env   # edita GGUF_PATH
./scripts/install.sh
journalctl -fu stevecan-agents
```

## Docker
```bash
GGUF_DIR=/ruta/a/modelos docker compose up -d
```

## Manual
```bash
./scripts/llama-server.sh &
python -m stevecan
```
Con Ollama o LM Studio: pon `LLM_BASE_URL` (p. ej. `http://127.0.0.1:11434/v1`) y `LLM_MODEL` con el nombre que muestre `ollama list`; en Ollama sube `OLLAMA_NUM_PARALLEL=8`.

## Que el agente conozca tu código
El modelo no memoriza código por sí solo: se le entrega por recuperación (RAG) en cada consulta. Índice FTS5 en SQLite, sin embeddings externos.
```bash
CODE_DIRS=/ruta/proyecto1:/ruta/proyecto2     # en .env; el agente librarian lo reindexa solo al cambiar
python -m stevecan.ingest /ruta/proyecto      # indexación manual inmediata
python -m stevecan.ask "¿dónde se inicializa el bus CAN y con qué bitrate?"
```
`ask` responde citando ruta y líneas. Los agentes `coder` y `synthesizer` usan el mismo índice. Fine-tuning (LoRA) no es necesario para esto y funciona peor para hechos concretos.

## Mejorar tus proyectos sin destrozarlos (developer)
```bash
PROJECT_DIRS=/ruta/astur-os:/ruta/astur-apk                     # en .env
python -m stevecan.developer /ruta/astur-apk "añade validación de entrada en LoginActivity"   # orden tuya (se encola)
python -m stevecan.developer /ruta/astur-apk "..." --now         # ejecutar ya
python -m stevecan.projects backup /ruta/astur-os                # backup manual
python -m stevecan.projects list /ruta/astur-os                  # backups disponibles
python -m stevecan.projects restore data/backups/astur-os/<ts>.tar.gz   # restaurar (antes guarda el estado actual)
```
Cada mejora sigue este orden y se aborta en cuanto algo falla:
1. **Backup real**: `data/backups/<proyecto>/<ts>.tar.gz`, verificado tras escribirse, más tag git `backup/<ts>`.
2. **Rama aislada** `stevecan/<ts>` en un worktree aparte: tu directorio de trabajo no se toca.
3. Cambio pequeño (≤ `MAX_CHANGE_LINES`, ≤ 4 ficheros) → comprobación de sintaxis → **tests del proyecto** (pytest, npm test, gradle, maven, cargo, go, make).
4. Si pasa: commit en la rama e informe en `data/improvements/`. Con `AUTO_APPLY=1` se fusiona en tu rama (solo si no tienes cambios sin confirmar). Si falla: rama borrada, tu código intacto.

## Biblioteca de skills de GitHub
```bash
python -m stevecan.skills sync                   # clona/actualiza las colecciones de skills-sources.txt (≈2.500 skills) e indexa
python -m stevecan.skills search "android gradle"
python -m stevecan.skills enable <nombre>        # lo copia a .claude/skills/ para Claude Code
```
**Todos** los agentes (los 37 y `ask`) reciben en cada tarea los skills de la biblioteca que encajan; `librarian` la clona si falta y la actualiza a diario. Añade repos en `skills-sources.txt`.

## Mejorar a tus agentes con lo aprendido
- `data/skills/<tema>/SKILL.md`: skills generados por `skillsmith`. Cópialos a `.claude/skills/` (o al directorio de skills de tu agente) y quedan disponibles.
- `data/proposals/*.md`: mejoras propuestas por `reviewer` para `stevecan/*.py`, con diff. Se aplican a mano tras revisarlas.
- `data/status.json`: tasa de acierto y tiempo medio de las katas (`trainer`), nota media de exámenes, cobertura por dominio.

## Datos
- `data/stevecan.db` — conocimiento, tareas, exámenes, eventos (SQLite FTS5)
- `data/notes/*.md` — notas de estudio
- `data/workspace/*.py` — experimentos ejecutados
- `data/status.json` — estado del sistema
- tablas `code_chunks` / `code_files` — índice de tu código

## Búsqueda web ilimitada
Los buscadores públicos bloquean tráfico automatizado con el tiempo. `docker compose` levanta un SearXNG propio
(`searxng/settings.yml`, cambia `secret_key`) y los agentes lo usan vía `SEARXNG_URL`. Sin él, se usa DuckDuckGo y Bing como respaldo.

## Tu servidor privado (recomendado frente a GitHub)
```bash
cp .env.example .env            # GGUF_PATH, PROJECT_DIRS, CODE_DIRS, API_TOKEN…
./scripts/deploy.sh usuario@servidor          # rsync + install.sh (systemd) + sync de skills
./scripts/remote.sh usuario@servidor status   # también: logs, restart, ask "…", improve /ruta "…", backups
```
Si el modelo corre en otra máquina, pon `LLM_BASE_URL=http://ip-del-servidor:8080/v1` en `.env`.

## Sistema unificado: una sola puerta de entrada
Todos los agentes comparten memoria y la consulta pasa por `consult`: primero conocimiento verificado + tu código + skills;
si no basta, **busca en internet**, lee las fuentes, responde citándolas y guarda los hechos (que `critic` verifica después).
Si tampoco hay fuentes, lo dice y encola la investigación. Nunca inventa.
```bash
python -m stevecan.ask "¿cómo firmo un APK con apksigner?"
python -m stevecan.serve        # API HTTP: GET /status, POST /ask, POST /improve, POST /research, GET /backups, GET /improvements
curl -s -X POST localhost:8765/ask -H 'Authorization: Bearer TOKEN' -d '{"question":"..."}'
```

## Ejecutar los agentes desde GitHub (Actions)
GitHub no tiene GPU: el modelo siempre corre en tu PC. GitHub solo orquesta. Workflow: `.github/workflows/agents.yml`
(ejecuciones de 340 min que se reencadenan solas + cron cada 6 h como red de seguridad; el estado se guarda en la rama `agents-data`).

**Modo A — runner self-hosted (recomendado):** tu PC ejecuta los jobs con el modelo local.
```bash
./scripts/install.sh                          # llama-server + agentes locales
RUNNER_TOKEN=<token> ./scripts/gh_runner.sh   # token: Settings > Actions > Runners > New self-hosted runner
```
Luego Actions → `agents` → *Run workflow*. Variable de repo `AGENTS_RUNNER` vacía o `self-hosted`.

**Modo B — runners de GitHub + túnel al modelo:**
```bash
cloudflared tunnel --url http://localhost:8080   # o ngrok http 8080
```
Secreto de repo `LLM_BASE_URL=https://<tu-tunel>/v1`, variable `AGENTS_RUNNER=github`. Cada job levanta su propio SearXNG.

Nota: `schedule` y el botón *Run workflow* solo aparecen cuando el workflow está en la rama por defecto (`master`).

## Skills de Claude Code incluidos
`.claude/skills/` trae vendorizados **superpowers** (obra/superpowers), **agent-skill** (anthropics/skills, solo los Apache 2.0)
y **fin-skills** (intercom/2x-skills). En una sesión de Claude Code sobre este repo: `/superpowers`, `/agent-skill`, `/fin-skills`
muestran el índice y cada skill se invoca por su nombre (`/brainstorming`, `/secure-github-actions`, `/mcp-builder`, …).
El hook de `.claude/settings.json` activa `using-superpowers` al iniciar la sesión. Detalle y licencias: `.claude/skills/THIRD_PARTY.md`.
