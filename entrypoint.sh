#!/bin/sh
set -eu

REPO_DIR="${REPO_DIR:-/data/repo}"
SMULE_USER="${SMULE_USER:-ElvaTorales1}"
LOG=""

log() {
  ts=$(date '+%Y-%m-%d %H:%M:%S')
  if [ -n "$LOG" ]; then
    echo "$ts $*" | tee -a "$LOG"
  else
    echo "$ts $*"
  fi
}

if [ -z "${GIT_REPO_URL:-}" ]; then
  echo "Falta GIT_REPO_URL en .env" >&2
  exit 1
fi

log "=== contenedor arrancado ==="
log "repo=$GIT_REPO_URL usuario=$SMULE_USER"

pull_repo() {
  runtime="canciones/fallidas.json canciones/progreso.txt canciones/manifest.json canciones/descarga.log"
  backup=$(mktemp -d)
  for f in $runtime; do
    [ -f "$REPO_DIR/$f" ] && cp "$REPO_DIR/$f" "$backup/$(basename "$f")"
  done
  git -C "$REPO_DIR" reset --hard HEAD
  git -C "$REPO_DIR" pull --ff-only
  for f in $runtime; do
    b="$backup/$(basename "$f")"
    [ -f "$b" ] && cp "$b" "$REPO_DIR/$f"
  done
  rm -rf "$backup"
}

if [ -d "$REPO_DIR/.git" ]; then
  log "actualizando repo..."
  pull_repo
elif [ -e "$REPO_DIR" ] && [ -n "$(ls -A "$REPO_DIR" 2>/dev/null)" ]; then
  # ponytail: volumen con canciones/ pero sin .git (arranque anterior falló al clonar)
  log "repo sin .git; reclonando y conservando canciones..."
  backup=$(mktemp -d)
  [ -d "$REPO_DIR/canciones" ] && cp -a "$REPO_DIR/canciones/." "$backup/"
  rm -rf "$REPO_DIR"
  git clone --depth 1 "$GIT_REPO_URL" "$REPO_DIR"
  mkdir -p "$REPO_DIR/canciones"
  [ -n "$(ls -A "$backup" 2>/dev/null)" ] && cp -an "$backup/." "$REPO_DIR/canciones/"
  rm -rf "$backup"
else
  log "clonando repo en $REPO_DIR..."
  rm -rf "$REPO_DIR"
  git clone --depth 1 "$GIT_REPO_URL" "$REPO_DIR"
fi

mkdir -p "$REPO_DIR/canciones"
LOG="$REPO_DIR/canciones/descarga.log"
cd "$REPO_DIR"
log "iniciando descargar.py @$SMULE_USER (xvfb)"
export HEADLESS=false
exec xvfb-run -a --server-args="-screen 0 1280x720x24" python3 descargar.py "$SMULE_USER"
