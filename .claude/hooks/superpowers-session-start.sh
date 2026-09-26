#!/usr/bin/env bash
# SessionStart: inyecta using-superpowers (equivalente al hook del plugin oficial) usando los skills vendorizados.
set -euo pipefail
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
FILE="$ROOT/.claude/skills/using-superpowers/SKILL.md"
[ -f "$FILE" ] || exit 0
python3 - "$FILE" <<'PY'
import json, sys
body = open(sys.argv[1], encoding="utf-8").read()
ctx = ("<EXTREMELY_IMPORTANT>\nYou have superpowers.\n\n"
       "Los skills están vendorizados en .claude/skills/ de este repo: invócalos por su nombre simple "
       "(p. ej. `brainstorming`, no `superpowers:brainstorming`). Índices: `superpowers`, `agent-skill`, `fin-skills`.\n\n"
       "**Below is the full content of your 'using-superpowers' skill. For all other skills, use the 'Skill' tool:**\n\n"
       + body + "\n</EXTREMELY_IMPORTANT>")
print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ctx}}))
PY
