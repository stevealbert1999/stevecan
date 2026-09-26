#!/usr/bin/env bash
# Servidor de embeddings para búsqueda semántica (opcional). Recomendado: Qwen3-Embedding-0.6B-Q8_0.gguf
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a
EMBED_GGUF="${EMBED_GGUF:?EMBED_GGUF no definido (ruta al GGUF de embeddings)}"
exec llama-server --model "$EMBED_GGUF" --embeddings --pooling last --host 127.0.0.1 --port "${EMBED_PORT:-8081}" \
  --ctx-size 8192 --batch-size 8192 --ubatch-size 8192 --n-gpu-layers "${GPU_LAYERS:-99}" --parallel 4 --alias embedding
