"""Thin wrapper around the Anthropic SDK."""
from anthropic import AsyncAnthropic

from . import config

_client: AsyncAnthropic | None = None


def client() -> AsyncAnthropic | None:
    global _client
    if _client is None and config.ANTHROPIC_API_KEY:
        _client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


async def ask(model: str, system: str, text: str, jpeg_b64: str | None = None, max_tokens: int = 200) -> str:
    c = client()
    if c is None:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    content: list[dict] = []
    if jpeg_b64:
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": jpeg_b64}})
    content.append({"type": "text", "text": text})
    resp = await c.messages.create(
        model=model, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": content}],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()
