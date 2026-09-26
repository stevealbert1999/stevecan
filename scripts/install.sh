#!/usr/bin/env bash
# Instala dependencias y registra los servicios systemd (24/7, reinicio automático).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# Comprobaciones previas: llama.cpp y sus flags
if ! command -v llama-server >/dev/null; then
  echo "ERROR: llama-server no está en el PATH. Instala llama.cpp (https://github.com/ggml-org/llama.cpp/releases) o usa docker compose." >&2
  exit 1
fi
HELP="$(llama-server --help 2>&1 || true)"
for f in --parallel --cont-batching --jinja; do
  grep -q -- "$f" <<<"$HELP" || echo "aviso: tu llama-server no soporta $f; actualiza llama.cpp para rendimiento óptimo" >&2
done
grep -q -- "--model-draft" <<<"$HELP" || echo "aviso: sin --model-draft (decodificación especulativa): actualiza llama.cpp si quieres DRAFT_GGUF" >&2
echo "llama-server: $(llama-server --version 2>&1 | head -1 || echo 'versión desconocida')"
python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
[ -f .env ] || cp .env.example .env
USER_NAME="$(id -un)"
for svc in stevecan-llama stevecan-agents stevecan-api; do
  sed -e "s#__ROOT__#$ROOT#g" -e "s#__USER__#$USER_NAME#g" "systemd/$svc.service" \
    | sudo tee "/etc/systemd/system/$svc.service" >/dev/null
done
if grep -qE '^EMBED_GGUF=.+' .env; then
  sed -e "s#__ROOT__#$ROOT#g" -e "s#__USER__#$USER_NAME#g" systemd/stevecan-embed.service | sudo tee /etc/systemd/system/stevecan-embed.service >/dev/null
  sudo systemctl daemon-reload && sudo systemctl enable --now stevecan-embed
fi
sudo systemctl daemon-reload
sudo systemctl enable --now stevecan-llama stevecan-agents stevecan-api
sudo systemctl status --no-pager stevecan-llama stevecan-agents stevecan-api
