# core: voice, router & hazards (part 2)

The service the wearer talks to. The phone relay connects to `ws://<laptop>:8000/stream`,
sends `frame` / `audio` / `ptt`, and gets `say` / `snap` back. Message shapes live in
[`contracts/`](contracts/CONTRACTS.md), which core owns.

## Run it

```bash
cd core
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # add keys; everything degrades gracefully without them
bash tests/run_with_stubs.sh  # memory stub :8001, browser stub :8002, core :8000
# or core alone, against real services: uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Then:

- Open http://localhost:8000/mirror (the judges' page) and click **Enable audio**.
- In another terminal: `python -m tests.fake_glasses` (webcam) or `--video clip.mp4`.
- Type "what's in front of me" or "where did I put my keys" into either the terminal or the mirror page.
- `curl localhost:8000/health` shows which keys and services are live.
- `python -m pytest tests -q` checks the keyword router and the safety filter.

## Layout

| Path | What | PRD |
|---|---|---|
| `app/main.py` | FastAPI app: `/stream`, `/health`, `/mirror` | C-1 |
| `app/session.py` | Per-connection loop: PTT buffering, intent dispatch, snaps, ingest timer | C-1, C-8 |
| `app/stt.py` | Cartesia Ink (batch on PTT release for now) | C-2 |
| `app/router.py` | Jev → Claude Sonnet fallback → keyword rules | C-3 |
| `app/tts.py` | Cartesia Sonic + pre-generated hazard phrases | C-4 |
| `app/hazards.py` | Local YOLO nano loop, direction + cooldown | C-5 |
| `app/vision.py` | Claude Haiku describe / signal | C-6, C-7 |
| `app/clients/` | Memory and browser HTTP clients with "unavailable" fallbacks | C-8, C-9, C-11 |
| `app/safety.py` | Banned-phrase filter, two-sentence cap | non-functional |
| `static/mirror.html` | Transcript, intent, latencies, reply audio for judges | C-10 |
| `tests/` | **Test-only.** Nothing in `app/` imports from here | |
| `tests/stubs/` | Fake memory and browser services matching the contracts | mocks |
| `tests/fake_glasses.py` | Webcam / video / JPEG sender standing in for the phone | mocks |
| `tests/fixtures/` | Recorded clips and JPEGs (git-ignored) | mocks |
| `tests/run_with_stubs.sh` | Starts both stubs plus core | |
| `tests/test_router.py` | Router accuracy + safety filter checks | C-3 |

## Without keys

- No `ANTHROPIC_API_KEY`: routing falls back to keyword rules, describe/signal say they can't look.
- No Cartesia key: use typed utterances; the mirror page speaks replies with the browser voice.
- No `ultralytics` or model: hazard loop turns itself off (see `/health`).

## Main TODOs

- `TODO(C-2)` streaming Ink with turn detection instead of PTT batch.
- `TODO(C-3)` real Jev call in `router.jev_route`; tune the threshold on 20 phrases.
- `TODO(C-4)` streaming Sonic for faster first audio.
- `TODO(C-8)` ingest on scene change, not just every 3 s.
- Verify Cartesia endpoint paths and model ids on the day (`stt.py`, `tts.py`).
