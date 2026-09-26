#!/usr/bin/env bash
# Controla el sistema en tu servidor privado.
#   scripts/remote.sh usuario@servidor status|logs|restart|stop|start|smoke|panel|ask "pregunta"|improve /ruta "instrucción"|backups [/ruta]
set -euo pipefail
HOST="${1:?uso: $0 usuario@servidor comando}"; CMD="${2:?comando}"; shift 2
DEST="${DEST:-stevecan}"
case "$CMD" in
  status)  ssh "$HOST" "systemctl status --no-pager stevecan-llama stevecan-agents stevecan-api | grep -E 'service|Active'; cat $DEST/data/status.json 2>/dev/null | head -40" ;;
  logs)    ssh -t "$HOST" "journalctl -fu stevecan-agents -u stevecan-api -u stevecan-llama" ;;
  restart) ssh "$HOST" "sudo systemctl restart stevecan-llama stevecan-agents stevecan-api" ;;
  stop)    ssh "$HOST" "sudo systemctl stop stevecan-agents stevecan-api" ;;
  start)   ssh "$HOST" "sudo systemctl start stevecan-llama stevecan-agents stevecan-api" ;;
  ask)     ssh "$HOST" "cd $DEST && .venv/bin/python -m stevecan.ask $(printf '%q ' "$@")" ;;
  improve) ssh "$HOST" "cd $DEST && .venv/bin/python -m stevecan.developer $(printf '%q ' "$@")" ;;
  backups) ssh "$HOST" "cd $DEST && .venv/bin/python -m stevecan.projects list $(printf '%q ' "$@")" ;;
  smoke)   ssh -t "$HOST" "cd $DEST && SMOKE_MINUTES=${SMOKE_MINUTES:-60} ./scripts/smoke.sh" ;;
  panel)   echo "http://${HOST#*@}:8765/  (abre un túnel: ssh -L 8765:localhost:8765 $HOST)" ;;
  *) echo "comando desconocido: $CMD" >&2; exit 2 ;;
esac
