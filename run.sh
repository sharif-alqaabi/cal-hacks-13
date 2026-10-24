#!/usr/bin/env bash
# Start memory (:8001), core (:8000) and a Cloudflare quick tunnel to core. Ctrl-C stops all three.
#   bash run.sh               # prints the public https://....trycloudflare.com URL (new on every run)
#   bash run.sh --no-tunnel   # just the two servers
cd "$(dirname "$0")"
trap 'kill 0' EXIT

(cd memory && set -a && source .env && set +a && exec .venv/bin/uvicorn app:app --port 8001) &
(cd core && exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000) &
[ "$1" = "--no-tunnel" ] || cloudflared tunnel --url http://localhost:8000 &

wait
