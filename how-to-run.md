# How to run

Two services run on one laptop: **core** (port 8000, what the phone talks to) and **memory** (port 8001, core calls it over localhost). The browser part is still a stub on 8002.

## 1. One-time setup

**Core**
```bash
cd core
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r tests/requirements.txt
cp .env.example .env
python -m tests.make_fixtures   # test frames + spoken WAVs (fixtures are gitignored; audio needs macOS)
```

**Memory**
```bash
cd memory
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## 2. Env files

Each part has its own `.env`. Never commit them, and ask Kevin for the values rather than pasting them in chat.

- **`core/.env`**: `ANTHROPIC_API_KEY`, `CARTESIA_API_KEY`, `CARTESIA_VOICE_ID`, `TYPESAFE_API_KEY`, plus `MEMORY_URL` / `BROWSER_URL` (default to `http://127.0.0.1:8001` and `:8002`). Set `DEMO_MODE=true` at the demo table. Everything else has defaults. Core still runs with keys missing, just with fallbacks.
- **`memory/.env`**: `MOSS_PROJECT_ID`, `MOSS_PROJECT_KEY`, `SPACETIME_DB`, `SPACETIME_TOKEN`, `ANTHROPIC_API_KEY`, and `MEMORY_PUBLIC_URL` (only needed for a public dashboard, see section 5). Memory doesn't load `.env` itself, so source it first (below).

## 3. Run it

**Core with stubs** (fake memory and browser, nothing else needed):
```bash
cd core && source .venv/bin/activate
bash tests/run_with_stubs.sh      # memory stub :8001, browser stub :8002, core :8000
```

**Core with real memory** (starts both, runs the memory demo beats, then shuts down):
```bash
bash core/tests/integration/run_with_memory.sh                   # needs memory/.env
bash core/tests/integration/run_with_memory.sh --local-backends  # Moss/SpacetimeDB faked locally
```
Note: this wipes or cleans up the test data it writes to SpacetimeDB.

**Both running for real, to keep up:**
```bash
# terminal 1
cd memory && source .venv/bin/activate && set -a && source .env && set +a
uvicorn app:app --port 8001
# terminal 2
cd core && source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 4. Mirror page and fake glasses

- Open http://localhost:8000/mirror, click **Enable audio**, then hold **Space** to talk or type in the box (e.g. `where did I put my keys`). With no phone connected, the mirror drives a session on its own.
- To stand in for the phone:
  ```bash
  cd core && source .venv/bin/activate
  python -m tests.fake_glasses                               # laptop webcam
  python -m tests.fake_glasses --images tests/fixtures/chair_walk
  python -m tests.fake_glasses --video walk.mp4
  ```
  In it, type a sentence and press Enter, `/ptt` to record from the mic, or `/wav tests/fixtures/audio/keys.wav`.

## 5. Public URL for the phone (Cloudflare quick tunnel)

Free, no account, supports WebSockets.
```bash
brew install cloudflared
bash tests/run_with_stubs.sh                        # terminal 1 (or the real setup above)
cloudflared tunnel --url http://localhost:8000      # terminal 2
```
Terminal 2 prints `https://<random-words>.trycloudflare.com`. **The URL changes every time you restart cloudflared**, so re-share it and update the phone app each time. It can take 10 to 20 seconds to start working.

**Test it, simplest first:**
1. **Health:** on a phone with wifi off, open `https://<url>/health`. You should see JSON.
2. **Mirror:** open `https://<url>/mirror` on the phone, type `where did I put my keys`, and hear the reply.
3. **WebSocket:** on the laptop, `npx wscat -c wss://<url>/stream` should connect with no errors.

**The phone app connects to `wss://<url>/stream`.**

If step 1 fails, check `http://localhost:8000/health` on the laptop first.

Memory needs its own tunnel only if the family dashboard or recall photos get opened on another phone. Then run `cloudflared tunnel --url http://localhost:8001` and put that URL in `MEMORY_PUBLIC_URL`. If the dashboard is shown only on the laptop, skip it.

## 6. Backup at the demo table: phone hotspot

Venue wifi often blocks device-to-device traffic and can kill the tunnel. Turn on the phone's hotspot, join the laptop to it, find the laptop's IP (`ipconfig getifaddr en0`, usually `172.20.10.x`), and point the phone app at `ws://<laptop-ip>:8000/stream`. No tunnel needed. If the phone app fails entirely, use the mirror's Space-bar push-to-talk.

## 7. Tests

Run from `core/` with the venv active unless noted.

**Offline** (no keys, no cost):

| Command | Needs |
|---|---|
| `python -m pytest tests -q` | nothing |
| `python -m tests.demo_script --offline` (add `--audio` for WAV input) | nothing, starts its own servers |
| `memory/.venv/bin/python memory/selftest.py` (from repo root) | nothing |

**Live** (real APIs, small cost):

| Command | Needs |
|---|---|
| `python -m tests.smoke_apis all` (or `stt`, `tts`, `vision`, `jev`, `router`, `yolo`) | keys in `core/.env` |
| `python -m tests.demo_script --live [--audio] [--only N]` | `bash tests/run_with_stubs.sh` running |
| `bash core/tests/integration/run_with_memory.sh` (from repo root) | `core/.env` and `memory/.env` |
| `set -a; source memory/.env; set +a; memory/.venv/bin/python memory/e2e.py` (from repo root) | `memory/.env`; wipes the database |

Before a demo: `python -m tests.smoke_apis all` should be all PASS, then check every pill on the mirror is green.
