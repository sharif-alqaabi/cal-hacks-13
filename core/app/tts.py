"""Text-to-speech with Cartesia Sonic. Returns raw pcm16 bytes ('' if TTS is unavailable)."""
import base64
import logging

import httpx

from . import config

log = logging.getLogger("core.tts")

_cache: dict[str, str] = {}   # text -> pcm16_b64, used for pre-generated hazard audio


async def synth(text: str) -> str:
    """Return base64 pcm16 at config.TTS_RATE, or '' so the phone can fall back to on-device TTS."""
    if text in _cache:
        return _cache[text]
    if not (config.CARTESIA_API_KEY and config.CARTESIA_VOICE_ID):
        return ""
    # TODO(C-4): stream chunks over Cartesia's WebSocket for faster first audio.
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                "https://api.cartesia.ai/tts/bytes",
                headers={"X-API-Key": config.CARTESIA_API_KEY, "Cartesia-Version": config.CARTESIA_VERSION},
                json={
                    "model_id": config.CARTESIA_TTS_MODEL,
                    "transcript": text,
                    "voice": {"mode": "id", "id": config.CARTESIA_VOICE_ID},
                    "output_format": {"container": "raw", "encoding": "pcm_s16le", "sample_rate": config.TTS_RATE},
                },
            )
            r.raise_for_status()
            return base64.b64encode(r.content).decode()
    except Exception as e:
        log.error("TTS failed: %s", e)
        return ""


async def pregenerate(phrases: list[str]) -> None:
    """Cache audio for fixed phrases (hazard warnings) so the hazard path needs no network call."""
    for p in phrases:
        audio = await synth(p)
        if audio:
            _cache[p] = audio
    log.info("pre-generated %d/%d phrases", len(_cache), len(phrases))
