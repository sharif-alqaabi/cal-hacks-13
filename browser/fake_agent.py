"""Stand-in for jev_ultrafast.Agent with BROWSER_FAKE=1: no Chrome, no keys.

It mimics the parts of the real Agent the runner uses (state, command("predict"/"act"), browser.observe/act/
evaluate/call, close) over two scripted pages: Gmail full-page compose and a Google results page.
The fake model is deliberately reckless: once the draft is filled it reaches for Send, so the guard must stop it.

FAKE_SCRIPT picks its behaviour: send (default), done (says DONE when filled), blocked, stuck (waits forever),
wrong_to (types a different recipient), signed_out (Gmail redirects to the Google sign-in page).
"""
import hashlib
import json
import os
import re
import time
from urllib.parse import parse_qs, urlparse

import gmail
import guard
import inbox
import lookup
import sites
from agents import StalePage

SENT: list[dict] = []        # every email the fake Gmail actually sent (shared across tabs, like a real mailbox)
VIOLATIONS: list[dict] = []  # sends that happened with the guard closed
RESULTS = [{"title": "Ace Hardware Polk St - Hours and Directions", "href": "https://www.acehardware.com/store/polk",
            "site": "Ace Hardware"},
           {"title": "Ace Hardware | Yelp", "href": "https://www.yelp.com/biz/ace-polk", "site": "Yelp · 120 reviews"},
           {"title": "Hardware stores near Polk St", "href": "https://www.example.com/hardware", "site": ""}]
INBOX = [{"unread": True, "who": [{"name": "Sam Lee", "email": "sam.calhacks.demo@gmail.com"}], "subject": "Lunch tomorrow?",
          "snippet": " - Want to grab lunch at noon?", "thread": "t-sam"},
         {"unread": True, "who": [{"name": "Google", "email": "no-reply@google.com"}], "subject": "Security alert",
          "snippet": " - A new sign-in on Mac OS", "thread": "t-google"},
         {"unread": False, "who": [{"name": "me", "email": "me@example.com"}, {"name": "Priya", "email": "priya@example.com"}],
          "subject": "Slides", "snippet": " - Here they are", "thread": "t-priya"}]
BODIES = {"t-sam": "Hi! Want to grab lunch tomorrow at noon at Tartine? Let me know. Sam",
          "t-google": "A new sign-in on Mac OS. If this was you, you don't need to do anything.",
          "t-priya": "Here are the slides for Sunday."}
LOOKUP_TEXT = "Ace Hardware Polk St\nHardware store in San Francisco\nOpen ⋅ Closes 9 PM\n(415) 555-0100"


def reset() -> None:
    SENT.clear()
    VIOLATIONS.clear()


def _clock(ts: float) -> str:
    return time.strftime("%I:%M %p", time.localtime(ts)).lstrip("0")


class FakeBrowser:
    def __init__(self, url: str):
        self.url = url
        self.target = "fake-tab"
        self.closed = False
        self.dom_guard = False
        self.guard_open = False
        self.dom_blocked = 0
        self.after_input = None
        q = parse_qs(urlparse(url).query)
        self.fields = {"to": q.get("to", [""])[0], "subject": q.get("su", [""])[0], "body": q.get("body", [""])[0]}

    # ---- page model -------------------------------------------------------

    def _kind(self) -> str:
        if "mail.google.com" in self.url and "view=cm" in self.url:
            return "compose"
        if "mail.google.com" in self.url and "#sent" in self.url:
            return "sent"
        if "mail.google.com" in self.url and "#inbox/" in self.url:
            return "thread"
        if "mail.google.com" in self.url and "#inbox" in self.url:
            return "inbox"
        if "google.com/search" in self.url:
            return "search"
        return "other"

    def _actions(self) -> list[dict]:
        kind = self._kind()
        acts: list[dict] = []
        if kind == "compose":
            acts = [
                {"id": "e1", "kind": "fill", "label": "To recipients", "role": "combobox", "value": self.fields["to"], "node": 1},
                {"id": "e2", "kind": "fill", "label": "Subject", "role": "textbox", "value": self.fields["subject"], "node": 2},
                {"id": "e3", "kind": "fill", "label": "Message Body", "role": "textbox", "value": self.fields["body"], "node": 3},
                {"id": "e4", "kind": "click", "label": "Send \u202a(⌘Enter)\u202c", "role": "button", "value": "", "node": 4},
                {"id": "e5", "kind": "click", "label": "Discard draft \u202a(⌘⇧D)\u202c", "role": "button", "value": "", "node": 5},
            ]
        elif kind == "search":
            acts = [
                {"id": "e1", "kind": "fill", "label": "Search", "role": "combobox", "value": "", "node": 1},
                {"id": "e2", "kind": "click", "label": "Ace Hardware Polk St - Hours", "role": "link", "value": "", "node": 2},
            ]
        return acts + [{"id": "wait", "kind": "wait", "label": "Wait for the page to update"}]

    def _text(self) -> str:
        kind = self._kind()
        if kind == "compose":
            return f"New Message\nTo {self.fields['to']}\nSubject {self.fields['subject']}\n{self.fields['body']}\nSend"
        if kind == "search":
            return LOOKUP_TEXT
        if kind == "sent":
            return "\n".join(self._sent_rows())
        return ""

    def _sent_rows(self) -> list[str]:
        return [f"To: {m['to'].split('@')[0]} {m['subject']} - {m['body']} {_clock(m['ts'])}" for m in reversed(SENT)]

    def _fp(self) -> str:
        return hashlib.sha256(json.dumps([self.url, self.fields]).encode()).hexdigest()

    def observe(self, screenshot: bool = True) -> dict:
        fp = self._fp()
        return {"url": self.url, "title": "Gmail" if "mail" in self.url else "Google", "text": self._text(),
                "actions": self._actions(), "scroll": {"y": 0, "height": 780}, "fingerprint": fp, "marker": fp}

    def fresh(self, page: dict, action: dict | None = None) -> bool:
        return page.get("fingerprint") == self._fp()

    # ---- CDP surface ------------------------------------------------------

    def call(self, method: str, **params):
        hist = self.__dict__.setdefault("history", [self.url])
        self.__dict__.setdefault("at", 0)
        if method == "Page.navigate":
            self.url = params["url"]
            del hist[self.at + 1:]
            hist.append(self.url)
            self.at = len(hist) - 1
        elif method == "Page.getNavigationHistory":
            return {"currentIndex": self.at, "entries": [{"id": i, "url": u} for i, u in enumerate(hist)]}
        elif method == "Page.navigateToHistoryEntry":
            self.at = params["entryId"]
            self.url = hist[self.at]
        elif method == "Page.addScriptToEvaluateOnNewDocument":
            self.dom_guard = True
        return {}

    def evaluate(self, expression: str):
        if expression == guard.DOM_GUARD_JS:
            self.dom_guard = True
            return True
        if expression == guard.OPEN_JS:
            self.guard_open = True
            return True
        if expression == guard.CLOSE_JS:
            self.guard_open = False
            return False
        if expression == guard.BLOCKED_COUNT_JS:
            return self.dom_blocked
        if expression == gmail.READ_DRAFT_JS:
            to = self.fields["to"]
            return {"emails": gmail.EMAIL_RX.findall(to), "names": [], "to_text": to,
                    "subject": self.fields["subject"], "body": self.fields["body"]}
        if expression == sites.PAGE_JS:
            host = urlparse(self.url).hostname or ""
            return {"ready": "complete", "url": self.url, "title": host.removeprefix("www.").split(".")[0].capitalize(),
                    "description": "", "heading": "", "text": self._text()}
        if expression == sites.FIRST_RESULT_JS:
            return "https://www.calhacks.io/" if self._kind() == "search" else None
        if expression == lookup.RESULTS_JS:
            return RESULTS if self._kind() == "search" else []
        if expression == inbox.ROWS_JS:
            return INBOX if self._kind() == "inbox" else None
        if expression == inbox.MESSAGE_JS:
            t = self.url.rsplit("/", 1)[-1]
            row = next((r for r in INBOX if r["thread"] == t), None)
            return {"subject": row["subject"], "sender": row["who"][-1]["name"], "address": row["who"][-1]["email"],
                    "body": BODIES[t]} if row and self._kind() == "thread" else None
        if expression == "location.href":
            return self.url
        if expression == "(() => [location.href, document.readyState])()":
            return [self.url, "complete"]
        if expression == gmail.SENT_ROWS_JS:
            return self._sent_rows() if self._kind() == "sent" else []
        return None

    def act(self, action: dict, page: dict, text: str | None = None) -> dict:
        if not self.fresh(page, action):
            raise StalePage("Page changed since this decision. Observe again.")
        label = action["label"]
        if action["kind"] == "fill":
            key = {"To recipients": "to", "Subject": "subject", "Message Body": "body"}.get(label)
            if key:
                self.fields[key] = text or ""
        elif action["kind"] == "click" and label.startswith("Send"):
            if self.dom_guard and not self.guard_open:
                self.dom_blocked += 1          # swallowed by the DOM layer of the guard
            else:
                msg = {**self.fields, "ts": time.time()}
                if not self.guard_open:
                    VIOLATIONS.append(msg)
                SENT.append(msg)
                self.url = gmail.base_url() + "#inbox"
        elif action["kind"] == "click" and label.startswith("Discard"):
            self.fields = {"to": "", "subject": "", "body": ""}
        self.after_input = action if action["kind"] != "wait" else None
        return {"executed": action["id"]}

    def close(self) -> None:
        self.closed = True


class FakeAgent:
    def __init__(self, url: str, goal: str):
        self.script = os.getenv("FAKE_SCRIPT", "send")
        if self.script == "signed_out":
            url = "https://accounts.google.com/v3/signin/identifier?continue=" + url
        self.browser = FakeBrowser(url)
        self.step_s = float(os.getenv("FAKE_STEP_S", "0"))
        self.values = self._values(goal)
        self.state = dict(browser=self.browser, goal=goal, page=self.browser.observe(), decision=None, history=[],
                          status="ready", decisions=[], text_calls=[], elapsed_ms=0, started_at=None)

    def _values(self, goal: str) -> dict:
        to = re.search(r"email to (\S+@[^\s\"]+?)\.\s", goal)
        subject = re.search(r'Subject: "(.*?)"', goal)
        body = re.search(r'Body: "(.*?)"', goal)
        to_val = to.group(1) if to else ""
        if self.script == "wrong_to":
            to_val = "someone.else@example.com"
        return {"To recipients": to_val, "Subject": subject.group(1) if subject else "",
                "Message Body": body.group(1) if body else ""}

    def _policy(self) -> str:
        if self.script == "blocked":
            return "BLOCKED"
        if self.script == "stuck":
            return "wait"
        page = self.state["page"]
        by_label = {a["label"]: a for a in page["actions"]}
        if "Message Body" in by_label:
            for label in ("To recipients", "Subject", "Message Body"):
                if not by_label[label]["value"]:
                    return by_label[label]["id"]
            return "DONE" if self.script == "done" else "e4"   # e4 = Send: the guard must stop this
        return "DONE"

    def command(self, name: str, body: dict | None = None) -> dict:
        st = self.state
        if name == "predict":
            if st["status"] in {"done", "blocked"}:
                raise ValueError("This run has stopped. Start a fresh demo.")
            if st["started_at"] is None:
                st["started_at"] = time.perf_counter()
            if not self.browser.fresh(st["page"]):
                st["page"] = self.browser.observe()
            time.sleep(self.step_s)
            choice = self._policy()
            action = next((a for a in st["page"]["actions"] if a["id"] == choice), None)
            op = {"fill": "TYPE_TEXT", "click": "CLICK", "wait": "WAIT"}.get(action["kind"], choice) if action else choice
            st["decision"] = {"choice": choice, "operation": op, "target": choice, "confidence": 0.97,
                              "probabilities": {choice: 0.97}, "latency_ms": int(self.step_s * 1000), "usage": {}}
            st["decisions"].append(st["decision"])
            st["status"] = "predicted"
        elif name == "act":
            decision, page = st["decision"], st["page"]
            if not decision or (body or {}).get("fingerprint") != page["fingerprint"]:
                raise ValueError("Observe and choose before acting")
            st["decision"] = None
            choice = decision["choice"]
            if choice in {"DONE", "BLOCKED"}:
                st["status"] = "done" if choice == "DONE" else "blocked"
                return st
            action = next(a for a in page["actions"] if a["id"] == choice)
            text = self.values.get(action["label"]) if action["kind"] == "fill" else None
            if text is not None:
                st["text_calls"].append({"field": action["label"], "value": text})
            self.browser.act(action, page, text=text)
            st["history"].append({"step": len(st["history"]) + 1, "action": action["label"], "kind": action["kind"],
                                  "choice": choice, "text": text, "url": page["url"]})
            st["page"] = self.browser.observe()
            st["status"] = "ready"
        else:
            raise ValueError("Unknown command")
        return st

    def close(self) -> None:
        self.browser.close()
