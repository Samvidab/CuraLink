#!/usr/bin/env bash
# CuraLink local launcher.
#   ./run_demo.sh            start (or reuse) API + web app; never resets data
#   ./run_demo.sh status     show what is running
#   ./run_demo.sh stop       stop only the processes this script started
#   ./run_demo.sh restart    stop + start (needed after editing .env: keys are read when the API starts)
#   ./run_demo.sh reset      reset fictional demo data (asks for confirmation)
#   ./run_demo.sh e2e        run browser tests on an ISOLATED stack (ports 8011/8454, separate DB)
# Ports: API_PORT (default 8000), WEB_PORT (default 8443).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-8443}"
RUN="$ROOT/.run/$API_PORT"   # per-stack state, so a test stack never touches the demo stack
API="http://127.0.0.1:$API_PORT"
WEB="http://localhost:$WEB_PORT"
mkdir -p "$RUN"

port_busy() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }
api_healthy() { curl -sf -m 2 "$API/api/v1/health" | grep -q '"demo_mode"'; }
web_healthy() { curl -sf -m 3 "$WEB/api/v1/health" | grep -q '"demo_mode"' && curl -sf -m 3 "$WEB/" | grep -q 'id="root"'; }
started_by_us() { [ -f "$RUN/$1.pid" ] && kill -0 "$(cat "$RUN/$1.pid")" 2>/dev/null; }
api_pids() { lsof -nP -iTCP:"$API_PORT" -sTCP:LISTEN -t 2>/dev/null | sort -u; }
# True if .env was modified after the running API process started (so it still has the old keys).
env_newer_than_api() {
  [ -f "$ROOT/.env" ] || return 1
  local env_ts newest=0 pid lstart ts
  env_ts=$(stat -f %m "$ROOT/.env" 2>/dev/null || stat -c %Y "$ROOT/.env")
  for pid in $(api_pids); do
    for p in $pid $(pgrep -P "$pid" 2>/dev/null); do
      lstart=$(ps -o lstart= -p "$p" 2>/dev/null) || continue
      ts=$(date -j -f "%a %b %d %T %Y" "$lstart" +%s 2>/dev/null || date -d "$lstart" +%s 2>/dev/null) || continue
      [ "$ts" -gt "$newest" ] && newest=$ts
    done
  done
  [ "$newest" -gt 0 ] && [ "$env_ts" -gt "$newest" ]
}

status() {
  if api_healthy; then echo "API  ✓ $API$(started_by_us api && echo ' (started by run_demo.sh)' || true)"; elif port_busy "$API_PORT"; then echo "API  ✗ port $API_PORT is used by another program"; else echo "API  – not running"; fi
  if web_healthy; then echo "Web  ✓ $WEB$(started_by_us web && echo ' (started by run_demo.sh)' || true)"; elif port_busy "$WEB_PORT"; then echo "Web  ✗ port $WEB_PORT is used by another program (or not proxying to the API)"; else echo "Web  – not running"; fi
}

stop() {
  for svc in web api; do
    if started_by_us "$svc"; then
      pid="$(cat "$RUN/$svc.pid")"
      pkill -TERM -P "$pid" 2>/dev/null || true
      kill -TERM "$pid" 2>/dev/null || true
      echo "Stopped $svc (pid $pid)"
    fi
    rm -f "$RUN/$svc.pid"
  done
  echo "Processes not started by this script were left alone."
}

reset() {
  api_healthy || { echo "API is not running at $API"; exit 1; }
  read -r -p "Reset ALL fictional demo data (cases, bookings, intake)? [y/N] " ans || ans=""
  [[ "$ans" =~ ^[Yy]$ ]] || { echo "Cancelled. Nothing was reset."; exit 0; }
  curl -sf -X POST -H 'X-CuraLink-Client: web' "$API/api/v1/demo/reset" >/dev/null && echo "Demo data reset."
}

start() {
  command -v uv >/dev/null || { echo "Install uv: https://docs.astral.sh/uv/"; exit 1; }
  command -v node >/dev/null || { echo "Install Node.js 22+"; exit 1; }
  PNPM="pnpm"; command -v pnpm >/dev/null || PNPM="npx -y pnpm@10.34.3"

  if api_healthy; then
    echo "Reusing CuraLink API already running at $API (data untouched)."
    if env_newer_than_api; then
      echo "⚠  .env changed after this API started, so it is still using the OLD keys/settings."
      echo "   Run: ./run_demo.sh restart"
    fi
  elif port_busy "$API_PORT"; then
    echo "Port $API_PORT is in use by something that isn't the CuraLink API. Free it or run: API_PORT=8001 ./run_demo.sh"; exit 1
  else
    (cd "$ROOT/backend" && uv sync --quiet)
    (cd "$ROOT/backend" && exec uv run uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT") >"$RUN/api.log" 2>&1 &
    echo $! >"$RUN/api.pid"
    for _ in $(seq 1 60); do api_healthy && break; sleep 0.5; done
    api_healthy || { echo "API failed to start; see $RUN/api.log"; exit 1; }
    echo "API started at $API (first run seeds fictional demo data; existing data is kept)."
  fi

  if web_healthy; then
    echo "Reusing web app already running at $WEB."
  elif port_busy "$WEB_PORT"; then
    echo "Port $WEB_PORT is in use by something that isn't CuraLink (or a dev server pointed at another API). Free it or run: WEB_PORT=8444 ./run_demo.sh"; exit 1
  else
    (cd "$ROOT/frontend" && $PNPM install --prefer-offline >/dev/null)
    (cd "$ROOT/frontend" && PORT="$WEB_PORT" CURALINK_API_URL="$API" exec $PNPM dev) >"$RUN/web.log" 2>&1 &
    echo $! >"$RUN/web.pid"
    for _ in $(seq 1 60); do web_healthy && break; sleep 0.5; done
    web_healthy || { echo "Web app failed to start; see $RUN/web.log"; exit 1; }
    echo "Web app started."
  fi
  echo
  echo "Open $WEB   ·   stop with: API_PORT=$API_PORT ./run_demo.sh stop   ·   logs in .run/$API_PORT/"
}

restart() {
  local foreign=""
  for pid in $(api_pids); do
    started_by_us api && [ "$pid" = "$(cat "$RUN/api.pid")" ] && continue
    pgrep -P "$(cat "$RUN/api.pid" 2>/dev/null || echo 0)" 2>/dev/null | grep -qx "$pid" && continue
    foreign="$foreign $pid"
  done
  if [ -n "$foreign" ] && ! started_by_us api; then
    echo "The API on port $API_PORT (pid$foreign) wasn't started by run_demo.sh, so I won't kill it."
    echo "Stop it yourself (Ctrl+C in its terminal, or: kill$foreign), then run ./run_demo.sh"
    exit 1
  fi
  stop
  sleep 1
  start
}

case "${1:-start}" in
  start) start ;;
  restart) restart ;;
  stop) stop ;;
  status) status ;;
  reset) reset ;;
  e2e)
    # Browser tests reset data on every test, so they get their own API, web server and database.
    shift
    E2E_DB="$ROOT/backend/e2e_isolated.db"
    API_PORT=8011 "$0" stop >/dev/null   # always test the current code, never a stale test server
    sleep 1
    # Blank keys: browser tests must be deterministic and must never spend money on live API calls.
    ANTHROPIC_API_KEY= CARTESIA_API_KEY= DATABASE_URL="sqlite:///$E2E_DB" API_PORT=8011 WEB_PORT=8454 "$0" start
    (cd "$ROOT/frontend" && E2E_BASE_URL=http://localhost:8454 npx playwright test "$@")
    ;;
  *) echo "Usage: $0 [start|restart|status|stop|reset|e2e]"; exit 2 ;;
esac
