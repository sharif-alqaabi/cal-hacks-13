"""Thin wrapper around the Anthropic SDK. ask() and stream_sentences() are the seams tests replace."""
import asyncio
import base64
import re
from typing import AsyncIterator

from anthropic import AsyncAnthropic, BadRequestError

from . import config

_client: AsyncAnthropic | None = None
_SENTENCE_END = re.compile(r"[.!?](?=\s|$)")
# Thinking off for every call (short spoken answers, 5-token router labels). Some models refuse
# "disabled" and name the setting to use instead; remember it per model.
_thinking: dict[str, dict] = {}


def available() -> bool:
    return bool(config.ANTHROPIC_API_KEY)


def client() -> AsyncAnthropic | None:
    global _client
    if _client is None and config.ANTHROPIC_API_KEY:
        _client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY, max_retries=0)
    return _client


def shrink_jpeg(jpeg_b64: str, max_edge: int = 768) -> str:
    """Re-encode to <= max_edge px on the long edge, JPEG q=80, to keep upload time low."""
    try:
        import cv2
        import numpy as np

        img = cv2.imdecode(np.frombuffer(base64.b64decode(jpeg_b64), np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return jpeg_b64
        h, w = img.shape[:2]
        if max(h, w) > max_edge:
            s = max_edge / max(h, w)
            img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return base64.b64encode(buf.tobytes()).decode() if ok else jpeg_b64
    except Exception:
        return jpeg_b64


def _content(text: str, jpeg_b64: str | None) -> list[dict]:
    content: list[dict] = []
    if jpeg_b64:
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                    "data": shrink_jpeg(jpeg_b64)}})
    content.append({"type": "text", "text": text})
    return content


def _thinking_off(model: str) -> dict:
    return _thinking.get(model, {"type": "disabled"})


def _learn_thinking(model: str, e: BadRequestError) -> bool:
    m = re.search(r'"thinking": \{"type": "(\w+)"\} instead', str(e))
    if m and _thinking.get(model, {}).get("type") != m.group(1):
        _thinking[model] = {"type": m.group(1)}
        return True
    return False


async def ask(model: str, system: str, text: str, jpeg_b64: str | None = None, max_tokens: int = 200,
              timeout: float = 10) -> str:
    c = client()
    if c is None:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    messages = [{"role": "user", "content": _content(text, jpeg_b64)}]

    async def call():
        try:
            return await c.messages.create(model=model, max_tokens=max_tokens, system=system, messages=messages,
                                           thinking=_thinking_off(model))
        except BadRequestError as e:
            if not _learn_thinking(model, e):
                raise
            return await c.messages.create(model=model, max_tokens=max_tokens, system=system, messages=messages,
                                           thinking=_thinking_off(model))

    resp = await asyncio.wait_for(call(), timeout)
    return "".join(b.text for b in resp.content if b.type == "text").strip()


async def warm_up(models: list[str]) -> None:
    """One tiny call per model at startup: opens the connection and learns the thinking setting."""
    for m in dict.fromkeys(models):
        try:
            await ask(m, "Reply with one word.", "hi", max_tokens=5, timeout=10)
        except Exception:
            pass


async def stream_sentences(model: str, system: str, text: str, jpeg_b64: str | None = None,
                           max_tokens: int = 90) -> AsyncIterator[str]:
    """Yield each sentence as soon as its terminal . ! ? arrives. Caller owns the overall timeout."""
    c = client()
    if c is None:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    buf = ""
    async with c.messages.stream(model=model, max_tokens=max_tokens, system=system, thinking=_thinking_off(model),
                                 messages=[{"role": "user", "content": _content(text, jpeg_b64)}]) as stream:
        async for delta in stream.text_stream:
            buf += delta
            while (m := _SENTENCE_END.search(buf)) and m.end() < len(buf):
                sentence, buf = buf[: m.end()].strip(), buf[m.end():]
                if sentence:
                    yield sentence
    if buf.strip():
        yield buf.strip()
