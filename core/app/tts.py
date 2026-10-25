"""Text-to-speech with Cartesia Sonic-3.5, one REST call per sentence (C-4).

Lookup order: memory -> disk cache (cache/tts/) -> network. Fixed phrases are pre-generated at
startup so hazards and fallback lines need no network after the first good boot.
synth() is the seam tests replace. Returns base64 pcm16 at TTS_RATE, or '' when unavailable.
"""
import asyncio
import base64
import hashlib
import logging

import numpy as np

from . import config, net

log = logging.getLogger("core.tts")

BASE = "https://api.cartesia.ai"
_mem: dict[str, str] = {}
status = {"cached": 0, "total": 0, "last_error": None}
API_MAX_SPEED = 1.5  # Cartesia rejects generation_config.speed above this; the rest is a local time-stretch


def available() -> bool:
    return bool(config.CARTESIA_API_KEY and config.CARTESIA_VOICE_ID)


def _key(text: str) -> str:
    raw = f"{config.CARTESIA_TTS_MODEL}|{config.CARTESIA_VOICE_ID}|{config.TTS_RATE}|{config.TTS_SPEED}|{text}"
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
    r = await net.client(BASE, config.TTS_TIMEOUT_S).post(
        "/tts/bytes",
        headers={"X-API-Key": config.CARTESIA_API_KEY, "Cartesia-Version": config.CARTESIA_VERSION},
        json={
            "model_id": config.CARTESIA_TTS_MODEL,
            "transcript": text,
            "voice": {"mode": "id", "id": config.CARTESIA_VOICE_ID},
            "language": "en",
            "generation_config": {"speed": min(config.TTS_SPEED, API_MAX_SPEED)},
            "output_format": {"container": "raw", "encoding": "pcm_s16le", "sample_rate": config.TTS_RATE},
        },
    )
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    return _stretch(r.content, config.TTS_SPEED / API_MAX_SPEED)


def _stretch(pcm: bytes, factor: float) -> bytes:
    """Speed pcm16 up by factor without changing pitch (WSOLA: 30 ms frames, 10 ms search)."""
    if factor <= 1.0 or len(pcm) < 4:
        return pcm
    x = np.frombuffer(pcm, np.int16).astype(np.float32)
    n, tol = int(0.03 * config.TTS_RATE), int(0.01 * config.TTS_RATE)
    hop = n // 2
    win = np.hanning(n).astype(np.float32)
    xp = np.pad(x, (tol, 2 * n + 2 * tol))
    out_len = int(len(x) / factor)
    y = np.zeros(out_len + n, np.float32)
    wsum = np.zeros_like(y)
    prev = None
    for k in range(out_len // hop + 1):
        ana = int(k * hop * factor)
        if prev is None:
            start = ana + tol
        else:
            target = xp[prev + hop: prev + hop + n]
            corr = np.correlate(xp[ana: ana + n + 2 * tol], target, "valid")
            start = ana + int(np.argmax(corr))
        y[k * hop: k * hop + n] += xp[start: start + n] * win
        wsum[k * hop: k * hop + n] += win
        prev = start
    y = y[:out_len] / np.maximum(wsum[:out_len], 1e-3)
    return np.clip(y, -32768, 32767).astype(np.int16).tobytes()


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
