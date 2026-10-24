# How to run

Two services run on one laptop: **core** (port 8000, what the phone talks to) and **memory** (port 8001, core calls it over localhost). The browser part (8002) isn't built yet, so browser requests answer "isn't available right now".

## 1. One-time setup

```
brew install cloudflared
```

**Core**
```bash
cd core
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r tests/requirements.txt
python -m tests.make_fixtures   # test frames + spoken WAVs (fixtures are gitignored; audio needs macOS)
```
Set up .env from the .env.example

**Memory**
```bash
cd memory
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```
Set up .env from the .env.example

**Dashboard** (needs Node)
```bash
cd dashboard
npm install
```
Optional: `.env` from `.env.example` only to point at a different SpacetimeDB.

## 2. Run it

run.sh is true source of running everything

From the repo root, this starts memory (8001), core (8000) and the Cloudflare tunnel to core. Ctrl-C stops all of them. Add `--no-tunnel` to skip the tunnel.
```bash
bash run.sh
```
It also starts the family dashboard, then opens the mirror (http://localhost:8000/mirror) and the dashboard (http://localhost:5173) in your browser, then the tunnel URL once it works.

## 3. Give Server URL to the phone (Cloudflare quick tunnel)

`bash run.sh` starts the tunnel too. Once the tunnel is connected, its `https://<random-words>.trycloudflare.com` URL opens in your browser. If the page doesn't load yet, wait 10 to 20 seconds and refresh. In the phone app, use `wss://<random-words>.trycloudflare.com/stream`. The URL changes every run.

## 4. Optional: manual testing without the phone

You don't need these for the real setup. They let you try things with `bash run.sh` running and no phone app.

**Mirror page.** Open http://localhost:8000/mirror and click **Enable audio**. Hold **Space** to talk through the laptop mic, or type a sentence in the box, like `where did I put my keys`. You'll hear the reply and see the transcript.

**Fake glasses.** This pretends to be the phone and streams frames to core. In a second terminal:
```bash
cd core && source .venv/bin/activate
python -m tests.fake_glasses                                  # laptop webcam
python -m tests.fake_glasses --images tests/fixtures/chair_walk  # a folder of JPEGs
python -m tests.fake_glasses --video walk.mp4                 # a video clip
```
Once it's running, type a sentence and press Enter to "say" it, `/ptt` to record from the mic, or `/wav tests/fixtures/audio/keys.wav` to play a recording.
