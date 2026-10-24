"""Speech-to-text with Cartesia Ink.

Scaffold version: buffer audio while PTT is held, then transcribe the whole clip on release.
TODO(C-2): switch to Ink's streaming WebSocket with turn detection so we don't need PTT.
"""
import io
import logging
import wave

import httpx

from . import config

log = logging.getLogger("core.stt")


def pcm_to_wav(pcm: bytes, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


async def transcribe(pcm: bytes, rate: int) -> str:
    if not pcm:
        return ""
    if not config.CARTESIA_API_KEY:
        log.warning("CARTESIA_API_KEY not set; STT disabled (use the text box / 'text' messages)")
        return ""
    # TODO(C-2): verify endpoint + model id against Cartesia docs on the day.
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            "https://api.cartesia.ai/stt",
            headers={"X-API-Key": config.CARTESIA_API_KEY, "Cartesia-Version": config.CARTESIA_VERSION},
            data={"model": config.CARTESIA_STT_MODEL, "language": "en"},
            files={"file": ("clip.wav", pcm_to_wav(pcm, rate), "audio/wav")},
        )
        r.raise_for_status()
        return r.json().get("text", "").strip()
