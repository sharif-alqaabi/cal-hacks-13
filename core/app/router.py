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
    ("recall", r"\b(where (did|is|are)|what was|when did|did i|who is)\b"),
    ("browser", r"\b(email|e-mail|text|message|send|look up|search|book|youtube|videos?|pause|resume|unpause)\b"
                r"|^(?:please )?(?:play|put on)\b"),
    ("task", r"\b(is this (the )?right|next item|order card|check this|order)\b"),
    ("describe", r"\b(what'?s|what is|describe|in front|around me|see)\b"),
]

# YouTube controls are short and ambiguous to a classifier ("pause", "play number two"): always the browser.
YOUTUBE_RX = re.compile(
    r"\byoutube\b|^(?:please |ok |okay )?(?:pause|resume|unpause|stop the video|"
    r"play (?:the )?(?:number )?(?:one|two|three|1|2|3|first|second|third|top|last)(?: one| video| result)?$)")

JEV_CRITERIA = {
    "describe": "Wants to know what is around or in front of them",
    "signal": "Asks about a pedestrian signal, walk sign, traffic light or crosswalk",
    "recall": "Asks about something seen earlier, like where they left an object or what someone wore",
    "remember": "Introduces a person or asks to remember something",
    "lost": "Says they are lost, need help, or want their family told where they are",
    "browser": "Wants a task done on the laptop or web, like sending an email, or YouTube: finding, playing, "
               "picking (\"play number two\"), pausing or resuming a video",
    "confirm": "Answers yes or no to a pending draft",
    "task": "Work mode: checks whether a held item is the right one for an order",
    "other": "Anything else, small talk or a general question",
}

ROUTER_SYSTEM = (
    "You classify a blind user's spoken request for their assistive glasses. "
    f"Reply with exactly one label from: {', '.join(INTENTS)}.\n"
    "describe=what's around/in front; signal=pedestrian signal/crosswalk; recall=asking about something seen earlier; "
    "remember=introducing a person or asking to remember something; lost=lost or needs help; "
    "browser=email/web task on the laptop, including YouTube (find, play, pick a numbered result, pause, resume a video); confirm=yes/no answer to a pending draft; task=checking items in work mode; other=anything else."
)


def keyword_route(text: str) -> str:
    t = text.lower().replace("’", "'").strip()
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
    """Returns (intent, source, ms) where source is jev|claude|keywords."""
    t0 = time.perf_counter()

    def done(intent: str, source: str) -> tuple[str, str, int]:
        return intent, source, int((time.perf_counter() - t0) * 1000)

    # A bare yes/no while a draft is waiting is always a confirm.
    hint = keyword_route(text)
    if pending_confirm and hint == "confirm":
        return done("confirm", "keywords")
    if YOUTUBE_RX.search(text.lower().replace("’", "'").strip().rstrip(".!?")):
        return done("browser", "keywords")
    # Claude starts alongside Jev instead of after it, so an unsure Jev costs max(jev, claude), not the sum.
    claude = asyncio.create_task(claude_route(text)) if llm.available() else None
    try:
        jev = await jev_route(text, pending_confirm)
        # Jev saying "other" when the keywords name a real intent ("I need help") goes to Claude, which was
        # right on all 30 test phrases; Jev put "I need help" in other at 0.65.
        if jev and jev[1] >= config.JEV_CONFIDENCE_THRESHOLD and not (jev[0] == "other" and hint != "other"):
            return done(jev[0], "jev")
        if claude:
            label = await claude
            if label:
                return done(label, "claude")
        return done(hint, "keywords")
    finally:
        if claude and not claude.done():
            claude.cancel()
