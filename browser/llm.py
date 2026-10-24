"""Claude calls (goal parsing, read-back summaries, lookup answers, /work). Every call has a timeout.

Works with an Anthropic key or an OpenRouter key (sk-or-...): OpenRouter's Anthropic-compatible Messages API takes the
same requests at https://openrouter.ai/api, with the key as a bearer token and model ids like anthropic/claude-sonnet-5.5.
"""
import asyncio
import json
import logging
import re

import config

log = logging.getLogger("browser.llm")
_client = None


def available() -> bool:
    return bool(config.ANTHROPIC_API_KEY)


def via_openrouter() -> bool:
    return "openrouter.ai" in config.ANTHROPIC_BASE_URL


def model_id(name: str) -> str:
    """claude-sonnet-5-5 -> anthropic/claude-sonnet-5.5 on OpenRouter; ids that already have a prefix pass through."""
    if not via_openrouter() or "/" in name:
        return name
    return "anthropic/" + re.sub(r"-(\d+)-(\d+)$", r"-\1.\2", name)


def thinking(name: str) -> dict:
    """Short spoken answers under tight timeouts: no up-front thinking. Thinking also shares max_tokens, so leaving
    Sonnet 5.5 at its default (adaptive, effort high) can use up the budget before any text. Sonnet 5.5 can't disable
    thinking; between_tools is its lowest setting. Haiku 5.5 can turn it off."""
    if "sonnet" in name:
        return {"thinking": {"type": "between_tools"}, "output_config": {"effort": "low"}}
    if "haiku" in name:
        return {"thinking": {"type": "disabled"}}
    return {}


def _anthropic():
    global _client
    if _client is None:
        from anthropic import AsyncAnthropic
        if via_openrouter():
            _client = AsyncAnthropic(auth_token=config.ANTHROPIC_API_KEY, base_url=config.ANTHROPIC_BASE_URL)
        else:
            _client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY, base_url=config.ANTHROPIC_BASE_URL)
    return _client


async def ask(system: str, content, *, max_tokens: int = 200, timeout: float = 4.0, model: str | None = None) -> str:
    """content: a string or a list of Anthropic content blocks. Raises on failure or timeout."""
    name = model or config.READBACK_MODEL
    msg = await asyncio.wait_for(
        _anthropic().messages.create(
            model=model_id(name),
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": content}],
            extra_body=thinking(name),
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
