#!/usr/bin/env bash
# Ship the current checkout to the server and (re)start it. Usage (from the repo root):
#   deploy/vultr/deploy.sh SERVER_IP API_HOST
# Copies only what the API needs (no .env, databases, node_modules or frontend), then builds on the server.
set -euo pipefail
SERVER="$1"; API_HOST="$2"
rsync -az --delete \
  --exclude '.git' --exclude '.env' --exclude '.env.*' --exclude '*.db' --exclude '*.db-journal' --exclude '.secrets' \
  --exclude '.venv' --exclude '__pycache__' --exclude '.run' --exclude 'frontend' --exclude '*.zip' \
  ./backend ./sample_data ./deploy "deploy@${SERVER}:/opt/curalink/app/"
ssh "deploy@${SERVER}" "cd /opt/curalink/app/deploy/vultr && printf 'API_HOST=%s\n' '${API_HOST}' > .env && sudo docker compose up -d --build && sudo docker compose ps"
