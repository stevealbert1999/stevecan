#!/usr/bin/env bash
# Registra este PC como runner self-hosted de GitHub Actions y lo deja como servicio (arranque automático).
# 1) GitHub -> repo -> Settings -> Actions -> Runners -> "New self-hosted runner" -> copia el token.
# 2) RUNNER_TOKEN=<token> scripts/gh_runner.sh   (opcional: REPO=owner/repo, RUNNER_DIR=~/actions-runner)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO="${REPO:-$(git -C "$ROOT" remote get-url origin | sed -E 's#.*github.com[:/]##; s#\.git$##')}"
RUNNER_TOKEN="${RUNNER_TOKEN:?Falta RUNNER_TOKEN (Settings > Actions > Runners > New self-hosted runner)}"
RUNNER_DIR="${RUNNER_DIR:-$HOME/actions-runner}"
ARCH="$(uname -m)"; case "$ARCH" in x86_64) ARCH=x64;; aarch64|arm64) ARCH=arm64;; esac
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"; [ "$OS" = "darwin" ] && OS=osx
VER="$(curl -sf https://api.github.com/repos/actions/runner/releases/latest | sed -nE 's/.*"tag_name": *"v([^"]+)".*/\1/p')"
mkdir -p "$RUNNER_DIR" && cd "$RUNNER_DIR"
curl -sfL -o runner.tar.gz "https://github.com/actions/runner/releases/download/v${VER}/actions-runner-${OS}-${ARCH}-${VER}.tar.gz"
tar xzf runner.tar.gz && rm -f runner.tar.gz
./config.sh --unattended --url "https://github.com/${REPO}" --token "$RUNNER_TOKEN" \
  --name "${RUNNER_NAME:-$(hostname)-stevecan}" --labels self-hosted,stevecan --replace
sudo ./svc.sh install "$(id -un)"
sudo ./svc.sh start
sudo ./svc.sh status
echo "Runner registrado. Asegúrate de que llama-server corre en este PC (scripts/install.sh o scripts/llama-server.sh)."
