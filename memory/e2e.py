"""End-to-end test with real calls to everything: the endpoints, Moss, SpacetimeDB, and Claude (about 10 Haiku
and a few Sonnet calls, a few cents). Mock scenes are written descriptions, so Claude captions text, not pixels.
It wipes the database first and again at the end.

    set -a; source memory/.env; set +a; memory/.venv/bin/python memory/e2e.py
"""
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE / "mock")]
os.environ.update(MEMORY_TEST_SCENES="1", MEMORY_ALLOW_RESET="1")

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import drive  # noqa: E402
from app import app  # noqa: E402

FAILS = []


def check(ok: bool, what: str) -> None:
    print(f"{'ok  ' if ok else 'FAIL'} {what}")
    if not ok:
        FAILS.append(what)


def settle(c: TestClient) -> None:
    time.sleep(1)
    for _ in range(120):
        if c.get("/health").json()["pending"] == 0:
            return
        time.sleep(0.5)
    FAILS.append("captioning never finished")


with TestClient(app) as c:
    check(c.get("/health").json()["ok"], "/health")
    check(c.post("/reset").json() == {"ok": True}, "/reset wipes the database")

    now = time.time()
    for ev in json.loads((HERE / "mock/script.json").read_text()):
        ts = now - ev["min_ago"] * 60
        jpeg = drive.render_scene(ev["scene"])
        assert c.post("/ingest", json={"ts": ts, "jpeg_b64": jpeg}).status_code == 202
        if ev.get("say"):
            r = c.post("/remember", json={"label": ev["say"], "ts": ts + 2, "jpeg_b64": jpeg}).json()
            check(r == {"ok": True}, f"/remember {ev['say']!r}")
        settle(c)
    h = c.get("/health").json()
    # 9 scenes, one repeated: 8 captioned frames + 2 remembers (a person and a fact) = 10 moments
    check(h["moments"] == 10, f"duplicate scene skipped: {h['moments']} moments, expected 10")

    for q in json.loads((HERE / "mock/questions.json").read_text()):
        t0 = time.perf_counter()
        r = c.post("/recall", json={"question": q["q"]})
        ms = (time.perf_counter() - t0) * 1000
        answer = r.json()["answer"] if r.status_code == 200 else f"HTTP {r.status_code}"
        ok = (q["expect"].lower() in answer.lower()) if "expect" in q else bool(re.search(q["expect_regex"], answer))
        check(ok, f"{q['q']!r} ({ms:.0f} ms) -> {answer}")

    check(c.post("/alert", json={"kind": "lost", "note": "I'm lost"}).json() == {"ok": True}, "/alert lost")
    check(c.post("/alert", json={"kind": "bogus"}).status_code == 422, "/alert rejects a bad kind")
    check(c.post("/ingest", json={"ts": now, "jpeg_b64": "not an image"}).status_code == 202, "/ingest tolerates junk")

    # Dashboard-side delete: a moment removed in SpacetimeDB must stop appearing in recall.
    keys = next(m for m in app.state.svc.moments if "key" in m["caption_json"].lower())
    check(c.post("/recall", json={"question": "where are my keys"}).json()["answer"] != "I haven't seen that.", "keys found before delete")
    r = httpx.post(f"{os.getenv('SPACETIME_HOST', 'https://maincloud.spacetimedb.com')}/v1/database/{os.environ['SPACETIME_DB']}/call/delete_moment",
                   json=[keys["id"]], headers={"Authorization": f"Bearer {os.environ['SPACETIME_TOKEN']}"})
    check(r.status_code == 200, "delete_moment reducer")
    check(c.post("/recall", json={"question": "where are my keys"}).json()["answer"] == "I haven't seen that.", "deleted moment no longer recalled")

    check(c.post("/reset").json() == {"ok": True}, "/reset cleans up")

sys.exit(1 if FAILS else 0)
