#!/usr/bin/env bash
# Instala dependencias y registra los servicios systemd (24/7, reinicio automático).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
[ -f .env ] || cp .env.example .env
USER_NAME="$(id -un)"
for svc in stevecan-llama stevecan-agents stevecan-api; do
  sed -e "s#__ROOT__#$ROOT#g" -e "s#__USER__#$USER_NAME#g" "systemd/$svc.service" \
    | sudo tee "/etc/systemd/system/$svc.service" >/dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable --now stevecan-llama stevecan-agents stevecan-api
sudo systemctl status --no-pager stevecan-llama stevecan-agents stevecan-api
