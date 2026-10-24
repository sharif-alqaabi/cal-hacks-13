"""Judges' mirror: broadcasts transcript, intent, latencies and replies to /mirror viewers."""
import asyncio
import json
import time

from fastapi import WebSocket


class Mirror:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()

    async def add(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.add(ws)

    def remove(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def emit(self, kind: str, **data) -> None:
        if not self.clients:
            return
        msg = json.dumps({"kind": kind, "t": time.time(), **data})
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.remove(ws)


mirror = Mirror()
