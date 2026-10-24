# cal-hacks-13

Assistive smart glasses for blind and low-vision people. To run everything, see [how-to-run.md](how-to-run.md).

A voice-first assistant on Meta Ray-Ban glasses for blind and low-vision adults who work. The glasses stream what the
wearer sees and hears to a laptop, and the assistant answers out loud: it warns about obstacles ahead, reads pedestrian
signals, remembers where things were put down and what people were wearing, and sends an email or looks something up
on the laptop, asking before anything irreversible. A live family dashboard lets someone the wearer trusts see alerts
and step in. It works **alongside the cane, not instead of it**, and it never tells anyone a crossing is "safe".

## How it fits together

```
Meta Ray-Ban glasses --Bluetooth--> phone app --WebSocket /stream--> core :8000 (voice, router, hazards, describe)
                                                                       |-- HTTP --> memory  :8001 (timeline, recall) --> SpacetimeDB, Moss
                                                                       |-- HTTP --> browser :8002 (laptop agent)    --> Chrome (Jev Ultrafast)
family dashboard (React) <-- SpacetimeDB subscriptions
```

Four services, one owner each, connected only through the contracts in [`core/contracts/`](core/contracts/CONTRACTS.md).
Every service answers `GET /health`, and each can run alone against stubs or fakes.

| Folder | What | Port | Details |
|---|---|---|---|
| `phone/` | Glasses relay app (Meta Wearables Device Access Toolkit) | | _phone owner: fill in_ |
| [`core/`](core) | Voice loop, intent router, hazards, describe/signal, judges' mirror page | 8000 | [core/README.md](core/README.md) |
| [`memory/`](memory) | Frame captions, timeline, recall, "I'm lost" alerts | 8001 | [below](#memory-moss-and-spacetimedb) |
| [`dashboard/`](dashboard) | Family dashboard (React, SpacetimeDB subscriptions) | 5173 in dev, or served by memory at 8001 | [dashboard/README.md](dashboard/README.md) |
| [`browser/`](browser) | Laptop agent: email and lookups by voice, confirm before sending | 8002 | [browser/README.md](browser/README.md) |

Setup for every service: copy its `.env.example` to `.env` and add keys. `.env` is git-ignored and no key is
committed anywhere. Each service degrades to a spoken "isn't available right now" rather than going silent.

## Where each sponsor tool is used

| Tool | Where | What it does |
|---|---|---|
| **Meta Wearables Device Access Toolkit** | `phone/` | Camera frames (~5 fps), microphone and speakers of the Ray-Ban glasses; the glasses are the only interface |
| **Cartesia Ink-2** (speech to text) | `core/app/stt.py` | Streaming STT over WebSocket, one stream per push-to-talk turn, with keyterms ("Sam", "Palace of Fine Arts") |
| **Cartesia Sonic-3.5** (text to speech) | `core/app/tts.py` | Every spoken reply, synthesized per sentence so the first sentence plays while the next is generated |
| **TypeSafe Jev** | `core/app/router.py` | One typed decision per utterance: describe, signal, recall, remember, lost, browser, confirm, task, other |
| **Jev Ultrafast** (Browser Use, built on Jev) | `browser/` | Drives Chrome on the laptop: picks one operation and one page element per step |
| **Claude Haiku 5.5** | `core/app/vision.py`, `memory/captions.py` | Scene descriptions, pedestrian-signal reading (as JSON, so the spoken wording is fixed), frame captions and recall answers for memory |
| **Claude Sonnet 5.5** | `core/app/router.py`, `browser/` | Router fallback; parsing laptop requests, email read-back summaries, lookup answers, work-mode item checks |
| **Moss** | `memory/moss_index.py` | Semantic and keyword search over captions for "where did I put my keys?" |
| **SpacetimeDB** | `memory/spacetimedb/`, `memory/stdb.py`, `dashboard/` | The memory timeline (moment, person, alert, recall tables) and the live family dashboard's subscriptions |
| **Ultralytics YOLO** (local) | `core/app/hazards.py` | Obstacle warnings on the laptop with no network round trip |

### Cartesia features used

- **Ink-2 streaming STT**: raw 8 kHz (glasses) or 16 kHz (phone) PCM over the WebSocket, `finalize` on push-to-talk
  release (then wait for `flush_done`), transcripts concatenated from `is_final` messages, and keyterms that bias
  recognition toward the demo's names and phrases ("Sam", "Palace of Fine Arts", "I'm lost").
- **Sonic-3.5 TTS** at 24 kHz PCM: one request per sentence, a disk cache keyed by model/voice/text, and fixed phrases
  (every hazard warning, "Working on it.", every "isn't available" line) pre-generated at startup so warnings
  play instantly and keep working if the wifi drops.
- Urgent replies (hazards) interrupt whatever is playing; normal replies queue in order.

## Memory: Moss and SpacetimeDB

The glasses remember what they see, so the wearer can ask "where did I put my keys?" or "what was Sam wearing?" without having told them to remember anything. A family member watches alerts and answers live on a dashboard.

```
glasses → core ──/ingest every ~3 s──▶ memory (:8001) ──Claude Haiku──▶ caption JSON
                                          │                              │
                                          │                  ┌───────────┴───────────┐
                                          │                  ▼                       ▼
                                          │          SpacetimeDB (maincloud)    Moss index
                                          │          moment/person/alert/recall  one doc per object,
                                          │                  │                  person, scene, fact
            core ──/recall {question}────▶│◀─── top hits ────┼──────────────────────┘
                 ◀── {answer, ts, thumb} ─┘                  │ live subscription
                                                             ▼
                                                  family dashboard (React, :8001/)
```

### Moss: the agent's recall

- **What goes in.** Every kept frame is captioned by Claude Haiku 5.5 into JSON: objects with color, size and the surface they're on, people and their clothing, the place, and any sign text. Each moment becomes several Moss docs (`<id>:scene`, `<id>:o0…`, `<id>:p0…`, `<id>:fact`), so a search for "keys" matches the keys doc instead of being diluted by the whole kitchen (`memory/moss_index.py`).
- **Search.** `/recall` runs one hybrid keyword-plus-semantic query (`alpha=0.55`, top 8). It takes about 3 ms in our logs, well inside Moss's sub-10 ms range, so it never shows in the spoken answer's latency.
- **Answering.**
  - A hit at or above `FAST_SCORE` 0.45 is answered from a template, with no model call.
  - A weaker hit is answered by Haiku from the top entries, each with its "seen at …" time.
  - Below `MIN_SCORE` 0.3 the answer is "I haven't seen that." It never guesses a location.
  - For "what color…" or "what did the sign say" questions, memory looks again at the saved frames around the best hits instead of trusting the caption (the look-back).
- **Lifetime.** The Moss index lives in the service's session and is rebuilt from SpacetimeDB at startup. SpacetimeDB is the source of truth because the dashboard deletes there. The service picks up deletions every 3 s and drops them from Moss, along with their thumbnail files.

### SpacetimeDB: the durable, live timeline

- **Module.** `memory/spacetimedb/src/index.ts` (TypeScript, SpacetimeDB 2.x) is published to maincloud as `calhacks13-memory`.
- **Public tables:**

  | Table | Columns |
  |---|---|
  | `moment` | `id, ts, caption_json, thumb_url, place_note` |
  | `person` | `name, clothing_note, last_seen_ts` |
  | `alert` | `id, ts, kind, note, resolved` |
  | `recall` | `id, ts, question, answer, thumb_url` |

- **Reducers:**
  - The memory service calls `add_moment`, `upsert_person`, `raise_alert` and `add_recall`.
  - The dashboard calls `resolve_alert`, `delete_moments_since` (the last 10 minutes) and `delete_all`.
  - `delete_moment` is used by the tests.
- **Writes from Python.** There's no Python SDK, so memory calls reducers over HTTP and reads with SQL (`memory/stdb.py`, keepalive 120 s).
- **Live push.** The dashboard (`dashboard/`) uses the TypeScript SDK's React hooks (`useTable`) and generated bindings. New moments, people, alerts and recall answers appear without a refresh. For example, an "I'm lost" alert opens a red band on the family member's phone as it happens.
- **Shortcut.** Reducers don't check who is calling yet, so anyone who knows the database name can call them. That's fine for the event. The upgrade is to store the memory service's identity in `init` and check `ctx.sender`.

### Dashboard

Build it once with `cd dashboard && npm install && npm run build`. The memory service then serves it at `http://<MEMORY_PUBLIC_URL>/`, so a phone opens one address and the thumbnails share its origin. The page is dark and phone-first, and has these sections:

- open alerts with **I'm on it**;
- what the glasses see now;
- the last question asked and its answer, with the matching photo;
- people the wearer has introduced;
- a timeline of the day;
- hold-to-forget buttons for the last 10 minutes or everything.

Alerts are announced by screen readers.

### Privacy

Memory keeps captions and small thumbnails only, never video or audio. People are named only after the wearer introduces them, and faces are never described. Everything can be deleted from the dashboard, and the demo data is wiped after the event.

### Tests

- `memory/selftest.py` and `npm test` in `dashboard/`: offline checks.
- `memory/e2e.py`: real Claude, Moss and SpacetimeDB, a few cents. It wipes the database.
- `memory/mock/drive.py seed | ask | chat`: the same flow through core, for a live demo.

## Laptop agent: Jev Ultrafast

"Email Sam that I'm at the Palace of Fine Arts" becomes a Gmail draft in Chrome, read back out loud, and sent only
after a spoken "send". Lookups ("when does the hardware store close today?") come back as one spoken sentence.
Details and setup: [browser/README.md](browser/README.md).

- **Guarded loop.** Jev Ultrafast's predict-then-act loop is split so every chosen action is checked before it runs.
  Anything labelled send, delete, buy or similar parks the task until core sends `/confirm` with `yes: true`. A second
  layer in the page itself swallows clicks on send-like buttons unless the service has just heard yes.
- **Honest results.** The read-back comes from the page's To, Subject and Body fields, not the agent's claims; after
  "send", the service checks the Sent folder before saying it went out.
- **Judges' trace.** `http://localhost:8002/trace` shows each step, the hold before Send, and the verification.
- **Never silent.** Every failure is spoken ("I got stuck on Gmail after I type in Subject. Nothing was sent.").

## Responsible design

- Never says a crossing is "safe": signal answers describe what is visible, and an output filter drops any sentence
  with a banned phrase.
- Works alongside the cane: an eye-level camera can't feel curbs, drop-offs or ground texture.
- People are labeled only when the wearer names them ("this is my brother Sam"); strangers are never identified.
- Nothing irreversible on the laptop without a spoken yes: the browser agent is stopped before every send, delete or
  buy control, reads the draft back from the page, and checks the Sent folder before saying "Sent".
- Demo accounts only: a throwaway Gmail in its own Chrome profile; no real credentials or personal email anywhere.

## Known limitations

- The glasses microphone is 8 kHz (phone-call quality); short commands and push-to-talk work best in a noisy room.
- Cloud model calls take 1 to 3 s on venue wifi; obstacle warnings run locally so they don't wait on the network.
- Obstacle warnings come from a general object detector: they cover people, bikes, cars and furniture, not curbs,
  steps or holes.
- Memory only knows what the camera saw while streaming.
- The laptop agent works in Chrome on Gmail and Google search only. Jev Ultrafast does not support iframes, shadow roots,
  canvas, uploads or pop-up tabs, and it never signs in, pays, buys or uploads. It only emails contacts listed in
  `DEMO_CONTACTS`.
- _Owners: add anything specific to the phone app._

## Team

_Add all four teammates and their roles (also on Devpost)._
