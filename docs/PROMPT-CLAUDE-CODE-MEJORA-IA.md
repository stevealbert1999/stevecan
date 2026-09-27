# PROMPT PARA CLAUDE CODE — MEJORAR LA IA LOCAL, ENTRENARLA MÁS Y CREAR EL AGENTE "SENTINEL" (24/7 SIEMPRE AL DÍA)

> Pega este documento entero como primer mensaje a Claude Code abierto en el repo `stevecan` (rama nueva desde `master`).
> Reglas: sin preguntas, sin mocks, sin simulaciones, sin datos inventados. Todo lo que se añade se prueba con `pytest -q` y contra el `llama-server` real cuando exista (`LLM_BASE_URL`). Commits pequeños, cada uno verde. Al final: PR a `master` con la salida real de los tests en la descripción.

## 0. Contexto que ya existe (léelo antes de tocar nada)

- `stevecan/config.py` (variables `.env`, `_env` sanitizado, `EXPERT_DOMAINS`, `CODE_DIRS`, `PROJECT_DIRS`, `TRAIN_*`, `EVAL_*`, `REASONING`, `BEST_OF`, `DRAFT_GGUF`).
- `stevecan/llm.py` (`chat`, `ask`, `ask_json`, `ask_hard`, `refine`, `best_of`, `healthy`).
- `stevecan/memory.py` (SQLite + FTS5: `knowledge`, `tasks`, `code_files/code_chunks`, `skills_lib`, `lessons`, `plans`, `metrics`, `embeddings`).
- `stevecan/roles.py` (14 roles + 24 expertos; `build_agents()`), `stevecan/agent.py` (`run_forever`, `skills()`, `lessons()`, `learn_from_failure()`).
- `stevecan/tools.py` (`web_search` SearXNG→DDG→Bing, `fetch_page` con guard SSRF, `sanitize_untrusted`, `run_python`).
- `stevecan/dataset.py` (`build()` desde memoria verificada + `DATASETS`), `stevecan/train.py` (`check()`, `run()` LoRA CPU → GGUF), `stevecan/evaluate.py` (`evaluate()` con umbrales), `stevecan/docs.py` y `stevecan/skills.py` (sync + índice), `stevecan/serve.py` (API + dashboard), `stevecan/smoke.py`.
- `scripts/llama-server.sh` (flags probados con `--help`, `--parallel 8 --cont-batching`, `--model-draft`), `systemd/*.service`, `docker-compose.yml`, `tests/` (28 tests, `DATA_DIR` aislado por `conftest.py`).

Ejecuta primero `pytest -q` y `python -m stevecan.smoke` (si hay servidor) y anota el estado de partida en el PR.

---

## 1. OBJETIVO A — MEJORAR LA IA LOCAL (más acierto con el mismo modelo)

Implementa, cada punto con su test:

1. **Evaluación antes/después obligatoria.** `stevecan/bench.py`: banco fijo de 40 tareas reales guardadas en `data/bench/*.json` (20 preguntas de código sobre `CODE_DIRS` con respuesta verificable por grep/AST, 10 katas con tests, 10 hechos con fuente). `python -m stevecan.bench` ejecuta contra el servidor y guarda `metrics(bench_score, bench_tool_errors, bench_latency)`. Todo cambio de prompt, parámetros o pesos se acepta solo si `bench_score` no baja.
2. **Prompts de sistema por rol con ejemplos reales.** Cada rol en `roles.py` recibe 2-3 ejemplos few-shot extraídos de sus propias ejecuciones verificadas (tabla `knowledge` con `verified=1` y `lessons`), regenerados a diario por el `Curator`. Nunca ejemplos escritos a mano con datos ficticios.
3. **Recuperación mejor.** `memory.search` y `search_code` pasan a **híbrido**: FTS5 + embeddings cuando `EMBED_BASE_URL` existe, fusión RRF, re-ranking por recencia (`updated_at`) y por `confidence`. Los chunks de código llevan el nombre de la función/clase (parseo con `ast` para Python, `tree-sitter` opcional para el resto, regex de firmas como fallback).
4. **Razonamiento y autocrítica por defecto en tareas difíciles** (`REASONING=1` ya existe): amplía `ask_hard` con verificación por ejecución cuando la respuesta contiene código (se ejecuta con `run_python`/tests reales y, si falla, se corrige hasta 2 veces).
5. **Parámetros de decodificación por tarea**: `temperature 0.2/top_p 0.9` para código y hechos, `0.7` para curriculum/síntesis; `repeat_penalty 1.05`; `min_p 0.05`. Configurables en `.env` y medidos con `bench`.
6. **Gramáticas para JSON**: cuando `ask_json` pide un objeto, envía `response_format` con JSON Schema (llama-server con `--jinja`) y valida; fallback al parseo tolerante actual.
7. **Decodificación especulativa activa**: `scripts/llama-server.sh` usa `DRAFT_GGUF` si existe; `bench` mide tokens/s con y sin borrador y lo deja anotado en `metrics`.
8. **Lecciones que se aplican**: `agent.lessons()` ya inyecta lecciones; añade que cada fallo de tool/JSON/test genere lección con `evidence` y que `bench` compruebe que la tasa de errores de formato baja entre ejecuciones.

---

## 2. OBJETIVO B — ENTRENARLA MÁS (pesos reales, sin GPU obligatoria)

1. **Dataset continuo y limpio.** `dataset.build()` produce tres ficheros `data/datasets/{sft,pref,eval}.jsonl`:
   - `sft`: pares (instrucción, respuesta) solo de `knowledge.verified=1`, katas con tests en verde, notas de `synthesizer`, resúmenes de código de `librarian`, respuestas de `consult` que el usuario marcó útiles (`/feedback` en la API).
   - `pref`: pares (elegida, rechazada) de `best_of` (la que eligió el juez frente a las descartadas) y de `refine` (versión corregida frente a la original).
   - `eval`: 5 % separado por hash, nunca usado para entrenar.
   Deduplicación por hash normalizado, filtro de longitud, filtro de PII (regex de emails/tokens/rutas de home), y registro de procedencia (`source`, `ts`, `ids`).
2. **Entrenamiento por etapas en CPU** (`train.py`):
   - Etapa 1 SFT LoRA sobre `TRAIN_BASE_MODEL` (por defecto `Qwen/Qwen3-0.6B`; opción `Qwen/Qwen3-1.7B` si hay ≥ 32 GB RAM) con `sft.jsonl`.
   - Etapa 2 **DPO/ORPO** con `pref.jsonl` (usa `trl`; si no está instalado, `check()` lo dice con el comando real de instalación).
   - Exporta a GGUF (`convert_hf_to_gguf.py` de `LLAMA_CPP_DIR`) y cuantiza Q8_0.
   - Evalúa el GGUF resultante con `bench` (levantando un `llama-server` temporal en un puerto libre); solo se promociona a `DRAFT_GGUF` y a `data/models/current.gguf` si mejora `bench_score` y no empeora `bench_latency`. Si no, se guarda en `data/models/rejected/` con el informe.
3. **El modelo grande también aprende**: para `Qwen3-30B-A3B` en GPU con ≥ 24 GB, `train.py --target big` hace QLoRA 4-bit con `peft` sobre `sft.jsonl` + DPO con `pref.jsonl`, exporta el adaptador y lo fusiona a GGUF; misma puerta de `bench`. Sin GPU, el comando lo dice claramente y no simula nada.
4. **Planificación del entrenamiento**: el rol `Tuner` entrena cada `AUTO_TRAIN_EVERY_HOURS` solo si hay ≥ `TRAIN_MIN_EXAMPLES` ejemplos nuevos desde el último entrenamiento (contador en `metrics`), nunca mientras `developer` está aplicando cambios, y baja la prioridad del proceso (`nice 19`, `TRAIN_THREADS = cpus/2`) para no frenar al servidor.
5. **Registro**: `data/models/REGISTRY.md` con fecha, dataset (n ejemplos, hash), hiperparámetros, `bench` antes/después, decisión. `python -m stevecan.train --history` lo imprime.

---

## 3. OBJETIVO C — AGENTE `SENTINEL`: 24/7 RECOPILA LA INFORMACIÓN DEL MOMENTO Y MANTIENE TODO AL DÍA

Nuevo rol en `roles.py` (`class Sentinel(Agent)`), añadido a `build_agents()`, con su propio `systemd` timer no: corre dentro de `run_forever` como los demás, con ciclo de 15 min (configurable `SENTINEL_EVERY_MIN`).

### 3.1 Fuentes reales que vigila (todas con fecha y URL; `data/sentinel/sources.yaml`, editable)
- **Tu código**: cada repo de `CODE_DIRS` y `PROJECT_DIRS`: `git fetch --all`, nuevos commits en todas las ramas, diff por fichero, reindexa solo lo cambiado (`replace_code_file`), resume cada commit (mensaje + diff) en `knowledge(topic="repo:<nombre>")`, marca como obsoletas (`confidence` ↓, `verified=0`) las entradas de conocimiento que citan líneas que ya no existen.
- **Dependencias de tus proyectos**: parsea `requirements*.txt`, `pyproject.toml`, `package.json`, `build.gradle(.kts)`, `Cargo.toml`, `go.mod`, `platformio.ini`; para cada paquete consulta la API real (PyPI JSON, npm registry, Maven Central, crates.io, pkg.go.dev, GitHub Releases/Atom) y registra nueva versión, changelog y breaking changes.
- **Lenguajes y herramientas**: feeds oficiales de releases (python.org, nodejs.org, go.dev, rust-lang.org releases, kotlinlang, developer.android.com/studio releases, llama.cpp releases, Arduino/ESP-IDF/PlatformIO releases, kernel.org).
- **Seguridad**: NVD (API 2.0) y GitHub Advisory Database filtrados por las dependencias detectadas; OSV API por ecosistema.
- **Noticias técnicas del momento**: Hacker News (API oficial Firebase), lobste.rs (JSON), arXiv (API Atom, categorías cs.SE/cs.AI/cs.PL), blogs oficiales por RSS (lista en `sources.yaml`), GitHub Trending (scrape de la página con `fetch_page`, o la búsqueda `created:>fecha` de la API).
- **Documentación**: `docs.sync()` y `skills.sync()` diarios; diff de lo que cambió.
- **Fuentes que el usuario añada** por API: `POST /sentinel/sources` (url, tipo rss|atom|json|html|github|pypi|npm, filtro).

### 3.2 Qué hace con cada novedad
1. Descarga (`fetch_page`/httpx con `sanitize_untrusted`), extrae hechos con fecha, guarda `knowledge(topic, content, source=url, confidence, published_at, fetched_at)` — añade las columnas `published_at`, `fetched_at`, `expires_at` a `knowledge` con migración.
2. Clasifica impacto para **tus proyectos**: "afecta a Astur OS/APK" si toca una dependencia, lenguaje o API que aparece en el índice de código; en ese caso crea tarea `kind="upgrade-check"` para `developer` (que solo prepara la rama y los tests; no mergea).
3. Encola a `critic` la verificación de cada hecho nuevo (contraste con una segunda fuente) antes de subir `confidence`.
4. Actualiza `data/notes/NOW.md` (estado del mundo técnico relevante, con fecha) y `data/sentinel/digest-YYYY-MM-DD.md` (resumen diario: versiones nuevas, CVEs, cambios en tus repos, tendencias). El digest se expone en la API (`/sentinel/digest`) y en el dashboard.
5. **Caducidad**: hechos de tipo "versión actual" y "noticia" llevan `expires_at`; al expirar sin renovación pasan a `verified=0` y `curator` los archiva. Así el modelo nunca cita como "actual" algo viejo.
6. Alimenta el entrenamiento: las novedades verificadas entran en `sft.jsonl` con la fecha en la instrucción ("A fecha de 2026-09-27, ¿cuál es la última versión estable de X?") para que el modelo aprenda a responder con fecha.
7. Alimenta a los expertos: cada novedad relevante para un dominio se añade a `plans` del experto (`plan_add(domain, subtopic)`) para que la estudie.

### 3.3 Límites y seguridad
- Respeta `robots.txt`, `ETag`/`If-Modified-Since`, máximo 1 petición/segundo por dominio, backoff en 429/5xx, cache en `data/sentinel/cache/`.
- Todo contenido externo es datos, no instrucciones (`sanitize_untrusted`); nunca ejecuta código descargado.
- Sin claves: todas las fuentes listadas funcionan sin token; `GITHUB_TOKEN` opcional para subir el límite.
- Métricas en `metrics`: fuentes ok/fallo, hechos nuevos/día, hechos caducados, latencia; alertas en `data/alerts.log` si una fuente lleva > 24 h fallando.

### 3.4 Tests (`tests/test_sentinel.py`, sin mocks)
- Repo git real en `tmp_path`: un commit nuevo se detecta, se reindexa solo el fichero cambiado y el conocimiento que citaba una línea borrada baja de confianza.
- Parseo de manifiestos reales (`requirements.txt`, `package.json`, `platformio.ini`) del propio repo y de fixtures reales.
- Fuentes: `@pytest.mark.network` consulta PyPI JSON de `httpx` y el feed de releases de `ggml-org/llama.cpp`; se salta con motivo si no hay red.
- Caducidad: un hecho con `expires_at` en el pasado queda `verified=0` tras el ciclo de `curator`.
- Digest: se genera el fichero del día con secciones no vacías cuando hay novedades.

---

## 4. INTEGRACIÓN CON CLAUDE CODE Y CON ASTUR

1. `skillsmith` convierte cada digest semanal en una skill `data/skills/now-YYYY-WW/SKILL.md` ("estado actual de X") para que Claude Code y Astur la carguen.
2. API nueva: `GET /sentinel/now` (JSON con versiones actuales de las dependencias del usuario y fecha), `GET /sentinel/digest?date=`, `POST /sentinel/sources`, `POST /feedback` (marca una respuesta como útil/inútil → dataset).
3. `python -m stevecan.ask` antepone la fecha y el bloque `NOW.md` resumido a la consulta, para que las respuestas sobre "última versión", "novedades" y "compatibilidad" salgan al día y con fuente.
4. `README.md`: nueva tabla con `sentinel`, `bench`, entrenamiento por etapas y las variables nuevas (`SENTINEL_EVERY_MIN`, `SENTINEL_SOURCES`, `GITHUB_TOKEN`, `TRAIN_TARGET`, `BENCH_MIN_SCORE`).

---

## 5. ORDEN DE TRABAJO Y CRITERIO DE HECHO

1. `bench.py` + banco de 40 tareas + test → commit.
2. Recuperación híbrida + chunks con símbolos → commit.
3. Gramáticas JSON + parámetros por tarea + `ask_hard` con verificación por ejecución → commit.
4. `dataset.build()` con sft/pref/eval y filtros → commit.
5. `train.py` por etapas (SFT → DPO → GGUF → bench → promoción) → commit.
6. `Sentinel` (repos, dependencias, releases, CVEs, noticias, docs), migración de `knowledge`, caducidad, digest, API → commit.
7. `skillsmith`/`ask`/README/systemd → commit.
8. `pytest -q` verde, `python -m stevecan.smoke` y `python -m stevecan.bench` contra el servidor real si existe, y PR a `master` con las salidas reales pegadas.

Hecho = todos los tests pasan, `bench_score` no ha bajado respecto al inicio, el `Sentinel` ha producido un digest real con al menos una fuente de red (o el test marca claramente que no hubo red), y ningún fichero contiene datos inventados.
