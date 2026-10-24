"""Spike: are docs added to a Moss session searchable immediately, and how fast is a query?

    pip install moss
    set -a; source memory/.env; set +a
    python3 memory/spikes/moss_freshness.py

Never pushes, so nothing is left in the Moss cloud.
"""
import asyncio
import os
import time

from moss import DocumentInfo, MossClient, QueryOptions

OPTS = QueryOptions(top_k=3, alpha=0.55)


def doc(id, text, place):
    return DocumentInfo(id=id, text=text, metadata={"ts": str(int(time.time() * 1000)), "place": place})


async def timed_query(session, q):
    t0 = time.perf_counter()
    res = await session.query(q, OPTS)
    ms = (time.perf_counter() - t0) * 1000
    top = res.docs[0] if res.docs else None
    print(f"{q!r}: {ms:.1f} ms wall, {res.time_taken_ms} ms moss -> "
          f"{top.id if top else None} score={top.score if top else 0:.3f}")
    return top


async def main():
    client = MossClient(os.environ["MOSS_PROJECT_ID"], os.environ["MOSS_PROJECT_KEY"])
    async with await client.session(index_name="spike-moments") as s:
        await s.add_docs([
            doc("m1", "keys on wooden table by the front door", "home"),
            doc("m2", "Sam wearing a red hoodie and jeans in the kitchen", "home"),
            doc("m3", "street crossing with walk signal, cars waiting", "outside"),
        ])
        assert (await timed_query(s, "where did I put my keys")).id == "m1"

        # The real index grows while it is being queried: add after the first query, then ask again.
        await s.add_docs([doc("m4", "black wallet on the office desk next to a laptop", "office")])
        assert (await timed_query(s, "where is my wallet")).id == "m4", "doc added after a query was not searchable"

        # Never-seen item: its top score is a first data point for the "I haven't seen that" threshold.
        await timed_query(s, "where is my passport")

    print("OK: new session docs are searchable immediately, no push or reload")


asyncio.run(main())
