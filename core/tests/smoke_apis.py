"""One live call per external API: python -m tests.smoke_apis [all|stt|tts|vision|jev|yolo]

Prints PASS/FAIL/SKIP (SKIP when the key is missing) with latency. Never prints key values.
"""
import asyncio
import base64
import json
import re
import statistics
import sys
import time
import wave
from pathlib import Path

from app import config, llm, router, stt, tts, vision

FIX = Path(__file__).resolve().parent / "fixtures"
OUT = Path(__file__).resolve().parent / "out"


def norm(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", "", s.lower()).split())


def report(name: str, status: str, detail: str = "") -> bool:
    print(f"{status:<4} {name:<8} {detail}", flush=True)
    return status != "FAIL"


async def check_stt() -> bool:
    if not stt.available():
        return report("stt", "SKIP", "no CARTESIA_API_KEY")
    table = json.loads((FIX / "transcripts.json").read_text())["by_file"]
    wavs = sorted(p for p in (FIX / "audio").glob("*.wav") if not p.stem.endswith("_16k"))
    real = sorted((FIX / "real" / "audio").glob("*.wav")) if (FIX / "real" / "audio").exists() else []
    ok, lines = 0, []
    for p in wavs:
        with wave.open(str(p)) as w:
            pcm, rate = w.readframes(w.getnframes()), w.getframerate()
        t0 = time.perf_counter()
        try:
            turn = await stt.start_turn(rate)
            step = rate * 2 // 10
            for i in range(0, len(pcm), step):
                await turn.feed(pcm[i:i + step])
            t_up = time.perf_counter()
            text = await turn.finish()
        except Exception as e:
            lines.append(f"    {p.name}: ERROR {e}")
            continue
        good = norm(text) == norm(table[p.name])
        ok += good
        lines.append(f"    {p.name}: {'ok ' if good else 'BAD'} {text!r} (finalize {int((time.perf_counter() - t_up) * 1000)} ms)")
    for p in real:
        lines.append(f"    real/{p.name}: (no label) see transcript in turn log")
    print("\n".join(lines))
    need = min(4 * len(wavs) // 5 + (1 if 4 * len(wavs) % 5 else 0), len(wavs))
    return report("stt", "PASS" if ok >= need else "FAIL", f"{ok}/{len(wavs)} exact (need {need}) at 8 kHz")


async def check_tts() -> bool:
    if not tts.available():
        return report("tts", "SKIP", "no CARTESIA_API_KEY / CARTESIA_VOICE_ID")
    text = f"Chair coming up ahead, slightly left. {time.time():.0f}"   # bypass the cache
    t0 = time.perf_counter()
    try:
        pcm = await tts._fetch(text)
    except Exception as e:
        return report("tts", "FAIL", str(e))
    ms = int((time.perf_counter() - t0) * 1000)
    OUT.mkdir(exist_ok=True)
    with wave.open(str(OUT / "tts.wav"), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(config.TTS_RATE), w.writeframes(pcm)
    secs = len(pcm) / 2 / config.TTS_RATE
    return report("tts", "PASS" if secs > 0.5 else "FAIL", f"{ms} ms, {secs:.1f} s audio -> tests/out/tts.wav")


async def check_vision() -> bool:
    if not llm.available():
        return report("vision", "SKIP", "no ANTHROPIC_API_KEY")
    real = FIX / "real"
    room = real / "room.jpg" if (real / "room.jpg").exists() else FIX / "room.jpg"
    b64 = base64.b64encode(room.read_bytes()).decode()
    t0 = time.perf_counter()
    sentences, first = [], None
    try:
        async for s in vision.describe(b64):
            first = first or int((time.perf_counter() - t0) * 1000)
            sentences.append(s)
    except Exception as e:
        return report("vision", "FAIL", f"describe: {e}")
    ok = report("describe", "PASS" if sentences else "FAIL",
                f"first {first} ms, total {int((time.perf_counter() - t0) * 1000)} ms on {room.name}: {sentences}")
    signals = sorted(real.glob("crosswalk_*.jpg")) if real.exists() else []
    if not signals:
        signals = [FIX / "crosswalk.jpg"]
    want = {"walk": "walk sign is on", "dont_walk": "don't walk", "countdown": "counting down"}
    right = 0
    for p in signals:
        t0 = time.perf_counter()
        try:
            out = await vision.signal(base64.b64encode(p.read_bytes()).decode())
        except Exception as e:
            out = [f"ERROR {e}"]
        state = p.stem.replace("crosswalk_", "") if p.parent == real else "walk"
        good = want.get(state, "") in out[0]
        right += good
        print(f"    {p.name}: {'ok ' if good else 'BAD'} {out} ({int((time.perf_counter() - t0) * 1000)} ms)")
    synthetic = signals[0].parent != real
    status = "PASS" if right == len(signals) else ("SKIP" if synthetic else "FAIL")
    return report("signal", status, f"{right}/{len(signals)}" + (" (synthetic drawing; record real/crosswalk_*.jpg)" if synthetic else "")) and ok


async def check_jev() -> bool:
    if not config.TYPESAFE_API_KEY:
        return report("jev", "SKIP", "no TYPESAFE_API_KEY")
    from tests.test_router import LABELLED

    right, times, low, errors = 0, [], 0, 0
    for text, want in LABELLED:
        t0 = time.perf_counter()
        got = await router.jev_route(text)
        times.append((time.perf_counter() - t0) * 1000)
        if got is None:
            errors += 1
            print(f"    {text!r}: no answer")
            continue
        label, conf = got
        low += conf < config.JEV_CONFIDENCE_THRESHOLD
        right += label == want
        if label != want:
            print(f"    {text!r}: got {label} ({conf:.2f}), want {want}")
    med = statistics.median(times)
    ok = right >= 18 and med < 500
    return report("jev", "PASS" if ok else "FAIL",
                  f"{right}/20 right, median {med:.0f} ms, {low} below threshold, {errors} errors")


async def check_router_fallback() -> bool:
    if not llm.available():
        return report("claude-r", "SKIP", "no ANTHROPIC_API_KEY")
    from tests.test_router import LABELLED

    right, times = 0, []
    for text, want in LABELLED:
        t0 = time.perf_counter()
        got = await router.claude_route(text)
        times.append((time.perf_counter() - t0) * 1000)
        right += got == want
        if got != want:
            print(f"    {text!r}: got {got}, want {want}")
    return report("claude-r", "PASS" if right >= 18 else "FAIL",
                  f"{right}/20 right, median {statistics.median(times):.0f} ms ({config.ROUTER_FALLBACK_MODEL})")


def check_yolo() -> bool:
    from app.hazards import HazardDetector, HazardTracker
    from tests.demo_script import load_frames

    d = HazardDetector()
    d.load()
    if not d.enabled:
        return report("yolo", "FAIL", "model did not load")
    src = FIX / "real" / "chair_walk.mp4"
    if not src.exists():
        src = FIX / "zoom_walk"
    frames = load_frames(src)
    d.tracker = HazardTracker()
    fired, times = [], []
    for i, jpg in enumerate(frames):
        b64 = base64.b64encode(jpg).decode()
        t0 = time.perf_counter()
        boxes = d.detect(b64)
        times.append((time.perf_counter() - t0) * 1000)
        w = d.tracker.decide(boxes, 100 + i * 0.2)
        if w:
            fired.append((i, w))
    clear = load_frames(FIX / "clear_path")
    d.tracker = HazardTracker()
    false = sum(bool(d.tracker.decide(d.detect(base64.b64encode(j).decode()), 100 + i * 0.2)) for i, j in enumerate(clear))
    med = statistics.median(times)
    ok = bool(fired) and false <= 1 and med < 200
    return report("yolo", "PASS" if ok else "FAIL",
                  f"median {med:.0f} ms/frame, warnings on {src.name}: {fired[:3]}, false warnings on clear_path: {false}")


async def main(which: str) -> int:
    checks = {"stt": check_stt, "tts": check_tts, "vision": check_vision, "jev": check_jev,
              "router": check_router_fallback}
    results = []
    for name, fn in checks.items():
        if which in ("all", name):
            results.append(await fn())
    if which in ("all", "yolo"):
        results.append(await asyncio.to_thread(check_yolo))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "all")))
