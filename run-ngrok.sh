#!/usr/bin/env bash
# Start memory (:8001), core (:8000), the browser agent (:8002) with its own demo Chrome (CDP :9222),
# the family dashboard (Vite dev server, :5173) and an ngrok tunnel to core on your fixed static domain.
# Same as run.sh, but the public URL never changes, so the phone app is set once: wss://<domain>/stream
#   bash run-ngrok.sh                                  # domain from $NGROK_DOMAIN or the .ngrok-domain file
#   NGROK_DOMAIN=xyz.ngrok-free.app bash run-ngrok.sh
#   bash run-ngrok.sh --no-tunnel                      # everything except the tunnel
# One-time: brew install ngrok; ngrok config add-authtoken <token>; claim a free domain under Domains in the
# ngrok dashboard; echo xyz.ngrok-free.app > .ngrok-domain
cd "$(dirname "$0")"
NGROK_DOMAIN=${NGROK_DOMAIN:-$(cat .ngrok-domain 2>/dev/null | tr -d '[:space:]')}
if [ "$1" != "--no-tunnel" ] && [ -z "$NGROK_DOMAIN" ]; then
  echo "No ngrok domain. Run: echo xyz.ngrok-free.app > .ngrok-domain  (or set NGROK_DOMAIN)"; exit 1
fi
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
[ "$1" = "--no-tunnel" ] || ngrok http 8000 --url="$NGROK_DOMAIN" --log=stdout --log-level=warn &

# Once each is up, open the mirror, the dashboard, then the tunnel URL, in the default browser
(until curl -sf localhost:8000/health >/dev/null; do sleep 0.5; done; open http://localhost:8000/mirror
 until curl -sf localhost:5173 >/dev/null; do sleep 0.5; done; open http://localhost:5173
 [ "$1" = "--no-tunnel" ] && exit
 until curl -sf "https://$NGROK_DOMAIN/health" >/dev/null; do sleep 0.5; done
 echo; echo "Tunnel up. Phone app Server URL: wss://$NGROK_DOMAIN/stream"; echo
 open "https://$NGROK_DOMAIN/health") &

wait
