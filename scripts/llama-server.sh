#!/usr/bin/env bash
# Arranca llama-server con batching continuo y N slots para que los 8 agentes
# compartan el modelo sin límite de peticiones.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a
GGUF_PATH="${GGUF_PATH:?GGUF_PATH no definido}"
NP="${LLM_PARALLEL:-8}"
CTX="${CTX_PER_SLOT:-8192}"
exec llama-server \
  --model "$GGUF_PATH" \
  --host 0.0.0.0 --port 8080 \
  --parallel "$NP" \
  --ctx-size $((NP * CTX)) \
  --cont-batching \
  --n-gpu-layers "${GPU_LAYERS:-99}" \
  --flash-attn on \
  --cache-type-k q8_0 --cache-type-v q8_0 \
  --jinja \
  --metrics
