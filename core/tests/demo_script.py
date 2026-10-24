"""Scripted demo beats against a running core, pass/fail + latency table (PRD 2 rehearsal).

  python -m tests.demo_script --offline        # starts stubs + tests.run_offline itself, tears down after
  python -m tests.demo_script --live           # core already running with real keys (tests/run_with_stubs.sh)
  flags: --audio (send WAVs over PTT instead of text), --only N, --url, --memory-url, --browser-url

Connects to /stream like the phone, streams the beat's frames at 5 fps, answers snaps, sends the
utterance and checks the say messages. Also listens on /mirror/ws for intents, hazard lag and turn logs.
"""
import argparse
import asyncio
import base64
import json
import os
import re
import subprocess
import sys
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import websockets

CORE = Path(__file__).resolve().parent.parent
FIX = CORE / "tests" / "fixtures"
REAL = FIX / "real"
WAVS = {
    "what's in front of me": "describe", "what does the signal say": "signal", "where did I put my keys": "keys",
    "email Sam that I'm at the Palace of Fine Arts": "email", "yes send it": "yes", "I'm lost": "lost",
}
FIRST_SAY_MAX_S = 3.5
NEGATIVE = re.compile(r"\b(can't|cannot|haven't|didn't|doesn't|don't|isn't|not)\b", re.I)   # "I can't see your keys" is a miss


def first_existing(*paths: Path) -> Path | None:
    return next((p for p in paths if p.exists()), None)


def load_frames(src: Path) -> list[bytes]:
    if src.is_dir():
        return [p.read_bytes() for p in sorted(src.glob("*.jpg"))]
    if src.suffix.lower() in (".mp4", ".mov", ".m4v"):
        import cv2
        cap, out, i = cv2.VideoCapture(str(src)), [], 0
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        step = max(1, round(fps / 5))
        while True:
            ok, img = cap.read()
            if not ok:
                break
            if i % step == 0:
                h, w = img.shape[:2]
                img = cv2.resize(img, (640, int(h * 640 / w)))
                out.append(cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])[1].tobytes())
            i += 1
        return out
    return [src.read_bytes()]


@dataclass
class Ctx:
    url: str
    mode: str
    audio: bool
    memory_url: str
    browser_url: str
    says: list = field(default_factory=list)       # (t, msg)
    mirror: list = field(default_factory=list)     # (t, event)

    @property
    def http(self) -> str:
        return self.url.replace("ws://", "http://").rsplit("/stream", 1)[0]


class Phone:
    """One /stream connection: frames at 5 fps in the background, snap answers, say collection."""

    def __init__(self, ctx: Ctx, frames: list[bytes], loop_frames: bool = True) -> None:
        self.ctx, self.frames, self.loop_frames = ctx, frames, loop_frames
        self.current = frames[0] if frames else None
        self.frames_done = asyncio.Event()

    async def __aenter__(self):
        self.ws = await websockets.connect(self.ctx.url, max_size=None)
        self.tasks = [asyncio.create_task(self._recv())]
        if self.frames:
            self.tasks.append(asyncio.create_task(self._send_frames()))
        return self

    async def __aexit__(self, *exc):
        for t in self.tasks:
            t.cancel()
        await self.ws.close()

    def set_frames(self, frames: list[bytes]) -> None:
        self.frames, self.current = frames, frames[0]

    def _frame(self, jpg: bytes, snap_id=None) -> str:
        m = {"type": "frame", "ts": time.time(), "jpeg_b64": base64.b64encode(jpg).decode(), "w": 640, "h": 480}
        if snap_id:
            m["snap_id"] = snap_id
        return json.dumps(m)

    async def _send_frames(self) -> None:
        i = 0
        while True:
            if i >= len(self.frames):
                if not self.loop_frames:
                    self.frames_done.set()
                    return
                i = 0
            self.current = self.frames[i]
            await self.ws.send(self._frame(self.current))
            i += 1
            await asyncio.sleep(0.2)

    async def _recv(self) -> None:
        async for raw in self.ws:
            m = json.loads(raw)
            if m["type"] == "say":
                self.ctx.says.append((time.time(), m))
            elif m["type"] == "snap" and self.current:
                await self.ws.send(self._frame(self.current, m["snap_id"]))

    async def utter(self, text: str) -> float:
        """Send an utterance; returns the time the turn 'ended' (text sent / PTT up)."""
        wav = FIX / "audio" / f"{WAVS.get(text, '')}.wav"
        if self.ctx.audio and text in WAVS and wav.exists():
            with wave.open(str(wav)) as w:
                pcm, rate = w.readframes(w.getnframes()), w.getframerate()
            await self.ws.send(json.dumps({"type": "ptt", "state": "down"}))
            step = rate * 2 // 10
            for i in range(0, len(pcm), step):
                await self.ws.send(json.dumps({"type": "audio", "ts": time.time(), "rate": rate,
                                               "pcm16_b64": base64.b64encode(pcm[i:i + step]).decode()}))
                await asyncio.sleep(0.1)
            await self.ws.send(json.dumps({"type": "ptt", "state": "up"}))
        else:
            await self.ws.send(json.dumps({"type": "text", "text": text}))
        return time.time()


async def wait_says(ctx: Ctx, since: float, n: int, timeout: float, urgent: bool | None = False) -> list:
    end = time.time() + timeout
    while time.time() < end:
        got = [(t, m) for t, m in ctx.says if t >= since and (urgent is None or m["urgent"] == urgent)]
        if len(got) >= n:
            return got
        await asyncio.sleep(0.05)
    return [(t, m) for t, m in ctx.says if t >= since and (urgent is None or m["urgent"] == urgent)]


def mirror_events(ctx: Ctx, kind: str, since: float) -> list[dict]:
    return [e for t, e in ctx.mirror if t >= since and e.get("kind") == kind]


async def stub_log(base: str) -> list | None:
    try:
        async with httpx.AsyncClient(timeout=2) as c:
            r = await c.get(f"{base}/_log")
            return r.json() if r.status_code == 200 else None
    except Exception:
        return None


async def turn_reply(ctx: Ctx, t0: float, n: int, timeout: float = 10) -> tuple[list[str], int | None]:
    got = await wait_says(ctx, t0, n, timeout)
    texts = [m["text"] for _, m in got]
    first = int((got[0][0] - t0) * 1000) if got else None
    return texts, first


def banned(texts: list[str]) -> bool:
    from app.safety import is_banned
    return any(is_banned(t) for t in texts)


def frames_for(name: str, ctx: Ctx) -> list[bytes]:
    real = {"room": REAL / "room.jpg", "keys": REAL / "keys_on_table.jpg", "crosswalk": REAL / "crosswalk_walk.jpg"}
    synth = {"room": FIX / "room.jpg", "keys": FIX / "keys_on_table.jpg", "crosswalk": FIX / "crosswalk.jpg"}
    src = first_existing(real[name], synth[name]) if ctx.mode == "live" else synth[name]
    return load_frames(src)


# ---- beats -------------------------------------------------------------------

async def beat_hazard(ctx: Ctx):
    if ctx.mode == "live":
        src = first_existing(REAL / "chair_walk.mp4", FIX / "zoom_walk")
        pat = r"^Stop, chair" if src and src.suffix == ".mp4" else r"^Stop, "
    else:
        src, pat = FIX / "chair_walk", r"^Stop, chair"
    if src is None:
        return "SKIP", None, None, "no hazard frames"
    t0 = time.time()
    async with Phone(ctx, load_frames(src), loop_frames=False) as ph:
        await ph.frames_done.wait()
        await asyncio.sleep(1)
    urgent = await wait_says(ctx, t0, 1, 0.1, urgent=True)
    hits = [(t, m) for t, m in urgent if re.match(pat, m["text"])]
    hz = [e for e in mirror_events(ctx, "hazard", t0) if re.match(pat, e["text"])]
    lag = hz[0]["lag_ms"] if hz else None
    ok = bool(hits) and lag is not None and lag < 1000
    gaps = [b - a for (a, _), (b, _) in zip(hits, hits[1:])]
    ok = ok and all(g >= 3 for g in gaps)
    texts = [m["text"] for _, m in urgent]
    note = f"warnings {texts}, lag {lag} ms, src {src.name}" if urgent else f"no warning (src {src.name})"
    return ("PASS" if ok else "FAIL"), lag, int((time.time() - t0) * 1000), note


async def beat_signal(ctx: Ctx):
    async with Phone(ctx, frames_for("crosswalk", ctx)) as ph:
        await asyncio.sleep(0.6)
        t0 = await ph.utter("what does the signal say")
        texts, first = await turn_reply(ctx, t0, 1, 8)
        await asyncio.sleep(1.5)
        texts, _ = await turn_reply(ctx, t0, 2, 0.1)
    intents = [e["intent"] for e in mirror_events(ctx, "intent", t0 - 0.5)]
    ok = (bool(texts) and intents[:1] == ["signal"] and re.search(r"walk|don't walk|counting down|can't read", texts[0])
          and not banned(texts) and first is not None and first < FIRST_SAY_MAX_S * 1000)
    return ("PASS" if ok else "FAIL"), first, int((time.time() - t0) * 1000), f"{intents[:1]} {texts}"


async def beat_keys(ctx: Ctx):
    async with Phone(ctx, frames_for("keys", ctx)) as ph:
        await asyncio.sleep(6)
        ph.set_frames(frames_for("room", ctx))
        await asyncio.sleep(0.5)
        t0 = await ph.utter("where did I put my keys")
        texts, first = await turn_reply(ctx, t0, 1, 8)
    log = await stub_log(ctx.memory_url)
    ingests = None if log is None else sum(e["endpoint"] == "/ingest" for e in log)
    limit = 2000 if ctx.mode == "offline" else FIRST_SAY_MAX_S * 1000
    ok = bool(texts) and "keys" in texts[0].lower() and not NEGATIVE.search(texts[0]) and first is not None and first < limit and (ingests is None or ingests >= 1)
    return ("PASS" if ok else "FAIL"), first, int((time.time() - t0) * 1000), f"ingests={ingests} {texts}"


async def beat_email(ctx: Ctx):
    async with Phone(ctx, frames_for("room", ctx)) as ph:
        await asyncio.sleep(0.4)
        t0 = await ph.utter("email Sam that I'm at the Palace of Fine Arts")
        texts, first = await turn_reply(ctx, t0, 2, 45)
        t1 = await ph.utter("yes send it")
        texts2, _ = await turn_reply(ctx, t1, 1, 45)
    log = await stub_log(ctx.browser_url)
    confirms = None if log is None else [e for e in log if e["endpoint"] == "/confirm"]
    ok = (len(texts) >= 2 and texts[0] == "Working on it." and "send" in texts[1].lower()
          and bool(texts2) and texts2[0].startswith("Sent") and (confirms is None or (confirms and confirms[-1]["body"]["yes"] is True)))
    return ("PASS" if ok else "FAIL"), first, int((time.time() - t0) * 1000), f"{texts} -> {texts2}"


async def beat_lost(ctx: Ctx):
    async with Phone(ctx, frames_for("room", ctx)) as ph:
        await asyncio.sleep(0.4)
        t0 = await ph.utter("I'm lost")
        texts, first = await turn_reply(ctx, t0, 1, 8)
    log = await stub_log(ctx.memory_url)
    alerts = None if log is None else [e for e in log if e["endpoint"] == "/alert"]
    ok = bool(texts) and "family" in texts[0] and (alerts is None or (alerts and alerts[-1]["body"]["kind"] == "lost"))
    return ("PASS" if ok else "FAIL"), first, int((time.time() - t0) * 1000), f"{texts}"


async def beat_memory_down(ctx: Ctx):
    async with httpx.AsyncClient(timeout=2) as c:
        try:
            r = await c.post(f"{ctx.memory_url}/_fail", json={"on": True})
            if r.status_code != 200:
                return "SKIP", None, None, "memory service has no /_fail (not the stub)"
        except Exception:
            return "SKIP", None, None, "memory service unreachable"
        try:
            async with Phone(ctx, frames_for("room", ctx)) as ph:
                await asyncio.sleep(0.4)
                t0 = await ph.utter("where did I put my keys")
                texts, first = await turn_reply(ctx, t0, 1, 8)
        finally:
            await c.post(f"{ctx.memory_url}/_fail", json={"on": False})
    from app import config
    ok = texts[:1] == ["Memory isn't available right now."] and first is not None and first < (config.SERVICE_TIMEOUT_S + 1) * 1000
    return ("PASS" if ok else "FAIL"), first, int((time.time() - t0) * 1000), f"{texts}"


async def beat_describe(ctx: Ctx):
    async with Phone(ctx, frames_for("room", ctx)) as ph:
        await asyncio.sleep(0.6)
        t0 = await ph.utter("what's in front of me")
        texts, first = await turn_reply(ctx, t0, 1, 8)
        await asyncio.sleep(2)
        texts, _ = await turn_reply(ctx, t0, 2, 0.1)
    ok = 1 <= len(texts) <= 2 and first is not None and first < FIRST_SAY_MAX_S * 1000 and not banned(texts)
    return ("PASS" if ok else "FAIL"), first, int((time.time() - t0) * 1000), f"{texts}"


async def beat_clear_path(ctx: Ctx):
    t0 = time.time()
    async with Phone(ctx, load_frames(FIX / "clear_path"), loop_frames=False) as ph:
        await ph.frames_done.wait()
        await asyncio.sleep(0.5)
    warnings = await wait_says(ctx, t0, 1, 0.1, urgent=True)
    ok = len(warnings) <= 1
    return ("PASS" if ok else "FAIL"), None, int((time.time() - t0) * 1000), f"{len(warnings)} warning(s) in 30 s"


async def beat_banned(ctx: Ctx):
    if ctx.mode != "offline":
        return "SKIP", None, None, "offline only"
    async with httpx.AsyncClient(timeout=2) as c:
        await c.post(f"{ctx.http}/_test/bad_llm", json={"on": True})
        try:
            # Signal answers are composed from JSON and cannot carry banned words, so the filter is
            # exercised through describe, where the model writes the sentence.
            async with Phone(ctx, frames_for("room", ctx)) as ph:
                await asyncio.sleep(0.4)
                t0 = await ph.utter("what's in front of me")
                texts, first = await turn_reply(ctx, t0, 1, 8)
                await asyncio.sleep(0.5)
        finally:
            await c.post(f"{ctx.http}/_test/bad_llm", json={"on": False})
    from app.safety import FALLBACK
    turns = mirror_events(ctx, "turn", t0)
    blocked = turns[-1]["banned_blocked"] if turns else 0
    ok = texts[:1] == [FALLBACK] and blocked > 0
    return ("PASS" if ok else "FAIL"), first, int((time.time() - t0) * 1000), f"{texts} banned_blocked={blocked}"


async def play_clip(ctx: Ctx, src: Path) -> tuple[float, list]:
    """Stream a clip once with no utterance; returns the start time and the urgent says it drew."""
    t0 = time.time()
    async with Phone(ctx, load_frames(src), loop_frames=False) as ph:
        await ph.frames_done.wait()
        await asyncio.sleep(1)
    return t0, await wait_says(ctx, t0, 1, 0.1, urgent=True)


async def beat_bicycle(ctx: Ctx):
    src = REAL / "bicycle_walk.mp4"
    if not src.exists():
        return "SKIP", None, None, "no bicycle_walk.mp4"
    t0, urgent = await play_clip(ctx, src)
    pat = r"^Stop, (bicycle|bike)"
    hits = [m["text"] for _, m in urgent if re.match(pat, m["text"])]
    hz = [e for e in mirror_events(ctx, "hazard", t0) if re.match(pat, e["text"])]
    lag = hz[0]["lag_ms"] if hz else None
    ok = bool(hits) and lag is not None and lag < 1000
    return ("PASS" if ok else "FAIL"), lag, int((time.time() - t0) * 1000), f"warnings {[m['text'] for _, m in urgent]}, lag {lag} ms"


async def beat_clear_hallway(ctx: Ctx):
    src = REAL / "clear_hallway.mp4"
    if not src.exists():
        return "SKIP", None, None, "no clear_hallway.mp4"
    t0, urgent = await play_clip(ctx, src)
    return ("PASS" if not urgent else "FAIL"), None, int((time.time() - t0) * 1000), f"warnings {[m['text'] for _, m in urgent]}"


BEATS = [
    ("Chair hazard", beat_hazard), ("Signal", beat_signal), ("Keys recall", beat_keys), ("Email", beat_email),
    ("Lost", beat_lost), ("Memory down", beat_memory_down), ("Describe", beat_describe),
    ("Clear path", beat_clear_path), ("Banned phrase", beat_banned),
    ("Bicycle hazard", beat_bicycle), ("Clear hallway", beat_clear_hallway),
]


async def listen_mirror(ctx: Ctx) -> None:
    async with websockets.connect(ctx.http.replace("http://", "ws://") + "/mirror/ws", max_size=None) as ws:
        async for raw in ws:
            e = json.loads(raw)
            if e.get("kind") != "frame":
                ctx.mirror.append((time.time(), e))


async def wait_health(base: str, timeout: float = 60) -> dict:
    end = time.time() + timeout
    async with httpx.AsyncClient(timeout=1) as c:
        while time.time() < end:
            try:
                return (await c.get(f"{base}/health")).json()
            except Exception:
                await asyncio.sleep(0.3)
    raise RuntimeError(f"core not up at {base}")


async def run(args) -> int:
    ctx = Ctx(args.url, "offline" if args.offline else "live", args.audio, args.memory_url, args.browser_url)
    health = await wait_health(ctx.http)
    print("health:", json.dumps({k: health.get(k) for k in ("stt", "tts", "tts_cached", "claude", "jev", "hazards",
                                                            "hazard_infer_ms", "memory", "browser")}))
    mirror_task = asyncio.create_task(listen_mirror(ctx))
    await asyncio.sleep(0.3)
    rows = []
    for i, (name, fn) in enumerate(BEATS, 1):
        if args.only and i != args.only:
            continue
        try:
            status, first, total, note = await fn(ctx)
        except Exception as e:
            status, first, total, note = "FAIL", None, None, f"error: {e!r}"
        rows.append((i, name, status, first, total, note))
        print(f"  {i}. {name:<14} {status:<4} first={first} total={total}  {note}", flush=True)
        await asyncio.sleep(0.5)
    mirror_task.cancel()
    print("\n| # | Beat | Result | First audio ms | Total ms |\n|---|---|---|---|---|")
    for i, name, status, first, total, _ in rows:
        print(f"| {i} | {name} | {status} | {first if first is not None else '-'} | {total if total is not None else '-'} |")
    return 1 if any(r[2] == "FAIL" for r in rows) else 0


def main() -> None:
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--offline", action="store_true")
    g.add_argument("--live", action="store_true")
    p.add_argument("--audio", action="store_true")
    p.add_argument("--only", type=int)
    p.add_argument("--url", default="ws://127.0.0.1:8000/stream")
    p.add_argument("--memory-url", default="http://127.0.0.1:8001")
    p.add_argument("--browser-url", default="http://127.0.0.1:8002")
    args = p.parse_args()

    procs = []
    if args.offline:
        env = {**os.environ, "MEMORY_URL": args.memory_url, "BROWSER_URL": args.browser_url,
               "LOG_DIR": str(CORE / "logs" / "offline"), "CACHE_DIR": str(CORE / "cache" / "offline")}
        for mod, port in (("tests.stubs.memory_stub:app", 8001), ("tests.stubs.browser_stub:app", 8002)):
            procs.append(subprocess.Popen([sys.executable, "-m", "uvicorn", mod, "--port", str(port),
                                           "--log-level", "warning"], cwd=CORE, env=env))
        procs.append(subprocess.Popen([sys.executable, "-m", "tests.run_offline"], cwd=CORE, env=env))
    try:
        code = asyncio.run(run(args))
    finally:
        for pr in procs:
            pr.terminate()
        for pr in procs:
            try:
                pr.wait(5)
            except Exception:
                pr.kill()
    sys.exit(code)


if __name__ == "__main__":
    main()
