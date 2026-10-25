# How to run

Three services run on one laptop: **core** (port 8000, what the phone talks to), **memory** (port 8001) and the **browser agent** (port 8002, drives a separate demo Chrome for email and lookups). Core calls the other two over localhost.

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

**Browser agent** (email and lookups)
```bash
brew install uv
cd browser
uv sync
```
Set up .env from the .env.example. The three keys are different: `TYPESAFE_API_KEY` and `ANTHROPIC_API_KEY` are the same values as in `core/.env`, and only `TEXT_MODEL_API_KEY` is the OpenRouter key. Keep `BU_CDP_URL=http://127.0.0.1:9222` in it.

Then sign in to the demo Chrome once (it's a separate profile, never your everyday Chrome):
```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --user-data-dir=$HOME/chrome-demo --remote-debugging-port=9222
```
In that window, sign in to the **throwaway Gmail** only, and set Settings > General > Undo send to 5 seconds. Quit it when done; run.sh reopens it. `browser-harness --doctor` says FAIL for the daemon until the service is running; that's normal.

**Dashboard** (needs Node)
```bash
cd dashboard
npm install
```
Optional: `.env` from `.env.example` only to point at a different SpacetimeDB.

## 2. Run it

run.sh is true source of running everything

From the repo root, this starts memory (8001), core (8000), the browser agent (8002) with the demo Chrome, and the Cloudflare tunnel to core. Ctrl-C stops all of them. Add `--no-tunnel` to skip the tunnel.
```bash
bash run.sh
```
It also starts the family dashboard, then opens the mirror (http://localhost:8000/mirror), and the dashboard (http://localhost:5173) in your browser, then the tunnel URL once it works.

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

## 5. Demo phrases that always hit their intent

Every phrase below was run through the live router on 2026-10-24 and landed on its intent through Jev, Claude and the keyword fallback. Say them close to word for word. Phrases marked *(slower)* were decided by Claude rather than Jev, about 0.7 s instead of 0.1 s, so prefer the others on stage.

| Intent | What it does | Say |
|---|---|---|
| describe | Describes the current view | "What's in front of me?" · "Describe what's around me." · "What do you see in front of me?" |
| signal | Reads a pedestrian signal | "Is the walk sign on?" · "Can I cross at this crosswalk?" · "What color is the traffic light?" |
| remember | Saves a person or a fact with the current frame | "This is my friend Kevin." · "Meet my friend Sam." · "Remember that my keys are in the top drawer." |
| recall | Answers from memory | "Where did I put my keys?" · "Do you know where my keys are?" · "What was Kevin wearing?" · "What else was on the table?" · "Where are my glasses?" · "When did I leave home?" *(slower)* |
| lost | Alerts the family dashboard | "I'm lost." · "Help me, I'm lost." · "I need help." |
| browser | Starts a laptop/web task | "Email my mom that I'm running late." · "Send an email to Sam saying I'll be there soon." · "Look up the hours for the nearest pharmacy." |
| task | Work mode item check | "Is this the right item?" · "Check this against the order." · "Next item." *(slower)* |
| confirm | Answers a waiting draft | "Yes, send it." · "No, cancel." |

Tips:
- Introduce a person ("This is my friend Kevin.") while they are in view, before asking what they wore. Recall only knows people who were introduced.
- Hold an object in view for about 5 seconds before asking where it is, so a captioned frame catches it.
- Keep the words help, walk and light out of other requests, and email, send and search out of describe questions: the keyword fallback checks those intents first.
