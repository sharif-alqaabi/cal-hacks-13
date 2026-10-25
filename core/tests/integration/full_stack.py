"""All three real services together (core 8000, memory 8001, browser agent 8002 + demo Chrome): one pass over every intent.

  python -m tests.integration.full_stack            # uses a running `bash run.sh`, or starts `run.sh --no-tunnel` itself
  bash core/tests/integration/run_full_stack.sh     # same, from anywhere

Beats use the demo phrases from how-to-run.md and check the routed intent on /mirror/ws plus the reply:
describe, signal, recall (keys), remember + recall (Sam's clothes), lost, other, task (/work with a frame),
browser + confirm (a real email to the DEMO_CONTACTS Sam, then "Yes, send it.").
Real memory writes to the shared SpacetimeDB, so this run's moments are deleted and its alerts resolved afterwards.
"""
import asyncio
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

from tests.demo_script import (FIRST_SAY_MAX_S, NEGATIVE, REAL, Ctx, Phone, banned, frames_for, listen_mirror,
                               load_frames, memory_settled, mirror_events, turn_reply)
from tests.integration.memory_beats import MEMORY, port_free, read_env, stdb_cleanup, stdb_empty, wait_up

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "core" / "tests" / "out"
UNAVAILABLE = re.compile(r"isn't available|couldn't|didn't catch", re.I)


def intent_of(ctx: Ctx, t0: float) -> str | None:
    got = [e["intent"] for e in mirror_events(ctx, "intent", t0 - 0.5)]
    return got[0] if got else None


async def ask(ctx: Ctx, frames: list[bytes], phrase: str, n: int = 1, warm: float = 0.6, timeout: float = 10):
    async with Phone(ctx, frames) as ph:
        await asyncio.sleep(warm)
        t0 = await ph.utter(phrase)
        texts, first = await turn_reply(ctx, t0, n, timeout)
    return t0, texts, first


def row(ctx, t0, texts, first, want, ok_reply):
    got = intent_of(ctx, t0)
    ok = got == want and ok_reply and not banned(texts)
    return ("PASS" if ok else "FAIL"), first, int((time.time() - t0) * 1000), f"intent={got} {texts}"


async def beat_describe(ctx):
    t0, texts, first = await ask(ctx, frames_for("room", ctx), "What's in front of me?")
    return row(ctx, t0, texts, first, "describe", bool(texts) and first < FIRST_SAY_MAX_S * 1000)


async def beat_signal(ctx):
    t0, texts, first = await ask(ctx, frames_for("crosswalk", ctx), "Is the walk sign on?")
    return row(ctx, t0, texts, first, "signal", bool(texts) and re.search(r"walk|counting down|can't read", texts[0]) is not None)


async def beat_recall_keys(ctx):
    async with Phone(ctx, frames_for("keys", ctx)) as ph:
        await asyncio.sleep(5)            # hold the keys in view so a captioned frame catches them
        ph.set_frames(frames_for("room", ctx))
        await memory_settled(ctx)
        t0 = await ph.utter("Where did I put my keys?")
        texts, first = await turn_reply(ctx, t0, 1, 10)
    said = texts[0] if texts else ""
    return row(ctx, t0, texts, first, "recall", "key" in said.lower() and not NEGATIVE.search(said))


async def beat_remember_sam(ctx):
    src = REAL / "meet_sam.mp4"
    if not src.exists():
        return "SKIP", None, None, "no meet_sam.mp4"
    async with Phone(ctx, load_frames(src)) as ph:
        await asyncio.sleep(4)            # Sam walks into frame
        t0 = await ph.utter("Meet my friend Sam.")
        texts, first = await turn_reply(ctx, t0, 1, 10)
        got = intent_of(ctx, t0)
        await memory_settled(ctx)
        t1 = await ph.utter("What was Sam wearing?")
        texts2, _ = await turn_reply(ctx, t1, 1, 10)
    got2, said = intent_of(ctx, t1), (texts2[0] if texts2 else "")
    ok = (got == "remember" and texts[:1] == ["Got it, I'll remember that."] and got2 == "recall"
          and re.search(r"green", said, re.I) is not None)
    return ("PASS" if ok else "FAIL"), first, int((time.time() - t0) * 1000), f"intents={got},{got2} {texts} -> {texts2}"


async def beat_lost(ctx):
    t0, texts, first = await ask(ctx, frames_for("room", ctx), "I'm lost.")
    return row(ctx, t0, texts, first, "lost", bool(texts) and "family" in texts[0])


async def beat_other(ctx):
    t0, texts, first = await ask(ctx, frames_for("room", ctx), "Tell me a joke.")
    return row(ctx, t0, texts, first, "other", bool(texts) and not UNAVAILABLE.search(texts[0]))


async def beat_task(ctx):
    src = REAL / "task_mismatch.mp4"
    frames = load_frames(src) if src.exists() else frames_for("room", ctx)
    t0, texts, first = await ask(ctx, frames, "Is this the right item?", warm=1)
    return row(ctx, t0, texts, first, "task", bool(texts) and not UNAVAILABLE.search(texts[0]))


async def beat_email_yes(ctx):
    async with Phone(ctx, frames_for("room", ctx)) as ph:
        await asyncio.sleep(0.4)
        t0 = await ph.utter("Email Sam that I'm at the Palace of Fine Arts.")
        texts, first = await turn_reply(ctx, t0, 2, 45)
        got = intent_of(ctx, t0)
        t1 = await ph.utter("Yes, send it.")
        texts2, _ = await turn_reply(ctx, t1, 1, 45)
    got2 = intent_of(ctx, t1)
    ok = (got == "browser" and len(texts) >= 2 and texts[0] == "Working on it." and "send" in texts[1].lower()
          and got2 == "confirm" and bool(texts2) and texts2[0].startswith("Sent"))
    return ("PASS" if ok else "FAIL"), first, int((time.time() - t0) * 1000), f"intents={got},{got2} {texts} -> {texts2}"


BEATS = [("Describe", beat_describe), ("Signal", beat_signal), ("Recall keys", beat_recall_keys),
         ("Remember + recall Sam", beat_remember_sam), ("Lost", beat_lost), ("Other", beat_other),
         ("Task (work mode)", beat_task), ("Email + yes", beat_email_yes)]


async def run(ctx: Ctx) -> int:
    core = await wait_up(f"{ctx.http}/health", 90)
    await wait_up(f"{ctx.memory_url}/health", 60)
    b = await wait_up(f"{ctx.browser_url}/health", 90)
    print(f"core memory={core.get('memory')} browser={core.get('browser')}")
    print(f"browser fake={b['fake']} chrome={b['chrome']} keys={b['keys']} contacts={b['contacts']}", flush=True)
    if b["fake"] or not b["chrome"]:
        print("browser agent is not driving the real demo Chrome: the email beat will not be real")
    mirror = asyncio.create_task(listen_mirror(ctx))
    await asyncio.sleep(0.3)
    rows = []
    for i, (name, fn) in enumerate(BEATS, 1):
        try:
            status, first, total, note = await fn(ctx)
        except Exception as e:
            status, first, total, note = "FAIL", None, None, f"error: {e!r}"
        rows.append((i, name, status, first, total))
        print(f"  {i}. {name:<22} {status:<4} first={first} total={total}  {note}", flush=True)
        await asyncio.sleep(0.5)
    mirror.cancel()
    print("\n| # | Beat | Result | First say ms | Total ms |\n|---|---|---|---|---|")
    for i, name, status, first, total in rows:
        print(f"| {i} | {name} | {status} | {first if first is not None else '-'} | {total if total is not None else '-'} |")
    return 1 if any(r[2] == "FAIL" for r in rows) else 0


def main() -> None:
    ctx = Ctx("ws://127.0.0.1:8000/stream", "live", False, "http://127.0.0.1:8001", "http://127.0.0.1:8002")
    proc = None
    if all(port_free(p) for p in (8000, 8001, 8002)):
        OUT.mkdir(exist_ok=True)
        print(f"starting bash run.sh --no-tunnel (log in {OUT}/run_sh.log)", flush=True)
        proc = subprocess.Popen(["bash", "run.sh", "--no-tunnel"], cwd=ROOT, start_new_session=True,
                                stdout=(OUT / "run_sh.log").open("w"), stderr=subprocess.STDOUT)
    elif not all(not port_free(p) for p in (8000, 8001, 8002)):
        sys.exit("some of ports 8000/8001/8002 are in use and some are not: stop run.sh fully, or start it fully")
    mem_env = read_env(MEMORY / ".env")
    real_db = all(mem_env.get(k) for k in ("SPACETIME_DB", "SPACETIME_TOKEN"))
    was_empty, since_ms = (stdb_empty(mem_env) if real_db else True), int(time.time() * 1000)
    try:
        code = asyncio.run(run(ctx))
    finally:
        if proc:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(10)
            except Exception:
                pass
        if real_db:
            stdb_cleanup(mem_env, was_empty, since_ms)
    sys.exit(code)


if __name__ == "__main__":
    main()
