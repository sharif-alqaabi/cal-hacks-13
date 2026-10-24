"""Output filter: no reply may tell the wearer something is safe (PRD 2 non-functional)."""
import logging
import re

log = logging.getLogger("core.safety")

BANNED = [
    r"\bsafe\b", r"\bsafely\b", r"\bclear to cross\b", r"\bgo ahead\b",
    r"\byou can cross\b", r"\bokay to cross\b", r"\bok to cross\b", r"\ball clear\b",
]
_banned_re = re.compile("|".join(BANNED), re.IGNORECASE)

FALLBACK = "I can describe what I see, but you decide when to cross."


def filter_reply(text: str) -> str:
    if _banned_re.search(text):
        log.warning("banned phrase blocked: %r", text)
        return FALLBACK
    return text


def max_two_sentences(text: str) -> str:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(parts[:2])
