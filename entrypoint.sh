#!/bin/sh
set -eu

REPO_DIR="${REPO_DIR:-/data/repo}"
SMULE_USER="${SMULE_USER:-ElvaTorales1}"

mkdir -p "$REPO_DIR"

if [ -z "${GIT_REPO_URL:-}" ]; then
  echo "Falta GIT_REPO_URL en .env" >&2
  exit 1
fi

if [ ! -d "$REPO_DIR/.git" ]; then
  echo "Clonando repo en $REPO_DIR..."
  git clone --depth 1 "$GIT_REPO_URL" "$REPO_DIR"
else
  echo "Actualizando repo..."
  git -C "$REPO_DIR" pull --ff-only
fi

cd "$REPO_DIR"
echo "Iniciando descarga de @$SMULE_USER..."
exec python3 descargar.py "$SMULE_USER"
