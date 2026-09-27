# PROMPT PARA CLAUDE CODE — MEJORAR MI IA LOCAL, ENTRENARLA MÁS Y CREAR EL AGENTE "SENTINEL" (24/7, SIEMPRE AL DÍA)

> Pega este documento entero como primer mensaje a Claude Code en una carpeta vacía (p. ej. `~/ia-local`).
> Reglas absolutas: no preguntes, no pidas confirmaciones, no dejes TODOs. **Prohibido** usar mock data, simulaciones, stubs o resultados inventados. Todo se prueba con `pytest -q` sobre ficheros, procesos y red reales, y contra el servidor del modelo real. Commits pequeños, cada uno con los tests en verde. Al terminar: repositorio git inicializado, `README.md` con instalación y uso, y un informe final con la salida real de `pytest -q`, del benchmark y del primer digest del Sentinel.

---

## 0. MI ENTORNO (úsalo tal cual; no inventes otro)

- Modelo local: `Qwen3-30B-A3B-Instruct-2507-Q4_K_M.gguf` servido con **llama.cpp `llama-server`** (API compatible OpenAI en `http://127.0.0.1:8080/v1`, `--jinja`, `--parallel 8 --cont-batching`). Variables: `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` (opcional), `LLM_PARALLEL`.
- Ruta del GGUF: `GGUF_PATH` (por defecto `/models/Qwen3-30B-A3B-Instruct-2507-Q4_K_M.gguf`). Carpeta de llama.cpp: `LLAMA_CPP_DIR` (contiene `convert_hf_to_gguf.py` y `llama-quantize`).
- Mis proyectos de código (los que la IA debe conocer y mantener al día): `CODE_DIRS` (rutas separadas por `:`), entre ellos Astur OS y Astur APK.
- Hardware: CPU con muchos núcleos y RAM; GPU opcional (`nvidia-smi` dice si existe). Nada se asume: cada script comprueba y dice qué falta con el comando real de instalación.
- Lenguaje del proyecto: **Python 3.11+**, `asyncio`, `httpx`, `sqlite3` (FTS5), `pyyaml`, `pytest`. Entrenamiento: `torch`, `transformers`, `peft`, `trl`, `datasets` (en `requirements-train.txt`, instalación aparte).
- Todo bajo un paquete `brain/` con `python -m brain.<módulo>` como interfaz y un `.env.example` documentado.

Antes de escribir código: ejecuta `curl -s $LLM_BASE_URL/models` y una completion mínima real; guarda la salida en `docs/BASELINE.md`. Si el servidor no responde, los módulos que lo necesitan se marcan `@pytest.mark.llm` y se saltan con motivo explícito; el resto se construye y prueba igual.

---

## 1. OBJETIVO A — MEJORAR LA IA LOCAL (más acierto con el mismo modelo)

Crea `brain/llm.py`, `brain/memory.py`, `brain/bench.py`, `brain/rag.py`. Cada punto con test propio.

1. **Cliente robusto** (`llm.py`): `chat`, `ask`, `ask_json` (con `response_format` JSON Schema cuando el servidor lo acepta y parseo tolerante como fallback), reintentos con backoff en 5xx/429/timeout, semáforo `LLM_PARALLEL`, métricas por llamada (tokens, latencia) en SQLite. Parámetros por tipo de tarea: `code`/`facts` → `temperature 0.2, top_p 0.9, min_p 0.05, repeat_penalty 1.05`; `creative` → `0.7`.
2. **Razonamiento y verificación por ejecución** (`ask_hard`): para tareas difíciles, razona primero en un bloque privado y responde después; si la respuesta contiene código Python, se **ejecuta de verdad** en subproceso aislado y, si falla, se corrige hasta 2 veces con el error real. `refine` (crítico que busca errores concretos y revisa) y `best_of` (N candidatos en paralelo + juez) configurables.
3. **Memoria** (`memory.py`, SQLite + FTS5): tablas `knowledge` (topic, content, source, confidence, verified, published_at, fetched_at, expires_at, created, updated), `code_files`/`code_chunks` (con `symbol` = nombre de función/clase), `lessons`, `metrics`, `events`, `feedback`. Migraciones idempotentes.
4. **RAG híbrido** (`rag.py`): índice de `CODE_DIRS` troceado por **símbolos** (`ast` para Python; `tree-sitter` si está instalado para JS/TS/C/C++/Java/Kotlin/Go/Rust; regex de firmas como fallback), FTS5 + embeddings (servidor `llama-server --embeddings` en `EMBED_BASE_URL`, opcional) fusionados con RRF, re-ranking por recencia y confianza. `python -m brain.ask "pregunta"` responde citando `ruta:líneas` y fuente. Reindexa solo lo que cambió (sha por fichero).
5. **Benchmark fijo** (`bench.py`): 40 tareas reales guardadas en `data/bench/*.json`, generadas **desde mis repos y desde fuentes reales**, nunca inventadas: 20 preguntas de código cuya respuesta se verifica por `grep`/AST sobre `CODE_DIRS`; 10 katas con tests `unittest` que se ejecutan; 10 hechos con URL de fuente que se comprueban por descarga. `python -m brain.bench` guarda `bench_score`, `bench_json_errors`, `bench_latency`, `tokens_por_segundo`. **Todo cambio de prompt, parámetros o pesos se acepta solo si `bench_score` no baja.**
6. **Lecciones**: cada fallo (JSON inválido, test rojo, hecho refutado) genera una lección corta en `lessons`; las lecciones relevantes se inyectan en tareas del mismo tipo; `bench` comprueba que la tasa de errores de formato baja entre ejecuciones.
7. **Decodificación especulativa**: `scripts/llama-server.sh` arranca el 30B con `--model-draft` cuando existe `DRAFT_GGUF` (el modelo pequeño entrenado en el Objetivo B); `bench` mide tokens/s con y sin borrador y lo registra.

---

## 2. OBJETIVO B — ENTRENARLA MÁS (pesos reales, sin GPU obligatoria)

Crea `brain/dataset.py`, `brain/train.py`, `requirements-train.txt`, `data/models/REGISTRY.md`.

1. **Dataset continuo y limpio** (`dataset.py build`): produce `data/datasets/{sft,pref,eval}.jsonl`:
   - `sft`: pares instrucción→respuesta procedentes **solo** de: hechos `verified=1` con fuente, katas cuyos tests pasaron, respuestas de `ask` que yo marqué útiles (`POST /feedback`), resúmenes de mi código generados y contrastados con el fichero real, novedades del Sentinel verificadas (con la fecha en la instrucción: "A fecha de AAAA-MM-DD, ¿cuál es la última versión estable de X?").
   - `pref`: pares (elegida, rechazada) de `best_of` (ganadora frente a las descartadas) y de `refine` (corregida frente a original).
   - `eval`: 5 % separado por hash del prompt, nunca usado para entrenar.
   - Deduplicación por hash normalizado, filtro de longitud, filtro de PII (emails, tokens, rutas de `/home`), procedencia (`source`, `ts`, `ids`) en cada línea. Datasets externos míos en `DATASETS` (jsonl/csv/txt/md) se incorporan con el mismo filtro.
2. **Entrenamiento por etapas en CPU** (`train.py run`):
   - Etapa 1: SFT LoRA sobre `TRAIN_BASE_MODEL` (por defecto `Qwen/Qwen3-0.6B`; `Qwen/Qwen3-1.7B` si RAM ≥ 32 GB) con `sft.jsonl`.
   - Etapa 2: **DPO** (o ORPO) con `pref.jsonl` usando `trl`.
   - Fusión, export a GGUF con `convert_hf_to_gguf.py`, cuantización Q8_0 con `llama-quantize`.
   - **Puerta de calidad**: levanta un `llama-server` temporal en un puerto libre con el GGUF nuevo, ejecuta `bench` y solo lo promociona a `data/models/current.gguf` (y a `DRAFT_GGUF`) si `bench_score` sube o se mantiene y `bench_latency` no empeora. Si no, va a `data/models/rejected/<ts>/` con el informe.
   - `train.py check` dice qué dependencias faltan con el comando exacto; `train.py --history` imprime el registro.
3. **El modelo grande también aprende**: `train.py run --target big`: QLoRA 4-bit con `peft` + `bitsandbytes` sobre `Qwen3-30B-A3B` (pesos HF) si hay GPU con ≥ 24 GB; SFT + DPO; export del adaptador y fusión a GGUF; misma puerta de `bench`. Sin GPU, el comando lo dice claro y termina; no simula nada.
4. **Planificación**: `python -m brain.train auto` (ejecutado por el daemon del §3.5) entrena cada `AUTO_TRAIN_EVERY_HOURS` solo si hay ≥ `TRAIN_MIN_EXAMPLES` ejemplos nuevos desde el último entrenamiento; con `nice 19` y `TRAIN_THREADS = cpus/2` para no frenar al servidor; nunca dos entrenamientos a la vez (lock en `data/train.lock`).
5. **Registro** (`REGISTRY.md`): fecha, dataset (n ejemplos, hash), hiperparámetros, `bench` antes/después, decisión (promocionado/rechazado), ruta del GGUF.

---

## 3. OBJETIVO C — AGENTE `SENTINEL`: 24/7 RECOPILA LA INFORMACIÓN DEL MOMENTO Y MANTIENE TODO AL DÍA

Crea `brain/sentinel.py`, `data/sentinel/sources.yaml`, `brain/daemon.py`, unidades `systemd/`.

### 3.1 Fuentes reales que vigila (todas con fecha y URL; editables en `sources.yaml`)
- **Mi código** (`CODE_DIRS`): `git fetch --all` cada ciclo; nuevos commits en todas las ramas; diff por fichero; reindexa solo lo cambiado; resume cada commit (mensaje + diff) en `knowledge(topic="repo:<nombre>")`; marca como obsoletas (`verified=0`, `confidence` ↓) las entradas de conocimiento que citan líneas o símbolos que ya no existen.
- **Dependencias de mis proyectos**: parsea `requirements*.txt`, `pyproject.toml`, `package.json`, `build.gradle(.kts)`, `Cargo.toml`, `go.mod`, `platformio.ini`; consulta la API real de cada ecosistema (PyPI JSON, npm registry, Maven Central, crates.io, `proxy.golang.org`, GitHub Releases/Atom) y registra versión nueva, changelog y breaking changes.
- **Lenguajes y herramientas**: feeds oficiales de releases (python.org, nodejs.org, go.dev, rust-lang.org, kotlinlang.org, developer.android.com/studio, `ggml-org/llama.cpp`, Arduino, ESP-IDF, PlatformIO, kernel.org).
- **Seguridad**: NVD API 2.0, OSV API y GitHub Advisory Database, filtrados por las dependencias detectadas.
- **Noticias técnicas del momento**: Hacker News (API oficial Firebase), lobste.rs (JSON), arXiv (API Atom: cs.SE, cs.AI, cs.PL, cs.OS), blogs oficiales por RSS (lista en `sources.yaml`), GitHub Trending (búsqueda `created:>fecha` en la API).
- **Modelos y llama.cpp**: releases de llama.cpp, novedades de Qwen (repositorio y organización en Hugging Face vía su API), para avisarme cuando salga un modelo o cuantización mejor.
- **Fuentes que yo añada** por API: `POST /sentinel/sources` (url, tipo `rss|atom|json|html|github|pypi|npm`, filtro).

### 3.2 Qué hace con cada novedad
1. Descarga (`httpx`, `ETag`/`If-Modified-Since`, `robots.txt`, máx. 1 petición/s por dominio, backoff en 429/5xx, caché en `data/sentinel/cache/`), sanea el contenido (es **datos**, nunca instrucciones), extrae hechos con fecha y guarda `knowledge(topic, content, source, published_at, fetched_at, expires_at, confidence)`.
2. **Verificación**: cada hecho nuevo se contrasta con una segunda fuente antes de subir `confidence`; los no confirmados quedan `verified=0`.
3. **Impacto en mis proyectos**: si toca una dependencia, lenguaje o API presente en el índice de código, escribe una tarea en `data/sentinel/todo/<fecha>-<slug>.md` (qué cambió, ficheros afectados por `grep`, pasos sugeridos, enlace al changelog). Nunca modifica mi código.
4. Actualiza `data/notes/NOW.md` (estado actual del mundo técnico relevante para mí, con fecha) y `data/sentinel/digest-AAAA-MM-DD.md` (versiones nuevas, CVEs, cambios en mis repos, tendencias, modelos nuevos). Disponible por `GET /sentinel/digest` y en el dashboard.
5. **Caducidad**: los hechos "versión actual" y "noticia" llevan `expires_at`; al expirar sin renovación pasan a `verified=0` y el `curator` los archiva. El modelo nunca cita como "actual" algo caducado.
6. Alimenta el dataset (§2.1) y el `NOW.md` que `brain.ask` antepone a cada consulta, para que las respuestas sobre "última versión", "novedades" y "compatibilidad" salgan al día y con fuente.

### 3.3 Límites y seguridad
- Sin claves obligatorias (todas las fuentes funcionan sin token; `GITHUB_TOKEN` opcional sube el límite).
- Nunca ejecuta código descargado; nunca sigue instrucciones contenidas en páginas (envoltorio de datos no confiables + filtro de frases de inyección).
- Métricas: fuentes ok/fallo, hechos nuevos/día, caducados, latencia; alerta en `data/alerts.log` si una fuente falla > 24 h.

### 3.4 Tests (`tests/test_sentinel.py`, sin mocks)
- Repo git real en `tmp_path`: un commit nuevo se detecta, se reindexa solo el fichero cambiado y el conocimiento que citaba una línea borrada baja de confianza.
- Parseo de manifiestos reales (`requirements.txt`, `package.json`, `platformio.ini`) desde fixtures reales del propio proyecto.
- `@pytest.mark.network`: PyPI JSON de `httpx`, feed Atom de releases de `ggml-org/llama.cpp`, HN top stories; se saltan con motivo si no hay red.
- Caducidad: un hecho con `expires_at` en el pasado queda `verified=0` tras un ciclo.
- Digest: se genera el fichero del día con secciones no vacías cuando hay novedades.

### 3.5 Ejecución 24/7
- `python -m brain.daemon`: bucle asyncio con los agentes `sentinel` (cada `SENTINEL_EVERY_MIN`, por defecto 15), `curator` (caducidad, duplicados, limpieza), `trainer` (§2.4) y `bench` semanal; nunca muere: cada error se registra y se reintenta con backoff; espera al modelo si no responde.
- `systemd/brain-llama.service` (llama-server con `--model-draft` si hay `DRAFT_GGUF`), `systemd/brain-daemon.service`, `systemd/brain-api.service`; `scripts/install.sh` los instala y habilita; equivalente Windows con Task Scheduler en `scripts/windows/`.
- `python -m brain.api`: `GET /status`, `POST /ask`, `POST /feedback`, `GET /sentinel/now`, `GET /sentinel/digest?date=`, `POST /sentinel/sources`, `GET /metrics`, `GET /dashboard` (HTML sin dependencias). Token opcional `API_TOKEN`.

---

## 4. INTEGRACIÓN CON CLAUDE CODE Y CON MIS AGENTES

1. `python -m brain.skills`: convierte cada digest semanal en una skill `data/skills/now-AAAA-WW/SKILL.md` ("estado actual de X, con fuentes y fecha") y las verificadas por tema en `data/skills/<tema>/SKILL.md`, formato Agent Skills (frontmatter `name`/`description`), para cargarlas en `.claude/skills/`.
2. `python -m brain.mcp`: servidor MCP (stdio) que expone `ask`, `search_code`, `now`, `digest`, `bench` para que Claude Code y cualquier agente los usen como herramientas.
3. `README.md`: instalación, `.env`, arranque del servidor recomendado (`--ctx-size`, `--parallel 8 --cont-batching --cache-reuse 256 --jinja --model-draft`), comandos (`ask`, `bench`, `dataset build`, `train run|check|auto|--history`, `daemon`, `api`, `skills`, `mcp`), y cómo añadir fuentes al Sentinel.

---

## 5. ORDEN DE TRABAJO Y CRITERIO DE HECHO

1. `docs/BASELINE.md` con la comprobación real del servidor → `llm.py` + `memory.py` + tests → commit.
2. `rag.py` (índice por símbolos, híbrido, `ask`) + tests → commit.
3. `bench.py` + 40 tareas reales generadas desde mis repos y fuentes → ejecutar y guardar el resultado inicial → commit.
4. `ask_hard` con ejecución, `refine`, `best_of`, lecciones, parámetros por tarea, gramáticas JSON → `bench` no baja → commit.
5. `dataset.py` (sft/pref/eval, filtros, procedencia) + tests → commit.
6. `train.py` (SFT → DPO → GGUF → bench → promoción, `--target big`, `auto`, lock, REGISTRY) + tests de las partes sin GPU → commit.
7. `sentinel.py` + `sources.yaml` + migración de `knowledge` + caducidad + digest + `todo/` + tests → commit.
8. `daemon.py`, `api.py`, `skills.py`, `mcp.py`, `systemd/`, `scripts/`, README → commit.
9. Ejecutar `pytest -q`, `python -m brain.bench` y un ciclo real de `python -m brain.sentinel once`; pegar las tres salidas reales en `docs/REPORT.md`.

**Hecho** = todos los tests pasan (los `@llm`/`@network` saltados solo con motivo real), `bench_score` final ≥ inicial, el Sentinel ha producido un digest real con al menos una fuente de red (o el informe dice explícitamente que no hubo red), el daemon arranca y sobrevive a que apague el servidor del modelo, y ningún fichero del proyecto contiene datos inventados.
