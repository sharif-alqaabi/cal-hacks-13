"""Fake phone for core: streams scene frames to core's /stream and sends typed sentences as `text` messages.

Core's own router turns each sentence into the contract request memory receives (watch the memory terminal),
so this tests the real speech-to-JSON path. Memory must run with MEMORY_TEST_SCENES=1, which makes it read
each scene from the JPEG comment this script writes instead of looking at pixels.

    python mock/drive.py seed    # reset memory, replay mock/script.json (a morning's timeline)
    python mock/drive.py ask     # run mock/questions.json through core, PASS/FAIL each
    python mock/drive.py chat    # ':scene <description>' changes the view, anything else is spoken to core

CORE_URL (default ws://127.0.0.1:8000/stream) and MEMORY_URL (default http://127.0.0.1:8001) can be overridden.
"""
import argparse
import asyncio
import base64
import io
import json
import os
import re
import sys
import textwrap
import time
import zlib
from pathlib import Path

import httpx
import websockets
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
CORE_URL = os.getenv("CORE_URL", "ws://127.0.0.1:8000/stream")
MEMORY_URL = os.getenv("MEMORY_URL", "http://127.0.0.1:8001")
FPS = 2


def render_scene(text: str) -> str:
    """A 640x480 JPEG (base64) for a scene description. The description rides in the JPEG comment, where memory
    reads it in test mode. The 4x4 pattern comes from the text, so different scenes look different to core's
    scene-change check and memory's duplicate check, and the same scene twice is identical."""
    bits = zlib.crc32(text.encode())
    img = Image.new("RGB", (640, 480), (40, 40, 40))
    d = ImageDraw.Draw(img)
    for r in range(4):
        for c in range(4):
            shade = 215 if (bits >> (r * 4 + c)) & 1 else 35
            d.rectangle([c * 160, 130 + r * 88, c * 160 + 159, 130 + r * 88 + 87], fill=(shade, shade, shade))
    d.rectangle([0, 0, 640, 130], fill=(20, 20, 60))
    try:
        font = ImageFont.load_default(size=14)
    except TypeError:  # Pillow without sized default fonts
        font = ImageFont.load_default()
    d.multiline_text((8, 6), "\n".join(textwrap.wrap(text, 78)[:8]), fill=(255, 255, 255), font=font)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=70, comment=text.encode("utf-8"))
    return base64.b64encode(buf.getvalue()).decode()


def frame_msg(jpeg_b64: str, ts: float, snap_id: str | None = None) -> str:
    return json.dumps({"type": "frame", "ts": ts, "jpeg_b64": jpeg_b64, "w": 640, "h": 480, "snap_id": snap_id})


class Phone:
    def __init__(self, ws) -> None:
        self.ws = ws
        self.inbox: asyncio.Queue[str] = asyncio.Queue()  # spoken replies from core
        self.jpeg: str | None = None                      # what the camera currently sees
        self.offset = 0.0                                 # seconds into the past the frame timestamps are set
        self.first_ms = 0
        self.reader = asyncio.create_task(self._read())

    async def _read(self) -> None:
        try:
            async for raw in self.ws:
                m = json.loads(raw)
                if m["type"] == "say":
                    self.inbox.put_nowait(m["text"])
                elif m["type"] == "snap" and self.jpeg:  # core asks for a full-resolution frame: send the same scene
                    await self.ws.send(frame_msg(self.jpeg, time.time() - self.offset, m["snap_id"]))
        except websockets.ConnectionClosed:
            pass

    async def stream(self, seconds: float) -> None:
        for _ in range(max(1, int(seconds * FPS))):
            if self.jpeg:
                await self.ws.send(frame_msg(self.jpeg, time.time() - self.offset))
            await asyncio.sleep(1 / FPS)

    async def say(self, text: str, timeout: float = 20.0, quiet: float = 1.5) -> list[str]:
        """Send a typed sentence (skips speech-to-text) and collect core's spoken replies."""
        while not self.inbox.empty():
            self.inbox.get_nowait()
        t0 = time.perf_counter()
        await self.ws.send(json.dumps({"type": "text", "text": text}))
        out: list[str] = []
        try:
            out.append(await asyncio.wait_for(self.inbox.get(), timeout))
            self.first_ms = int((time.perf_counter() - t0) * 1000)  # time to the first spoken reply
            while True:  # a reply can arrive as two consecutive says, one per sentence
                out.append(await asyncio.wait_for(self.inbox.get(), quiet))
        except asyncio.TimeoutError:
            return out


async def wait_idle(http: httpx.AsyncClient, timeout: float = 90.0) -> None:
    """Block until memory has finished captioning what it was sent."""
    await asyncio.sleep(1.0)  # let core's last ingest request land
    t0 = time.time()
    while time.time() - t0 < timeout:
        if (await http.get("/health")).json()["pending"] == 0:
            return
        await asyncio.sleep(0.5)
    print(f"  (memory still captioning after {timeout:.0f} s)")


async def seed(phone: Phone, http: httpx.AsyncClient) -> None:
    r = await http.post("/reset")
    if r.status_code == 403:
        sys.exit("memory refused /reset: start it with MEMORY_ALLOW_RESET=1")
    r.raise_for_status()
    for ev in json.loads((HERE / "script.json").read_text()):
        phone.jpeg, phone.offset = render_scene(ev["scene"]), ev["min_ago"] * 60
        print(f"[{ev['min_ago']:>3} min ago] {ev['scene'][:88]}...")
        await phone.stream(ev.get("hold_s", 3.5))  # long enough for core to ingest the scene
        if ev.get("say"):
            says = await phone.say(ev["say"])
            print(f"    you:  {ev['say']}\n    core: {' '.join(says) or '(no reply)'}")
        await wait_idle(http)
    print(f"seeded: {(await http.get('/health')).json()['moments']} moments in the timeline")


async def ask(phone: Phone) -> int:
    failed = 0
    for q in json.loads((HERE / "questions.json").read_text()):
        reply = " ".join(await phone.say(q["q"]))
        ms = phone.first_ms
        ok = q["expect"].lower() in reply.lower() if "expect" in q else bool(re.search(q["expect_regex"], reply))
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {q['q']!r}  ({ms} ms)\n      -> {reply or '(no reply)'}")
    print(f"\n{len(json.loads((HERE / 'questions.json').read_text())) - failed} passed, {failed} failed")
    return failed


async def chat(phone: Phone) -> None:
    print("':scene <description>' changes what the camera sees; anything else is spoken to core. Ctrl+D quits.")

    async def feed() -> None:
        while True:
            await phone.stream(1)

    feeder = asyncio.create_task(feed())
    loop = asyncio.get_running_loop()
    try:
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                break
            line = line.strip()
            if line.startswith(":scene "):
                phone.jpeg, phone.offset = render_scene(line[7:].strip()), 0.0
                print("  (the camera now sees that)")
            elif line:
                print("  core:", " ".join(await phone.say(line)) or "(no reply)")
    finally:
        feeder.cancel()


async def main(mode: str) -> None:
    try:
        async with httpx.AsyncClient(base_url=MEMORY_URL, timeout=30) as http:
            await http.get("/health")
    except httpx.HTTPError:
        sys.exit(f"can't reach memory at {MEMORY_URL}: start it with uvicorn app:app --port 8001")
    try:
        ws = await websockets.connect(CORE_URL, max_size=None)
    except OSError:
        sys.exit(f"can't reach core at {CORE_URL}: start it with uvicorn app.main:app --port 8000")
    async with ws, httpx.AsyncClient(base_url=MEMORY_URL, timeout=30) as http:
        phone = Phone(ws)
        failed = await {"seed": lambda: seed(phone, http), "ask": lambda: ask(phone), "chat": lambda: chat(phone)}[mode]()
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["seed", "ask", "chat"])
    try:
        asyncio.run(main(p.parse_args().mode))
    except KeyboardInterrupt:
        pass
