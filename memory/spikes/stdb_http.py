"""Spike: call a SpacetimeDB reducer over HTTP from Python, read the row back with SQL, time both.

Needs the real module published (see memory/spacetimedb) and in memory/.env:
    SPACETIME_DB=calhacks13-memory
    SPACETIME_TOKEN=<output of: spacetime login show --token>

Run (stdlib only):
    set -a; source memory/.env; set +a
    python3 memory/spikes/stdb_http.py
"""
import json
import os
import time
import urllib.error
import urllib.request

HOST = os.environ.get("SPACETIME_HOST", "https://maincloud.spacetimedb.com")
DB = os.environ["SPACETIME_DB"]
TOKEN = os.environ["SPACETIME_TOKEN"]


def post(path, body, content_type):
    req = urllib.request.Request(
        f"{HOST}/v1/database/{DB}/{path}", data=body.encode(), method="POST",
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": content_type},
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            out = r.read().decode()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{path}: HTTP {e.code} {e.read().decode()}")
    return out, (time.perf_counter() - t0) * 1000


# Several rounds: the first one pays for DNS and TLS, later ones show the steady-state latency.
for i in range(5):
    ts = int(time.time() * 1000)
    caption = json.dumps({"objects": [{"name": "keys", "on": "wooden table"}], "place": "home"})
    _, call_ms = post("call/add_moment", json.dumps([ts, caption, "http://localhost:8001/thumbs/spike.jpg", "home"]),
                      "application/json")
    out, sql_ms = post("sql", f"SELECT * FROM moment WHERE ts = {ts}", "text/plain")
    rows = json.loads(out)[0]["rows"]
    assert len(rows) == 1, f"row not read back: {out}"
    print(f"round {i + 1}: add_moment {call_ms:.0f} ms, sql read-back {sql_ms:.0f} ms, row={rows[0]}")

print("OK: reducer call over HTTP works and the row is readable right after")
