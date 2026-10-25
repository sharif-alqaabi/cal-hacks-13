"""Runs browser tasks for /task and /confirm.

Jev Ultrafast's own run() is predict-then-act with nothing in between. drive() splits it so every chosen action
passes guard.is_irreversible() before it executes; a send-like action parks the task until /confirm.
The agent is synchronous (CDP calls), so all browser work runs on one worker thread: tasks never overlap in Chrome.
Every path returns a sentence to speak; nothing fails silently (PRD 4 B-7).
"""
import asyncio
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import partial

import agents
import config
import gmail
import goals
import guard
import inbox
import lookup
import readback
import sites
import tracelog
import youtube
from agents import StalePage

log = logging.getLogger("browser.runner")

EXEC = ThreadPoolExecutor(max_workers=1, thread_name_prefix="browser")

CHROME_DOWN = "Chrome isn't connected to the assistant."
NO_KEYS = "The browser agent's keys aren't set up."
NOT_SIGNED_IN = "The laptop isn't signed in to email."
EXPIRED = "That draft has expired. Please ask me again."
CANCELLED = "Okay, I didn't send it. Nothing went out."
BROKE = "Something went wrong in the browser."


class Failed(Exception):
    """Raised inside a flow with the sentence to speak."""

    def __init__(self, say: str):
        super().__init__(say)
        self.say = say


@dataclass
class Outcome:
    kind: str                    # parked | done | blocked | timeout | budget | error
    action: dict | None = None
    error: str = ""


@dataclass
class Task:
    task_id: str
    agent: object
    plan: goals.EmailPlan
    draft: gmail.Draft
    created: float = field(default_factory=time.monotonic)


class Store:
    """One working Chrome tab: the newest agent replaces (and closes) the previous one,
    except after "open a new tab", which keeps the old tab open behind it until "close this tab"."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.pending: dict[str, Task] = {}
        self.current = None
        self.kept: list = []   # older tabs left open by "open a new tab", newest last

    def keep_current(self) -> None:
        with self.lock:
            if self.current is not None:
                self.kept.append(self.current)
            self.current = None
            self.pending.clear()

    def close_tab(self):
        """Runs on the browser thread. Closes the working tab and returns to the one behind it (or None)."""
        self.close_current()
        with self.lock:
            self.current = self.kept.pop() if self.kept else None
        return self.current

    def adopt(self, agent) -> None:
        with self.lock:
            old, self.current = self.current, agent
        if old is not None and old is not agent:
            _close(old)

    def put(self, task: Task) -> None:
        with self.lock:
            self.pending = {task.task_id: task}

    def pop(self, task_id: str) -> Task | None:
        with self.lock:
            task = self.pending.pop(task_id, None)
        if task and time.monotonic() - task.created > config.TASK_TTL_S:
            return None
        return task

    def close_current(self) -> None:
        """Runs on the browser thread."""
        with self.lock:
            agent, self.current = self.current, None
            self.pending.clear()
        if agent is not None:
            _close(agent)


store = Store()


def _close(agent) -> None:
    try:
        agent.close()
    except Exception as e:
        log.warning("closing tab failed: %r", e)


# ---- the guarded loop --------------------------------------------------------

def _action(page: dict, choice: str) -> dict | None:
    return next((a for a in page.get("actions", []) if a.get("id") == choice), None)


def drive(agent, task_id: str, deadline: float, max_steps: int | None = None) -> Outcome:
    st = agent.state
    steps = 0
    while True:
        if st["status"] == "done":
            return Outcome("done")
        if st["status"] == "blocked":
            return Outcome("blocked")
        if time.monotonic() >= deadline:
            return Outcome("timeout")
        if max_steps is not None and steps >= max_steps:
            return Outcome("budget")
        try:
            agent.command("predict")
        except StalePage:
            continue
        except Exception as e:
            return Outcome("error", error=f"{type(e).__name__}: {e}")
        d = st["decision"]
        action = _action(st["page"], d["choice"])
        label = action["label"] if action else d["choice"]
        tracelog.emit(task_id, "predict", f"{d.get('operation', '')} {label}".strip(),
                   p=round(float(d.get("confidence") or 0), 2), ms=d.get("latency_ms"))
        if guard.is_irreversible(action):
            st["decision"] = None
            st["status"] = "ready"
            guard.log("blocked", task_id, label=action["label"], url=st["page"].get("url", ""))
            tracelog.emit(task_id, "guard", f"Held before \"{action['label']}\": waiting for a spoken yes")
            return Outcome("parked", action=action)
        try:
            agent.command("act", {"fingerprint": st["page"]["fingerprint"]})
        except StalePage:
            st["decision"] = None
            st["status"] = "ready"
            try:
                st["page"] = agent.browser.observe(screenshot=False)
            except Exception as e:
                return Outcome("error", error=f"{type(e).__name__}: {e}")
            continue
        except Exception as e:
            return Outcome("error", error=f"{type(e).__name__}: {e}")
        if action:
            steps += 1
            typed = st["history"][-1].get("text") if st["history"] else None
            tracelog.emit(task_id, "act", f"{_verb(action)} {action['label']}" + (f": \"{typed}\"" if typed else ""))


def _verb(action: dict) -> str:
    return {"fill": "type in", "click": "press", "select": "choose", "scroll": "scroll", "wait": "wait"}.get(
        action.get("kind", ""), action.get("kind", ""))


# ---- spoken failures (B-7) ---------------------------------------------------

def _error_say(error: str) -> str:
    e = error.lower()
    if "text_model_api_key" in e:
        return "The browser agent can't type without its text model key."
    if "typesafe_api_key" in e or "keyerror" in e:
        return NO_KEYS
    if "budget" in e:
        return "That took too many steps."
    if "model" in e or "http" in e or "typesafe" in e:
        return "The browser agent's model isn't responding."
    if "harness" in e or "daemon" in e or "cdp" in e:
        return CHROME_DOWN
    return BROKE


def explain(outcome: Outcome, agent, site: str, email: bool) -> str:
    tail = " Nothing was sent." if email else ""
    st = getattr(agent, "state", None) or {}
    if gmail.signed_out(st.get("page", {}).get("url", "")):
        return NOT_SIGNED_IN + tail
    hist = [h for h in st.get("history") or [] if h.get("kind") in {"fill", "click", "select"}]
    last = f" after I {_verb(hist[-1])} {hist[-1]['action']}" if hist else ""
    if outcome.kind == "timeout":
        return f"I ran out of time on {site}{last}.{tail}"
    if outcome.kind == "blocked":
        return f"I got stuck on {site}{last}.{tail}"
    if outcome.kind == "budget":
        return f"I couldn't find that on {site}.{tail}"
    return _error_say(outcome.error) + tail


# ---- flows (run on the browser thread) ---------------------------------------

def _start(task_id: str, url: str, goal: str, site: str):
    if not agents.chrome_ready():
        agents.reconnect_in_background()
        raise Failed(CHROME_DOWN)
    if not config.FAKE and not config.TYPESAFE_API_KEY:
        raise Failed(NO_KEYS)
    try:
        try:
            agent = agents.make_agent(url, goal)
        except Exception as e:   # Chrome sometimes drops the first call on a brand-new tab: one retry
            if "key" in str(e).lower():
                raise
            log.warning("opening the tab failed, retrying once: %r", e)
            agent = agents.make_agent(url, goal)
    except Exception as e:
        log.exception("could not start agent")
        raise Failed(_error_say(f"{type(e).__name__}: {e}") if "key" in str(e).lower() else f"I couldn't open {site} in Chrome.")
    store.adopt(agent)
    try:
        guard.install(agent.browser)
    except Exception as e:
        log.warning("DOM guard not installed (policy guard still on): %r", e)
        tracelog.emit(task_id, "guard", "Page guard unavailable; action guard still on")
    agents.activate(agent.browser)
    return agent


def email_draft(task_id: str, plan: goals.EmailPlan, deadline: float):
    agent = _start(task_id, gmail.compose_url(plan if config.GMAIL_PREFILL else None), gmail.goal(plan), "Gmail")
    if gmail.signed_out(agent.state["page"].get("url", "")):
        raise Failed(f"{NOT_SIGNED_IN} Nothing was sent.")
    out = drive(agent, task_id, deadline)
    if out.kind not in {"parked", "done"}:
        raise Failed(explain(out, agent, "Gmail", email=True))
    draft = gmail.read_draft(agent.browser)
    tracelog.emit(task_id, "draft", f"To: {', '.join(draft.emails) or draft.to_text or '(empty)'} | "
                                 f"Subject: {draft.subject or '(none)'} | Body: {draft.body or '(empty)'}")
    if not gmail.addressed_to(draft, plan.to_addr, plan.to_name):
        raise Failed(f"The draft isn't addressed to {plan.to_name}, so I won't send it. Please ask me again.")
    if not draft.body:
        raise Failed("I couldn't write the message. Nothing was sent.")
    return agent, draft


def lookup_open(task_id: str, plan: goals.LookupPlan):
    agent = _start(task_id, lookup.search_url(plan.query), lookup.goal(plan.query), "Google")
    return agent, agent.state["page"].get("text", "")


_search: dict = {"agent": None, "results": [], "query": ""}   # the Google tab and its top results


def lookup_results(task_id: str, agent, query: str, wait_s: float = 5.0) -> list:
    results = lookup.read_results(agent.browser, timeout=wait_s)
    _search.update(agent=agent, results=results, query=query)
    _yt["results"] = []
    tracelog.emit(task_id, "read", " | ".join(f"{r.title} ({r.site})" for r in results) or "(no results)")
    return results


def _search_agent():
    agent = _search["agent"]
    return agent if agent is not None and agent is store.current else None


def search_pick(task_id: str, pick: int):
    """"open the second result": open that link in the search tab and read the page. Never clicks anything."""
    agent, results = _search_agent(), _search["results"]
    if not results:
        raise Failed("Search for something first, then pick a result.")
    if pick > len(results):
        raise Failed(f"There were only {len(results)} results.")
    r = results[pick - 1]
    if agent is None:   # the search tab was replaced (a website, an email): the links still work
        agent = _start(task_id, r.href, sites.goal(sites.SitePlan(r.href, r.site)), r.site or "that page")
        _search["agent"] = agent
        page = sites.read(agent.browser, fallback=agent.state.get("page"))
        tracelog.emit(task_id, "read", f"{page.get('title') or '(no title)'} | {page.get('url', '')}")
        return r, page
    tracelog.emit(task_id, "act", f"open result {pick}: {r.href}")
    sites.open_site(agent.browser, r.href)
    page = sites.read(agent.browser, fallback=agent.state.get("page"))
    tracelog.emit(task_id, "read", f"{page.get('title') or '(no title)'} | {page.get('url', '')}")
    return r, page


def lookup_more(agent, task_id: str, deadline: float):
    out = drive(agent, task_id, deadline, max_steps=config.LOOKUP_MAX_STEPS)
    try:
        text = agent.browser.observe(screenshot=False).get("text", "")
    except Exception:
        text = agent.state.get("page", {}).get("text", "")
    return out, text


_yt: dict = {"agent": None, "results": []}   # the YouTube tab and the results last read aloud


def _yt_agent():
    """The open YouTube tab, if it is still the current one (an email or lookup replaces it)."""
    agent = _yt["agent"]
    return agent if agent is not None and agent is store.current else None


def _yt_play(task_id: str, agent, video: youtube.Video, latest: bool = False) -> str:
    tracelog.emit(task_id, "act", f"open {video.title}")
    st = youtube.play(agent.browser, video)
    say = youtube.playing_say(video, st, latest=latest)
    if st.get("ad"):
        tracelog.emit(task_id, "act", "ad playing: will press Skip ad when it appears")
        EXEC.submit(youtube.skip_ads, agent.browser)   # after this reply; the next task queues behind it
    return say


def youtube_run(task_id: str, plan: youtube.YouTubePlan) -> str:
    if plan.action in {"pause", "resume", "pick"}:
        agent = _yt_agent()
        if agent is None:
            raise Failed("Ask me to find videos first, then pick one." if plan.action == "pick"
                         else "Nothing is playing on YouTube right now.")
        b = agent.browser
        if plan.action == "pause":
            tracelog.emit(task_id, "act", "pause the video")
            return "Paused." if youtube.pause(b) else "I couldn't find a video to pause."
        if plan.action == "resume":
            tracelog.emit(task_id, "act", "play the video")
            return "Playing again." if youtube.resume(b) else "I couldn't start the video."
        results = _yt["results"]
        if not results:
            raise Failed("Ask me to find videos first, then pick one.")
        if plan.pick > len(results):
            raise Failed(f"There were only {len(results)} results.")
        return _yt_play(task_id, agent, results[plan.pick - 1])

    store.close_current()
    if plan.action == "open":
        agent = _start(task_id, "https://www.youtube.com/", "Open YouTube. Never subscribe, like, comment or buy.", "YouTube")
        _yt.update(agent=agent, results=[])
        return "YouTube is open. What should I search for? Say, for example, find videos about cooking."
    query = plan.query
    agent = _start(task_id, youtube.search_url(query), youtube.goal(plan), "YouTube")
    _yt.update(agent=agent, results=[])
    if plan.action == "latest":
        video = youtube.latest_from(agent.browser, query)
        if video is None:
            raise Failed(f"I couldn't find a YouTube channel called {query}.")
        return _yt_play(task_id, agent, video, latest=True)
    videos = youtube.read_results(agent.browser)
    tracelog.emit(task_id, "read", " | ".join(f"{v.title} ({v.channel}, {v.length})" for v in videos) or "(no results)")
    if not videos:
        raise Failed(f"I couldn't find any YouTube videos for {query}.")
    if plan.action == "play":
        return _yt_play(task_id, agent, videos[0])
    _yt["results"] = videos
    _search["results"] = []
    return youtube.results_say(query, videos)


_mail: dict = {"agent": None, "mails": [], "listed": []}   # the Gmail inbox tab, its rows and the ones read aloud


def _mail_agent():
    agent = _mail["agent"]
    return agent if agent is not None and agent is store.current else None


def _open_inbox(task_id: str):
    agent = _mail_agent()
    if agent is None:
        store.close_current()
        agent = _start(task_id, inbox.inbox_url(), inbox.goal(), "Gmail")
        _mail.update(agent=agent, mails=[], listed=[])
    else:
        agents.navigate(agent.browser, inbox.inbox_url())
        time.sleep(0.5)
    mails = inbox.read_rows(agent.browser)
    if mails is None:
        try:
            url = agent.browser.evaluate("location.href") or ""
        except Exception:
            url = agent.state.get("page", {}).get("url", "")
        raise Failed(NOT_SIGNED_IN if gmail.signed_out(url) else "Your inbox didn't load.")
    _mail["mails"] = mails
    return agent, mails


def inbox_run(task_id: str, plan: inbox.InboxPlan) -> dict:
    """Read-only: opens the inbox or one email by URL. Never clicks, so nothing is archived, deleted or replied to."""
    if plan.action == "list":
        agent, mails = _open_inbox(task_id)
        _mail["listed"] = [m for m in mails if m.unread][:inbox.TOP_N]
        tracelog.emit(task_id, "read", " | ".join(f"{m.sender}: {m.subject}" for m in _mail["listed"]) or "(no unread)")
        return {"say": inbox.list_say(mails)}
    agent = _mail_agent()
    mails = _mail["mails"] if agent else []
    if plan.sender:
        mail = inbox.find(mails, plan.sender) if mails else None
        if mail is None:
            agent, mails = _open_inbox(task_id)
            mail = inbox.find(mails, plan.sender)
        if mail is None:
            raise Failed(f"I don't see an email from {plan.sender} in your inbox.")
    else:
        if agent is None:
            agent, mails = _open_inbox(task_id)
        pool = (_mail["listed"] if agent is _mail["agent"] else []) or [m for m in mails if m.unread] or mails
        if not pool:
            raise Failed("Your inbox is empty.")
        if plan.pick > len(pool):
            raise Failed(f"I only read out {len(pool)}.")
        mail = pool[plan.pick - 1]
    if not mail.thread:
        raise Failed(f"I couldn't open the email from {mail.sender}.")
    tracelog.emit(task_id, "act", f"open the email from {mail.sender}: {mail.subject}")
    msg = inbox.open_mail(agent.browser, mail)
    tracelog.emit(task_id, "read", f"{msg.get('sender') or mail.sender} | {msg.get('subject') or mail.subject} | "
                                   f"{' '.join((msg.get('body') or '').split())[:200] or '(no body)'}")
    return {"mail": mail, "msg": msg}


def site_open(task_id: str, plan: sites.SitePlan) -> dict:
    """Open the site (via Google's first result when the name isn't known) and read the page. Never clicks anything."""
    if plan.url:
        agent = _start(task_id, plan.url, sites.goal(plan), plan.name)
    else:
        agent = _start(task_id, sites.search_url(plan.name), sites.goal(plan), plan.name)
        url = sites.first_result(agent.browser)
        if not url:
            raise Failed(f"I couldn't find a website for {plan.name}.")
        tracelog.emit(task_id, "act", f"open the first Google result: {url}")
        sites.open_site(agent.browser, url)
    page = sites.read(agent.browser, fallback=agent.state.get("page"))
    tracelog.emit(task_id, "read", f"{page.get('title') or '(no title)'} | {page.get('url', '')}")
    return page


def tab_run(task_id: str, plan: sites.TabPlan) -> str:
    if plan.action == "close":
        if store.current is None and not store.kept:
            raise Failed("There's no tab of mine open to close.")
        tracelog.emit(task_id, "act", "close the tab")
        back = store.close_tab()
        if back is None:
            return "Closed the tab."
        agents.activate(back.browser)
        page = sites.read(back.browser, fallback=back.state.get("page"))
        title = sites.title_of(page)
        return f"Closed the tab. You're back on {title}." if title else "Closed the tab."
    store.keep_current()
    if plan.site:
        return None   # run_task opens the site in the new tab
    tracelog.emit(task_id, "act", "open a new tab")
    _start(task_id, sites.NEW_TAB_URL, "Open a new tab. Never post, buy or delete anything.", "a new tab")
    return sites.new_tab_say()


def nav_run(task_id: str, plan: sites.NavPlan) -> str:
    """The back / forward arrows in the working tab. Search results, YouTube results and the inbox stay usable."""
    agent = store.current
    if agent is None:
        raise Failed("There's no page of mine open.")
    tracelog.emit(task_id, "act", f"press the {plan.action} arrow")
    if not sites.history_step(agent.browser, plan.action):
        raise Failed("There's no earlier page in this tab." if plan.action == "back" else "There's no page to go forward to.")
    page = sites.read(agent.browser, fallback=agent.state.get("page"))
    tracelog.emit(task_id, "read", f"{page.get('title') or '(no title)'} | {page.get('url', '')}")
    return sites.nav_say(plan.action, page)


def send_and_verify(task: Task) -> str:
    b, name = task.agent.browser, task.plan.to_name
    try:
        gmail.click_send(b)
    except gmail.SendError as e:
        guard.log("send_failed", task.task_id, reason=e.say)
        tracelog.emit(task.task_id, "fail", e.say)
        return f"{e.say} Nothing was sent."
    guard.log("sent", task.task_id, to=task.plan.to_addr, subject=task.draft.subject)
    tracelog.emit(task.task_id, "act", "press Send (after spoken yes)")
    ok = gmail.verify_sent(b, task.draft, name, task.plan.to_addr)
    guard.log("verified" if ok else "unverified", task.task_id)
    tracelog.emit(task.task_id, "verify", "Found it in the Sent folder" if ok else "Not found in the Sent folder")
    if ok:
        return f"Sent to {name}. I checked your Sent folder."
    return "I pressed send, but I can't find it in your Sent folder yet. Please check before resending."


def cancel(task: Task) -> str:
    guard.log("cancelled", task.task_id)
    tracelog.emit(task.task_id, "act", "No click: draft left unsent")
    say = CANCELLED
    if config.VERIFY_CANCEL:
        clean = gmail.verify_absent(task.agent.browser, task.draft, task.plan.to_name, task.plan.to_addr)
        if clean is False:
            guard.log("violation", task.task_id, subject=task.draft.subject)
            say = "Warning: that email is in your Sent folder."
        elif clean:
            guard.log("cancel_verified", task.task_id)
        tracelog.emit(task.task_id, "verify", {True: "Sent folder is clean", False: "Found in Sent folder!",
                                            None: "Sent folder didn't load"}[clean])
    store.close_current()
    return say


# ---- async entry points --------------------------------------------------------

async def _in_browser(fn, *args, timeout: float):
    loop = asyncio.get_running_loop()
    return await asyncio.wait_for(loop.run_in_executor(EXEC, partial(fn, *args)), max(timeout, 1.0))


def _reply(task_id: str, say: str, needs_confirm: bool = False) -> dict:
    return {"task_id": task_id, "say": say, "needs_confirm": needs_confirm}


async def run_task(goal: str) -> dict:
    task_id = uuid.uuid4().hex[:8]
    t0 = time.monotonic()
    deadline = t0 + config.TASK_BUDGET_S
    tracelog.emit(task_id, "goal", goal)
    youtube.skip_stop.set()
    plan = await goals.parse(goal)
    email = isinstance(plan, goals.EmailPlan)
    try:
        if isinstance(plan, goals.Unsupported):
            tracelog.emit(task_id, "fail", plan.say)
            return _reply(task_id, plan.say)
        if isinstance(plan, goals.YouTubePlan) and plan.action == "pick" and not (_yt_agent() and _yt["results"]) \
                and (_search["results"] or _yt_agent() is None):
            tracelog.emit(task_id, "plan", f"Open search result {plan.pick}")   # "open the second result"
            r, page = await _in_browser(search_pick, task_id, plan.pick, timeout=deadline - time.monotonic() + 4)
            say = lookup.opened_say(r, await sites.summary(page))
            tracelog.emit(task_id, "answer", say, ms=int((time.monotonic() - t0) * 1000))
            return _reply(task_id, say)
        if isinstance(plan, goals.InboxPlan):   # reuses the inbox tab, so no close_current here
            tracelog.emit(task_id, "plan", "Read the inbox" if plan.action == "list"
                          else f"Read the email from {plan.sender}" if plan.sender else f"Read email {plan.pick}")
            out = await _in_browser(inbox_run, task_id, plan, timeout=deadline - time.monotonic() + 4)
            say = out.get("say") or inbox.read_say(out["mail"], out["msg"], await inbox.body_line(out["msg"].get("body", "")))
            tracelog.emit(task_id, "answer", say, ms=int((time.monotonic() - t0) * 1000))
            return _reply(task_id, say)
        if isinstance(plan, goals.NavPlan):   # keeps the open tab
            tracelog.emit(task_id, "plan", f"Go {plan.action}")
            say = await _in_browser(nav_run, task_id, plan, timeout=deadline - time.monotonic() + 4)
            tracelog.emit(task_id, "answer", say, ms=int((time.monotonic() - t0) * 1000))
            return _reply(task_id, say)
        if isinstance(plan, goals.YouTubePlan):   # pause/resume/pick keep the open tab, so no close_current here
            tracelog.emit(task_id, "plan", f"YouTube {plan.action}: {plan.query or plan.pick or ''}".strip())
            say = await _in_browser(youtube_run, task_id, plan, timeout=deadline - time.monotonic() + 4)
            tracelog.emit(task_id, "answer", say, ms=int((time.monotonic() - t0) * 1000))
            return _reply(task_id, say)
        if isinstance(plan, goals.TabPlan):
            tracelog.emit(task_id, "plan", f"Tab {plan.action}" + (f": {plan.site.name}" if plan.site else ""))
            say = await _in_browser(tab_run, task_id, plan, timeout=deadline - time.monotonic() + 4)
            if say is not None:
                tracelog.emit(task_id, "answer", say, ms=int((time.monotonic() - t0) * 1000))
                return _reply(task_id, say)
            plan = plan.site   # "open a new tab and go to Reddit": the old tab is kept, open the site in a new one
        else:
            await _in_browser(store.close_current, timeout=5)
        if isinstance(plan, goals.SitePlan):
            tracelog.emit(task_id, "plan", f"Open {plan.name}: {plan.url or 'first Google result'}")
            page = await _in_browser(site_open, task_id, plan, timeout=deadline - time.monotonic() + 4)
            say = sites.say(plan, page, await sites.summary(page))
            tracelog.emit(task_id, "answer", say, ms=int((time.monotonic() - t0) * 1000))
            return _reply(task_id, say)
        left = lambda: deadline - time.monotonic() + 4   # noqa: E731  the loop stops at the deadline; this is slack
        if email:
            if not plan.message:
                return _reply(task_id, f"What should the email to {plan.to_name} say?")
            if not plan.to_addr:
                return _reply(task_id, f"I don't have an email address for {plan.to_name}.")
            tracelog.emit(task_id, "plan", f"Email {plan.to_name} <{plan.to_addr}>: \"{plan.subject}\" / {plan.message}")
            agent, draft = await _in_browser(email_draft, task_id, plan, deadline, timeout=left())
            say = readback.compose(plan.to_name, draft.subject, await readback.body_line(draft.body))
            store.put(Task(task_id, agent, plan, draft))
            tracelog.emit(task_id, "readback", say, ms=int((time.monotonic() - t0) * 1000))
            return _reply(task_id, say, needs_confirm=True)

        tracelog.emit(task_id, "plan", f"Look up: {plan.query}")
        agent, text = await _in_browser(lookup_open, task_id, plan, timeout=left())
        if plan.listing:   # "search for X": read the top results
            results = await _in_browser(lookup_results, task_id, agent, plan.query, timeout=left())
            say = lookup.results_say(plan.query, results)
            tracelog.emit(task_id, "answer" if results else "fail", say, ms=int((time.monotonic() - t0) * 1000))
            return _reply(task_id, say)
        ans = await lookup.answer(plan.query, text)
        results = await _in_browser(lookup_results, task_id, agent, plan.query, 1.5, timeout=left())   # for "open the first result"
        if not ans:
            out, text = await _in_browser(lookup_more, agent, task_id, deadline, timeout=left())
            ans = await lookup.answer(plan.query, text)
            if not ans and results and out.kind != "error":   # still no answer: read the links from the first page
                say = lookup.results_say(plan.query, results, lead="I couldn't find a direct answer. Here are the top results.")
                tracelog.emit(task_id, "answer", say, ms=int((time.monotonic() - t0) * 1000))
                return _reply(task_id, say)
            if not ans:
                say = (explain(out, agent, "Google", email=False) if out.kind in {"error", "timeout", "blocked"}
                       else f"I couldn't find the answer. I searched Google for {plan.query}.")
                tracelog.emit(task_id, "fail", say)
                return _reply(task_id, say)
        tracelog.emit(task_id, "answer", ans, ms=int((time.monotonic() - t0) * 1000))
        return _reply(task_id, ans)
    except Failed as f:
        tracelog.emit(task_id, "fail", f.say)
        return _reply(task_id, f.say)
    except asyncio.TimeoutError:
        say = ("I ran out of time on Gmail. Nothing was sent." if email
               else "I ran out of time on YouTube." if isinstance(plan, goals.YouTubePlan)
               else f"I ran out of time opening {plan.name}." if isinstance(plan, goals.SitePlan)
               else "I ran out of time with the tabs." if isinstance(plan, goals.TabPlan)
               else "I ran out of time reading your email." if isinstance(plan, goals.InboxPlan)
               else "I ran out of time looking that up.")
        tracelog.emit(task_id, "fail", say)
        return _reply(task_id, say)
    except Exception:
        log.exception("task failed")
        say = BROKE + (" Nothing was sent." if email else "")
        tracelog.emit(task_id, "fail", say)
        return _reply(task_id, say)


async def confirm(task_id: str, yes: bool) -> str:
    task = store.pop(task_id)
    if task is None:
        tracelog.emit(task_id, "fail", EXPIRED)
        return EXPIRED
    guard.log("confirm", task_id, yes=yes)
    tracelog.emit(task_id, "confirm", "Heard yes: sending" if yes else "Heard cancel: not sending")
    try:
        if yes:
            return await _in_browser(send_and_verify, task, timeout=config.CONFIRM_BUDGET_S)
        return await _in_browser(cancel, task, timeout=config.CONFIRM_BUDGET_S)
    except asyncio.TimeoutError:
        if yes:
            return "I couldn't confirm the email went out. Please check your Sent folder before resending."
        return CANCELLED
    except Exception:
        log.exception("confirm failed")
        if yes:
            return "Something went wrong while sending. Please check your Sent folder before resending."
        return CANCELLED
