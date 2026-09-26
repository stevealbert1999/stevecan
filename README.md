# stevecan — 8 agentes de aprendizaje 24/7 sobre Qwen3-30B-A3B local

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

## Datos
- `data/stevecan.db` — conocimiento, tareas, exámenes, eventos (SQLite FTS5)
- `data/notes/*.md` — notas de estudio
- `data/workspace/*.py` — experimentos ejecutados
- `data/status.json` — estado del sistema

## Búsqueda web ilimitada
Los buscadores públicos bloquean tráfico automatizado con el tiempo. `docker compose` levanta un SearXNG propio
(`searxng/settings.yml`, cambia `secret_key`) y los agentes lo usan vía `SEARXNG_URL`. Sin él, se usa DuckDuckGo y Bing como respaldo.

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

Nota: `schedule` y el botón *Run workflow* solo aparecen cuando el workflow está en la rama por defecto (`main`).

## Skills de Claude Code incluidos
`.claude/skills/` trae vendorizados **superpowers** (obra/superpowers), **agent-skill** (anthropics/skills, solo los Apache 2.0)
y **fin-skills** (intercom/2x-skills). En una sesión de Claude Code sobre este repo: `/superpowers`, `/agent-skill`, `/fin-skills`
muestran el índice y cada skill se invoca por su nombre (`/brainstorming`, `/secure-github-actions`, `/mcp-builder`, …).
El hook de `.claude/settings.json` activa `using-superpowers` al iniciar la sesión. Detalle y licencias: `.claude/skills/THIRD_PARTY.md`.
