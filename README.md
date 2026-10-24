# cal-hacks-13

Assistive smart glasses for blind and low-vision people. To run everything, see [how-to-run.md](how-to-run.md).

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
