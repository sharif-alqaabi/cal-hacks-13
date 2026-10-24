"""Shared kept-alive HTTP clients for the hot path (TTS, Jev).

A fresh httpx client per call paid a TCP + TLS handshake every time: measured ~140 ms -> ~75 ms per Jev call
and ~100 ms per TTS sentence. One client per base URL and event loop (tests run several loops).
"""
import asyncio
import logging

import httpx

log = logging.getLogger("core.net")

_clients: dict[str, tuple[asyncio.AbstractEventLoop, httpx.AsyncClient]] = {}


def client(base: str, timeout: float) -> httpx.AsyncClient:
    loop = asyncio.get_running_loop()
    hit = _clients.get(base)
    if hit is None or hit[0] is not loop:
        c = httpx.AsyncClient(base_url=base, timeout=timeout, limits=httpx.Limits(keepalive_expiry=300))
        _clients[base] = (loop, c)
        return c
    return hit[1]


async def keep_warm(every_s: float = 30, also=None) -> None:
    """Touch each origin while idle so a demo turn after a pause doesn't pay the handshake again.
    `also` is an extra coroutine function run each round (the Anthropic client keeps its own pool)."""
    while True:
        await asyncio.sleep(every_s)
        if also is not None:
            await also()
        for base, (loop, c) in list(_clients.items()):
            if loop is asyncio.get_running_loop():
                try:
                    await c.head("/", timeout=3)
                except Exception as e:
                    log.debug("keep-warm %s: %s", base, e)
