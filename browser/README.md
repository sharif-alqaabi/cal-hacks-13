# browser: laptop agent (part 4)

Lets the wearer get web tasks done by voice. "Email Sam that I'm at the Palace of Fine Arts" becomes a Gmail draft,
read back out loud, and sent only after a spoken "send". Lookups ("when does the hardware store close today?")
come back as one spoken sentence. Built on [Jev Ultrafast](https://github.com/browser-use/jev-ultrafast), which
drives Chrome through Browser Harness. Core calls it at `BROWSER_URL` (port 8002); the contract is
[`core/contracts/browser.py`](../core/contracts/browser.py).

| Endpoint | Request | Response |
|---|---|---|
| `POST /task` | `{goal}` | `{task_id, say, needs_confirm}` |
| `POST /confirm` | `{task_id, yes}` | `{say}` |
| `POST /work` (P2) | `{utterance, jpeg_b64}` | `{say}` |
| `GET /health` | | `{ok, fake, chrome, keys, contacts, pending, ...}` |
| `GET /trace` | | live step-by-step trace page for judges |

## Run it

```bash
cd browser
curl -LsSf https://astral.sh/uv/install.sh | sh     # once, if uv is missing
uv sync
cp .env.example .env                                # add keys, see below

BROWSER_FAKE=1 uv run uvicorn app:app --port 8002   # no Chrome, no keys: scripted fake Gmail (for core integration)
uv run uvicorn app:app --port 8002                  # real: Jev Ultrafast drives your Chrome
```

Then `uv run python cli.py "email Sam that I'm at the Palace of Fine Arts"` stands in for core (add `--say` to hear
replies through macOS `say`), and http://localhost:8002/trace shows every step.

## One-time setup for the real agent

1. **Keys** in `browser/.env`: `TYPESAFE_API_KEY` (Jev), `TEXT_MODEL_API_KEY` (OpenRouter, writes typed text),
   `ANTHROPIC_API_KEY` (goal parsing, read-back summaries, lookup answers, `/work`). Without the Anthropic key, rule-based
   fallbacks parse goals and read opening hours.
2. **Chrome profile**: make a dedicated Chrome profile for the demo. Sign in to a **throwaway Gmail** there,
   never a real account.
3. **Gmail settings** in that account: Settings > General > Undo send = **5 seconds** (`UNDO_SEND_S=5`);
   add a contact for Sam (a second throwaway address) and set `DEMO_CONTACTS=Sam=<that address>`. No signature.
4. **Remote debugging**: open `chrome://inspect/#remote-debugging`, tick "Allow remote debugging for this browser
   instance", and click **Allow** on the popup. Check with `uv run browser-harness --doctor` (daemon alive, 1 connection).
   The service connects in the background at startup and again after any "Chrome isn't connected" reply.
5. **Try it**: `uv run python cli.py --say "email Sam that I'm at the Palace of Fine Arts"`. If typing into the
   message body fails, set `GMAIL_PREFILL=1`: To/Subject/Body go into the compose URL and the agent only reviews the draft;
   the guard, read-back and Sent-folder check are unchanged.

## How it stays safe

- **Guard, policy layer** (`guard.py`, `runner.drive`): Jev's loop is split into predict and act. Every chosen action
  is checked before it runs; a click on anything labelled send/submit/delete/discard/buy/pay/... parks the task.
- **Guard, DOM layer**: a capture-phase listener injected into every page swallows clicks on send-like buttons
  (and Cmd/Ctrl+Enter) unless `window.__guardOpen` is set, which only `gmail.click_send()` does, after `/confirm yes`.
- **Independent checks**: the read-back is read from the page's To/Subject/Body fields, not from the agent's claims;
  a draft to anyone but the resolved contact is refused. After "send", the service waits out Undo send and looks for
  the email in the Sent folder before saying "Sent".
- **Recipients** only come from `DEMO_CONTACTS`; the agent never guesses an address. Purchases and payments are refused.
- **Never silent**: every failure returns a spoken sentence ("I got stuck on Gmail after I type in Subject. Nothing was
  sent.", "The laptop isn't signed in to email.", "Chrome isn't connected to the assistant.").
- `logs/guard.jsonl` records every hold, confirm, send, verification and (if one ever happened) violation.

## Checks

| Command | What | Needs |
|---|---|---|
| `uv run pytest -q` | guard, goal parsing, read-back, Sent matching, the whole HTTP flow on the fake, contract shapes against core's models | nothing |
| `uv run python cli.py "<goal>"` | one task by hand, y/n prompt | service running |
| `uv run python runs.py --email 5 --lookup 5` | PRD 4 acceptance: email 4/5 in < 30 s, 0 unconfirmed sends, 0 silent failures, lookup 4/5 in < 20 s | real service started with `VERIFY_CANCEL=1` |

## Layout

| Path | What | PRD |
|---|---|---|
| `app.py` | FastAPI: `/task`, `/confirm`, `/work`, `/health`, `/trace` | B-1, B-6 |
| `runner.py` | Guarded predict/act loop, one-tab task store, email/lookup/confirm flows, spoken failures | B-1, B-2, B-3, B-7 |
| `guard.py` | Irreversible-action check, DOM interceptor, guard log | B-2 |
| `gmail.py` | Compose URL, read the draft from the DOM, the one guarded Send click, Sent-folder check | B-3, B-4 |
| `readback.py` | Spoken read-back template; Claude shortens long bodies | B-4 |
| `goals.py` | Utterance to email/lookup plan (Claude, then rules); contacts | B-1 |
| `lookup.py` | Google search, one-sentence answer | B-5 |
| `work.py`, `orders/` | Work mode: item vs order card, next step | B-8 |
| `tracelog.py`, `static/trace.html` | Judges' trace | B-6 |
| `agents.py`, `fake_agent.py` | Real Jev agent or the scripted fake | |
| `cli.py`, `runs.py` | Core stand-in; acceptance runner | |

## Known limitations

- Gmail only. Jev Ultrafast can't handle iframes, shadow roots, canvas, uploads, pop-up tabs or nested scrolling,
  so other mail sites may block. Gmail's markup can change; every selector lives in `gmail.py`.
- One browser task at a time; a new request discards an unanswered draft.
- The Sent-folder check matches recipient, subject and a recent time; a resend of an identical email within
  three minutes could match the earlier one.
- Lookups read the Google results page first; questions whose answer isn't on it get up to 6 more agent steps.
- Not built: sign-in, passwords, payments, purchases, file uploads (by design).
