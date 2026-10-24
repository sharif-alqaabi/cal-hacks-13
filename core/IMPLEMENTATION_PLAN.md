# Core (Part 2) implementation plan: voice, router & hazards

Audience: the Claude agent that implements Part 2 of the Cal Hacks 13 assistive-glasses project.
Owner: Kevin (Engineer 2). Written Fri Oct 23 2026, ~9:30 PM PT. Devpost closes Sun Oct 25, 9:00 AM. Judging Sun 10:30 AM.

> "Part 2" here means **Engineer 2's part (core)** from PRD 2, not the team plan's "P2" priority (work mode). Work mode is a small, optional slice of core (section 6.9).

The goal is a **reliable live demo**, not production code. Every decision below favours "the demo never goes silent" over elegance.

---

## 0. How to use this document

1. Read sections 1–3 (what core is, the decisions, the target layout).
2. Work through section 7 (build order) top to bottom. Each step ends with a test you can run with **no other team member's code and no API keys** (section 8).
3. When a key is available, run the matching live smoke test (section 8.5) before you rely on that service.
4. Do not wait on teammates. Memory (Part 3), browser (Part 4) and the phone relay (Part 1) are all replaced by test doubles in `core/tests/`.

Source of truth, in priority order: (1) Kevin's decisions recorded in section 2, (2) this plan, (3) PRD 2 and the team plan PDFs in the project files, (4) the existing scaffold. **The scaffold was written before these decisions were settled. Where it disagrees with this plan, follow this plan and rewrite the scaffold code.** Keep the scaffold where this plan says "keep".

Project docs (read-only reference): `Cal Hacks 13.0 — Assistive Glasses Team Plan.pdf`, `PRD 1…4`, `sponsors.pdf`. Kevin can share them; the important parts are summarised here.

---

## 1. What core is

Core is the single FastAPI service on the demo laptop that the wearer talks to. It is the only service that talks to the phone, and the only one that speaks.

```
 Phone relay (Part 1)                      CORE (this part, :8000)                          Teammates
 ───────────────────                       ────────────────────────                          ─────────
 frame ~5 fps 640x480 JPEG ──┐       ┌──▶ hazard loop (local YOLO, no network) ──▶ say(urgent)
 audio pcm16 8 kHz ──────────┤       │
 ptt down/up ────────────────┼─/stream──▶ Session ──▶ STT (Cartesia Ink-2, streamed)
 text (dev only) ────────────┘       │         └──▶ Router (Jev → Claude → keywords)
                                     │               └──▶ handlers:
 ◀── say {text, pcm16, urgent}       │                     describe / signal → Claude Haiku (vision)
 ◀── snap {snap_id}                  │                     recall/remember/lost ──HTTP──▶ Memory (Part 3, :8001)
                                     │                     browser/confirm/task ──HTTP──▶ Browser (Part 4, :8002)
                                     │               └──▶ safety filter ──▶ TTS (Cartesia Sonic-3.5) ──▶ say
                                     ├──▶ every ~3 s or scene change: POST /ingest ─────────▶ Memory
                                     └──▶ /mirror page for judges (transcript, intent, latency, audio)
```

Two things run continuously: **YOLO on every frame** (hazards) and **a frame to memory every ~3 s** (memory does its own captioning, not core). Everything else starts only when the wearer speaks.

Core never touches SpacetimeDB or Moss. It calls the memory service over HTTP at `MEMORY_URL`.

---

## 2. Decisions (settled with Kevin; do not re-litigate)

| # | Decision | Notes |
|---|---|---|
| D1 | **Claude Haiku 5.5 (`claude-haiku-5-5`) for all vision** (describe, signal, work-mode frame). Sonnet 5.5 (`claude-sonnet-5-5`) only for text: router fallback. | Price is not a concern. Google is not a sponsor, so no Gemini. One SDK, one key, clean Anthropic-track story. If signal reading fails on test frames, try Sonnet for that one intent via `SIGNAL_MODEL`. |
| D2 | **Hazards are a local auto-loop; descriptions are on request only.** YOLO nano runs on every frame (~5 fps) and speaks short warnings. Claude is never in the hazard path. | Cloud calls are 1–3 s on venue wifi, too slow for "you're about to hit a chair", and would talk non-stop. |
| D3 | **Snap is P1, with a fallback.** Describe/signal ask the phone for a full-res `snap`, wait ≤ 1.2 s, then use the latest streamed frame. | Keep the scaffold's `fresh_frame()`. Never block on the phone. |
| D4 | **Push-to-talk is the turn trigger.** PTT down opens an STT stream, PTT up finalizes it. Ink-2 turn detection without PTT is out of scope. | Shared, noisy judging table. Glasses tap can't be used (it pauses the toolkit session). |
| D5 | **Every external service has a local fallback**, chosen automatically when its key is missing or a call fails/times out. | Section 5 lists each one. `/health` shows what's live. |
| D6 | **Never say "safe".** An output filter runs on every reply. Signal answers describe what is seen, never a decision. | Zero banned phrases is a PRD acceptance metric. |
| D7 | **Core owns `contracts/`.** Shapes in section 4 are agreed with the other parts; changing them needs Kevin. | |
| D8 | **All test-only code lives in `core/tests/`.** Nothing under `app/` or `contracts/` may import from `tests/`. Tests inject fakes by patching `app.*` module attributes. | Kevin's explicit rule. |
| D9 | **Webcam-first.** Every flow must work with a laptop webcam pretending to be the glasses. Glasses are an upgrade. | The webcam sender for *testing* is `tests/fake_glasses.py`. A stage webcam fallback is Part 1's job (PRD 1 G-11); see open question Q1. |
| D10 | **Mirror page is the stage screen**: live frame, transcript, intent, per-stage latency, every reply played through laptop speakers, plus a laptop push-to-talk (space bar + laptop mic). | Glasses speakers are open-ear; judges won't hear them. Laptop PTT lets the demo run even if the phone app is not ready. |
| D11 | **Replies are at most two sentences**, streamed sentence by sentence to TTS so first audio lands fast. | |

---

## 3. Target layout

Current scaffold (after Kevin's "tests-only into tests/" move) and what happens to each file:

```
core/
├── IMPLEMENTATION_PLAN.md        this file
├── README.md                     KEEP, update at the end (step 12)
├── .env.example                  UPDATE (section 9)
├── .gitignore                    UPDATE: add cache/, logs/
├── requirements.txt              UPDATE: runtime deps only; move pytest to tests/requirements.txt
├── app/
│   ├── main.py                   KEEP + extend: headless session, laptop PTT, frame preview to mirror
│   ├── config.py                 KEEP + new settings (section 9)
│   ├── session.py                REWRITE parts: streaming STT turns, sentence-streamed replies, barge-in,
│   │                             scene-change ingest, turn log. Keep handler structure (do_<intent>).
│   ├── stt.py                    REWRITE: Ink-2 WebSocket per PTT turn (section 6.2)
│   ├── tts.py                    REWRITE: Sonic-3.5, per-sentence, disk cache, pre-generated phrases (6.4)
│   ├── router.py                 REWRITE jev_route (real Jev call), add timeouts; keep keywords + Claude (6.3)
│   ├── hazards.py                REFACTOR: split pure decide() from YOLO I/O; fix phrase wording (6.5)
│   ├── vision.py                 REWRITE: streamed Haiku describe; signal as JSON → composed sentence (6.6)
│   ├── llm.py                    EXTEND: ask() with timeout + image resize; add stream_sentences()
│   ├── safety.py                 EXTEND: sentence-level filtering (6.7)
│   ├── mirror.py                 KEEP
│   ├── turnlog.py                NEW: JSONL per-turn latency log → logs/turns.jsonl
│   └── clients/memory.py, browser.py   KEEP (add per-call timeouts; ingest fire-and-forget)
├── contracts/                    KEEP as is (section 4). Only documented additions.
├── static/mirror.html            EXTEND (6.8)
├── cache/                        runtime: pre-generated TTS audio (git-ignored)
├── logs/                         runtime: turns.jsonl (git-ignored)
└── tests/                        ALL test-only code (D8)
    ├── requirements.txt          NEW: pytest, pytest-asyncio (optional)
    ├── conftest.py               NEW: fixtures that install fakes, in-process stubs
    ├── fakes.py                  NEW: FakeLLM, FakeSTT, FakeTTS, ColorDetector, install()
    ├── run_offline.py            NEW: run core on :8000 with every external API faked
    ├── run_with_stubs.sh         KEEP (stubs :8001/:8002 + real core :8000)
    ├── demo_script.py            NEW: scripted demo beats, pass/fail + latency table
    ├── smoke_apis.py             NEW: one live call per API, skips when the key is missing
    ├── make_fixtures.py          NEW: generates synthetic frames + spoken-phrase WAVs
    ├── fake_glasses.py           KEEP + small additions (8.2)
    ├── stubs/memory_stub.py      EXTEND: /_log, /_fail (8.3)
    ├── stubs/browser_stub.py     EXTEND: /_log
    ├── fixtures/                 media, git-ignored except README and transcripts.json
    ├── test_router.py            EXTEND to 20 phrases
    ├── test_safety.py            NEW
    ├── test_hazards.py           NEW
    ├── test_contracts.py         NEW
    └── test_session_e2e.py       NEW: in-process /stream tests with fakes and stubs
```

The old copies at `core/stubs/`, `core/tools/`, `core/fixtures/` and `core/run_all.sh` are superseded by `core/tests/`. If they are still present when you start, delete them (ask Kevin for delete permission if the file system refuses), and make sure nothing references them.

---

## 4. Contracts (keep; these are agreed with Parts 1, 3 and 4)

Source of truth is the Pydantic models in `core/contracts/`. Summary:

**`/stream` WebSocket (phone ⇄ core)**, JSON text frames with a `type` field:

| Dir | type | Fields | Notes |
|---|---|---|---|
| phone→core | `frame` | `ts, jpeg_b64, w, h, snap_id?` | ~5 fps, 640×480, JPEG q≈70. `snap_id` only when answering a snap. |
| phone→core | `audio` | `ts, pcm16_b64, rate` | mono s16le, 8000 Hz from glasses (HFP), 16000 from phone mic. Send ~100 ms chunks. |
| phone→core | `ptt` | `state: down\|up` | |
| phone→core | `text` | `text` | dev/demo only, skips STT |
| core→phone | `say` | `id, text, pcm16_b64, rate, urgent` | `pcm16_b64` may be `""` (phone then uses on-device TTS). `urgent` interrupts playback. |
| core→phone | `snap` | `snap_id` | phone replies with one full-res `frame` carrying `snap_id` |

**One behavioural addition to confirm with Part 1 (Q2):** a reply may arrive as **two consecutive non-urgent `say` messages** (one per sentence). The phone must **queue** non-urgent says and play them in order; an urgent say clears the queue and interrupts. Add this sentence to `contracts/CONTRACTS.md`. No field changes.

**Memory (`MEMORY_URL`)**: `POST /ingest {ts, jpeg_b64}` → 202; `POST /recall {question}` → `{answer, ts?, thumb_url?}`; `POST /remember {label, ts, jpeg_b64}` → `{ok}`; `POST /alert {kind: lost|help, note}` → `{ok}`; `GET /health`.

**Browser (`BROWSER_URL`)**: `POST /task {goal}` → `{task_id, say, needs_confirm}`; `POST /confirm {task_id, yes}` → `{say}`; `POST /work {utterance, jpeg_b64}` → `{say}`; `GET /health`.

**Intent labels**: `describe, signal, recall, remember, lost, browser, confirm, task, other`.

---

## 5. Fallback matrix (D5)

Fallbacks are automatic. A missing key means "use the fallback from the start"; a failed or timed-out call means "use the fallback for this turn".

| Service | Primary | Timeout | Fallback | What the wearer hears |
|---|---|---|---|---|
| STT | Cartesia Ink-2 WebSocket | 3 s after PTT up | none on the audio; the typed box on the mirror page and `text` messages always work | "Sorry, I couldn't hear that." |
| Router | TypeSafe Jev | 0.8 s | Claude Sonnet (2 s) → keyword rules | (no audible effect) |
| TTS | Cartesia Sonic-3.5 | 4 s per sentence | disk cache → `pcm16_b64=""` (phone on-device TTS; mirror uses browser `speechSynthesis`) | same words, different voice |
| Vision | Claude Haiku | 6 s total | none | "I can't look right now, please try again." |
| Hazards | YOLO nano, local | n/a | loop disabled if ultralytics/model missing (`/health.hazards=false`) | nothing (see Q3) |
| Memory | Part 3 service | 4 s (`/ingest` 2 s, fire-and-forget) | none | "Memory isn't available right now." |
| Browser | Part 4 service | `/task` 40 s, `/confirm` 40 s, `/work` 15 s | none | "The laptop assistant isn't available right now." |
| Snap | phone full-res frame | 1.2 s | latest streamed frame | n/a |
| No frame yet | | | | "I can't see anything from the glasses right now." |

---

## 6. Component specs

### 6.1 Session and turn lifecycle (`app/session.py`)

One `Session` per phone connection (keep the scaffold class; most plumbing is good). Changes:

1. **Headless session.** `Session(ws=None)` must work: `send()` becomes a no-op when `ws is None`, but mirror events and laptop audio still happen. `main.py` creates one headless session at startup and uses it whenever no phone is connected. When a phone connects it becomes the active session; when it disconnects, fall back to the headless one. Frames from the laptop PTT path (6.8) feed whichever session is active. This lets the full voice loop be demoed and tested from the mirror page alone.
2. **Turn = PTT down → PTT up.** On `ptt down`: cancel any in-flight turn task (barge-in, see 4), then `self.stt_turn = await stt.start_turn(rate)`. On each `audio` while a turn is open: `await self.stt_turn.feed(pcm)`. On `ptt up`: spawn `self.finish_turn()`, which does `text = await self.stt_turn.finish()` then `handle_utterance(text)`. If `start_turn` fails, buffer audio locally and give up with "Sorry, I couldn't hear that." on `up`. Audio rate: take it from the first `audio` message of the turn (default 8000). **Because `start_turn` needs the rate, open the STT stream lazily on the first audio chunk**, buffering until then.
3. **Reply streaming.** Replace `say(text)` usage in `handle_utterance` with `await self.speak(sentences)` where `sentences` is an async iterator of sentence strings. `speak()` caps at 2 sentences, filters each through safety, synthesises each with TTS, and sends one `say` per sentence. Simple handlers that return a string are wrapped into a one- or two-item iterator. Describe uses Claude streaming (6.6) so sentence 1 is spoken while sentence 2 is still generating.
4. **Barge-in.** Track `self.turn_task`. A new `ptt down` cancels it (stop speaking stale answers). Hazard warnings are never cancelled.
5. **Hazard priority.** Hazard `say` must not wait behind a slow non-urgent TTS call. Synthesis happens outside `send_lock`; only the WebSocket send is locked (already true; keep it that way). Hazard audio is always from the cache.
6. **Ingest loop** (C-8): every frame, compute a 16×12 grayscale thumbnail; ingest when `now - last_ingest ≥ INGEST_EVERY_S` (3 s) **or** mean absolute difference vs the last ingested thumbnail > `SCENE_CHANGE_THRESHOLD` (default 18 on 0–255) and `now - last_ingest ≥ 1 s`. Fire-and-forget with `spawn()`; never await memory on the frame path. Skip snap frames (they are larger and duplicates).
7. **Turn log.** At the end of each turn, append one JSON line to `logs/turns.jsonl`: `{ts, transcript, intent, route_source, stt_ms, route_ms, handler_ms, first_audio_ms, total_ms, reply, banned_blocked}`. `first_audio_ms` = PTT up (or text arrival) → first `say` sent. Hazards log `{ts, kind:"hazard", text, lag_ms}`. This is how PRD latency targets get measured.
8. Keep `do_<intent>` handlers and their messages. Small fixes:
   - `do_remember`: pass the raw utterance as `label` (memory parses "this is my brother Sam").
   - `do_confirm`: if nothing is pending, say "There's nothing waiting for a yes right now." (keep).
   - `do_browser`: speak "Working on it." immediately (pre-generated), then await `/task`.
   - `do_other`: Claude Haiku text answer, two sentences, 4 s timeout, "Sorry, I didn't catch what you need." on failure.
   - Router gets `pending_confirm=self.pending_task_id is not None` (keep).

### 6.2 Speech to text (`app/stt.py`): Cartesia Ink-2 streaming

Verified against docs.cartesia.ai on Oct 23 2026 (`/api-reference/stt/stt.md`). Re-check field names if a call fails.

- URL: `wss://api.cartesia.ai/stt/websocket?model=ink-2&encoding=pcm_s16le&sample_rate={rate}&cartesia_version={CARTESIA_VERSION}` plus repeated `&keyterm=` params.
- Auth: header `X-API-Key: {CARTESIA_API_KEY}` (server side).
- `CARTESIA_VERSION` default `2026-08-14` (the scaffold's `2025-04-16` is outdated).
- Send audio as **binary** frames of raw pcm16, ~100 ms each (re-chunk what the phone sends).
- On PTT up send the text message `finalize`. Collect every `{"type":"transcript","is_final":true,"text":...}` and **concatenate `text` exactly as received** (no strip, no added spaces; deltas carry their own whitespace). Stop at `{"type":"flush_done"}`. Then send `close` and close the socket. `{"type":"error"}` → raise.
- Keyterms (Ink-2 supports up to 100): `Sam, keys, crosswalk, signal, Palace of Fine Arts, email, send it, I'm lost` plus anything in `STT_KEYTERMS` (comma-separated env).
- Interface (this is the seam tests fake):

```python
class SttTurn(Protocol):
    async def feed(self, pcm: bytes) -> None: ...
    async def finish(self) -> str: ...     # final transcript, "" if nothing
    async def cancel(self) -> None: ...

async def start_turn(rate: int) -> SttTurn   # raises if no key / connect fails
```

- Use the `websockets` package (already a dependency). Run a receiver task per turn that collects finals into a buffer and sets an event on `flush_done`. `finish()` = send `finalize`, wait for the event with a 3 s timeout, return the buffer stripped of leading/trailing whitespace.
- Open the socket on the first audio chunk of the turn (6.1-2) so connection setup overlaps with the wearer talking.
- Delete the scaffold's guessed `POST /stt` batch call.

### 6.3 Router (`app/router.py`)

Order: **confirm short-circuit → Jev → Claude → keywords** (keep the scaffold shape).

**Jev** (verified against docs.typesafe.ai quickstart, Oct 23 2026): use `httpx`, not the SDK, so it stays async and needs no new dependency.

```
POST https://api.typesafe.ai/v1/systemone
Authorization: Bearer {TYPESAFE_API_KEY}
Content-Type: application/json

{
  "model": "jev-latest",
  "state": "<utterance>"   (prefix "A draft is waiting for yes or no. " when pending_confirm),
  "questions": {
    "intent": {
      "type": "choice",
      "instructions": "What does a blind user wearing camera glasses want from this spoken request?",
      "criteria": {
        "describe": "Wants to know what is around or in front of them",
        "signal":   "Asks about a pedestrian signal, walk sign, traffic light or crosswalk",
        "recall":   "Asks about something seen earlier, like where they left an object or what someone wore",
        "remember": "Introduces a person or asks to remember something",
        "lost":     "Says they are lost or need help from family",
        "browser":  "Wants a task done on the laptop or web, like sending an email",
        "confirm":  "Answers yes or no to a pending draft",
        "task":     "Work mode: checks whether a held item is the right one for an order",
        "other":    "Anything else, small talk or a general question"
      }
    }
  }
}
→ {"answers": {"intent": {"type":"choice","choice":"recall","confidence":0.93,"probabilities":{...}}}, ...}
```

- Use `answers.intent.choice` if `confidence ≥ JEV_CONFIDENCE_THRESHOLD` (start at 0.6; tune with the 20-phrase test). Timeout 0.8 s. Any error → treat as unavailable.
- **Claude fallback**: keep the scaffold prompt; model `ROUTER_FALLBACK_MODEL` (Sonnet), `max_tokens=5`, 2 s timeout. If Sonnet's latency busts the < 500 ms router target in practice, set `ROUTER_FALLBACK_MODEL=claude-haiku-5-5` in `.env`; no code change.
- **Keywords**: keep the scaffold rules; extend to pass all 20 test phrases.
- `route()` returns `(intent, source, ms)`; mirror shows source.

### 6.4 Text to speech (`app/tts.py`): Cartesia Sonic-3.5

- Use REST per sentence: `POST https://api.cartesia.ai/tts/bytes`, headers `X-API-Key`, `Cartesia-Version: {CARTESIA_VERSION}`, body `{"model_id": "sonic-3.5", "transcript": text, "voice": {"mode":"id","id": CARTESIA_VOICE_ID}, "language":"en", "output_format": {"container":"raw","encoding":"pcm_s16le","sample_rate": 24000}}`. Response body is raw PCM. (The scaffold already does this; confirm the path and the version header on the first live run. The TTS WebSocket at `wss://api.cartesia.ai/tts/websocket` with `context_id`/`continue` is the documented upgrade if first audio is too slow; do not start there.)
- Per-sentence calls already give "streamed" first audio: sentence 1 plays while sentence 2 is synthesised.
- **Disk cache**: `cache/tts/{sha1(model|voice|rate|text)}.pcm`. Look up memory → disk → network. Write after every successful call.
- **Pre-generate at startup** (background task, reported in `/health` as `tts_cached: n/total`): all hazard phrases (6.5) plus fixed lines: "Working on it.", "Got it, I'll remember that.", "I've let your family know where you are.", every `UNAVAILABLE` string, `NO_FRAME`, `VISION_DOWN`, the safety `FALLBACK`, "Sorry, I couldn't hear that.", "There's nothing waiting for a yes right now.". With the disk cache, hazards keep working with wifi down after the first successful boot.
- Voice: pick a calm, clear voice in the Cartesia playground and put its id in `CARTESIA_VOICE_ID`. (`GET https://api.cartesia.ai/voices` lists ids.)
- Return `""` when TTS is unavailable (keep the contract behaviour).
- Interface (test seam): `async def synth(text: str) -> str` (base64 pcm16 at `TTS_RATE`, or `""`).

### 6.5 Hazard loop (`app/hazards.py`)

Keep YOLO nano and the overall rule. Refactor so the decision logic is a pure, unit-testable function:

```python
@dataclass
class Box: cls: str; conf: float; x1: float; y1: float; x2: float; y2: float   # normalised 0..1

class HazardTracker:
    def decide(self, boxes: list[Box], now: float) -> str | None   # pure, no I/O
class HazardDetector:                                             # I/O wrapper
    def load(self) -> None                                        # YOLO(config.YOLO_MODEL); imgsz=320
    def detect(self, jpeg_b64: str) -> list[Box]                  # decode + model; the test seam
    def check(self, jpeg_b64: str, now: float) -> str | None      # detect → tracker.decide
```

Rule in `decide()` (tune on fixtures, start here):

- Classes: `person, bicycle, motorcycle, car, bus, truck, chair, couch, bench, dining table` with conf ≥ 0.4. **`DEMO_MODE=true` drops `person`** (people walking past the shared judging table must not trigger warnings) and raises `MIN_AREA`.
- In path: box centre x within 0.2–0.8 and box bottom y ≥ 1/3 of the frame.
- Large: area ≥ `MIN_AREA` (0.06 normal, 0.10 demo mode).
- Growing: compare against the largest same-class area seen **~0.6 s ago** (keep a short per-class history deque of `(t, area)`), require ratio ≥ 1.15. Comparing against only the previous frame (scaffold) is too noisy at 5 fps.
- **Very close** override: area ≥ 0.35 and in path → warn even if not growing (the wearer stopped right in front of it).
- Cooldown: `HAZARD_COOLDOWN_S` (3 s) per class.
- Choose the largest qualifying box.

Wording (PRD: "Stop, chair ahead, slightly left."):

| centre x | phrase |
|---|---|
| < 0.35 | `Stop, {name} on your left.` |
| 0.35–0.45 | `Stop, {name} ahead, slightly left.` |
| 0.45–0.55 | `Stop, {name} ahead.` |
| 0.55–0.65 | `Stop, {name} ahead, slightly right.` |
| > 0.65 | `Stop, {name} on your right.` |

`all_phrases()` returns every name × direction for pre-generation.

Runtime: run `check()` via `asyncio.to_thread`; skip frames while one is in flight (keep `hazard_busy`); rate cap `HAZARD_FPS`. On Apple Silicon ultralytics picks `mps` automatically; log the measured inference ms at startup with one dummy frame and show it in `/health`. If ~5 fps doesn't hold, drop `imgsz` to 256. Model file `yolov8n.pt` downloads on first run; run once on good wifi before the event and keep the `.pt` (git-ignored). If the hazard ever reaches the mirror, emit `hazard {text, lag_ms, box}` so the mirror can draw the box.

### 6.6 Vision (`app/vision.py`, `app/llm.py`)

Anthropic Python SDK, `AsyncAnthropic`. Before sending, re-encode the frame to ≤ 768 px on the long edge, JPEG q=80 (cv2) to keep upload time low.

**Describe (C-6)**: `VISION_MODEL` (Haiku), `max_tokens=90`, streamed with `client.messages.stream(...)`. `llm.stream_sentences()` yields each completed sentence as soon as its terminal `.`/`!`/`?` arrives, so TTS starts on sentence 1. Overall timeout 6 s. Keep the scaffold system prompt, add: "Use clock-free directions: left, ahead, right. Mention distance only as near or far. No preamble."

**Signal (C-7)**: do not let the model write the spoken sentence. Ask for JSON and compose the sentence in code, so wording is controlled and can never include banned phrases:

```
system: You read pedestrian signals for a blind person. Look only at what is visible.
        Reply with JSON only: {"signal": "walk" | "dont_walk" | "countdown" | "unclear" | "none",
        "countdown": <int or null>, "vehicles": [{"motion": "moving"|"stopped", "from": "left"|"right"|"ahead"}]}
```

Compose:
- walk → "The walk sign is on." · dont_walk → "The signal shows don't walk." · countdown → "The signal is counting down, {n} seconds." · unclear → "I can't read the signal clearly." · none → "I don't see a pedestrian signal."
- second sentence from moving vehicles only: one → "A car is moving from your {from}." ; several → "Cars are moving from your left and right." ; none moving → omit.
- On JSON parse failure → "I can't read the signal clearly."
- Model: `SIGNAL_MODEL` (default = `VISION_MODEL`). `max_tokens=120`, not streamed, 6 s timeout.

**Work mode (`do_task`)**: forwards the frame to browser `/work` (Part 4 owns the logic). No Claude call in core.

### 6.7 Safety (`app/safety.py`)

- Keep the banned list; add `\bno cars?\b.*\bcross\b`, `\bit'?s fine to cross\b`, `\bwalk now\b`, `\byou'?re clear\b`.
- Filter **per sentence**: drop any sentence that matches; if nothing is left, use `FALLBACK` ("I can describe what I see, but you decide when to cross."). Log every block and count it in the turn log (`banned_blocked`).
- Keep `max_two_sentences`.

### 6.8 Mirror page (`static/mirror.html`, `app/main.py`)

Keep the existing page and add:

1. **Live frame**: core sends the latest frame to mirror clients at ≤ 2 fps (`kind:"frame", jpeg_b64`), drawn in an `<img>`. Draw the last hazard box in red for 1 s.
2. **Laptop push-to-talk**: hold **Space** (or the on-screen button) to talk through the laptop mic. Page uses `getUserMedia`, downsamples to 16 kHz pcm16 in an `AudioWorklet` (or `ScriptProcessor` for simplicity), and sends `{"ptt":"down"}`, `{"audio": b64, "rate":16000}` chunks every ~100 ms, `{"ptt":"up"}` over `/mirror/ws`. `main.py` forwards these to the active session exactly like phone messages.
3. **Typed utterances** keep working and go to the active session, headless included.
4. **Status pills** from `/health`, polled every 3 s: phone, STT, TTS (`cached n/total`), Claude, Jev, hazards (inference ms), memory up/down, browser up/down.
5. **Recall thumbnail**: if a recall response has `thumb_url`, show it.
6. Reply audio: keep the existing PCM player; urgent interrupts, non-urgent queue (do not cut off sentence 1 when sentence 2 arrives). Browser `speechSynthesis` fallback when `pcm16_b64` is empty.

### 6.9 Browser orchestration (P1) and work mode (P2)

Keep the scaffold logic: `/task` → read back → `pending_task_id` → "yes"/"no" → `/confirm`. Only P0 must pass before the Saturday 6 PM freeze; do these after section 7 step 9.

### 6.10 `/health`

Return: `ok, phones_connected, active_session (phone|headless), stt, tts, tts_cached, claude, jev, hazards, hazard_infer_ms, memory {url, up}, browser {url, up}, demo_mode`. Memory/browser `up` comes from a background `GET /health` every 5 s (1 s timeout), never from inside the request.

---

## 7. Build order

Each step lists its done-check. All checks run without teammates or keys unless marked **live**.

| Step | Work | Done when |
|---|---|---|
| 1 | Clean layout: remove superseded `stubs/`, `tools/`, `fixtures/`, `run_all.sh` if still present; create `tests/requirements.txt`, `tests/conftest.py`, `tests/fakes.py`; update `.gitignore` | `python -m pytest tests -q` passes; `grep -rn "tests" app contracts` finds no imports |
| 2 | `tests/make_fixtures.py` and fixtures (8.4) | fixture files exist; `transcripts.json` lists the phrases |
| 3 | Headless session + `turnlog.py` + `test_session_e2e.py` first cases (text in → say out with stubs) | e2e tests for recall, lost, browser+yes, memory down pass |
| 4 | Hazard refactor (`decide()`), new wording, `test_hazards.py`, `ColorDetector` fake | unit tests pass; offline demo beat 1 passes |
| 5 | Safety per-sentence + `test_safety.py` | passes |
| 6 | Streaming STT turn interface + `FakeSTT`; session PTT flow | e2e PTT test (WAV fixture → transcript → reply) passes offline; **live**: `smoke_apis.py stt` gets ≥ 4/5 phrases right on the 8 kHz WAVs |
| 7 | TTS rewrite: per-sentence, disk cache, pre-generation; `speak()` | e2e test sees 2 `say` messages for a 2-sentence reply; **live**: `smoke_apis.py tts` writes a playable WAV |
| 8 | Vision rewrite: streamed describe, JSON signal; `FakeLLM` | e2e describe/signal pass offline; **live**: `smoke_apis.py vision` on the crosswalk and room fixtures |
| 9 | Jev in router; extend `test_router.py` to 20 phrases | keyword router ≥ 18/20 offline; **live**: `smoke_apis.py jev` ≥ 18/20 with median < 500 ms |
| 10 | Ingest on scene change; `/health` upgrade; memory/browser health poller | e2e: stub `/_log` shows ingests at ≥ 1 per 3 s and an extra one after a scene cut |
| 11 | Mirror page additions (6.8) | manual: typed + Space-bar PTT both produce spoken replies; frame preview live |
| 12 | `tests/demo_script.py` (8.6) all beats, then README update | `python -m tests.demo_script --offline` all PASS; then with keys, `--live` all PASS |

Milestones from PRD 2 (PT): Fri 9 PM contracts + `/stream` + `/health` (done in scaffold) · Fri 11 PM speech in/out working · Sat 10 AM router live, first e2e with real services · **Sat 6 PM freeze**: hazards, describe, signal, mirror · Sun 7 AM demo script run twice on the demo laptop.

---

## 8. Test strategy (no other parts needed)

Three layers, all inside `core/tests/`:

1. **Unit** (pytest, pure functions): router, safety, hazard `decide()`, contracts, signal sentence composer.
2. **In-process end to end** (pytest): FastAPI `TestClient` opens `/stream`, external APIs replaced by fakes, memory/browser replaced by the stub apps mounted in-process. No ports, no network, runs in seconds.
3. **Running system**: `tests/demo_script.py` drives the real server over a real WebSocket through the scripted demo beats, in `--offline` (all fakes) or `--live` (real keys) mode.

Plus `tests/smoke_apis.py` for one real call per API when keys exist.

### 8.1 Fakes (`tests/fakes.py`)

All fakes implement the same seams the app exposes. Install them by patching module attributes (`monkeypatch.setattr` in pytest; plain assignment in `run_offline.py`).

| Seam patched | Fake | Behaviour |
|---|---|---|
| `app.stt.start_turn` | `FakeSTT` | Accumulates fed PCM; on `finish()` returns `transcripts.json[sha1(pcm)]`, else `""`. Lets PTT be tested end to end with real audio bytes and deterministic text. |
| `app.llm.ask`, `app.llm.stream_sentences` | `FakeLLM` | Keyed on the system prompt: describe → "A chair is ahead, slightly left. A table is on your right."; signal → `{"signal":"walk","countdown":null,"vehicles":[{"motion":"moving","from":"left"}]}`; router → keyword result; other → "I'm here to help. Ask me what's around you." A `FakeLLM(bad=True)` variant returns "It is safe to cross now." to prove the filter. 150 ms artificial delay. |
| `app.tts.synth` | `FakeTTS` | Returns 0.3 s of 24 kHz silence per sentence (non-empty, so the say path and audio player are exercised) or `""` with `FakeTTS(empty=True)`. |
| `app.router.jev_route` | `FakeJev` | Uses the keyword router with confidence 0.9, or returns `None` to test fallback. |
| `app.hazards.detector.detect` | `ColorDetector` | No YOLO needed. Finds pure-magenta (`#FF00FF`) pixels with `cv2.inRange` and returns one `Box(cls="chair", conf=0.9, …)` around them. Synthetic frames from `make_fixtures.py` draw a growing magenta rectangle, so the full hazard pipeline (decode → detect → decide → cached TTS → urgent say) runs deterministically. |
| memory/browser clients | in-process stubs | Patch `app.clients.memory._client` / `browser._client` to return `httpx.AsyncClient(transport=httpx.ASGITransport(app=stub_app), base_url="http://stub")`. A "memory down" case points at an app that raises or at a closed port. |

`tests/run_offline.py`: installs every fake globally, then `uvicorn.run(app.main.app, port=8000)`. With `tests/run_with_stubs.sh`'s stub processes (or `--with-stubs`, which starts them as subprocesses) this is a full system needing no keys and no YOLO.

### 8.2 `tests/fake_glasses.py` (keep, add)

Already: webcam / `--video` / `--images`, typed lines as `text` messages, `/ptt` mic recording, snap replies. Add:
- `/wav <file>`: sends `ptt down`, the WAV's PCM in 100 ms `audio` chunks at real-time pace, `ptt up`.
- `--rate 8000|16000` for `/ptt` and `/wav` (8000 mimics the glasses HFP mic).
- Print latency from PTT up to first `say` received.

### 8.3 Stubs (`tests/stubs/`)

Keep the canned answers (PRD: recall → "Your keys are on the table, 3:42 PM."; task → needs_confirm + fixed draft). Add test-only endpoints:
- `GET /_log` → every request received (`endpoint, ts, body without jpeg`). Lets tests assert that ingest happened, alerts carried the note, `/confirm` got `yes=true`.
- `POST /_fail {"on": true}` on the memory stub → all endpoints return 503. Lets the demo script test "memory down" without killing processes.
- Optional: `STUB_LATENCY_MS` env to simulate slow services.

### 8.4 Fixtures (`tests/make_fixtures.py`, `tests/fixtures/`)

Generated (committed `transcripts.json`; media git-ignored, regenerated on demand):
- `chair_walk/0000.jpg…` 25 frames (5 s at 5 fps): grey background, magenta rectangle centred at x≈0.42, bottom in the lower third, area growing from 0.03 to 0.30. Expected: one "Stop, chair ahead, slightly left." between frames ~8 and ~12, and no repeat within 3 s.
- `clear_path/` 150 frames (30 s): no magenta. Expected: zero warnings (false-warning metric).
- `scene_cut/`: 10 frames of one solid colour then 10 of another (scene-change ingest).
- `audio/*.wav`: the demo phrases spoken at 8 kHz mono s16le. On macOS: `say -o x.aiff "<phrase>"` then `afconvert -f WAVE -d LEI16@8000 x.aiff x.wav`. Also a 16 kHz copy. `transcripts.json` maps `sha1(pcm)` → phrase and `file` → phrase. Phrases: "what's in front of me", "what does the signal say", "where did I put my keys", "email Sam that I'm at the Palace of Fine Arts", "yes send it", "I'm lost", "this is my brother Sam".

Recorded by Kevin (for `--live`; ask him, 10 minutes of work):
- `real/chair_walk.mp4`: phone or webcam held at eye height walking toward a real chair (YOLO test).
- `real/crosswalk_walk.jpg`, `real/crosswalk_dont_walk.jpg`, `real/crosswalk_countdown.jpg`: photos of a pedestrian signal (or the looping crosswalk footage on a monitor, as at the table). C-7 needs 5 of 5 correct.
- `real/room.jpg`, `real/keys_on_table.jpg`.
- `real/audio/*.wav`: Kevin saying the demo phrases into the glasses mic if available, else the phone.

### 8.5 Live API smoke tests (`tests/smoke_apis.py`)

`python -m tests.smoke_apis [all|stt|tts|vision|jev|yolo]`. Each check prints PASS/FAIL/SKIP (SKIP when its key is missing) and its latency:
- **stt**: each `audio/*.wav` through `stt.start_turn` → compare to `transcripts.json` (normalised: lowercase, no punctuation). Pass at ≥ 4/5 (C-2).
- **tts**: synth "Stop, chair ahead, slightly left." → write `out/tts.wav`, report ms.
- **vision**: describe `real/room.jpg`; signal on each `real/crosswalk_*.jpg` against the state in the filename; time-to-first-sentence and total.
- **jev**: the 20 labelled phrases from `test_router.py` → accuracy and median ms.
- **yolo**: load model, run `real/chair_walk.mp4` frames through the real detector + `decide()`, report inference ms and when the warning fired.

### 8.6 Scripted demo beats (`tests/demo_script.py`)

`python -m tests.demo_script --offline` (starts stubs + `run_offline` itself as subprocesses, tears them down after) or `--live` (assumes `bash tests/run_with_stubs.sh` is running with real keys, or `--memory-url/--browser-url` pointing at real services). Flags: `--audio` sends WAVs over PTT instead of `text` messages, to exercise STT. `--only N` runs one beat.

It connects to `/stream` like the phone, streams the beat's frames at 5 fps, answers snaps, sends the utterance, and asserts on the `say` messages it receives:

| # | Beat | Frames | Utterance | Pass if |
|---|---|---|---|---|
| 1 | Chair hazard | `chair_walk/` (offline) or `real/chair_walk.mp4` (live) | none | an `urgent` say matching `^Stop, chair` arrives; lag from the triggering frame < 1 s; no repeat within 3 s |
| 2 | Signal | crosswalk image | "what does the signal say" | intent `signal`; reply matches `walk|don't walk|counting down|can't read`; no banned phrase; first say < 3.5 s |
| 3 | Keys recall | `keys_on_table` for 6 s first (so ingest fires), then room | "where did I put my keys" | stub `/_log` shows ≥ 1 ingest; reply contains "keys"; first say < 2 s (offline) |
| 4 | Email | room | "email Sam that I'm at the Palace of Fine Arts", then "yes send it" | "Working on it." then a read-back containing "send"; after "yes", reply "Sent."; stub log shows `/confirm yes=true` |
| 5 | Lost | room | "I'm lost" | reply mentions family; stub log shows `/alert kind=lost` |
| 6 | Memory down | room | `POST /_fail on`, then "where did I put my keys" | reply is exactly "Memory isn't available right now." within `SERVICE_TIMEOUT_S + 1` s; then `/_fail off` |
| 7 | Describe | room | "what's in front of me" | 1–2 says; first < 3.5 s; no banned phrase |
| 8 | Clear path | `clear_path/` 30 s | none | ≤ 1 hazard warning (PRD false-warning target) |
| 9 | Banned phrase | room, with `FakeLLM(bad=True)` (offline only) | "what does the signal say" | reply is the safety fallback; turn log `banned_blocked > 0` |

Output: a table of beat, PASS/FAIL, first-audio ms, total ms; exit code 1 on any FAIL. This is the rehearsal script for every checkpoint, and the same beats are the live pitch (team plan: chair, crosswalk, keys, email, "I'm lost").

### 8.7 pytest suite (`python -m pytest tests -q`, offline, < 30 s)

- `test_router.py`: 20 labelled phrases (fill from section 8.4 phrases plus variants like "is it walk", "what's around me", "where are my keys", "send an email to Sam", "nope", "help me", "who is this", "check this item"); keyword ≥ 18/20; confirm short-circuit when pending; Jev below threshold falls back.
- `test_safety.py`: each banned phrase blocked; sentence-level drop keeps the clean sentence; all-banned → FALLBACK; max two sentences.
- `test_hazards.py`: growing centred box warns once; static box doesn't; off-centre doesn't; top-of-frame doesn't; cooldown; very-close override; demo mode ignores person; direction table; phrase wording.
- `test_contracts.py`: every inbound type parses; unknown type raises; outbound JSON shapes match CONTRACTS.md; signal JSON → sentence composer cases.
- `test_session_e2e.py`: with `TestClient`: text → recall reply; PTT with WAV bytes → FakeSTT → reply; 2-sentence describe → 2 says in order; snap request answered vs timeout fallback; browser task + yes; confirm with nothing pending; memory down message; hazard frames → urgent say; scene change triggers extra ingest; headless session reply via `/mirror/ws` text.

---

## 9. Configuration (`.env.example` additions)

```
CARTESIA_VERSION=2026-08-14
CARTESIA_STT_MODEL=ink-2
CARTESIA_TTS_MODEL=sonic-3.5
STT_KEYTERMS=Sam,Palace of Fine Arts
SIGNAL_MODEL=claude-haiku-5-5
JEV_MODEL=jev-latest
JEV_TIMEOUT_S=0.8
ROUTER_FALLBACK_TIMEOUT_S=2
VISION_TIMEOUT_S=6
SCENE_CHANGE_THRESHOLD=18
MIRROR_FRAME_FPS=2
```

Keys Kevin must supply in `core/.env` for `--live`: `ANTHROPIC_API_KEY`, `CARTESIA_API_KEY`, `CARTESIA_VOICE_ID`, `TYPESAFE_API_KEY`. Never commit `.env`.

`requirements.txt` (runtime): fastapi, uvicorn[standard], websockets, httpx, pydantic, python-dotenv, anthropic, numpy, opencv-python, ultralytics. `tests/requirements.txt`: pytest, sounddevice (optional, for `/ptt`).

---

## 10. Demo-day runbook (for the README, step 12)

1. Laptop on ethernet. `cd core && source .venv/bin/activate`.
2. `python -m tests.smoke_apis all`: every live service PASS.
3. Start core against the real teammates (`MEMORY_URL`, `BROWSER_URL` in `.env`): `uvicorn app.main:app --host 0.0.0.0 --port 8000`. If a teammate's service isn't ready, `bash tests/run_with_stubs.sh` instead.
4. Open `http://localhost:8000/mirror` on the judge-facing screen, click **Enable audio**, check every status pill is green and `tts_cached` is full.
5. `DEMO_MODE=true` at the shared table.
6. Phone relay connects to `ws://<laptop-ip>:8000/stream`. If it can't, use the mirror's Space-bar push-to-talk and the stage webcam (Q1).
7. Run `python -m tests.demo_script --live --only 3` against the real memory service once to confirm the keys beat.

---

## 11. Open questions for Kevin (do not block on these; use the default)

- **Q1 Stage webcam fallback.** `tests/fake_glasses.py` is test-only by your rule. If the glasses fail at the midnight gate, the stage needs a webcam sender. Default: Part 1 owns it (PRD 1 G-11). If they don't, it should move to a non-test location.
- **Q2 Split `say` messages.** Part 1 must queue non-urgent says (section 4). Default: assume yes; if not, `speak()` can join both sentences into one `say` behind a `SAY_SPLIT=false` flag.
- **Q3 Hazards off.** If YOLO can't load, should core say "Obstacle warnings are off" once at connect? Default: yes, once.
- **Q4 Jev key.** Whose TypeSafe key, and its rate limits (team plan open question). Default: Claude fallback covers it.
- **Q5 Demo laptop.** OS and GPU decide the YOLO size; default nano at `imgsz=320`.
