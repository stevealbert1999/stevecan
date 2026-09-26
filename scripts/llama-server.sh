#!/usr/bin/env bash
# Arranca llama-server con batching continuo y N slots para que los agentes compartan el modelo sin límite de peticiones.
# Comprueba con `llama-server --help` qué flags soporta tu versión y solo usa los disponibles.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a
GGUF_PATH="${GGUF_PATH:?GGUF_PATH no definido}"
[ -f "$GGUF_PATH" ] || { echo "no existe el modelo: $GGUF_PATH" >&2; exit 1; }
command -v llama-server >/dev/null || { echo "llama-server no está en el PATH (instala llama.cpp)" >&2; exit 1; }
NP="${LLM_PARALLEL:-8}"
CTX="${CTX_PER_SLOT:-8192}"
HELP="$(llama-server --help 2>&1 || true)"
has() { grep -q -- "$1" <<<"$HELP"; }
ARGS=(--model "$GGUF_PATH" --host 0.0.0.0 --port "${LLM_PORT:-8080}" --ctx-size $((NP * CTX)) --n-gpu-layers "${GPU_LAYERS:-99}")
has "--parallel" && ARGS+=(--parallel "$NP")
has "--cont-batching" && ARGS+=(--cont-batching)
has "--threads" && ARGS+=(--threads "${THREADS:-$(nproc 2>/dev/null || sysctl -n hw.ncpu)}")
if has "--flash-attn"; then
  # versiones nuevas: --flash-attn on|off|auto ; antiguas: flag booleano
  if grep -q -- "--flash-attn.*\(on\|auto\)" <<<"$HELP"; then ARGS+=(--flash-attn on); else ARGS+=(--flash-attn); fi
fi
has "--cache-type-k" && ARGS+=(--cache-type-k q8_0 --cache-type-v q8_0)
has "--cache-reuse" && ARGS+=(--cache-reuse 256)
has "--jinja" && ARGS+=(--jinja)
has "--metrics" && ARGS+=(--metrics)
if [ -n "${DRAFT_GGUF:-}" ] && [ -f "$DRAFT_GGUF" ] && has "--model-draft"; then
  # Decodificación especulativa: el modelo pequeño propone tokens y el 30B los verifica en bloque.
  ARGS+=(--model-draft "$DRAFT_GGUF")
  has "--draft-max" && ARGS+=(--draft-max "${DRAFT_MAX:-16}")
  has "--draft-min" && ARGS+=(--draft-min "${DRAFT_MIN:-4}")
  has "--n-gpu-layers-draft" && ARGS+=(--n-gpu-layers-draft 99)
elif [ -n "${DRAFT_GGUF:-}" ]; then
  echo "aviso: DRAFT_GGUF definido pero este llama-server no soporta --model-draft o el fichero no existe" >&2
fi
echo "llama-server ${ARGS[*]}"
exec llama-server "${ARGS[@]}"
