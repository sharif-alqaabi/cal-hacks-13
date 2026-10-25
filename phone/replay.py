"""Replay a glasses recording into core, as if the phone were live (PRD G-10).

  python phone/replay.py phone/fixtures/demo.jsonl                       # to $CORE_URL or ws://127.0.0.1:8000/stream
  python phone/replay.py demo.jsonl --url ws://<laptop>:8000/stream --from 30 --to 95 --loop
  python phone/replay.py demo.jsonl --export out/ --from 30 --to 60 --mp4  # frames + one WAV per push-to-talk turn

Messages go out with their recorded gaps (scaled by --speed) and `ts` rewritten to now.
Recorded snap answers are skipped; core's live `snap` requests are answered with the latest
recorded frame. Replies from core are printed. Recordings come from phone/tools/recorder.py.
"""
import argparse
import asyncio
import base64
import json
import os
import sys
import time
import wave
from pathlib import Path


def load(path: str, start: float, end: float | None) -> list[dict]:
    rows = []
    with open(path) as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                if r["t"] >= start and (end is None or r["t"] <= end):
                    rows.append(r)
    if not rows:
        sys.exit(f"no messages in {path} between {start}s and {end if end is not None else 'the end'}")
    return rows


def stream_url(text: str) -> str:
    s = text.strip()
    if s.startswith("http://"):
        s = "ws://" + s[7:]
    elif s.startswith("https://"):
        s = "wss://" + s[8:]
    elif "://" not in s:
        s = "ws://" + s
    head, _, path = s.partition("://")[2].partition("/")
    return s if path else s.rstrip("/") + "/stream"


async def replay(args) -> None:
    import websockets

    rows = load(args.file, args.start, args.end)
    url = stream_url(args.url)
    latest = {"frame": None}
    async with websockets.connect(url, max_size=None) as ws:
        print(f"replaying {len(rows)} messages ({rows[-1]['t'] - rows[0]['t']:.0f}s) from {args.file} to {url}")

        async def receive() -> None:
            async for raw in ws:
                m = json.loads(raw)
                if m.get("type") == "say":
                    print(f"  << say{' URGENT' if m.get('urgent') else ''}: {m.get('text')}")
                elif m.get("type") == "snap" and latest["frame"]:
                    frame = dict(latest["frame"], ts=time.time(), snap_id=m["snap_id"])
                    await ws.send(json.dumps(frame))
                    print(f"  << snap {m['snap_id']} (answered)")

        async def send() -> None:
            while True:
                t_first, wall0 = rows[0]["t"], time.monotonic()
                for r in rows:
                    delay = (r["t"] - t_first) / args.speed - (time.monotonic() - wall0)
                    if delay > 0:
                        await asyncio.sleep(delay)
                    msg = r["msg"]
                    if msg["type"] == "frame":
                        if msg.get("snap_id"):
                            continue
                        latest["frame"] = msg
                    elif msg["type"] == "ptt":
                        print(f"  >> ptt {msg['state']} at {r['t']:.1f}s")
                    if "ts" in msg:
                        msg = dict(msg, ts=time.time())
                    await ws.send(json.dumps(msg))
                if not args.loop:
                    return
                print("  -- looping")

        receiver = asyncio.create_task(receive())
        await send()
        await asyncio.sleep(3)  # let the last replies arrive
        receiver.cancel()


def export(args) -> None:
    import cv2
    import numpy as np

    rows = load(args.file, args.start, args.end)
    out = Path(args.export)
    out.mkdir(parents=True, exist_ok=True)
    frames = [r for r in rows if r["msg"]["type"] == "frame" and not r["msg"].get("snap_id")]

    if args.mp4 and frames:
        span = max(frames[-1]["t"] - frames[0]["t"], 1e-3)
        fps = max(1.0, round((len(frames) - 1) / span, 1))
        first = cv2.imdecode(np.frombuffer(base64.b64decode(frames[0]["msg"]["jpeg_b64"]), np.uint8), cv2.IMREAD_COLOR)
        h, w = first.shape[:2]
        path = out / "frames.mp4"
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
        for r in frames:
            img = cv2.imdecode(np.frombuffer(base64.b64decode(r["msg"]["jpeg_b64"]), np.uint8), cv2.IMREAD_COLOR)
            writer.write(cv2.resize(img, (w, h)) if img.shape[:2] != (h, w) else img)
        writer.release()
        print(f"wrote {path} ({len(frames)} frames, {fps} fps)")
    elif frames:
        d = out / "frames"
        d.mkdir(exist_ok=True)
        for i, r in enumerate(frames):
            (d / f"{i:05d}_{r['t']:08.2f}s.jpg").write_bytes(base64.b64decode(r["msg"]["jpeg_b64"]))
        print(f"wrote {len(frames)} JPEGs to {d}")

    turns, pcm, rate, t_down = [], bytearray(), None, None
    for r in rows:
        m = r["msg"]
        if m["type"] == "ptt" and m["state"] == "down":
            pcm, rate, t_down = bytearray(), None, r["t"]
        elif m["type"] == "audio" and t_down is not None:
            pcm += base64.b64decode(m["pcm16_b64"])
            rate = m["rate"]
        elif m["type"] == "ptt" and m["state"] == "up" and t_down is not None:
            if pcm and rate:
                turns.append((t_down, bytes(pcm), rate))
            t_down = None
    for i, (t, data, rate) in enumerate(turns, 1):
        path = out / f"turn_{i:02d}.wav"
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(data)
        print(f"wrote {path} ({len(data) / 2 / rate:.1f}s @ {rate} Hz, pressed at {t:.1f}s)")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("file")
    p.add_argument("--url", default=os.environ.get("CORE_URL", "ws://127.0.0.1:8000/stream"))
    p.add_argument("--from", dest="start", type=float, default=0)
    p.add_argument("--to", dest="end", type=float)
    p.add_argument("--speed", type=float, default=1.0)
    p.add_argument("--loop", action="store_true")
    p.add_argument("--export", metavar="DIR", help="write frames and per-turn WAVs instead of replaying")
    p.add_argument("--mp4", action="store_true", help="with --export: one frames.mp4 instead of JPEGs")
    a = p.parse_args()
    try:
        export(a) if a.export else asyncio.run(replay(a))
    except KeyboardInterrupt:
        pass
