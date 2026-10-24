"""Intent router (C-3): Jev first, Claude when Jev is unsure, keywords if both are unavailable."""
import logging
import re
import time

import httpx

from contracts.intents import INTENTS
from . import config, llm

log = logging.getLogger("core.router")

# Last-resort rules so the demo never stalls. Order matters.
KEYWORDS: list[tuple[str, str]] = [
    ("confirm", r"^(yes|yeah|yep|sure|send it|do it|confirm|no|nope|cancel|don't)\b"),
    ("lost", r"\b(i'?m lost|i am lost|help me|help)\b"),
    ("signal", r"\b(signal|crosswalk|walk sign|walk|light|crossing)\b"),
    ("remember", r"\b(this is|remember (that|this)|meet my)\b"),
    ("recall", r"\b(where (did|is|are)|what was|when did|did i|who is)\b"),
    ("browser", r"\b(email|e-mail|text|message|send|look up|search|book)\b"),
    ("task", r"\b(is this (the )?right|next item|order card|check this|order)\b"),
    ("describe", r"\b(what'?s|what is|describe|in front|around me|see)\b"),
]

JEV_CRITERIA = {
    "describe": "Wants to know what is around or in front of them",
    "signal": "Asks about a pedestrian signal, walk sign, traffic light or crosswalk",
    "recall": "Asks about something seen earlier, like where they left an object or what someone wore",
    "remember": "Introduces a person or asks to remember something",
    "lost": "Says they are lost or need help from family",
    "browser": "Wants a task done on the laptop or web, like sending an email",
    "confirm": "Answers yes or no to a pending draft",
    "task": "Work mode: checks whether a held item is the right one for an order",
    "other": "Anything else, small talk or a general question",
}

ROUTER_SYSTEM = (
    "You classify a blind user's spoken request for their assistive glasses. "
    f"Reply with exactly one label from: {', '.join(INTENTS)}.\n"
    "describe=what's around/in front; signal=pedestrian signal/crosswalk; recall=asking about something seen earlier; "
    "remember=introducing a person or asking to remember something; lost=lost or needs help; "
    "browser=email/web task on the laptop; confirm=yes/no answer to a pending draft; task=checking items in work mode; other=anything else."
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
    try:
        async with httpx.AsyncClient(timeout=config.JEV_TIMEOUT_S) as c:
            r = await c.post(config.JEV_URL, json=body,
                             headers={"Authorization": f"Bearer {config.TYPESAFE_API_KEY}"})
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
        out = await llm.ask(config.ROUTER_FALLBACK_MODEL, ROUTER_SYSTEM, text, max_tokens=5,
                            timeout=config.ROUTER_FALLBACK_TIMEOUT_S)
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
    if pending_confirm and keyword_route(text) == "confirm":
        return done("confirm", "keywords")
    jev = await jev_route(text, pending_confirm)
    if jev and jev[1] >= config.JEV_CONFIDENCE_THRESHOLD:
        return done(jev[0], "jev")
    if llm.available():
        label = await claude_route(text)
        if label:
            return done(label, "claude")
    return done(keyword_route(text), "keywords")
