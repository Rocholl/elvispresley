#!/bin/sh
set -eu

REPO_DIR="${REPO_DIR:-/data/repo}"
SMULE_USER="${SMULE_USER:-ElvaTorales1}"

mkdir -p "$REPO_DIR/canciones"
LOG="$REPO_DIR/canciones/descarga.log"
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG"; }

if [ -z "${GIT_REPO_URL:-}" ]; then
  echo "Falta GIT_REPO_URL en .env" >&2
  exit 1
fi

log "=== contenedor arrancado ==="
log "repo=$GIT_REPO_URL usuario=$SMULE_USER"

if [ ! -d "$REPO_DIR/.git" ]; then
  log "clonando repo en $REPO_DIR..."
  git clone --depth 1 "$GIT_REPO_URL" "$REPO_DIR"
else
  log "actualizando repo..."
  git -C "$REPO_DIR" pull --ff-only
fi

cd "$REPO_DIR"
log "iniciando descargar.py @$SMULE_USER"
exec python3 descargar.py "$SMULE_USER"
