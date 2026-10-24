"""Irreversible-action guard (PRD 4 B-2): nothing that sends, deletes or buys runs without /confirm yes.

Two layers:
- policy: the runner checks every chosen action with is_irreversible() before it executes;
- DOM: install() adds a capture-phase listener to the page that swallows clicks on send-like controls
  (and Gmail's Cmd/Ctrl+Enter) unless window.__guardOpen is set, which only gmail.click_send() does.
Every block, confirm, send and violation is appended to logs/guard.jsonl.
"""
import json
import re
import threading
import time

import config

IRREVERSIBLE = re.compile(
    r"\b(send|submit|delete|trash|discard|buy|purchase|pay|place order|checkout|check out|confirm|post|publish"
    r"|unsubscribe|book now|reserve|order now)\b",
    re.I,
)

DOM_GUARD_JS = r"""(() => {
  if (window.__guardInstalled) return true;
  window.__guardInstalled = true;
  window.__guardOpen = false;
  window.__guardBlocked = 0;
  const RX = /\b(send|submit|delete|trash|discard|buy|purchase|pay|place order|checkout|publish)\b/i;
  const label = e => (e.getAttribute('aria-label') || e.getAttribute('data-tooltip') || e.value ||
    e.innerText || '').slice(0, 120);
  const block = ev => {
    if (window.__guardOpen) return;
    const el = ev.target instanceof Element ?
      ev.target.closest('button,[role="button"],input[type="submit"],input[type="button"],a') : null;
    if (!el || !RX.test(label(el))) return;
    ev.stopImmediatePropagation();
    ev.preventDefault();
    window.__guardBlocked += 1;
  };
  for (const t of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'])
    window.addEventListener(t, block, true);
  window.addEventListener('keydown', ev => {
    if (!window.__guardOpen && ev.key === 'Enter' && (ev.metaKey || ev.ctrlKey)) {
      ev.stopImmediatePropagation();
      ev.preventDefault();
      window.__guardBlocked += 1;
    }
  }, true);
  return true;
})()"""

OPEN_JS = "window.__guardOpen = true"
CLOSE_JS = "window.__guardOpen = false"
BLOCKED_COUNT_JS = "window.__guardBlocked || 0"

_lock = threading.Lock()


def is_irreversible(action: dict | None) -> bool:
    if not action or action.get("kind") not in {"click", "select"}:
        return False
    return bool(IRREVERSIBLE.search(action.get("label", "")))


def install(browser) -> None:
    """Add the DOM layer to the current document and every later one in this tab."""
    browser.call("Page.addScriptToEvaluateOnNewDocument", source=DOM_GUARD_JS)
    browser.evaluate(DOM_GUARD_JS)


def log(event: str, task_id: str = "", **fields) -> None:
    """event: blocked, confirm, sent, cancelled, cancel_verified, violation."""
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    rec = {"ts": time.time(), "event": event, "task_id": task_id, **fields}
    with _lock, open(config.LOG_DIR / "guard.jsonl", "a") as f:
        f.write(json.dumps(rec) + "\n")


def read_log() -> list[dict]:
    path = config.LOG_DIR / "guard.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
