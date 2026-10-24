"""Output filter: no reply may tell the wearer something is safe (PRD 2 non-functional)."""
import logging
import re

log = logging.getLogger("core.safety")

BANNED = [
    r"\bsafe\b", r"\bsafely\b", r"\bclear to cross\b", r"\bgo ahead\b",
    r"\byou can cross\b", r"\bokay to cross\b", r"\bok to cross\b", r"\ball clear\b",
    r"\bno cars?\b.*\bcross\b", r"\bit'?s fine to cross\b", r"\bwalk now\b", r"\byou'?re clear\b",
]
_banned_re = re.compile("|".join(BANNED), re.IGNORECASE)

FALLBACK = "I can describe what I see, but you decide when to cross."


def is_banned(text: str) -> bool:
    return bool(_banned_re.search(text.replace("’", "'")))


def split_sentences(text: str) -> list[str]:
    return [p for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p]


def filter_sentence(sentence: str) -> str | None:
    """None when the sentence must be dropped."""
    if is_banned(sentence):
        log.warning("banned phrase blocked: %r", sentence)
        return None
    return sentence


def filter_reply(text: str) -> str:
    """Drop banned sentences; if nothing is left, use FALLBACK."""
    kept = [s for s in split_sentences(text) if filter_sentence(s) is not None]
    return " ".join(kept) if kept else FALLBACK


def max_two_sentences(text: str) -> str:
    return " ".join(split_sentences(text)[:2])
