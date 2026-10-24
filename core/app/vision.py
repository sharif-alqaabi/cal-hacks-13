"""On-request vision with Claude (C-6 describe, C-7 signal)."""
from . import config, llm

DESCRIBE_SYSTEM = (
    "You are the eyes of a blind person wearing camera glasses. In at most two short spoken sentences, "
    "describe what is in front of them, naming obstacles first with left/ahead/right. "
    "Never say anything is safe."
)

SIGNAL_SYSTEM = (
    "You read pedestrian signals for a blind person. In at most two short spoken sentences, report what the "
    "signal shows: walk, don't walk, a countdown number, or unclear; then any moving vehicles and their direction. "
    "Describe only what you see. Never say it is safe, clear, or okay to cross, and never tell them to go."
)


async def describe(jpeg_b64: str) -> str:
    return await llm.ask(config.VISION_MODEL, DESCRIBE_SYSTEM, "What is in front of me?", jpeg_b64, max_tokens=120)


async def signal(jpeg_b64: str) -> str:
    return await llm.ask(config.VISION_MODEL, SIGNAL_SYSTEM, "What does the pedestrian signal show?", jpeg_b64, max_tokens=120)


async def chat(text: str) -> str:
    return await llm.ask(config.VISION_MODEL, "You are a helpful voice assistant. Answer in at most two short spoken sentences.", text, max_tokens=120)
