#!/bin/sh
set -eu

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Creado .env desde .env.example"
fi

docker compose up -d --build
echo "Arrancado. Logs: docker compose logs -f"
