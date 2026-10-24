"""Memory logic with no HTTP: ingest -> caption -> store, /remember, /recall, /alert.

app.py is the thin FastAPI layer. SpacetimeDB holds the durable timeline, Moss searches it, and
`self.moments` is an in-memory copy (sorted by ts) for the timeline questions Moss can't answer.
"""
import asyncio
import base64
import io
import json
import logging
import os
import re
import time
from pathlib import Path

from PIL import Image

import captions
from moss_index import MossIndex, known, parse_ref
from stdb import Stdb

log = logging.getLogger("memory")

TEST_SCENES = os.getenv("MEMORY_TEST_SCENES", "").strip().lower() in {"1", "true", "yes", "on"}
PUBLIC_URL = os.getenv("MEMORY_PUBLIC_URL", "http://localhost:8001").rstrip("/")
THUMB_DIR = Path(__file__).resolve().parent / "thumbs"

# shortcut: tuned on the 7 mock questions with real captions (real hits 0.5-1.0, a never-seen item 0.19); retune on real photos.
MIN_SCORE = 0.3    # below this a hit doesn't count: "I haven't seen that."
FAST_SCORE = 0.45  # at or above this an object/person/fact hit is answered from a template, without Sonnet
DUP_DIFF = 3.0     # mean grey-level difference (0-255) between 16x16 thumbnails under which a frame is a duplicate
NOT_SEEN = "I haven't seen that."

LEAVE = re.compile(r"\bwhen did i (?:leave|left|exit|go out of|head out of|get out of)\b", re.I)
ARRIVE = re.compile(r"\bwhen did i (?:arrive|reach|get (?:home|back|to)|come (?:home|back|in)|walk in)\b", re.I)
PLACE_WORDS = {"home": "home", "house": "home", "apartment": "home", "office": "office", "work": "office",
               "store": "store", "shop": "store"}
PLACE_NAME = {"home": "home", "office": "the office", "store": "the store"}


# ---- frames -----------------------------------------------------------------

def _image(jpeg_b64: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(jpeg_b64)))


def frame_hash(jpeg_b64: str) -> bytes | None:
    """16x16 grey thumbnail, or None when the data isn't an image."""
    try:
        return _image(jpeg_b64).convert("L").resize((16, 16)).tobytes()
    except Exception:
        return None


def hash_diff(a: bytes, b: bytes) -> float:
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def scene_of(jpeg_b64: str) -> str | None:
    """Test mode only: the scene description mock/drive.py embeds in the JPEG comment field."""
    if not TEST_SCENES:
        return None
    try:
        comment = _image(jpeg_b64).info.get("comment")
    except Exception:
        return None
    text = comment.decode("utf-8", "replace") if isinstance(comment, bytes) else comment
    return text or None


# ---- time and answers -------------------------------------------------------

def clock(ts_ms: int) -> str:
    return time.strftime("%I:%M %p", time.localtime(ts_ms / 1000)).lstrip("0")


def when_phrase(ts_ms: int, now_ms: int) -> str:
    mins = (now_ms - ts_ms) // 60000
    if mins < 1:
        return "just now"
    if mins < 60:
        return f"about {mins} minute{'s' if mins != 1 else ''} ago"
    seen, now = time.localtime(ts_ms / 1000), time.localtime(now_ms / 1000)
    if seen[:3] == now[:3]:
        return f"at {clock(ts_ms)}"
    return f"on {time.strftime('%b %d', seen).replace(' 0', ' ')} at {clock(ts_ms)}"


def timeline_answer(question: str, moments: list[dict]) -> tuple[str, dict] | None:
    """'When did I leave the house?' from place changes in the timeline. None when it isn't such a question
    or the timeline has no such change, so the caller falls back to search."""
    leaving = bool(LEAVE.search(question))
    if not leaving and not ARRIVE.search(question):
        return None
    words = re.findall(r"[a-z]+", question.lower())
    place = next((PLACE_WORDS[w] for w in words if w in PLACE_WORDS), "home")
    for i in range(len(moments) - 1, 0, -1):
        a, b = moments[i - 1], moments[i]
        if leaving and a["place_note"] == place and b["place_note"] != place:
            gap_ms = b["ts"] - a["ts"]
            when = f"around {clock(a['ts'])}" if gap_ms < 15 * 60000 else f"between {clock(a['ts'])} and {clock(b['ts'])}"
            return f"You left {PLACE_NAME[place]} {when}.", a
        if not leaving and a["place_note"] != place and b["place_note"] == place:
            where = "home" if place == "home" else f"to {PLACE_NAME[place]}"
            return f"You got {where} around {clock(b['ts'])}.", b
    return None


def to_second_person(statement: str) -> str:
    """'I put my wallet on the shelf' -> 'you put your wallet on the shelf' (the wearer hears it, so it's 'you')."""
    for first, second in ((r"\bI'm\b", "you're"), (r"\bI've\b", "you've"), (r"\bI'll\b", "you'll"), (r"\bI\b", "you"),
                          (r"\bmy\b", "your"), (r"\bmine\b", "yours"), (r"\bme\b", "you")):
        statement = re.sub(first, second, statement, flags=re.I if first.startswith(r"\bm") else 0)
    return statement


def _no_article(name) -> str:
    return re.sub(r"^(?:a|an|the|some|my|your)\s+", "", known(name), flags=re.I)


def template(moment: dict, kind: str, idx: int, now_ms: int) -> str | None:
    """A ready-to-speak sentence for an object, person or fact hit, or None when the details are too thin."""
    c = json.loads(moment["caption_json"])
    when = when_phrase(moment["ts"], now_ms)
    if kind == "o":
        o = c["objects"][idx]
        name, color = _no_article(o.get("name")), known(o.get("color"))
        loc = " ".join(x for x in (known(o.get("on_or_in")), known(o.get("near"))) if x)
        if not name or not loc or known(o.get("text")):  # an object with readable text is a question about the text: Sonnet
            return None
        # Two short sentences: core speaks the first as soon as it is synthesised, so what and where come first.
        detail = f"{color[0].upper()}{color[1:]}, seen {when}" if color else f"Seen {when}"
        return f"I last saw your {name} {loc}. {detail}."
    if kind == "p":
        p = c["people"][idx]
        name, clothing = known(p.get("name")), known(p.get("clothing"))
        return f"{name} was wearing {clothing}. Seen {when}." if name and clothing else None
    if kind == "fact":
        f = c["fact"]
        statement = to_second_person(known(f.get("statement")))
        if not statement:
            return None
        loc = f.get("location") or {}
        name = known(loc.get("name"))
        extras = ", ".join(x for x in (known(loc.get("color")), known(loc.get("material")), known(loc.get("near"))) if x)
        tail = f" That's the {name}{f' ({extras})' if extras else ''}." if name else ""
        return f"You told me {statement}, {when}.{tail}"
    return None


# ---- the service ------------------------------------------------------------

class Service:
    def __init__(self) -> None:
        self.db = Stdb()
        self.index = MossIndex()
        self.moments: list[dict] = []        # rows of the moment table, sorted by ts
        self.people: dict[str, dict] = {}    # rows of the person table, by name
        self.ids: set[int] = set()           # every moment id in use, so two frames in one ms can't collide
        self.queue: asyncio.Queue = asyncio.Queue(10)
        self.pending = 0                     # frames queued or being captioned; app.py shows it on /health
        self.last_hash: bytes | None = None  # thumbnail of the last frame kept, for duplicate skipping
        self.tasks: list[asyncio.Task] = []
        self.bg: set[asyncio.Task] = set()

    async def start(self) -> None:
        THUMB_DIR.mkdir(exist_ok=True)
        rows = await self.db.sql("SELECT * FROM moment")
        self.moments = sorted(rows, key=lambda m: m["ts"])
        self.ids = {m["id"] for m in rows}
        self.people = {p["name"]: p for p in await self.db.sql("SELECT * FROM person")}
        await self.index.open(self.moments)
        self.tasks = [asyncio.create_task(self._worker()) for _ in range(2)]
        log.info("started: %d moments, %d people, test scenes %s", len(rows), len(self.people), TEST_SCENES)

    async def close(self) -> None:
        for t in self.tasks:
            t.cancel()
        await self.index.close()
        await self.db.close()

    # -- ingest ---------------------------------------------------------------

    def ingest(self, ts: float, jpeg_b64: str) -> None:
        """Called for every ~3 s frame core sends. Returns at once; captioning happens in the workers."""
        h = frame_hash(jpeg_b64)
        if h is None:
            log.warning("ingest: not a decodable JPEG")
            return
        if self.last_hash is not None and hash_diff(h, self.last_hash) < DUP_DIFF:
            return
        self.last_hash = h
        if self.queue.full():
            self.queue.get_nowait()  # drop the oldest: a fresh frame is worth more than a complete backlog
            self.pending -= 1
        self.queue.put_nowait((ts, jpeg_b64))
        self.pending += 1

    async def _worker(self) -> None:
        while True:
            ts, jpeg_b64 = await self.queue.get()
            try:
                await self._caption(ts, jpeg_b64)
            except Exception as e:
                log.error("caption failed: %r", e)
            finally:
                self.pending -= 1

    async def _caption(self, ts: float, jpeg_b64: str) -> None:
        scene = scene_of(jpeg_b64)
        cap = await captions.caption(None if scene is not None else jpeg_b64, scene, self._known_people())
        mid = self._new_id(ts)
        await self._store({"id": mid, "ts": mid, "caption_json": json.dumps(cap),
                           "thumb_url": self._thumb(mid, jpeg_b64), "place_note": cap["place"]})
        for p in cap["people"]:  # a named person seen again: keep what they look like today
            name, clothing = known(p.get("name")), known(p.get("clothing"))
            if name in self.people and clothing:
                await self._set_person(name, clothing, mid)

    # -- remember -------------------------------------------------------------

    async def remember(self, label: str, ts: float, jpeg_b64: str) -> bool:
        """label is what the wearer said. Introduces a person, or stores a fact like 'my passport is in the drawer'."""
        scene = scene_of(jpeg_b64)
        r = await captions.remember(label, None if scene is not None else jpeg_b64, scene)
        base = {"said": label, "place": r["place"], "place_detail": r["place_detail"]}
        mid = self._new_id(ts)
        if r["kind"] == "person":
            name, clothing = known(r["person"]["name"]), known(r["person"]["clothing"])
            if not name:
                log.warning("remember: no name in %r", label)
                return False
            await self._set_person(name, clothing or "unknown", mid)
            cap = {**base, "scene": "", "objects": [], "text": [],
                   "people": [{"name": name, "clothing": clothing, "position": ""}]}
        else:
            f = r["fact"]
            if not known(f["item"]) or not known(f["statement"]):
                log.warning("remember: no fact in %r", label)
                return False
            cap = {**base, "fact": f}
        await self._store({"id": mid, "ts": mid, "caption_json": json.dumps(cap),
                           "thumb_url": self._thumb(mid, jpeg_b64), "place_note": r["place"]})
        return True

    # -- recall ---------------------------------------------------------------

    async def recall(self, question: str) -> dict:
        now_ms = int(time.time() * 1000)
        await self._prune()
        best = None
        hit = timeline_answer(question, self.moments)
        if hit:
            answer, best = hit
        else:
            docs = (await self.index.search(question))[0] if self.moments else []  # nothing indexed yet: nothing to ask
            by_id = {m["id"]: m for m in self.moments}
            strong = [(d, by_id[parse_ref(d.id)[0]]) for d in docs
                      if d.score >= MIN_SCORE and parse_ref(d.id)[0] in by_id]
            log.info("recall %r top hits: %s", question, [(d.id, round(d.score, 2)) for d in docs[:3]])  # for tuning MIN/FAST_SCORE
            if not strong:
                answer = NOT_SEEN
            else:
                top = max(d.score for d, _ in strong)
                # Among the near-best hits (the same thing seen several times) trust the most recent.
                doc, best = max((x for x in strong if x[0].score >= top - 0.08), key=lambda x: x[1]["ts"])
                _, kind, idx = parse_ref(doc.id)
                tpl = template(best, kind, idx, now_ms)
                if tpl and doc.score >= FAST_SCORE:
                    answer = tpl
                else:
                    entries = [self._entry(d, m, now_ms) for d, m in sorted(strong[:5], key=lambda x: -x[1]["ts"])]
                    try:
                        answer = await captions.answer(question, entries)
                    except Exception as e:
                        if not tpl:
                            raise
                        log.warning("answer failed, using the template: %r", e)
                        answer = tpl
        thumb = (best or {}).get("thumb_url") or None
        self._bg(self.db.call("add_recall", now_ms, question, answer, thumb or ""))
        return {"answer": answer, "ts": best["ts"] / 1000 if best else None, "thumb_url": thumb}

    @staticmethod
    def _entry(doc, moment: dict, now_ms: int) -> str:
        told = (doc.metadata or {}).get("kind") == "fact"
        return f"{'you told me' if told else 'seen'} {when_phrase(moment['ts'], now_ms)}: {doc.text}"

    async def _prune(self) -> None:
        """Forget moments deleted from the dashboard: SpacetimeDB is the source of truth."""
        before = list(self.moments)  # a moment added while the query runs isn't in `alive` yet, so don't judge it
        alive = {r["id"] for r in await self.db.sql("SELECT id FROM moment")}
        dead = [m for m in before if m["id"] not in alive]
        if dead:
            gone = {m["id"] for m in dead}
            self.moments = [m for m in self.moments if m["id"] not in gone]
            await self.index.delete(dead)

    # -- alert ----------------------------------------------------------------

    async def alert(self, kind: str, note: str) -> None:
        """Family alert: what the wearer said, the last place, and who was seen lately with what they wore."""
        now_ms = int(time.time() * 1000)
        parts = [note.strip() or kind]
        if self.moments:
            last = self.moments[-1]
            c = json.loads(last["caption_json"])
            place = ", ".join(x for x in (known(c.get("place_detail")), known(c.get("place"))) if x)
            signs = "; ".join(s for s in c.get("text", []) if known(s))
            if place:
                parts.append(f"Last place: {place}{f', near a sign reading {signs}' if signs else ''}, "
                             f"{when_phrase(last['ts'], now_ms)}.")
        recent = [p for p in self.people.values() if p["last_seen_ts"] >= now_ms - 30 * 60000]
        if recent:
            parts.append("People: " + "; ".join(f"{p['name']} in {p['clothing_note']}" for p in recent) + ".")
        await self.db.call("raise_alert", now_ms, kind, " ".join(parts))

    # -- test support ---------------------------------------------------------

    async def reset(self) -> None:
        """Wipe everything. app.py only exposes this when MEMORY_ALLOW_RESET is set."""
        await self.db.call("delete_all")
        await self.index.delete(self.moments)
        self.moments, self.people, self.ids, self.last_hash = [], {}, set(), None

    # -- helpers --------------------------------------------------------------

    def _known_people(self) -> str:
        return "; ".join(f"{p['name']}: {p['clothing_note']}" for p in self.people.values())

    def _new_id(self, ts: float) -> int:
        i = int(ts * 1000)
        while i in self.ids:
            i += 1
        self.ids.add(i)
        return i

    def _thumb(self, mid: int, jpeg_b64: str) -> str:
        img = _image(jpeg_b64).convert("RGB")
        img.thumbnail((320, 240))
        img.save(THUMB_DIR / f"{mid}.jpg", "JPEG", quality=70)
        return f"{PUBLIC_URL}/thumbs/{mid}.jpg"

    async def _store(self, moment: dict) -> None:
        await self.db.call("add_moment", moment["ts"], moment["caption_json"], moment["thumb_url"], moment["place_note"])
        await self.index.add(moment)
        self.moments.append(moment)
        self.moments.sort(key=lambda m: m["ts"])

    async def _set_person(self, name: str, clothing: str, ts_ms: int) -> None:
        await self.db.call("upsert_person", name, clothing, ts_ms)
        self.people[name] = {"name": name, "clothing_note": clothing, "last_seen_ts": ts_ms}

    def _bg(self, coro) -> None:
        """Fire and forget (a failure is logged, never raised): the answer must not wait on a dashboard row."""
        async def quiet():
            try:
                await coro
            except Exception as e:
                log.warning("background call failed: %r", e)
        t = asyncio.create_task(quiet())
        self.bg.add(t)
        t.add_done_callback(self.bg.discard)
