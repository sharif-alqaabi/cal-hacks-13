"""Test doubles for every external seam core has. install() patches app module attributes.

Nothing under app/ imports this; tests and tests/run_offline.py install it.
"""
import asyncio
import base64
import hashlib
import json
from pathlib import Path

import httpx
import numpy as np

FIXTURES = Path(__file__).resolve().parent / "fixtures"

DESCRIBE_REPLY = ["A chair is ahead, slightly left.", "A table is on your right."]
SIGNAL_REPLY = '{"signal":"walk","countdown":null,"vehicles":[{"motion":"moving","from":"left"}]}'
CHAT_REPLY = "I'm here to help. Ask me what's around you."
BAD_REPLY = "It is safe to cross now."


def load_transcripts() -> dict:
    p = FIXTURES / "transcripts.json"
    return json.loads(p.read_text()) if p.exists() else {"by_sha1": {}, "by_file": {}}


class FakeSTTTurn:
    def __init__(self, table: dict) -> None:
        self.table = table
        self.pcm = bytearray()

    async def feed(self, pcm: bytes) -> None:
        self.pcm.extend(pcm)

    async def finish(self) -> str:
        await asyncio.sleep(0.05)
        return self.table.get(hashlib.sha1(bytes(self.pcm)).hexdigest(), "")

    async def cancel(self) -> None:
        pass


class FakeSTT:
    def __init__(self) -> None:
        self.table = load_transcripts()["by_sha1"]

    async def start_turn(self, rate: int) -> FakeSTTTurn:
        return FakeSTTTurn(self.table)


class FakeLLM:
    """Answers keyed on the system prompt. bad=True makes every free-text answer a banned phrase."""

    def __init__(self, bad: bool = False, delay: float = 0.15) -> None:
        self.bad = bad
        self.delay = delay
        self.calls: list[str] = []

    async def ask(self, model, system, text, jpeg_b64=None, max_tokens=200, timeout=10) -> str:
        from app import router, vision

        await asyncio.sleep(self.delay)
        self.calls.append(system[:20])
        if system == router.ROUTER_SYSTEM:
            return router.keyword_route(text)
        if system == vision.SIGNAL_SYSTEM:
            return SIGNAL_REPLY
        return BAD_REPLY if self.bad else CHAT_REPLY

    async def stream_sentences(self, model, system, text, jpeg_b64=None, max_tokens=90):
        self.calls.append(system[:20])
        for s in ([BAD_REPLY] if self.bad else DESCRIBE_REPLY):
            await asyncio.sleep(self.delay)
            yield s


class FakeTTS:
    def __init__(self, empty: bool = False, rate: int = 24000) -> None:
        self.empty = empty
        self.audio = "" if empty else base64.b64encode(bytes(int(rate * 0.3) * 2)).decode()
        self.texts: list[str] = []

    async def synth(self, text: str) -> str:
        self.texts.append(text)
        return self.audio

    async def synth_urgent(self, text: str) -> str:
        self.texts.append(text)
        return self.audio


class FakeJev:
    def __init__(self, unavailable: bool = False) -> None:
        self.unavailable = unavailable

    async def jev_route(self, text: str, pending_confirm: bool = False):
        from app import router

        if self.unavailable:
            return None
        return router.keyword_route(text), 0.9


class ColorDetector:
    """No YOLO: one 'chair' box around pure-magenta pixels."""

    def detect(self, jpeg_b64: str):
        import cv2
        from app.hazards import Box

        img = cv2.imdecode(np.frombuffer(base64.b64decode(jpeg_b64), np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return []
        mask = cv2.inRange(img, (200, 0, 200), (255, 60, 255))   # BGR magenta, JPEG-tolerant
        ys, xs = np.nonzero(mask)
        if len(xs) < 50:
            return []
        h, w = mask.shape
        return [Box("chair", 0.9, xs.min() / w, ys.min() / h, (xs.max() + 1) / w, (ys.max() + 1) / h)]


def asgi_client_factory(stub_app):
    def make(timeout: float | None = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=stub_app), base_url="http://stub",
                                 timeout=timeout or 4)
    return make


def install(setattr_=setattr, bad: bool = False, jev: bool = True, tts_empty: bool = False,
            detector: bool = True) -> dict:
    """Patch every external API seam. setattr_ is monkeypatch.setattr in pytest, plain setattr otherwise."""
    from app import hazards, llm, router, stt, tts
    from app.hazards import HazardTracker

    fakes = {"llm": FakeLLM(bad=bad), "tts": FakeTTS(empty=tts_empty), "stt": FakeSTT(),
             "jev": FakeJev(unavailable=not jev), "detector": ColorDetector()}
    setattr_(stt, "start_turn", fakes["stt"].start_turn)
    setattr_(stt, "available", lambda: True)
    setattr_(llm, "ask", fakes["llm"].ask)
    setattr_(llm, "stream_sentences", fakes["llm"].stream_sentences)
    setattr_(llm, "available", lambda: True)
    setattr_(tts, "synth", fakes["tts"].synth)
    setattr_(tts, "synth_urgent", fakes["tts"].synth_urgent)
    setattr_(tts, "available", lambda: True)
    setattr_(router, "jev_route", fakes["jev"].jev_route)
    if detector:
        setattr_(hazards.detector, "detect", fakes["detector"].detect)
        setattr_(hazards.detector, "enabled", True)
        setattr_(hazards.detector, "infer_ms", 1)
        setattr_(hazards.detector, "tracker", HazardTracker())
    return fakes


def install_stubs(setattr_=setattr, memory_app=None, browser_app=None) -> None:
    """Point the memory/browser clients at in-process stub apps (no ports)."""
    from app.clients import browser, memory
    from tests.stubs import browser_stub, memory_stub

    setattr_(memory, "_client", asgi_client_factory(memory_app or memory_stub.app))
    setattr_(browser, "_client", asgi_client_factory(browser_app or browser_stub.app))
