#!/usr/bin/env bash
# Starts the CuraLink API (port 8000) and web app (port 8443) with fictional demo data.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

command -v uv >/dev/null || { echo "Install uv: https://docs.astral.sh/uv/"; exit 1; }
command -v node >/dev/null || { echo "Install Node.js 22+"; exit 1; }
PNPM="pnpm"; command -v pnpm >/dev/null || PNPM="npx -y pnpm@10.34.3"

(cd "$ROOT/backend" && uv sync --quiet)
(cd "$ROOT/frontend" && $PNPM install --prefer-offline >/dev/null)

(cd "$ROOT/backend" && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000) &
API_PID=$!
trap 'kill $API_PID 2>/dev/null' EXIT
until curl -sf http://127.0.0.1:8000/api/v1/health >/dev/null; do sleep 0.5; done
curl -sf -X POST -H 'X-CuraLink-Client: web' http://127.0.0.1:8000/api/v1/demo/reset >/dev/null
echo "API ready · demo data reset · open http://localhost:8443"
cd "$ROOT/frontend" && PORT=8443 $PNPM dev
