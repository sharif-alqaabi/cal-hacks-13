"""Claude calls (goal parsing, read-back summaries, lookup answers, /work). Every call has a timeout."""
import asyncio
import json
import logging
import re

import config

log = logging.getLogger("browser.llm")
_client = None


def available() -> bool:
    return bool(config.ANTHROPIC_API_KEY)


def _anthropic():
    global _client
    if _client is None:
        from anthropic import AsyncAnthropic
        _client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


async def ask(system: str, content, *, max_tokens: int = 200, timeout: float = 4.0, model: str | None = None) -> str:
    """content: a string or a list of Anthropic content blocks. Raises on failure or timeout."""
    msg = await asyncio.wait_for(
        _anthropic().messages.create(
            model=model or config.READBACK_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": content}],
        ),
        timeout,
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()


async def ask_json(system: str, content, **kw) -> dict | None:
    """ask() and parse the first JSON object in the reply; None on any failure."""
    try:
        text = await ask(system, content, **kw)
        m = re.search(r"\{.*\}", text, re.S)
        return json.loads(m.group(0)) if m else None
    except Exception as e:
        log.warning("claude json call failed: %r", e)
        return None
