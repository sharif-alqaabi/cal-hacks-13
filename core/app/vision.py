"""On-request vision with Claude (C-6 describe, C-7 signal) and the general chat answer."""
import json
import re
from typing import AsyncIterator

from . import config, llm

# The first sentence is kept short on purpose: it is synthesised and spoken while the second is still being
# written, and TTS time grows with sentence length (measured: ~16 words -> ~12, first audio ~0.3 s sooner).
DESCRIBE_SYSTEM = (
    "You are the eyes of a blind person wearing camera glasses. Reply in two short spoken sentences. "
    "The first sentence is under ten words and names the most important thing ahead, an obstacle first if there is one. "
    "The second adds the layout using left, ahead or right. Never say anything is safe or clear. "
    "Mention distance only as near or far. No preamble. "
    "If they ask something specific (a color, an order, what someone looks like), answer that question directly "
    "instead, in at most two short sentences; list items strictly left to right as seen in the image."
)

SIGNAL_SYSTEM = (
    "You read pedestrian signals for a blind person. Look only at what is visible.\n"
    'Reply with JSON only: {"signal": "walk" | "dont_walk" | "countdown" | "unclear" | "none", '
    '"countdown": <int or null>, "vehicles": [{"motion": "moving"|"stopped", "from": "left"|"right"|"ahead"}]}\n'
    'If digits are lit next to the hand, the signal is "countdown" with that number, not "dont_walk".'
)

CHAT_SYSTEM = "You are a helpful voice assistant for a blind person. Answer in at most two short spoken sentences."

SIGNAL_SENTENCES = {
    "walk": "The walk sign is on.",
    "dont_walk": "The signal shows don't walk.",
    "unclear": "I can't read the signal clearly.",
    "none": "I don't see a pedestrian signal.",
}
UNCLEAR = SIGNAL_SENTENCES["unclear"]


def describe(jpeg_b64: str, question: str = "") -> AsyncIterator[str]:
    return llm.stream_sentences(config.VISION_MODEL, DESCRIBE_SYSTEM, question.strip() or "What is in front of me?",
                                jpeg_b64, max_tokens=120)


def compose_signal(raw: str) -> list[str]:
    """Signal JSON from the model -> one or two fixed sentences. Wording never comes from the model."""
    m = re.search(r"\{.*\}", raw or "", re.S)
    try:
        data = json.loads(m.group(0) if m else raw)
    except Exception:
        return [UNCLEAR]
    if not isinstance(data, dict):
        return [UNCLEAR]
    sig = str(data.get("signal", "unclear")).lower()
    if sig == "countdown":
        n = data.get("countdown")
        try:
            first = f"The signal is counting down, {int(n)} seconds."
        except (TypeError, ValueError):
            first = "The signal is counting down."
    else:
        first = SIGNAL_SENTENCES.get(sig, UNCLEAR)
    out = [first]
    vehicles = data.get("vehicles") or []
    moving = [v for v in vehicles if isinstance(v, dict) and v.get("motion") == "moving"]
    if len(moving) == 1:
        side = moving[0].get("from")
        out.append(f"A car is moving from your {side}." if side in ("left", "right") else "A car is moving ahead of you.")
    elif len(moving) > 1:
        sides = sorted({v.get("from") for v in moving if v.get("from") in ("left", "right")})
        out.append("Cars are moving from your left and right." if len(sides) == 2 else
                   f"Cars are moving from your {sides[0]}." if sides else "Cars are moving ahead of you.")
    return out


async def signal(jpeg_b64: str) -> list[str]:
    raw = await llm.ask(config.SIGNAL_MODEL, SIGNAL_SYSTEM, "What does the pedestrian signal show?", jpeg_b64,
                        max_tokens=120, timeout=config.VISION_TIMEOUT_S)
    return compose_signal(raw)


async def chat(text: str) -> str:
    return await llm.ask(config.VISION_MODEL, CHAT_SYSTEM, text, max_tokens=120, timeout=config.CHAT_TIMEOUT_S)
