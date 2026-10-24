# core: voice, router & hazards (part 2)

The service the wearer talks to. The phone relay connects to `ws://<laptop>:8000/stream`,
sends `frame` / `audio` / `ptt`, and gets `say` / `snap` back. Message shapes live in
[`contracts/`](contracts/CONTRACTS.md), which core owns. Design and decisions: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

## Run it

```bash
cd core
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r tests/requirements.txt
cp .env.example .env          # add keys; everything degrades gracefully without them
python -m tests.make_fixtures # synthetic frames + spoken-phrase WAVs (macOS for audio)
bash tests/run_with_stubs.sh  # memory stub :8001, browser stub :8002, real core :8000
# or core alone, against real services: uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Then open http://localhost:8000/mirror, click **Enable audio**, and either hold **Space** to talk through
the laptop mic or type into the box. With no phone connected, the mirror drives a headless session.
`python -m tests.fake_glasses` (webcam) or `--images tests/fixtures/chair_walk` stands in for the phone;
in it, type a sentence, `/ptt`, or `/wav tests/fixtures/audio/keys.wav`.

## Checks

| Command | What | Needs |
|---|---|---|
| `python -m pytest tests -q` | unit + in-process e2e (router, safety, hazards, contracts, /stream) | nothing |
| `python -m tests.demo_script --offline [--audio]` | the 9 demo beats against a real server with every API faked | nothing (starts its own processes) |
| `python -m tests.smoke_apis [all\|stt\|tts\|vision\|jev\|router\|yolo]` | one live call per API, PASS/FAIL/SKIP + latency | keys in `.env` |
| `python -m tests.demo_script --live [--audio]` | the demo beats with real keys | `bash tests/run_with_stubs.sh` running |

Per-turn latency goes to `logs/turns.jsonl` (`stt_ms, route_ms, handler_ms, first_audio_ms, total_ms, banned_blocked`).

## Demo-day runbook

1. Laptop on ethernet. `cd core && source .venv/bin/activate`.
2. `python -m tests.smoke_apis all`: every live service PASS.
3. Start core against the real teammates (`MEMORY_URL`, `BROWSER_URL` in `.env`):
   `uvicorn app.main:app --host 0.0.0.0 --port 8000`. If a teammate's service isn't ready, `bash tests/run_with_stubs.sh` instead.
4. Open `http://localhost:8000/mirror` on the judge-facing screen, click **Enable audio**, check every pill is green and `TTS n/n` is full.
5. `DEMO_MODE=true` at the shared table (ignores people walking past, needs bigger boxes).
6. Phone relay connects to `ws://<laptop-ip>:8000/stream`. If it can't, use the mirror's Space-bar push-to-talk.
7. `python -m tests.demo_script --live --only 3` against the real memory service once to confirm the keys beat.

## Layout

| Path | What | PRD |
|---|---|---|
| `app/main.py` | FastAPI app: `/stream`, `/health`, `/mirror`, headless session, laptop PTT forwarding, service health poller | C-1, C-10 |
| `app/session.py` | Per-wearer loop: PTT turns, barge-in, sentence-streamed replies, snaps, scene-change ingest, turn log | C-1, C-8 |
| `app/stt.py` | Cartesia Ink-2 WebSocket, one stream per PTT turn | C-2 |
| `app/router.py` | Jev → Claude Sonnet → keyword rules | C-3 |
| `app/tts.py` | Cartesia Sonic-3.5 per sentence, disk cache, pre-generated fixed phrases | C-4 |
| `app/hazards.py` | Local YOLO nano; pure `HazardTracker.decide()` | C-5 |
| `app/vision.py`, `app/llm.py` | Claude Haiku streamed describe, signal as JSON → fixed sentences | C-6, C-7 |
| `app/clients/` | Memory and browser HTTP clients with "unavailable" fallbacks | C-8, C-9, C-11 |
| `app/safety.py` | Per-sentence banned-phrase filter, two-sentence cap | non-functional |
| `app/turnlog.py` | `logs/turns.jsonl` | |
| `static/mirror.html` | Live frame, transcript, intent, latencies, status pills, reply audio, laptop PTT | C-10 |
| `tests/` | **Test-only.** Nothing in `app/` imports from here. Fakes, stubs, fixtures, demo script, smoke tests | |

## Fallbacks

Missing key = fallback from the start; failed or slow call = fallback for that turn.
No Cartesia: typed utterances work, mirror and phone use their own voice. No Claude: router uses keywords,
describe/signal say "I can't look right now". No Jev: Claude routes. No YOLO: `/health.hazards=false`, phone hears
"Obstacle warnings are off." once. Memory/browser down: a spoken "isn't available right now".
