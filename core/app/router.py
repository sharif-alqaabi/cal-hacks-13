"""Intent router (C-3): Jev first, Claude when Jev is unsure, keywords if both are unavailable."""
import logging
import re
import time

import asyncio
from urllib.parse import urlsplit

from contracts.intents import INTENTS
from . import config, llm, net

log = logging.getLogger("core.router")

# Last-resort rules so the demo never stalls. Order matters.
KEYWORDS: list[tuple[str, str]] = [
    ("confirm", r"^(yes|yeah|yep|sure|send it|do it|confirm|no|nope|cancel|don't)\b"),
    ("lost", r"\b(i'?m lost|i am lost|help me|help)\b"),
    ("signal", r"\b(signal|crosswalk|walk sign|walk|light|crossing)\b"),
    ("remember", r"\b(this is|remember (that|this)|meet my)\b"),
    ("recall", r"\b(where (did|is|are|was)|what was|when did|did i|who (is|was)|do you know where|have you seen|do you remember|what else (was|were)|last (see|saw)|come across)\b"),
    ("browser", r"\b(email|e-mail|text|message|send|look up|search|book|youtube|videos?|pause|resume|unpause)\b"
                r"|^(?:please )?(?:play|put on)\b"),
    ("task", r"\b(is this (the )?right|next item|order card|check this|order)\b"),
    ("describe", r"\b(what'?s|what is|describe|in front|around me|see)\b"),
]

# YouTube controls are short and ambiguous to a classifier ("pause", "play number two"): always the browser.
YOUTUBE_RX = re.compile(
    r"\byoutube\b|^(?:please |ok |okay )?(?:pause|resume|unpause|stop the video|"
    r"play (?:the )?(?:number )?(?:one|two|three|1|2|3|first|second|third|top|last)(?: one| video| result)?$)")

# "go to Instagram", "open nytimes.com", "open the Exploratorium website": the browser opens the site. Only named
# sites, domains or "... website" count, so "go to the kitchen" is left to the classifiers.
SITES = (r"x|twitter|instagram|insta|facebook|reddit|linkedin|tiktok|threads|gmail|google(?: maps| calendar| docs| drive)?|"
         r"wikipedia|amazon|netflix|spotify|github|hacker news|espn|cnn|bbc(?: news)?|(?:the )?new york times|ny ?times|"
         r"weather\.com|chatgpt|claude|pinterest|twitch|yelp|ebay|craigslist|devpost|cal ?hacks")
SITE_RX = re.compile(
    r"^(?:hey |ok |okay )?(?:can you |could you |would you |please )*(?:go to|go on|open(?: up)?|pull up|bring up|"
    r"take me to|navigate to|visit|load)\s+(?:the\s+)?"
    rf"(?:(?:{SITES})(?:\s+(?:website|site|page|homepage))?|[\w-]+(?:\.| dot )[a-z]{{2,}}(?:/\S*)?|"
    r"[\w' -]+?\s+(?:website|web site|homepage))(?:\s+(?:for me|please|on the laptop|in chrome))*$"
    r"|^(?:can you |could you |please )*(?:open|close|start)\s+(?:up\s+)?(?:a |this |the |that |another |my )?"
    r"(?:new |blank |current )?(?:browser )?tab\b")

# Reading the inbox ("any new emails?", "read the one from Sam") and searching Google ("search for tacos", "open the
# second result") are always the browser: a classifier can read "read the one from Sam" as memory.
MAIL = r"(?:e-?mails?|mail|inbox)"
WEB_RX = re.compile(
    r"^(?:hey |ok |okay )?(?:can you |could you |would you |please )*(?:"
    rf"(?:do i have |are there |did i get )?any (?:new |unread )?{MAIL}"
    rf"|(?:read|check|go through|what'?s in)(?: me)? my (?:new |unread )?(?:{MAIL}|messages)"
    rf"|(?:do i have|i have) (?:new|unread) (?:{MAIL}|messages)"
    r"|(?:read|open)(?: me)? (?:the |that )?(?:one|e-?mail|message|mail) from\b"
    r"|(?:search|google)(?: google| search)?(?: for)?\s+\S"
    r"|(?:open(?: up)?|click(?: on)?|tap(?: on)?|press|select|go to|go into|take me to|pull up|show me) (?:the )?"
    r"(?:(?:number )?(?:one|two|three|1|2|3|first|second|third|top|last) (?:one|result|search result|link|website|web ?site|site|page|article|option)"
    r"|(?:result|link|website|option) (?:number )?(?:one|two|three|1|2|3|first|second|third|top|last))(?: please)?$"
    r"|(?:click|tap)(?: on)? (?:the )?(?:number )?(?:one|two|three|1|2|3|first|second|third|top|last)(?: one)?$)")

# Past-tense wording means the answer is in memory, not in the camera ("what color was the car", "have you seen my
# wallet", "did I leave the stove on"). Only overrides describe/other/recall, so "email Sam that I left 5 minutes ago",
# "did the walk sign turn on" and "this is Sam, I saw him earlier" keep their own intents.
PAST = re.compile(r"\b(did|didn'?t|was|wasn'?t|were|weren'?t|had|saw|seen|earlier|ago|yesterday|last (time|night|week))\b")
PAST_OVERRIDES = {"describe", "other", "recall"}

JEV_CRITERIA = {
    "describe": "Wants to know what is around or in front of them right now, in the present ('what's in front of me?'). Never a question about earlier",
    "signal": "Asks about a pedestrian signal, walk sign, traffic light or crosswalk",
    "recall": "Asks about anything from earlier, however it is phrased: where they left or last saw something, what else was somewhere, what someone looked like or wore, who they met or talked to, who someone is ('who is this?', since only memory knows names), 'do you know where my keys are', 'have you seen my wallet', 'do you remember', 'did I'",
    "remember": "Introduces a person or asks to remember something",
    "lost": "Says they are lost, need help, or want their family told where they are",
    "browser": "Wants a task done on the laptop or web, like sending an email, reading new emails (\"any new emails?\", \"read the one from Sam\"), searching Google or opening a search result, opening a website (\"go to Instagram\"), opening or closing a tab, "
               "or YouTube: finding, playing, picking (\"play number two\"), pausing or resuming a video",
    "confirm": "Answers yes or no to a pending draft",
    "task": "Work mode: checks whether a held item is the right one for an order",
    "other": "Anything else, small talk or a general question",
}

ROUTER_SYSTEM = (
    "You classify a blind user's spoken request for their assistive glasses. "
    f"Reply with exactly one label from: {', '.join(INTENTS)}.\n"
    "describe=what's around/in front of them right now; signal=pedestrian signal/crosswalk; "
    "recall=anything about earlier or the past, or who someone is (\"who is this?\": only memory knows names) "
    "(where something was left or last seen, what else was somewhere, who they met, "
    "what someone wore, \"do you know where my keys are\", \"have you seen\"); "
    "remember=introducing a person or asking to remember something; lost=lost or needs help; "
    "browser=email/web task on the laptop, including reading the inbox (any new emails, read the one from Sam), a Google search and opening one of its results, opening a website (go to Instagram, open nytimes.com), opening or closing a browser tab, and YouTube (find, play, pick a numbered result, pause, resume a video); confirm=yes/no answer to a pending draft; task=checking items in work mode; other=anything else."
)


def keyword_route(text: str) -> str:
    t = text.lower().replace("’", "'").strip()
    if SITE_RX.match(t.rstrip(".!?")) or WEB_RX.match(t.rstrip(".!?")):
        return "browser"
    for intent, pat in KEYWORDS:
        if re.search(pat, t):
            return intent
    return "other"


async def jev_route(text: str, pending_confirm: bool = False) -> tuple[str, float] | None:
    """Return (intent, confidence) from TypeSafe Jev, or None if unavailable."""
    if not config.TYPESAFE_API_KEY:
        return None
    state = ("A draft is waiting for yes or no. " if pending_confirm else "") + text
    body = {
        "model": config.JEV_MODEL,
        "state": state,
        "questions": {"intent": {
            "type": "choice",
            "instructions": "What does a blind user wearing camera glasses want from this spoken request?",
            "criteria": JEV_CRITERIA,
        }},
    }
    u = urlsplit(config.JEV_URL)
    try:
        r = await net.client(f"{u.scheme}://{u.netloc}", config.JEV_TIMEOUT_S).post(
            u.path, json=body, headers={"Authorization": f"Bearer {config.TYPESAFE_API_KEY}"})
        r.raise_for_status()
        ans = r.json()["answers"]["intent"]
        choice = ans.get("choice")
        if choice not in INTENTS:
            return None
        return choice, float(ans.get("confidence") or 0.0)
    except Exception as e:
        log.warning("jev route failed: %s", e)
        return None


async def claude_route(text: str) -> str | None:
    try:
        # Sonnet 5.5 at low effort with its default thinking: p50 790 ms vs 945 ms with thinking turned off
        # ("between_tools"), same 60/60 labels on the router test phrases.
        out = await llm.ask(config.ROUTER_FALLBACK_MODEL, ROUTER_SYSTEM, text, max_tokens=16,
                            timeout=config.ROUTER_FALLBACK_TIMEOUT_S, effort="low")
        label = out.strip().lower().split()[0].strip(".,")
        return label if label in INTENTS else None
    except Exception as e:
        log.warning("claude route failed: %s", e)
        return None


async def route(text: str, pending_confirm: bool = False) -> tuple[str, str, int]:
    """Returns (intent, source, ms) where source is jev|claude|keywords|tense."""
    t0 = time.perf_counter()

    def done(intent: str, source: str) -> tuple[str, str, int]:
        return intent, source, int((time.perf_counter() - t0) * 1000)

    # A bare yes/no while a draft is waiting is always a confirm.
    hint = keyword_route(text)
    if pending_confirm and hint == "confirm":
        return done("confirm", "keywords")
    said = text.lower().replace("’", "'").strip().rstrip(".!?")
    if YOUTUBE_RX.search(said) or SITE_RX.match(said) or WEB_RX.match(said):
        return done("browser", "keywords")
    # Past tense goes straight to memory, without waiting on Jev: the camera can't answer about earlier.
    if hint in PAST_OVERRIDES and PAST.search(text.lower().replace("’", "'")):
        return done("recall", "tense")
    # Claude starts alongside Jev instead of after it, so an unsure Jev costs max(jev, claude), not the sum.
    claude = asyncio.create_task(claude_route(text)) if llm.available() else None
    try:
        jev = await jev_route(text, pending_confirm)
        # Jev saying "other" when the keywords name a real intent ("I need help") goes to Claude, which was
        # right on all 30 test phrases; Jev put "I need help" in other at 0.65.
        # Likewise "describe" when the words are about the past ("what else was on the table"): Jev reads those as a look at the scene.
        if jev and jev[1] >= config.JEV_CONFIDENCE_THRESHOLD and not (
                (jev[0] == "other" and hint != "other") or (jev[0] == "describe" and hint == "recall")):
            return done(jev[0], "jev")
        if claude:
            label = await claude
            if label:
                return done(label, "claude")
        return done(hint, "keywords")
    finally:
        if claude and not claude.done():
            claude.cancel()
