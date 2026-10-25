#!/usr/bin/env bash
# Start memory (:8001), core (:8000), the browser agent (:8002) with its own demo Chrome (CDP :9222),
# the family dashboard (Vite dev server, :5173) and a Cloudflare quick tunnel to core. Ctrl-C stops everything.
#   bash run.sh               # prints the public https://....trycloudflare.com URL (new on every run)
#   bash run.sh --no-tunnel   # everything except the tunnel
cd "$(dirname "$0")"
trap 'kill 0' EXIT

[ -d dashboard/node_modules ] || (cd dashboard && npm install)

(cd memory && set -a && source .env && set +a && exec .venv/bin/uvicorn app:app --port 8001) &
(cd core && exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000) &

# Browser agent: a separate Chrome profile (sign in to the throwaway Gmail there once), never your everyday Chrome
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if ! curl -sf localhost:9222/json/version >/dev/null; then
  "$CHROME" --user-data-dir="$HOME/chrome-demo" --remote-debugging-port=9222 >/dev/null 2>&1 &
  until curl -sf localhost:9222/json/version >/dev/null; do sleep 0.5; done
fi
(cd browser && export BU_CDP_URL=http://127.0.0.1:9222 && exec uv run uvicorn app:app --port 8002) &
(cd dashboard && exec npm run dev -- --port 5173 --strictPort) &
TUNNEL_LOG=$(mktemp)
[ "$1" = "--no-tunnel" ] || cloudflared tunnel --url http://localhost:8000 2>&1 | tee "$TUNNEL_LOG" &

# Once each is up, open the mirror, the dashboard, then the tunnel URL, in the default browser
(until curl -sf localhost:8000/health >/dev/null; do sleep 0.5; done; open http://localhost:8000/mirror
 until curl -sf localhost:5173 >/dev/null; do sleep 0.5; done; open http://localhost:5173
 [ "$1" = "--no-tunnel" ] && exit
 until URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$TUNNEL_LOG" | head -1) && [ -n "$URL" ] \
   && grep -q 'Registered tunnel connection' "$TUNNEL_LOG"; do sleep 0.5; done
 open "$URL") &

wait
