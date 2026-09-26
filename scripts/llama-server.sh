#!/usr/bin/env bash
# Arranca llama-server con batching continuo y N slots para que los 8 agentes
# compartan el modelo sin límite de peticiones.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a
GGUF_PATH="${GGUF_PATH:?GGUF_PATH no definido}"
NP="${LLM_PARALLEL:-8}"
CTX="${CTX_PER_SLOT:-8192}"
DRAFT_ARGS=()
if [ -n "${DRAFT_GGUF:-}" ] && [ -f "$DRAFT_GGUF" ]; then
  # Decodificación especulativa: el modelo pequeño (entrenado con stevecan.train o Qwen3-0.6B) propone tokens
  # y el 30B los verifica en bloque. 1.5-3x más rápido en código y texto repetitivo, misma calidad.
  DRAFT_ARGS=(--model-draft "$DRAFT_GGUF" --draft-max "${DRAFT_MAX:-16}" --draft-min "${DRAFT_MIN:-4}" --n-gpu-layers-draft 99)
fi
exec llama-server \
  --model "$GGUF_PATH" "${DRAFT_ARGS[@]}" \
  --threads "${THREADS:-$(nproc)}" \
  --cache-reuse 256 \
  --host 0.0.0.0 --port 8080 \
  --parallel "$NP" \
  --ctx-size $((NP * CTX)) \
  --cont-batching \
  --n-gpu-layers "${GPU_LAYERS:-99}" \
  --flash-attn on \
  --cache-type-k q8_0 --cache-type-v q8_0 \
  --jinja \
  --metrics
