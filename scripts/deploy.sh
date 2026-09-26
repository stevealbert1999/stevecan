#!/usr/bin/env bash
# Despliega y arranca todo el sistema en TU servidor privado por SSH (no en GitHub).
#   scripts/deploy.sh usuario@servidor [/ruta/remota]      (por defecto ~/stevecan)
# Requisitos en el servidor: ssh, rsync, python3, sudo, llama-server (o Docker) y el .gguf en GGUF_PATH del .env.
set -euo pipefail
HOST="${1:?uso: $0 usuario@servidor [/ruta/remota]}"
DEST="${2:-stevecan}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$ROOT/.env" ] || { echo "falta .env (copia .env.example y rellénalo)"; exit 1; }
rsync -az --delete \
  --exclude .git --exclude data --exclude .venv --exclude '__pycache__' \
  "$ROOT/" "$HOST:$DEST/"
ssh "$HOST" "cd '$DEST' && chmod +x scripts/*.sh && ./scripts/install.sh && .venv/bin/python -m stevecan.skills sync"
echo "Desplegado en $HOST:$DEST. Estado: scripts/remote.sh $HOST status"
