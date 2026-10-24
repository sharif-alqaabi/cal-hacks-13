"""Run the real memory service (memory/app.py) with SpacetimeDB and Moss swapped for in-process stand-ins.

Everything else is memory's own code: the HTTP layer, the ingest queue, captioning and answers with Claude.
Use it when memory/.env has no Moss or SpacetimeDB credentials. Needs ANTHROPIC_API_KEY.

    memory/.venv/bin/python core/tests/integration/memory_local.py --port 8001

Test-only endpoint: GET /_local/calls (every reducer call memory made, e.g. raise_alert).
"""
import argparse
import re
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path

MEMORY = Path(__file__).resolve().parents[3] / "memory"
STOP = {"a", "an", "the", "i", "my", "me", "is", "are", "was", "did", "do", "where", "what", "when", "who",
        "put", "leave", "left", "of", "on", "in", "to", "it", "at"}


def words(text: str) -> set[str]:
    return {w.rstrip("s") for w in re.findall(r"[a-z]+", text.lower()) if w not in STOP}


# ---- moss stand-in: word overlap instead of semantic search -------------------

@dataclass
class DocumentInfo:
    id: str
    text: str
    metadata: dict = field(default_factory=dict)


@dataclass
class QueryOptions:
    top_k: int = 8
    alpha: float = 0.55


@dataclass
class Hit:
    id: str
    text: str
    metadata: dict
    score: float


class LocalSession:
    def __init__(self) -> None:
        self.docs: dict[str, DocumentInfo] = {}

    async def add_docs(self, docs) -> None:
        self.docs.update({d.id: d for d in docs})

    async def delete_docs(self, ids) -> None:
        for i in ids:
            self.docs.pop(i, None)

    async def query(self, question: str, opts: QueryOptions):
        q = words(question)
        hits = [Hit(d.id, d.text, d.metadata, len(q & words(d.text)) / len(q)) for d in self.docs.values() if q]
        return types.SimpleNamespace(docs=sorted(hits, key=lambda h: -h.score)[:opts.top_k])

    async def close(self) -> None:
        pass


class MossClient:
    def __init__(self, *_) -> None:
        pass

    async def session(self, *_, **__) -> LocalSession:
        return LocalSession()

    async def close(self) -> None:
        pass


# ---- SpacetimeDB stand-in: the reducers memory calls, kept in lists ---------

CALLS: list[dict] = []


class LocalStdb:
    def __init__(self) -> None:
        self.moments: list[dict] = []
        self.people: dict[str, dict] = {}

    async def call(self, reducer: str, *args) -> None:
        CALLS.append({"reducer": reducer, "args": list(args)})
        if reducer == "add_moment":
            ts, caption_json, thumb_url, place_note = args
            self.moments.append({"id": ts, "ts": ts, "caption_json": caption_json, "thumb_url": thumb_url,
                                 "place_note": place_note})
        elif reducer == "upsert_person":
            name, clothing, ts = args
            self.people[name] = {"name": name, "clothing_note": clothing, "last_seen_ts": ts}
        elif reducer == "delete_all":
            self.moments.clear()
            self.people.clear()

    async def sql(self, query: str) -> list[dict]:
        if "FROM person" in query:
            return list(self.people.values())
        if query.startswith("SELECT id"):
            return [{"id": m["id"]} for m in self.moments]
        return list(self.moments)

    async def close(self) -> None:
        pass


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8001)
    args = p.parse_args()

    sys.modules["moss"] = types.SimpleNamespace(DocumentInfo=DocumentInfo, MossClient=MossClient,
                                                QueryOptions=QueryOptions)
    sys.path.insert(0, str(MEMORY))
    import stdb
    stdb.Stdb = LocalStdb
    import service
    service.Stdb = LocalStdb
    import uvicorn
    from app import app

    @app.get("/_local/calls")
    def calls():
        return CALLS

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
