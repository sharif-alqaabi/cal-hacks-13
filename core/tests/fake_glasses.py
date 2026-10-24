"""Pretend to be the phone relay: stream frames to core and type utterances.

  python -m tests.fake_glasses                      # laptop webcam
  python -m tests.fake_glasses  --video walk.mp4    # loop a recorded clip
  python -m tests.fake_glasses  --images tests/fixtures/ # cycle through JPEGs

Type a sentence and press Enter to "say" it (sent as a text message, skipping STT).
Type /ptt to send a push-to-talk down/up with a short mic recording (needs sounddevice).
Type /wav <file> to send a WAV over push-to-talk at real-time pace (e.g. tests/fixtures/audio/keys.wav).
--rate 8000|16000 sets the /ptt mic rate (8000 mimics the glasses HFP mic).
Prints the latency from PTT up / text sent to the first say received.
"""
import argparse
import asyncio
import base64
import json
import sys
import time
import wave
from pathlib import Path

import cv2
import websockets


def open_source(args):
    if args.images:
        paths = sorted(p for p in Path(args.images).iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
        if not paths:
            sys.exit(f"no images in {args.images}")
        i = 0

        def nxt():
            nonlocal i
            img = cv2.imread(str(paths[i % len(paths)]))
            i += 1
            return img
        return nxt
    cap = cv2.VideoCapture(args.video if args.video else args.camera)
    if not cap.isOpened():
        sys.exit("could not open video source")

    def nxt():
        ok, img = cap.read()
        if not ok and args.video:          # loop the clip
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, img = cap.read()
        return img if ok else None
    return nxt


def encode(img, width: int) -> dict:
    h, w = img.shape[:2]
    if w > width:
        img = cv2.resize(img, (width, int(h * width / w)))
    ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
    h, w = img.shape[:2]
    return {"type": "frame", "ts": time.time(), "jpeg_b64": base64.b64encode(jpg.tobytes()).decode(), "w": w, "h": h}


async def main(args):
    next_frame = open_source(args)
    latest = {"img": None, "t_end": None}
    async with websockets.connect(args.url, max_size=None) as ws:
        print(f"connected to {args.url}. Type to speak, Ctrl+C to quit.")

        async def send_frames():
            while True:
                img = next_frame()
                if img is not None:
                    latest["img"] = img
                    await ws.send(json.dumps(encode(img, 640)))
                await asyncio.sleep(1 / args.fps)

        async def receive():
            async for raw in ws:
                m = json.loads(raw)
                if m["type"] == "say":
                    tag = "URGENT " if m.get("urgent") else ""
                    lat = ""
                    if latest["t_end"] and not m.get("urgent"):
                        lat = f"  ({int((time.time() - latest['t_end']) * 1000)} ms to first say)"
                        latest["t_end"] = None
                    print(f"\n  << {tag}{m['text']}{lat}")
                elif m["type"] == "snap" and latest["img"] is not None:
                    f = encode(latest["img"], 1280)
                    f["snap_id"] = m["snap_id"]
                    await ws.send(json.dumps(f))

        async def typing():
            loop = asyncio.get_running_loop()
            while True:
                line = (await loop.run_in_executor(None, sys.stdin.readline)).strip()
                if not line:
                    continue
                if line == "/ptt":
                    await push_to_talk(ws, rate=args.rate)
                elif line.startswith("/wav "):
                    await send_wav(ws, line[5:].strip())
                else:
                    await ws.send(json.dumps({"type": "text", "text": line}))
                latest["t_end"] = time.time()

        await asyncio.gather(send_frames(), receive(), typing())


async def push_to_talk(ws, seconds: float = 3.0, rate: int = 8000):
    try:
        import sounddevice as sd
    except ImportError:
        print("pip install sounddevice to use /ptt")
        return
    print(f"  recording {seconds:.0f}s…")
    await ws.send(json.dumps({"type": "ptt", "state": "down"}))
    pcm = await asyncio.to_thread(lambda: sd.rec(int(seconds * rate), samplerate=rate, channels=1, dtype="int16", blocking=True))
    await ws.send(json.dumps({"type": "audio", "ts": time.time(), "pcm16_b64": base64.b64encode(pcm.tobytes()).decode(), "rate": rate}))
    await ws.send(json.dumps({"type": "ptt", "state": "up"}))


async def send_wav(ws, path: str):
    try:
        with wave.open(path) as w:
            pcm, rate = w.readframes(w.getnframes()), w.getframerate()
    except Exception as e:
        print(f"  can't read {path}: {e}")
        return
    await ws.send(json.dumps({"type": "ptt", "state": "down"}))
    step = rate * 2 // 10   # 100 ms
    for i in range(0, len(pcm), step):
        await ws.send(json.dumps({"type": "audio", "ts": time.time(), "rate": rate,
                                  "pcm16_b64": base64.b64encode(pcm[i:i + step]).decode()}))
        await asyncio.sleep(0.1)
    await ws.send(json.dumps({"type": "ptt", "state": "up"}))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="ws://127.0.0.1:8000/stream")
    p.add_argument("--camera", type=int, default=0)
    p.add_argument("--video")
    p.add_argument("--images")
    p.add_argument("--fps", type=float, default=5)
    p.add_argument("--rate", type=int, default=8000, choices=[8000, 16000])
    try:
        asyncio.run(main(p.parse_args()))
    except KeyboardInterrupt:
        pass
