"""End-to-end check of the integration layer, with no Claude calls: write a moment to SpacetimeDB,
read it back, find it in Moss, delete it from both.

    set -a; source memory/.env; set +a
    memory/.venv/bin/python memory/smoke.py
"""
import asyncio
import json
import time

from moss_index import MossIndex
from stdb import Stdb


async def timed(label, coro):
    t0 = time.perf_counter()
    out = await coro
    print(f"{label}: {(time.perf_counter() - t0) * 1000:.0f} ms")
    return out


async def main():
    db, index = Stdb(), MossIndex()
    ts = int(time.time() * 1000)
    caption = json.dumps({
        "place": "home", "place_detail": "workshop", "scene": "", "text": [], "people": [],
        "objects": [{"name": "purple umbrella", "color": "purple", "size": "walking-stick length", "material": "nylon",
                     "shape": "unknown", "state": "closed", "on_or_in": "on the smoke-test bench",
                     "near": "next to the vice", "position": "ahead", "text": ""}],
    })
    try:
        await timed("add_moment", db.call("add_moment", ts, caption, "http://localhost:8001/thumbs/smoke.jpg", "home"))
        rows = await timed("sql read-back", db.sql(f"SELECT * FROM moment WHERE ts = {ts}"))
        assert len(rows) == 1, f"row not found: {rows}"

        await timed("moss open from table", index.open(await db.sql("SELECT * FROM moment")))
        docs, ms = await index.search("where is my purple umbrella")
        print(f"moss search: {ms:.1f} ms, top hit {docs[0].id} score={docs[0].score:.3f}")
        assert docs and docs[0].id == f"{ts}:o0", f"top hit was {docs[:1]}"
    finally:
        await db.call("delete_moment", ts)  # runs even when an assert above failed
    assert not await db.sql(f"SELECT * FROM moment WHERE ts = {ts}"), "row still in SpacetimeDB"

    await index.delete(rows)
    docs, _ = await index.search("purple umbrella")
    assert not docs or not docs[0].id.startswith(f"{ts}:"), "doc still in Moss"
    await db.close()
    await index.close()
    print("OK")


asyncio.run(main())
