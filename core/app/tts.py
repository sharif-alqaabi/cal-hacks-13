"""Text-to-speech with Cartesia Sonic-3.5, one REST call per sentence (C-4).

Lookup order: memory -> disk cache (cache/tts/) -> network. Fixed phrases are pre-generated at
startup so hazards and fallback lines need no network after the first good boot.
synth() is the seam tests replace. Returns base64 pcm16 at TTS_RATE, or '' when unavailable.
"""
import asyncio
import base64
import hashlib
import logging

import httpx

from . import config

log = logging.getLogger("core.tts")

URL = "https://api.cartesia.ai/tts/bytes"
_mem: dict[str, str] = {}
status = {"cached": 0, "total": 0, "last_error": None}


def available() -> bool:
    return bool(config.CARTESIA_API_KEY and config.CARTESIA_VOICE_ID)


def _key(text: str) -> str:
    raw = f"{config.CARTESIA_TTS_MODEL}|{config.CARTESIA_VOICE_ID}|{config.TTS_RATE}|{text}"
    return hashlib.sha1(raw.encode()).hexdigest()


def _disk_path(text: str):
    return config.CACHE_DIR / "tts" / f"{_key(text)}.pcm"


def cached(text: str) -> str | None:
    k = _key(text)
    if k in _mem:
        return _mem[k]
    p = _disk_path(text)
    if p.exists() and p.stat().st_size > 0:
        _mem[k] = base64.b64encode(p.read_bytes()).decode()
        return _mem[k]
    return None


async def _fetch(text: str) -> bytes:
    async with httpx.AsyncClient(timeout=config.TTS_TIMEOUT_S) as client:
        r = await client.post(
            URL,
            headers={"X-API-Key": config.CARTESIA_API_KEY, "Cartesia-Version": config.CARTESIA_VERSION},
            json={
                "model_id": config.CARTESIA_TTS_MODEL,
                "transcript": text,
                "voice": {"mode": "id", "id": config.CARTESIA_VOICE_ID},
                "language": "en",
                "output_format": {"container": "raw", "encoding": "pcm_s16le", "sample_rate": config.TTS_RATE},
            },
        )
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        return r.content


async def synth(text: str) -> str:
    hit = cached(text)
    if hit is not None:
        return hit
    if not available():
        return ""
    try:
        pcm = await asyncio.wait_for(_fetch(text), config.TTS_TIMEOUT_S)
    except Exception as e:
        status["last_error"] = str(e)
        log.error("TTS failed: %s", e)
        return ""
    if not pcm:
        return ""
    try:
        p = _disk_path(text)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(pcm)
    except Exception as e:
        log.warning("TTS cache write failed: %s", e)
    b64 = base64.b64encode(pcm).decode()
    _mem[_key(text)] = b64
    return b64


async def synth_urgent(text: str) -> str:
    """Hazard path: cache only, never the network. '' lets the phone use on-device TTS."""
    return cached(text) or ""


async def pregenerate(phrases: list[str]) -> None:
    """Cache audio for fixed phrases so hazards and fallback lines need no network call."""
    phrases = list(dict.fromkeys(phrases))
    status["total"], status["cached"] = len(phrases), 0
    sem = asyncio.Semaphore(4)

    async def one(p: str) -> None:
        async with sem:
            if cached(p) is not None or await synth(p):
                status["cached"] += 1

    await asyncio.gather(*(one(p) for p in phrases))
    log.info("pre-generated %d/%d phrases", status["cached"], status["total"])
