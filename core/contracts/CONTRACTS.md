# Contracts (owned by core / Engineer 2)

Pydantic models in this folder are the source of truth. Ping Eng 2 before changing anything.

## /stream WebSocket (phone relay <-> core)

| Direction | type | Fields |
|---|---|---|
| phone -> core | `frame` | `{ts, jpeg_b64, w, h, snap_id?}` ~5 fps, 640x480, JPEG q~70 |
| phone -> core | `audio` | `{ts, pcm16_b64, rate}` |
| phone -> core | `ptt` | `{state: "down" \| "up"}` |
| phone -> core | `text` | `{text}` dev/demo only, skips STT |
| core -> phone | `say` | `{id, text, pcm16_b64, rate, urgent}` urgent interrupts playback |
| core -> phone | `snap` | `{snap_id}` answer with one full-res `frame` carrying `snap_id` |

`audio.rate` is 8000 from the glasses (HFP) or 16000 from the phone mic; send ~100 ms chunks.
A reply may arrive as **two consecutive non-urgent `say` messages** (one per sentence). The phone must
**queue** non-urgent says and play them in order; an urgent say clears the queue and interrupts.
`pcm16_b64` may be `""`: speak `text` with on-device TTS.

## Memory (MEMORY_URL)

| Endpoint | Request | Response |
|---|---|---|
| POST /ingest | `{ts, jpeg_b64}` | 202 |
| POST /recall | `{question}` | `{answer, ts, thumb_url}` |
| POST /remember | `{label, ts, jpeg_b64}` | `{ok}` |
| POST /alert | `{kind: "lost"\|"help", note}` | `{ok}` |
| GET /health | | 200 |

## Browser (BROWSER_URL)

| Endpoint | Request | Response |
|---|---|---|
| POST /task | `{goal}` | `{task_id, say, needs_confirm}` |
| POST /confirm | `{task_id, yes}` | `{say}` |
| POST /work (P2) | `{utterance, jpeg_b64}` | `{say}` |
| GET /health | | 200 |

## Intent labels

`describe, signal, recall, remember, lost, browser, confirm, task, other`
