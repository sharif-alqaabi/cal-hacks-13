"""Checks that every stored caption becomes searchable Moss docs, and that each thing in it can be found again.

Read-only and free: reads the moment table, builds the same docs the service builds (to_docs) into a separate
local Moss session, then asks one plain question per object, named person and remembered fact, plus questions
about things never seen. No Claude calls, nothing written to SpacetimeDB or the Moss cloud.

    set -a; source memory/.env; set +a; memory/.venv/bin/python memory/check_index.py [--k 3] [--show 10]
"""
import argparse
import asyncio
import collections
import json
import os

from moss import MossClient, QueryOptions

from moss_index import known, parse_ref, to_docs
from service import FAST_SCORE, MIN_SCORE, content_words, hit_name, pick
from stdb import Stdb

# Things a wearer might ask about. Any that do appear in the captions are skipped as negatives.
NEGATIVES = ["passport", "umbrella", "giraffe", "wallet", "guitar", "toothbrush", "bicycle", "piano"]


def head(name: str) -> str:
    """'round holographic sticker' -> 'sticker': what someone would actually ask for."""
    return name.split()[-1] if name else ""


async def main(k: int, show: int) -> int:
    db = Stdb()
    rows = sorted(await db.sql("SELECT * FROM moment"), key=lambda r: r["ts"])
    await db.close()

    # 1. Coverage: every moment parses and turns into docs; every object has somewhere to be.
    problems, thin, all_docs = [], [], []
    names: dict[str, tuple[str, str]] = {}  # doc id -> (kind, lowercased name)
    per_kind = collections.Counter()
    for r in rows:
        try:
            c = json.loads(r["caption_json"])
        except ValueError:
            problems.append(f"moment {r['id']}: caption_json is not JSON")
            continue
        docs = to_docs(r)
        if not docs:
            problems.append(f"moment {r['id']}: produced no Moss docs")
            continue
        all_docs += docs
        for d in docs:
            _, kind, idx = parse_ref(d.id)
            per_kind[d.metadata["kind"]] += 1
            if kind == "o":
                o = c["objects"][idx]
                names[d.id] = ("object", known(o.get("name")).lower())
                if not (known(o.get("on_or_in")) or known(o.get("near"))):
                    thin.append(f"{d.id} {o.get('name')!r}: no on_or_in or near, so a recall can't say where")
            elif kind == "p" and known(c["people"][idx].get("name")):
                names[d.id] = ("person", known(c["people"][idx]["name"]).lower())
            elif kind == "fact":
                names[d.id] = ("fact", known(c["fact"].get("item")).lower())

    print(f"== coverage: {len(rows)} moments -> {len(all_docs)} docs "
          f"({', '.join(f'{n} {kind}' for kind, n in per_kind.most_common())})")
    for p in problems:
        print(f"FAIL {p}")
    print(f"{'ok  ' if not thin else 'WARN'} {len(thin)} object docs with no location")
    for t in thin[:show]:
        print(f"     {t}")
    if not all_docs:
        print("nothing to search")
        return 1

    # 2. Round trip: index exactly those docs, then ask for each thing by name.
    client = MossClient(os.environ["MOSS_PROJECT_ID"], os.environ["MOSS_PROJECT_KEY"])
    session = await client.session("moments-check", auto_load_on_init=False)  # local only, never pushed
    await session.add_docs(all_docs)

    async def search(q: str):
        return (await session.query(q, QueryOptions(top_k=k, alpha=0.55))).docs  # the service's alpha

    targets = sorted({v for v in names.values() if v[1]})
    found = findable = fast = 0
    misses = []
    for kind, n in targets:
        q = {"object": f"where is the {n}", "person": f"what was {n} wearing", "fact": f"where is my {n}"}[kind]
        hits = await search(q)
        rank = next((i for i, d in enumerate(hits) if names.get(d.id) == (kind, n)), None)
        if rank is None:
            misses.append((q, hits))
            continue
        found += 1
        findable += hits[rank].score >= MIN_SCORE
        fast += hits[rank].score >= FAST_SCORE

    # The short way people ask ("the sticker", not "the round holographic sticker").
    multi = sorted({n for kind, n in names.values() if kind == "object" and " " in n})
    short_found = 0
    for n in multi:
        hits = await search(f"where is the {head(n)}")
        short_found += any(names.get(d.id, ("", ""))[0] == "object" and head(n) in names[d.id][1] for d in hits)

    total = len(targets)
    print(f"\n== round trip: {total} distinct things asked for by name, top {k} checked")
    print(f"{'ok  ' if found >= 0.9 * total else 'FAIL'} found in top {k}: {found}/{total}")
    print(f"{'ok  ' if findable >= 0.9 * total else 'WARN'} scored >= MIN_SCORE {MIN_SCORE}: {findable}/{total}"
          f"   (below it, recall says \"I haven't seen that\")")
    print(f"     scored >= FAST_SCORE {FAST_SCORE}: {fast}/{total}   (answered from a template, no Claude call)")
    if multi:
        print(f"{'ok  ' if short_found >= 0.9 * len(multi) else 'WARN'} found by the short name "
              f"(\"where is the {head(multi[0])}\"): {short_found}/{len(multi)}")
    for q, hits in misses[:show]:
        print(f"     miss: {q!r} -> " + "; ".join(f"{d.id} {d.score:.2f} {d.text[:40]!r}" for d in hits))

    # 3. What recall would do: the service's own search size, MIN_SCORE filter and pick().
    by_id = {r["id"]: r for r in rows}

    async def outcome(q: str):
        """(how recall answers, the thing it answers about): 'template' (no Claude call), 'claude', or 'not seen'."""
        hits = (await session.query(q, QueryOptions(top_k=8, alpha=0.55))).docs  # MossIndex.search's top_k
        strong = [(d, by_id[parse_ref(d.id)[0]]) for d in hits if d.score >= MIN_SCORE]
        if not strong:
            return "not seen", ""
        doc, moment, named = pick(q, strong)
        return ("template" if named and doc.score >= FAST_SCORE else "claude"), hit_name(doc, moment)

    print(f"\n== what recall would answer from (template = no Claude call; ignores look-back frames and follow-ups)")
    right = wrong = 0
    for kind, n in targets:
        q = {"object": f"where is the {n}", "person": f"what was {n} wearing", "fact": f"where is my {n}"}[kind]
        how, about = await outcome(q)
        if how != "not seen" and content_words(about) & content_words(n):
            right += 1
        else:
            wrong += 1
            if wrong <= show:
                print(f"     {q!r} -> {how}" + (f" about {about!r}" if about else ""))
    print(f"{'ok  ' if right >= 0.9 * total else 'FAIL'} answered about the thing asked for: {right}/{total}")

    # 4. Never seen: recall must never answer these from a template, or it states a sighting without checking.
    print("\n== never seen")
    text = " ".join(d.text.lower() for d in all_docs)
    bad = 0
    for neg in (n for n in NEGATIVES if n not in text):
        hits = await search(f"where is my {neg}")
        top = max((d.score for d in hits), default=0.0)
        how, about = await outcome(f"where is my {neg}")
        bad += how == "template"
        print(f"{'FAIL' if how == 'template' else 'ok  '} {neg!r}: top score {top:.2f} -> {how}"
              + (f" (closest: {about!r})" if about else ""))

    await session.close()
    await client.close()
    return int(bool(problems) or found < 0.9 * total or right < 0.9 * total or bad > 0)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--k", type=int, default=3, help="how many top hits count as found (the service looks at 8)")
    p.add_argument("--show", type=int, default=10, help="how many misses and warnings to list")
    a = p.parse_args()
    raise SystemExit(asyncio.run(main(a.k, a.show)))
