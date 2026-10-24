"""Moss search over moment captions.

SpacetimeDB is the source of truth: this session is never pushed to the Moss cloud and is rebuilt
from the moment table at startup (shortcut: upgrade to push_index if that startup gets slow).

A moment becomes several docs, so a search for "keys" isn't diluted by the rest of the scene:
    <id>:scene   the scene sentence and any signs
    <id>:o<n>    one per object
    <id>:p<n>    one per person
    <id>:fact    something the wearer said ("my passport is in the drawer") with the place it points at
"""
import json
import os
import time

from moss import DocumentInfo, MossClient, QueryOptions

INDEX = "moments"


def known(value) -> str:
    """A caption field, or "" when the model wrote nothing or "unknown"."""
    v = (value or "").strip()
    return "" if v.lower() == "unknown" else v


def _join(*parts, sep=", ") -> str:
    return sep.join(p for p in (known(x) for x in parts) if p)


def _place(c: dict) -> str:
    detail, place = known(c.get("place_detail")), known(c.get("place"))
    if detail and place:
        return f"Place: {detail} ({place})."
    return f"Place: {detail or place}." if detail or place else ""


def object_text(o: dict) -> str:
    """Searchable sentence for one object. `position` is left out: it only meant something from where the wearer stood."""
    text = f' Text: "{known(o.get("text"))}".' if known(o.get("text")) else ""
    details = _join(o.get("color"), o.get("size"), o.get("material"), o.get("shape"),
                    o.get("state"), o.get("on_or_in"), o.get("near"))
    return f"{o.get('name', '')}: {details}.{text}" if details else f"{o.get('name', '')}.{text}"


def person_text(p: dict) -> str:
    name, clothing = known(p.get("name")) or "person", known(p.get("clothing"))
    return f"{name} wearing {clothing}." if clothing else f"{name}."


def location_text(loc: dict) -> str:
    return _join(loc.get("name"), loc.get("color"), loc.get("size"), loc.get("material"), loc.get("shape"),
                 loc.get("state"), loc.get("on_or_in"), loc.get("near"))


def to_docs(moment: dict) -> list[DocumentInfo]:
    """A moment row as Moss docs. Metadata values must be strings. A row that isn't a caption gives no docs."""
    try:
        c = json.loads(moment["caption_json"])
    except ValueError:
        return []
    where = _place(c)
    docs: list[tuple[str, str, str]] = []  # (doc id suffix, kind, text)
    if c.get("fact"):
        f = c["fact"]
        docs.append(("fact", "fact", f"{f.get('item', '')}: {f.get('statement', '')}. "
                                     f"Location: {location_text(f.get('location') or {})}. {where}"))
    else:
        scene = known(c.get("scene"))
        signs = "; ".join(s for s in c.get("text", []) if known(s))
        if scene or signs:
            docs.append(("scene", "scene", f"{scene}{f' Signs: {signs}.' if signs else ''} {where}"))
        docs += [(f"o{i}", "object", f"{object_text(o)} {where}") for i, o in enumerate(c.get("objects", []))]
        docs += [(f"p{i}", "person", f"{person_text(p)} {where}") for i, p in enumerate(c.get("people", []))]
    meta = {"moment_id": str(moment["id"]), "ts": str(moment["ts"]), "place": moment["place_note"]}
    return [DocumentInfo(id=f"{moment['id']}:{suffix}", text=text.strip(), metadata={**meta, "kind": kind})
            for suffix, kind, text in docs if text.strip()]


def parse_ref(doc_id: str) -> tuple[int, str, int]:
    """'1792800000000:o2' -> (1792800000000, 'o', 2); 'scene' and 'fact' have no index (0)."""
    moment_id, _, tail = doc_id.partition(":")
    letters = tail.rstrip("0123456789")
    return int(moment_id), letters, int(tail[len(letters):] or 0)


class MossIndex:
    async def open(self, moments: list[dict]) -> None:
        self.client = MossClient(os.environ["MOSS_PROJECT_ID"], os.environ["MOSS_PROJECT_KEY"])
        # No auto-load: the cloud copy is never written, so a session must never start from it.
        self.session = await self.client.session(INDEX, auto_load_on_init=False)
        docs = [d for m in moments for d in to_docs(m)]
        if docs:
            await self.session.add_docs(docs)

    async def add(self, moment: dict) -> None:
        await self.session.add_docs(to_docs(moment))

    async def delete(self, moments: list[dict]) -> None:
        ids = [d.id for m in moments for d in to_docs(m)]
        if ids:
            await self.session.delete_docs(ids)

    async def search(self, question: str, top_k: int = 8, alpha: float = 0.55):
        """Top hits (each with id, score, text, metadata) and the wall-clock milliseconds."""
        t0 = time.perf_counter()
        res = await self.session.query(question, QueryOptions(top_k=top_k, alpha=alpha))
        return res.docs, (time.perf_counter() - t0) * 1000

    async def close(self) -> None:
        await self.session.close()
        await self.client.close()
