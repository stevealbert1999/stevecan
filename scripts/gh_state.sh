#!/usr/bin/env bash
# Persiste data/ (SQLite, notas, experimentos) en la rama huérfana `agents-data` del repo.
# Un único commit que se reescribe en cada ejecución: el historial no crece.
#   scripts/gh_state.sh pull   -> restaura data/ desde la rama (si existe)
#   scripts/gh_state.sh push   -> guarda data/ en la rama
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA="${DATA_DIR:-$ROOT/data}"
BRANCH="${AGENTS_STATE_BRANCH:-agents-data}"
REPO="${GITHUB_REPOSITORY:-$(git -C "$ROOT" remote get-url origin | sed -E 's#.*github.com[:/]##; s#\.git$##')}"
if [ -n "${AGENTS_STATE_REMOTE:-}" ]; then
  REMOTE="$AGENTS_STATE_REMOTE"
elif [ -n "${GH_TOKEN:-}" ]; then
  REMOTE="https://x-access-token:${GH_TOKEN}@github.com/${REPO}.git"
else
  REMOTE="$(git -C "$ROOT" remote get-url origin)"
fi
GIT_ID=(-c user.name=stevecan-agents -c user.email=agents@stevecan.local)
mkdir -p "$DATA"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/stevecan-state.XXXXXX")"
trap 'rm -rf "${TMP:?}"' EXIT

case "${1:-}" in
  pull)
    if git ls-remote --exit-code --heads "$REMOTE" "$BRANCH" >/dev/null 2>&1; then
      git clone -q --depth 1 --branch "$BRANCH" "$REMOTE" "$TMP/state"
      rm -rf "${TMP:?}/state/.git"
      cp -a "$TMP/state/." "$DATA/"
      echo "estado restaurado desde $BRANCH: $(du -sh "$DATA" | cut -f1)"
    else
      echo "rama $BRANCH inexistente: se empieza desde cero"
    fi
    ;;
  push)
    mkdir -p "$TMP/state"
    # Excluye ficheros temporales de SQLite y el script de ejecución en curso
    tar -C "$DATA" --exclude='*.db-wal' --exclude='*.db-shm' --exclude='workspace/_run.py' -cf - . \
      | tar -C "$TMP/state" -xf -
    cd "$TMP/state"
    git init -q -b "$BRANCH"
    git "${GIT_ID[@]}" add -A
    git "${GIT_ID[@]}" commit -q --allow-empty -m "estado de los agentes $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    git push -q --force "$REMOTE" "HEAD:refs/heads/$BRANCH"
    echo "estado guardado en $BRANCH"
    ;;
  *) echo "uso: $0 pull|push" >&2; exit 2 ;;
esac
