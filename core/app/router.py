"""Intent router (C-3): Jev first, Claude when Jev is unsure, keywords if both are unavailable."""
import logging
import re

from contracts.intents import INTENTS
from . import config, llm

log = logging.getLogger("core.router")

# Last-resort rules so the demo never stalls. Order matters.
KEYWORDS: list[tuple[str, str]] = [
    ("confirm", r"^(yes|yeah|yep|send( it)?|do it|confirm|no|nope|cancel|don't)\b"),
    ("lost", r"\b(i'?m lost|i am lost|help me|help)\b"),
    ("signal", r"\b(signal|crosswalk|walk sign|light|crossing)\b"),
    ("remember", r"\b(this is|remember (that|this)|meet my)\b"),
    ("recall", r"\b(where (did|is|are)|what was|when did|did i)\b"),
    ("browser", r"\b(email|e-mail|send .* (to|a message)|look up|search|book|order)\b"),
    ("task", r"\b(is this (the )?right|next item|order card|check this)\b"),
    ("describe", r"\b(what'?s|what is|describe|in front|around me|see)\b"),
]


def keyword_route(text: str) -> str:
    t = text.lower().strip()
    for intent, pat in KEYWORDS:
        if re.search(pat, t):
            return intent
    return "other"


async def jev_route(text: str) -> tuple[str, float] | None:
    """Return (intent, confidence) from TypeSafe Jev, or None if unavailable."""
    if not config.TYPESAFE_API_KEY:
        return None
    # TODO(C-3): call Jev with the 9 labels and return its top label + probability.
    return None


ROUTER_SYSTEM = (
    "You classify a blind user's spoken request for their assistive glasses. "
    f"Reply with exactly one label from: {', '.join(INTENTS)}.\n"
    "describe=what's around/in front; signal=pedestrian signal/crosswalk; recall=asking about something seen earlier; "
    "remember=introducing a person or asking to remember something; lost=lost or needs help; "
    "browser=email/web task on the laptop; confirm=yes/no answer to a pending draft; task=checking items in work mode; other=anything else."
)


async def claude_route(text: str) -> str | None:
    try:
        out = await llm.ask(config.ROUTER_FALLBACK_MODEL, ROUTER_SYSTEM, text, max_tokens=5)
        label = out.strip().lower().split()[0].strip(".,")
        return label if label in INTENTS else None
    except Exception as e:
        log.warning("claude route failed: %s", e)
        return None


async def route(text: str, pending_confirm: bool = False) -> tuple[str, str]:
    """Returns (intent, source) where source is jev|claude|keywords."""
    # A bare yes/no while a draft is waiting is always a confirm.
    if pending_confirm and keyword_route(text) == "confirm":
        return "confirm", "keywords"
    jev = await jev_route(text)
    if jev and jev[1] >= config.JEV_CONFIDENCE_THRESHOLD:
        return jev[0], "jev"
    label = await claude_route(text)
    if label:
        return label, "claude"
    return keyword_route(text), "keywords"
