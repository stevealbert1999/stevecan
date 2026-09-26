#!/usr/bin/env bash
# Primera prueba real en el servidor: modelo, agentes y una hora de observación resumida.
#   scripts/smoke.sh            (local)      ·   scripts/remote.sh usuario@servidor smoke   (remoto)
set -uo pipefail
cd "$(dirname "$0")/.."
PY=".venv/bin/python"; [ -x "$PY" ] || PY=python3
echo "== 1) llama-server"; curl -sf -m 10 "${LLM_BASE_URL:-http://127.0.0.1:8080/v1}/models" >/dev/null && echo "responde" || { echo "NO responde: systemctl status stevecan-llama"; exit 1; }
echo "== 2) funciones con el modelo real"; $PY -m stevecan.smoke || exit 1
echo "== 3) pregunta de prueba"; $PY -m stevecan.ask "hola, ¿qué sabes hacer?" | head -20
echo "== 4) agentes: observación de ${SMOKE_MINUTES:-60} min (Ctrl+C para cortar; el resumen se imprime al final)"
START=$(date +%s)
timeout "$(( ${SMOKE_MINUTES:-60} * 60 ))" journalctl -fu stevecan-agents --since now -o cat 2>/dev/null | grep --line-buffered -E "INFO|WARNING|ERROR" | head -400
echo "== resumen"; $PY -m stevecan.evaluate | head -60
echo "eventos por agente en la ventana:"; $PY - <<PYEOF
from stevecan import memory
for r in memory.rows("SELECT agent, kind, COUNT(*) n FROM events WHERE created>=? GROUP BY agent, kind ORDER BY n DESC", ($START,)):
    print(f"  {r['agent']:<32} {r['kind']:<8} {r['n']}")
PYEOF
