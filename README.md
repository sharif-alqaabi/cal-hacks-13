# cal-hacks-13: a voice-first assistant on Meta Ray-Ban glasses

For blind and low-vision adults who work. The glasses stream what the wearer sees and hears to a laptop, and the
assistant answers out loud: it warns about obstacles ahead, reads pedestrian signals, remembers where things were
put down and what people were wearing, and sends an email or looks something up on the laptop, asking before
anything irreversible. A live family dashboard lets someone the wearer trusts see alerts and step in.
It works **alongside the cane, not instead of it**, and it never tells anyone a crossing is "safe".

## How it fits together

```
Meta Ray-Ban glasses --Bluetooth--> phone app --WebSocket /stream--> core :8000 (voice, router, hazards, describe)
                                                                       |-- HTTP --> memory  :8001 (timeline, recall) --> SpacetimeDB, Moss
                                                                       |-- HTTP --> browser :8002 (laptop agent)    --> Chrome (Jev Ultrafast)
family dashboard (React) <-- SpacetimeDB subscriptions
```

Four services, one owner each, connected only through the contracts in [`core/contracts/`](core/contracts/CONTRACTS.md).
Every service answers `GET /health`, and each can run alone against stubs or fakes.

| Folder | Service | Port | Run | README |
|---|---|---|---|---|
| `phone/` | Glasses relay app (Meta Wearables Device Access Toolkit) | | _phone owner: fill in_ | |
| [`core/`](core) | Voice loop, intent router, hazards, describe/signal, judges' mirror page | 8000 | `uvicorn app.main:app --port 8000` | [core/README.md](core/README.md) |
| [`memory/`](memory) | Frame captions, timeline, recall, "I'm lost" alerts | 8001 | `uvicorn app:app --port 8001` | [memory/.env.example](memory/.env.example) |
| `dashboard/` | Family dashboard | | _memory owner: fill in_ | |
| [`browser/`](browser) | Laptop agent: email and lookups by voice, confirm before sending | 8002 | `uv run uvicorn app:app --port 8002` | [browser/README.md](browser/README.md) |

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
| **Claude Haiku 5.5** | `core/app/vision.py`, `memory/captions.py` | Scene descriptions, pedestrian-signal reading (as JSON, so the spoken wording is fixed), frame captions for memory |
| **Claude Sonnet 5.5** | `core/app/router.py`, `browser/` | Router fallback; parsing laptop requests, email read-back summaries, lookup answers, work-mode item checks |
| **Moss** | `memory/moss_index.py` | Semantic and keyword search over captions for "where did I put my keys?" |
| **SpacetimeDB** | `memory/spacetimedb/`, `memory/stdb.py`, dashboard | The memory timeline (moment, person, alert tables) and the live family dashboard's subscriptions |
| **Ultralytics YOLO** (local) | `core/app/hazards.py` | Obstacle warnings on the laptop with no network round trip |

### Cartesia features used

- **Ink-2 streaming STT**: raw 8 kHz (glasses) or 16 kHz (phone) PCM over the WebSocket, `finalize` on push-to-talk
  release (then wait for `flush_done`), transcripts concatenated from `is_final` messages, and keyterms that bias
  recognition toward the demo's names and phrases ("Sam", "Palace of Fine Arts", "I'm lost").
- **Sonic-3.5 TTS** at 24 kHz PCM: one request per sentence, a disk cache keyed by model/voice/text, and fixed phrases
  (every hazard warning, "Working on it.", every "isn't available" line) pre-generated at startup so warnings
  play instantly and keep working if the wifi drops.
- Urgent replies (hazards) interrupt whatever is playing; normal replies queue in order.

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
- Memory only knows what the camera saw while streaming, and answers from captions, not from the original frames.
- The laptop agent works in Chrome on Gmail and Google search only. Jev Ultrafast does not support iframes, shadow roots,
  canvas, uploads or pop-up tabs, and it never signs in, pays, buys or uploads.
- _Owners: add anything specific to the phone app and dashboard._

## Team

_Add all four teammates and their roles (also on Devpost)._
