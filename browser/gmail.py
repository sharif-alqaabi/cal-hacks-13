"""Everything Gmail-specific: compose URL, reading the draft straight from the DOM, the guarded Send click,
and checking the Sent folder. Selectors live only here; if Gmail changes its markup, fix this file.

The agent's own DONE is never proof (PRD 4 honesty rule): read_draft() and verify_sent() look at the page themselves.
"""
import re
import time
from dataclasses import dataclass, field
from urllib.parse import quote, urlencode

import agents
import config
import guard
from agents import StalePage

EMAIL_RX = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
SEND_RX = re.compile(r"^\s*send\b", re.I)
CLOCK_RX = re.compile(r"\b(\d{1,2}):(\d{2})\s*([AP]M)\b", re.I)

READ_DRAFT_JS = r"""(() => {
  const chips = [...document.querySelectorAll('[data-hovercard-id]')].filter(e => e.closest('form'));
  const emails = chips.map(e => e.getAttribute('data-hovercard-id')).filter(v => v && v.includes('@'));
  const names = chips.map(e => e.getAttribute('data-name') || (e.innerText || '').trim()).filter(Boolean);
  const typed = [...document.querySelectorAll(
      'input[name="to"], textarea[name="to"], input[aria-label="To recipients" i], input[aria-label="To" i]')]
    .map(e => e.value).filter(Boolean);
  const subjectEl = document.querySelector('input[name="subjectbox"], input[aria-label="Subject" i], input[placeholder="Subject" i]');
  const bodyEl = document.querySelector(
    'div[aria-label="Message Body"][contenteditable="true"], div[g_editable="true"], form div[role="textbox"][contenteditable="true"]');
  return {emails, names, to_text: [...names, ...typed].join(', '),
          subject: subjectEl ? subjectEl.value : '', body: bodyEl ? bodyEl.innerText.trim() : ''};
})()"""

COMPOSE_READY_JS = """!!document.querySelector('input[name="subjectbox"], input[aria-label="Subject" i], input[placeholder="Subject" i]')"""

SENT_ROWS_JS = r"""(() => [...document.querySelectorAll('tr.zA')].slice(0, 8)
  .map(r => (r.innerText || '').replace(/\s+/g, ' ').trim()))()"""


class SendError(Exception):
    def __init__(self, say: str):
        super().__init__(say)
        self.say = say


@dataclass
class Draft:
    emails: list[str] = field(default_factory=list)
    to_text: str = ""
    subject: str = ""
    body: str = ""


def base_url() -> str:
    return f"https://mail.google.com/mail/u/{config.GMAIL_ACCOUNT_INDEX}/"


def compose_url(plan=None) -> str:
    """Full-page compose (no pop-up dialog). With a plan, To/Subject/Body are prefilled (GMAIL_PREFILL fallback)."""
    url = base_url() + "?view=cm&fs=1&tf=1"
    if plan is not None:
        url += "&" + urlencode({"to": plan.to_addr, "su": plan.subject, "body": plan.message}, quote_via=quote)
    return url


def sent_url() -> str:
    return base_url() + "#sent"


def goal(plan) -> str:
    if config.GMAIL_PREFILL:
        return (f"Check that this email draft is addressed to {plan.to_addr} with the subject \"{plan.subject}\". "
                "Do not click Send. Stop when the draft is ready.")
    return (f"Write an email to {plan.to_addr}. Subject: \"{plan.subject}\". Body: \"{plan.message}\". "
            "Select the matching recipient suggestion if one appears. Do not click Send. "
            "Stop when To, Subject and Body are filled.")


def signed_out(url: str) -> bool:
    return any(s in (url or "") for s in ("accounts.google.com", "ServiceLogin", "workspace.google.com"))


def read_draft(browser) -> Draft:
    v = browser.evaluate(READ_DRAFT_JS) or {}
    to_text = v.get("to_text", "") or ""
    emails = sorted({*(e.lower() for e in v.get("emails", [])), *(m.lower() for m in EMAIL_RX.findall(to_text))})
    body = (v.get("body", "") or "").split("\n-- \n")[0].strip()   # drop a signature block
    return Draft(emails=emails, to_text=to_text, subject=(v.get("subject", "") or "").strip(), body=body)


def wait_compose(browser, timeout_s: float = 8.0) -> bool:
    """Gmail is a single-page app: readyState is "complete" long before the compose form renders, and an agent
    that looks too early sees no fields and says BLOCKED. Wait for the Subject input instead."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if browser.evaluate(COMPOSE_READY_JS):
                return True
        except StalePage:
            pass
        time.sleep(0.25)
    return False


def addressed_to(draft: Draft, addr: str, name: str) -> bool:
    """The draft goes to exactly the resolved contact. Name-only chips count when Gmail hides the address."""
    if draft.emails:
        return draft.emails == [addr.lower()]
    return bool(name) and name.lower() in draft.to_text.lower()


def find_send(page: dict) -> dict | None:
    return next((a for a in page.get("actions", [])
                 if a.get("kind") == "click" and SEND_RX.search(a.get("label", ""))), None)


def click_send(browser) -> None:
    """The one place a Send click happens: only called from /confirm with yes=true. Opens the DOM guard for it."""
    for _ in range(2):
        page = browser.observe(screenshot=False)
        action = find_send(page)
        if action is None:
            raise SendError("I couldn't find the Send button.")
        browser.evaluate(guard.OPEN_JS)
        try:
            browser.act(action, page)
            return
        except StalePage:
            continue
        finally:
            try:
                browser.evaluate(guard.CLOSE_JS)
            except Exception:
                pass   # the click navigated away; the new document starts closed
    raise SendError("The page kept changing, so I didn't press Send.")


def _recent(row: str, now: float, window_s: float = 180) -> bool:
    """Rows from today show a clock time; require it to be within the last few minutes. No clock: can't tell, accept."""
    times = CLOCK_RX.findall(row)
    if not times:
        return True
    lt = time.localtime(now)
    now_min = lt.tm_hour * 60 + lt.tm_min
    for h, m, ampm in times:
        hour = int(h) % 12 + (12 if ampm.upper() == "PM" else 0)
        if abs(now_min - (hour * 60 + int(m))) * 60 <= window_s:
            return True
    return False


def row_matches(row: str, draft: Draft, name: str, addr: str, now: float | None = None) -> bool:
    r = " ".join(row.lower().split())
    who = (name and name.lower() in r) or (addr and (addr.lower() in r or addr.split("@")[0].lower() in r))
    key = " ".join(draft.subject.lower().split()) or " ".join(draft.body.lower().split())[:60]
    return bool(who and key and key in r and _recent(row, now or time.time()))


def sent_rows(browser, wait_s: float) -> list[str]:
    agents.navigate(browser, sent_url())
    deadline = time.monotonic() + wait_s
    rows: list[str] = []
    while time.monotonic() < deadline:
        try:
            rows = browser.evaluate(SENT_ROWS_JS) or []
        except StalePage:
            rows = []
        if rows:
            return rows
        time.sleep(0.4)
    return rows


def verify_sent(browser, draft: Draft, name: str, addr: str) -> bool:
    """Wait out Undo send (leaving the page earlier could cancel it), then look for the email in Sent."""
    time.sleep(config.UNDO_SEND_S + 1.5 if config.UNDO_SEND_S > 0 else 0)
    agents.navigate(browser, sent_url())
    deadline = time.monotonic() + config.SENT_POLL_S
    while time.monotonic() < deadline:
        try:
            rows = browser.evaluate(SENT_ROWS_JS) or []
        except StalePage:
            rows = []
        if any(row_matches(r, draft, name, addr) for r in rows):
            return True
        time.sleep(0.4)
    return False


def verify_absent(browser, draft: Draft, name: str, addr: str) -> bool | None:
    """After a cancel: True if Sent has no matching recent email, False if it does, None if Sent didn't load."""
    rows = sent_rows(browser, wait_s=4)
    if not rows:
        return None
    return not any(row_matches(r, draft, name, addr) for r in rows)
