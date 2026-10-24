"""Core + the real memory service together: starts both, runs the demo beats that touch memory, tears down.

  python -m tests.integration.memory_beats                    # real memory (memory/.env), real core (core/.env)
  python -m tests.integration.memory_beats --local-backends   # real memory code, Moss/SpacetimeDB stood in locally
  python -m tests.integration.memory_beats --offline-core     # core's LLM/STT/TTS faked, memory still real
  python -m tests.integration.memory_beats --demo             # first every tests.demo_script beat, then these
  flags: --core-port, --memory-port

Beats: health, ingest, recall "where did I put my keys", remember "this is my brother Sam", "I'm lost",
then memory is stopped and recall must say "Memory isn't available right now."
Real memory writes to its SpacetimeDB, so the run cleans up after itself: if the database was empty when it
started, everything is wiped (delete_all); otherwise only this run's moments are deleted and its alerts resolved.
"""
import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from contracts.memory import RecallResp
from tests.demo_script import NEGATIVE, Ctx, Phone, frames_for, turn_reply

CORE = Path(__file__).resolve().parents[2]
MEMORY = CORE.parent / "memory"
OUT = CORE / "tests" / "out"


def read_env(path: Path) -> dict:
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text().splitlines():
        k, sep, v = line.strip().partition("=")
        v = v.strip().strip("'\"")   # same as `source .env`: quotes are not part of the value
        if sep and k and not k.startswith("#") and v:
            out[k] = v
    return out


def port_free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


async def wait_up(url: str, timeout: float = 60) -> dict:
    end = time.time() + timeout
    async with httpx.AsyncClient(timeout=1) as c:
        while time.time() < end:
            try:
                r = await c.get(url)
                if r.status_code < 400:
                    return r.json()
            except Exception:
                pass
            await asyncio.sleep(0.3)
    raise RuntimeError(f"not up: {url}")


async def mem_health(ctx: Ctx) -> dict:
    async with httpx.AsyncClient(timeout=2) as c:
        return (await c.get(f"{ctx.memory_url}/health")).json()


async def wait_moments(ctx: Ctx, more_than: int, timeout: float = 30) -> dict:
    end, h = time.time() + timeout, {}
    while time.time() < end:
        h = await mem_health(ctx)
        if h["moments"] > more_than and h["pending"] == 0:
            break
        await asyncio.sleep(0.5)
    return h


# ---- beats -------------------------------------------------------------------

async def beat_health(ctx: Ctx):
    core = await wait_up(f"{ctx.http}/health", 10)
    for _ in range(20):  # core polls memory health in the background
        if core["memory"]["up"]:
            break
        await asyncio.sleep(0.5)
        core = await wait_up(f"{ctx.http}/health", 2)
    mem = await mem_health(ctx)
    ok = core["memory"]["up"] and core["memory"]["url"] == ctx.memory_url and mem.get("ok") is True
    return ("PASS" if ok else "FAIL"), None, None, f"core sees {core['memory']}, memory {mem}"


async def beat_ingest(ctx: Ctx):
    before = (await mem_health(ctx))["moments"]
    t0 = time.time()
    async with Phone(ctx, frames_for("keys", ctx)) as ph:
        await asyncio.sleep(4)       # core ingests every INGEST_EVERY_S (3 s)
        ph.set_frames(frames_for("room", ctx))
        await asyncio.sleep(4)
    h = await wait_moments(ctx, before + 1)
    ok = h["moments"] >= before + 2 and h["pending"] == 0
    return ("PASS" if ok else "FAIL"), None, int((time.time() - t0) * 1000), f"moments {before} -> {h['moments']}"


async def beat_recall(ctx: Ctx):
    async with Phone(ctx, frames_for("room", ctx)) as ph:
        await asyncio.sleep(0.5)
        t0 = await ph.utter("where did I put my keys")
        texts, first = await turn_reply(ctx, t0, 1, 10)
    # the same question straight to memory, parsed with core's contract model
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(f"{ctx.memory_url}/recall", json={"question": "where did I put my keys"})
    parsed = RecallResp.model_validate(r.json())
    said = texts[0] if texts else ""
    ok = ("key" in said.lower() and not NEGATIVE.search(said)
          and first is not None and first < 3500)
    return ("PASS" if ok else "FAIL"), first, int((time.time() - t0) * 1000), f"{texts} | direct: {parsed.model_dump()}"


async def beat_remember(ctx: Ctx):
    before = (await mem_health(ctx))["moments"]
    async with Phone(ctx, frames_for("room", ctx)) as ph:
        await asyncio.sleep(0.5)
        t0 = await ph.utter("this is my brother Sam")
        texts, first = await turn_reply(ctx, t0, 1, 10)
    h = await mem_health(ctx)
    ok = texts[:1] == ["Got it, I'll remember that."] and h["moments"] == before + 1
    return ("PASS" if ok else "FAIL"), first, int((time.time() - t0) * 1000), f"{texts}, moments {before} -> {h['moments']}"


async def beat_lost(ctx: Ctx):
    async with Phone(ctx, frames_for("room", ctx)) as ph:
        await asyncio.sleep(0.5)
        t0 = await ph.utter("I'm lost")
        texts, first = await turn_reply(ctx, t0, 1, 10)
    note = f"{texts}"
    alert_ok = True
    async with httpx.AsyncClient(timeout=2) as c:
        r = await c.get(f"{ctx.memory_url}/_local/calls")
        if r.status_code == 200:   # local backends: check the alert memory would have written
            alerts = [x["args"] for x in r.json() if x["reducer"] == "raise_alert"]
            alert_ok = bool(alerts) and alerts[-1][1] == "lost"
            note += f" | raise_alert {alerts[-1][1:] if alerts else None}"
    ok = bool(texts) and "family" in texts[0] and alert_ok
    return ("PASS" if ok else "FAIL"), first, int((time.time() - t0) * 1000), note


async def beat_memory_down(ctx: Ctx, stop_memory):
    stop_memory()
    from app import config
    async with Phone(ctx, frames_for("room", ctx)) as ph:
        await asyncio.sleep(0.5)
        t0 = await ph.utter("where did I put my keys")
        texts, first = await turn_reply(ctx, t0, 1, config.SERVICE_TIMEOUT_S + 4)
    ok = texts[:1] == ["Memory isn't available right now."] and first is not None and first < (config.SERVICE_TIMEOUT_S + 1) * 1000
    return ("PASS" if ok else "FAIL"), first, int((time.time() - t0) * 1000), f"{texts}"


# ---- SpacetimeDB cleanup -----------------------------------------------------

def stdb_client(env: dict) -> httpx.Client:
    host = env.get("SPACETIME_HOST", "https://maincloud.spacetimedb.com")
    return httpx.Client(base_url=f"{host}/v1/database/{env['SPACETIME_DB']}",
                        headers={"Authorization": f"Bearer {env['SPACETIME_TOKEN']}"}, timeout=10)


def stdb_rows(c: httpx.Client, query: str) -> list[dict]:
    r = c.post("/sql", content=query)
    r.raise_for_status()
    out = r.json()[0]
    cols = [e["name"]["some"] for e in out["schema"]["elements"]]
    return [dict(zip(cols, row)) for row in out["rows"]]


def stdb_call(c: httpx.Client, reducer: str, *args) -> None:
    c.post(f"/call/{reducer}", json=list(args)).raise_for_status()


def stdb_empty(env: dict) -> bool:
    with stdb_client(env) as c:
        return not any(stdb_rows(c, f"SELECT * FROM {t}") for t in ("moment", "person", "alert", "recall"))


def stdb_cleanup(env: dict, was_empty: bool, since_ms: int) -> None:
    with stdb_client(env) as c:
        if was_empty:
            stdb_call(c, "delete_all")
            print("cleanup: database was empty before the run, wiped it again")
            return
        stdb_call(c, "delete_moments_since", since_ms)
        alerts = [a for a in stdb_rows(c, "SELECT * FROM alert") if a["ts"] >= since_ms and not a["resolved"]]
        for a in alerts:
            stdb_call(c, "resolve_alert", a["id"])
        print(f"cleanup: deleted this run's moments, resolved {len(alerts)} alert(s); "
              "earlier data kept (recall rows and people this run added stay: memory has no reducer for them)")


# ---- orchestration -----------------------------------------------------------

def start(cmd: list[str], cwd: Path, env: dict, log: Path) -> subprocess.Popen:
    return subprocess.Popen(cmd, cwd=cwd, env=env, stdout=log.open("w"), stderr=subprocess.STDOUT)


def stop(p: subprocess.Popen) -> None:
    if p.poll() is None:
        p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()


async def run(ctx: Ctx, stop_memory) -> int:
    beats = [("Health", beat_health), ("Ingest", beat_ingest), ("Recall keys", beat_recall),
             ("Remember", beat_remember), ("Lost", beat_lost)]
    rows = []
    for i, (name, fn) in enumerate(beats, 1):
        try:
            status, first, total, note = await fn(ctx)
        except Exception as e:
            status, first, total, note = "FAIL", None, None, f"error: {e!r}"
        rows.append((i, name, status, first, total, note))
        print(f"  {i}. {name:<12} {status:<4} first={first} total={total}  {note}", flush=True)
    try:
        r = await beat_memory_down(ctx, stop_memory)
    except Exception as e:
        r = ("FAIL", None, None, f"error: {e!r}")
    rows.append((len(rows) + 1, "Memory down", *r))
    print(f"  {len(rows)}. {'Memory down':<12} {r[0]:<4} first={r[1]} total={r[2]}  {r[3]}", flush=True)
    print("\n| # | Beat | Result | First say ms | Total ms |\n|---|---|---|---|---|")
    for i, name, status, first, total, _ in rows:
        print(f"| {i} | {name} | {status} | {first if first is not None else '-'} | {total if total is not None else '-'} |")
    return 1 if any(r[2] == "FAIL" for r in rows) else 0


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--local-backends", action="store_true", help="stand in for Moss and SpacetimeDB")
    p.add_argument("--offline-core", action="store_true", help="fake core's STT/LLM/TTS (tests.run_offline)")
    p.add_argument("--core-port", type=int, default=8000)
    p.add_argument("--memory-port", type=int, default=8001)
    p.add_argument("--demo", action="store_true", help="also run every tests.demo_script beat first (browser stub on 8002)")
    args = p.parse_args()

    for port in (args.core_port, args.memory_port, *([8002] if args.demo else [])):
        if not port_free(port):
            sys.exit(f"port {port} is in use: stop whatever is on it (lsof -i :{port}) or pass another port")

    memory_url = f"http://127.0.0.1:{args.memory_port}"
    mem_env = {"MEMORY_PUBLIC_URL": memory_url, **os.environ, **read_env(MEMORY / ".env")}
    mem_env.setdefault("ANTHROPIC_API_KEY", read_env(CORE / ".env").get("ANTHROPIC_API_KEY", ""))
    if not args.local_backends:
        missing = [k for k in ("MOSS_PROJECT_ID", "MOSS_PROJECT_KEY", "SPACETIME_DB", "SPACETIME_TOKEN") if not mem_env.get(k)]
        if missing:
            sys.exit(f"memory/.env is missing {', '.join(missing)}: add it, or pass --local-backends")
    mem_py = MEMORY / ".venv" / "bin" / "python"
    mem_py = str(mem_py) if mem_py.exists() else sys.executable
    if args.local_backends:
        mem_cmd = [mem_py, str(CORE / "tests" / "integration" / "memory_local.py"), "--port", str(args.memory_port)]
    else:
        mem_cmd = [mem_py, "-m", "uvicorn", "app:app", "--port", str(args.memory_port), "--log-level", "warning"]

    core_env = {**os.environ, "MEMORY_URL": memory_url}
    if args.offline_core:
        core_env.update(LOG_DIR=str(CORE / "logs" / "offline"), CACHE_DIR=str(CORE / "cache" / "offline"))
        core_cmd = [sys.executable, "-m", "tests.run_offline", "--port", str(args.core_port)]
    else:
        core_cmd = [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                    "--port", str(args.core_port), "--log-level", "warning"]

    real_db = not args.local_backends
    was_empty, since_ms = (stdb_empty(mem_env) if real_db else True), int(time.time() * 1000)
    OUT.mkdir(exist_ok=True)
    mem = start(mem_cmd, MEMORY, mem_env, OUT / "memory.log")
    core = start(core_cmd, CORE, core_env, OUT / "core.log")
    procs = [core, mem]
    if args.demo:
        procs.append(start([sys.executable, "-m", "uvicorn", "tests.stubs.browser_stub:app", "--port", "8002",
                            "--log-level", "warning"], CORE, core_env, OUT / "browser_stub.log"))
    ctx = Ctx(f"ws://127.0.0.1:{args.core_port}/stream", "offline" if args.offline_core else "live",
              False, memory_url, "http://127.0.0.1:8002")
    print(f"memory: {'local backends' if args.local_backends else 'real Moss + SpacetimeDB'}, "
          f"core: {'offline fakes' if args.offline_core else 'real keys'}; logs in {OUT}/")
    try:
        asyncio.run(wait_up(f"{memory_url}/health", 60))
        print("memory health:", json.dumps(asyncio.run(wait_up(f"{memory_url}/health", 5))))
        asyncio.run(wait_up(f"{ctx.http}/health", 90))
        demo_code = 0
        if args.demo:
            print("\n== demo script beats, real memory in the loop ==", flush=True)
            demo_code = subprocess.call([sys.executable, "-m", "tests.demo_script", "--live", "--url", ctx.url,
                                         "--memory-url", memory_url], cwd=CORE)
            print("\n== memory beats ==", flush=True)
        code = asyncio.run(run(ctx, lambda: stop(mem))) or demo_code
    finally:
        for pr in procs:
            stop(pr)
        if real_db:
            stdb_cleanup(mem_env, was_empty, since_ms)
    sys.exit(code)


if __name__ == "__main__":
    main()
