"""Every Claude call the memory service makes: frame captions, /remember, and recall answers.

A frame is either a real JPEG or, in test mode, a written scene description (`scene`); both go through
the same prompts and schemas, so the test path exercises the real captioning logic.
"""
import json
import os

import anthropic
import httpx2

CAPTION_MODEL = os.getenv("CAPTION_MODEL", "claude-haiku-5-5")
ANSWER_MODEL = os.getenv("ANSWER_MODEL", "claude-haiku-5-5")  # claude-sonnet-5-5 also works, about 0.2 s slower and less steady

PLACES = ["home", "outside", "office", "store", "transit", "other"]

CAPTION_PROMPT = """\
You describe camera frames from smart glasses worn by a blind person. What you write is stored
as their visual memory, so later they can ask where something is, what it looked like, or what
a sign said. They can't check anything you write by looking, so accuracy matters more than
completeness.

For every object someone might later look for or bump into, record:
- color: main colors and any pattern, in plain words ("dark green", "red and white stripes")
- size: compared to something familiar ("palm-sized", "about a shoebox", "waist-high")
- material and shape, when you can tell ("brushed metal", "round", "soft fabric")
- state: open/closed, on/off, full/empty, when it applies
- on_or_in: the surface or container it's on or in, a phrase starting with a preposition
  ("on the wooden kitchen counter", "in the top drawer")
- near: one or two fixed landmarks beside it, a phrase starting with a preposition
  ("next to the kettle", "under the window")
- position: where it is relative to the wearer in this frame ("ahead, waist height, slightly left")
- text: any printed or handwritten text on it

Always include small, easily misplaced items (keys, wallet, phone, glasses, medication, cards,
remote) even when they're a small part of the frame. Also record vehicles in view, moving or
parked (type and color), and the buildings and storefronts around the wearer (color, material,
and any name on them), since they may later ask "what color was that car" or "what did the
store I just left look like". Skip things nobody would ask about.

Rules:
- Write "unknown" for any detail you can't see clearly. Never guess a color in poor light or a
  size you can't judge.
- Name a person only if they clearly match someone in the known-people list sent with the
  frame. Otherwise leave name empty and describe their clothing. Never describe faces.
- For documents, cards and screens, say what kind of thing it is ("a passport") but never copy
  ID, card or account numbers, passwords or addresses.
- place is one of: home, outside, office, store, transit, other. place_detail is the room or
  spot ("kitchen", "bus stop on a busy street").
- scene is one or two sentences on the layout a blind person needs to picture the space: where
  the main furniture, doors and walkways are.
- text is every sign, label or screen text readable in the frame, one string each.
"""

REMEMBER_PROMPT = """\
The wearer of smart glasses, who is blind, just said something they want remembered. The image
is what their camera saw at that moment. Decide which kind it is:
- person: they're introducing someone in view ("this is my brother Sam"). Return the name they
  used and that person's clothing and anything distinctive they're wearing or carrying. Never
  describe their face.
- fact: they're telling you where something is or something about an object ("my passport is
  in the drawer"). The item may not be visible, for example inside a closed drawer: take the
  item and the statement from their words. Then describe, from the image, the place they mean,
  with the same details as any object: color, size, material, shape, state, what it's on or in,
  landmarks near it, and the room.
- earlier: they're naming someone who was there before and isn't the subject of this image ("the
  guy I talked to at the coffee shop was Kevin", "that was Kevin", "remember him as Kevin"). Put
  the name in person.name and, in who, the words that say who and where ("man at the coffee
  shop"; empty if they gave none). Leave clothing empty: it comes from the earlier sighting.
If the image doesn't show the place they mean, set those details to "unknown" and keep the
statement. Write on_or_in and near as phrases starting with a preposition ("in the top drawer",
"left of the bed"). Never copy ID or card numbers. Fill in the part for the kind you chose and use empty
strings in the other parts. place is one of: home, outside, office, store, transit, other.
"""

RECALL_PROMPT = """\
Answer a blind person's question about where something is or what they saw, using the memory
entries below and, when frames are given, the frames themselves (oldest first, each labeled with
when it was seen and what was noted at the time). The entries were written before anyone asked and
may have left a detail out, so for how something looked (color, a sign, what someone wore) look at
the frames. One spoken sentence, under 30 words. Say when it was seen by copying the time words
from that entry or frame label exactly; never work out a time of your own. Describe the location by
touch and landmarks ("on the wooden counter, next to the kettle"), never "over there". If the best
entry is something they told you, say "You told me...". If entries disagree, trust the most recent.
Never add details that are in neither the entries nor the frames, and never read out ID, card or
account numbers. Never mention frames or entries in the sentence: the listener just hears what was seen. Set frame to the number of the frame the answer comes from, or -1 when it comes
from the entries. If nothing answers the question, say you haven't seen it and set frame to -1.
"""

OBJECT_FIELDS = ("name", "color", "size", "material", "shape", "state", "on_or_in", "near", "position", "text")
PERSON_FIELDS = ("name", "clothing", "position")
LOCATION_FIELDS = ("name", "color", "size", "material", "shape", "state", "on_or_in", "near", "text")


def _strings(fields) -> dict:
    return {
        "type": "object",
        "properties": {f: {"type": "string"} for f in fields},
        "required": list(fields),
        "additionalProperties": False,
    }


def _schema(properties: dict) -> dict:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


CAPTION_SCHEMA = _schema({
    "place": {"type": "string", "enum": PLACES},
    "place_detail": {"type": "string"},
    "scene": {"type": "string"},
    "objects": {"type": "array", "items": _strings(OBJECT_FIELDS)},
    "people": {"type": "array", "items": _strings(PERSON_FIELDS)},
    "text": {"type": "array", "items": {"type": "string"}},
})

REMEMBER_SCHEMA = _schema({
    "kind": {"type": "string", "enum": ["person", "fact", "earlier"]},
    "person": _strings(("name", "clothing")),
    "who": {"type": "string"},
    "fact": _schema({
        "item": {"type": "string"},
        "statement": {"type": "string"},
        "location": _strings(LOCATION_FIELDS),
    }),
    "place": {"type": "string", "enum": PLACES},
    "place_detail": {"type": "string"},
})

ANSWER_SCHEMA = _schema({"answer": {"type": "string"}, "frame": {"type": "integer"}})

_client: anthropic.AsyncAnthropic | None = None


def client() -> anthropic.AsyncAnthropic:
    """Created on first use so importing this module never needs a key."""
    global _client
    if _client is None:
        # The SDK drops idle connections after 5 s, so a recall after a pause paid a new TLS handshake
        # (~190 ms measured in core). Keep them for 5 minutes.
        http = anthropic.DefaultAsyncHttpxClient(limits=httpx2.Limits(max_connections=100, max_keepalive_connections=20,
                                                                      keepalive_expiry=300))
        _client = anthropic.AsyncAnthropic(http_client=http)
    return _client


def _frame_block(jpeg_b64: str | None, scene: str | None) -> dict:
    if scene is not None:
        return {"type": "text", "text": f"Camera view (written description, test mode): {scene}"}
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": jpeg_b64}}


async def _structured(system: str, schema: dict, content: list) -> dict:
    resp = await client().messages.create(
        model=CAPTION_MODEL,
        max_tokens=16000,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],  # fixed prompt, cached
        messages=[{"role": "user", "content": content}],
        output_config={"format": {"type": "json_schema", "schema": schema}, "effort": "low"},
    )
    if resp.stop_reason == "refusal":  # Haiku has no server-side fallback: the caller skips this frame
        raise RuntimeError("model refused the frame")
    return json.loads(next(b.text for b in resp.content if b.type == "text"))


async def caption(jpeg_b64: str | None = None, scene: str | None = None, known_people: str = "") -> dict:
    """Frame -> caption dict matching CAPTION_SCHEMA. known_people is e.g. "Sam: red hoodie, jeans"."""
    return await _structured(CAPTION_PROMPT, CAPTION_SCHEMA, [
        _frame_block(jpeg_b64, scene),
        {"type": "text", "text": f"Known people: {known_people or 'none'}"},
    ])


async def remember(said: str, jpeg_b64: str | None = None, scene: str | None = None) -> dict:
    """What the wearer said + the frame -> a person or a fact, matching REMEMBER_SCHEMA."""
    return await _structured(REMEMBER_PROMPT, REMEMBER_SCHEMA, [
        _frame_block(jpeg_b64, scene),
        {"type": "text", "text": f'The wearer said: "{said}"'},
    ])


async def answer(question: str, entries: list[str], frames: list[tuple[str, str, str]] = ()) -> dict:
    """{answer, frame} from the memory entries (newest first, each with its time) and optionally saved frames as
    (when, jpeg_b64, what was noted), oldest first. frame is the frame the answer came from, -1 for the entries."""
    content = [{"type": "text", "text": "Memory entries:\n" + ("\n".join(f"- {e}" for e in entries) or "(none)")}]
    for i, (when, jpeg_b64, note) in enumerate(frames):
        content.append({"type": "text", "text": f"Frame {i}, seen {when}" + (f". Noted then: {note}" if note else "")})
        content.append(_frame_block(jpeg_b64, None))
    content.append({"type": "text", "text": f"Question: {question}"})
    kw = dict(model=ANSWER_MODEL, max_tokens=16000, system=RECALL_PROMPT, messages=[{"role": "user", "content": content}],
              output_config={"effort": "low", "format": {"type": "json_schema", "schema": ANSWER_SCHEMA}})
    if ANSWER_MODEL.startswith("claude-haiku"):
        # Measured: adaptive thinking made Haiku's latency swing 0.8-2.6 s; with it off it is 0.8-0.9 s. Haiku has no refusal fallback.
        resp = await client().messages.create(thinking={"type": "disabled"}, **kw)
    else:
        resp = await client().beta.messages.create(
            betas=["server-side-fallback-2026-07-01"],
            extra_body={"fallbacks": "default"},  # SDK typings lag this parameter; route a policy decline to another model
            **kw)
    if resp.stop_reason == "refusal":
        raise RuntimeError("model refused the question")
    return json.loads(next(b.text for b in resp.content if b.type == "text"))
