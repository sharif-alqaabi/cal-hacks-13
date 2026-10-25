"""Stand-in for core that records everything the phone sends (PRD G-10).

  python phone/tools/recorder.py --name demo        # ws://0.0.0.0:8000/stream -> phone/fixtures/demo.jsonl

Point the app's core address at this laptop, walk the demo beats, Ctrl+C when done.
Every message is checked against core's contract (core/contracts/stream.py) and written as one
JSON line: {"t": seconds since the phone connected, "msg": {...}}.

It also acts as a mock core so the app can be exercised without core:
  - after every `ptt up` it sends a non-urgent `say` (no audio, so the phone uses its own voice)
  - every --snap-every seconds it sends a `snap`
  - every --urgent-every seconds (0 = off) it sends an urgent `say`
Type `u` + Enter for an urgent say, `s` + Enter for a snap.
"""
import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))
from contracts.stream import AudioMsg, FrameMsg, PttMsg, parse_inbound  # noqa: E402

FIXTURES = ROOT / "phone" / "fixtures"


class Stats:
    def __init__(self):
        self.frames = 0
        self.frames_this_s = 0
        self.fps = 0
        self.size = "-"
        self.audio_s = 0.0
        self.rate = None
        self.ptts = 0
        self.invalid = 0


class Recorder:
    def __init__(self, args):
        self.args = args
        self.path = FIXTURES / f"{args.name}.jsonl"
        self.stats = Stats()
        self.ws = None
        self.n = 0

    async def say(self, text: str, urgent: bool) -> None:
        if self.ws is None:
            return
        self.n += 1
        msg = {"type": "say", "id": f"m{self.n}", "text": text, "pcm16_b64": "", "rate": 24000, "urgent": urgent}
        await self.ws.send(json.dumps(msg))
        print(f"\n  >> say{' URGENT' if urgent else ''}: {text}")

    async def snap(self) -> None:
        if self.ws is None:
            return
        self.n += 1
        await self.ws.send(json.dumps({"type": "snap", "snap_id": f"s{self.n}"}))
        print(f"\n  >> snap s{self.n}")

    async def handler(self, ws) -> None:
        if self.ws is not None:
            print("\n  second phone refused; one recording at a time")
            await ws.close()
            return
        self.ws = ws
        t0 = time.time()
        FIXTURES.mkdir(parents=True, exist_ok=True)
        print(f"phone connected from {ws.remote_address[0]}, recording to {self.path}")
        with self.path.open("a") as out:
            try:
                async for raw in ws:
                    t = round(time.time() - t0, 3)
                    try:
                        msg = parse_inbound(raw)
                    except Exception as e:  # noqa: BLE001 - report every contract break, keep recording
                        self.stats.invalid += 1
                        print(f"\n  INVALID message at {t}s: {e}\n  {raw[:200]}")
                        continue
                    out.write(json.dumps({"t": t, "msg": json.loads(raw)}) + "\n")
                    await self.observe(msg)
            except ConnectionClosed:
                pass
        self.ws = None
        print(f"\nphone disconnected; {self.path} has {sum(1 for _ in self.path.open())} lines")

    async def observe(self, msg) -> None:
        s = self.stats
        if isinstance(msg, FrameMsg):
            if msg.snap_id is None:
                s.frames += 1
                s.frames_this_s += 1
            s.size = f"{msg.w}x{msg.h}"
        elif isinstance(msg, AudioMsg):
            s.rate = msg.rate
            s.audio_s += len(msg.pcm16_b64) * 3 / 4 / 2 / msg.rate
        elif isinstance(msg, PttMsg) and msg.state == "up":
            s.ptts += 1
            await self.say("Mock reply to your question.", urgent=False)

    async def status(self) -> None:
        while True:
            await asyncio.sleep(1)
            s = self.stats
            s.fps, s.frames_this_s = s.frames_this_s, 0
            line = (f"{s.fps:2d} fps {s.size:>9} | frames {s.frames} | audio {s.audio_s:5.1f}s"
                    f" @{s.rate or '-'} | ptt {s.ptts} | invalid {s.invalid}")
            print("\r" + line, end="", flush=True)

    async def timers(self) -> None:
        a = self.args
        last_snap = last_urgent = time.time()
        while True:
            await asyncio.sleep(0.5)
            now = time.time()
            if a.snap_every and now - last_snap >= a.snap_every:
                last_snap = now
                await self.snap()
            if a.urgent_every and now - last_urgent >= a.urgent_every:
                last_urgent = now
                await self.say("Stop, chair ahead, slightly left.", urgent=True)

    async def keys(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:  # no terminal (e.g. run in the background)
                return
            cmd = line.strip().lower()
            if cmd == "u":
                await self.say("Stop, chair ahead, slightly left.", urgent=True)
            elif cmd == "s":
                await self.snap()


def health(connection, request):
    if request.path != "/stream":
        return connection.respond(200, "ok\n")
    return None


async def main(args) -> None:
    rec = Recorder(args)
    async with serve(rec.handler, args.host, args.port, process_request=health, max_size=None):
        print(f"recorder on ws://{args.host}:{args.port}/stream -> {rec.path}")
        await asyncio.gather(rec.status(), rec.timers(), rec.keys())


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", default=datetime.now().strftime("rec-%Y%m%d-%H%M%S"))
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--snap-every", type=float, default=20)
    p.add_argument("--urgent-every", type=float, default=0)
    try:
        asyncio.run(main(p.parse_args()))
    except KeyboardInterrupt:
        print()
