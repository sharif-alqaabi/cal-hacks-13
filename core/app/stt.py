"""Speech-to-text with Cartesia Ink-2, one streaming WebSocket per push-to-talk turn (C-2).

PTT down opens a turn lazily on the first audio chunk, audio is streamed as binary pcm16,
PTT up sends `finalize` and waits for `flush_done`. start_turn() is the seam tests replace.
"""
import asyncio
import json
import logging
from typing import Protocol
from urllib.parse import urlencode

import websockets

from . import config

log = logging.getLogger("core.stt")

URL = "wss://api.cartesia.ai/stt/websocket"
KEYTERMS = ["Sam", "keys", "crosswalk", "signal", "Palace of Fine Arts", "email", "send it", "I'm lost"]


class SttTurn(Protocol):
    async def feed(self, pcm: bytes) -> None: ...
    async def finish(self) -> str: ...
    async def cancel(self) -> None: ...


def available() -> bool:
    return bool(config.CARTESIA_API_KEY)


class InkTurn:
    def __init__(self, ws, rate: int) -> None:
        self.ws = ws
        self.chunk = rate * 2 // 10          # ~100 ms of pcm16
        self.pending = bytearray()
        self.text: list[str] = []
        self.done = asyncio.Event()
        self.error: str | None = None
        self.receiver = asyncio.create_task(self._receive())

    async def _receive(self) -> None:
        try:
            async for raw in self.ws:
                if isinstance(raw, bytes):
                    continue
                m = json.loads(raw)
                t = m.get("type")
                if t == "transcript" and m.get("is_final"):
                    self.text.append(m.get("text", ""))
                elif t == "flush_done":
                    self.done.set()
                elif t == "error":
                    self.error = str(m.get("message") or m)
                    log.error("Ink error: %s", self.error)
                    self.done.set()
                    return
        except Exception as e:
            self.error = self.error or str(e)
        finally:
            self.done.set()

    async def feed(self, pcm: bytes) -> None:
        self.pending.extend(pcm)
        while len(self.pending) >= self.chunk:
            await self.ws.send(bytes(self.pending[: self.chunk]))
            del self.pending[: self.chunk]

    async def finish(self) -> str:
        try:
            if self.pending:
                await self.ws.send(bytes(self.pending))
                self.pending.clear()
            await self.ws.send("finalize")
            try:
                await asyncio.wait_for(self.done.wait(), config.STT_FINISH_TIMEOUT_S)
            except asyncio.TimeoutError:
                log.warning("Ink finalize timed out; using partial transcript")
            if self.error and not self.text:
                raise RuntimeError(self.error)
            return "".join(self.text).strip()
        finally:
            await self.cancel()

    async def cancel(self) -> None:
        try:
            await self.ws.send("close")
        except Exception:
            pass
        try:
            await self.ws.close()
        except Exception:
            pass
        self.receiver.cancel()


async def start_turn(rate: int) -> SttTurn:
    if not available():
        raise RuntimeError("CARTESIA_API_KEY not set")
    params = [
        ("model", config.CARTESIA_STT_MODEL), ("encoding", "pcm_s16le"), ("sample_rate", str(rate)),
        ("cartesia_version", config.CARTESIA_VERSION), ("language", "en"),
    ] + [("keyterm", k) for k in KEYTERMS + config.STT_KEYTERMS]
    ws = await asyncio.wait_for(
        websockets.connect(f"{URL}?{urlencode(params)}", additional_headers={"X-API-Key": config.CARTESIA_API_KEY},
                           max_size=None),
        timeout=3,
    )
    return InkTurn(ws, rate)
