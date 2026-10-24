"""Offline checks: no network, no Claude, no Moss, no SpacetimeDB, no cost.

    memory/.venv/bin/python memory/selftest.py
"""
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE / "mock")]
os.environ["MEMORY_TEST_SCENES"] = "1"  # before importing service, which reads it once

import captions  # noqa: E402
import drive  # noqa: E402
import moss_index  # noqa: E402
import service  # noqa: E402

lt = time.localtime()
NOON = int(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 12, 0, 0, 0, 0, -1)) * 1000)  # a fixed "now" away from midnight
MIN = 60000

CAP = {
    "place": "home", "place_detail": "kitchen", "scene": "Small kitchen.", "text": ["EXIT"],
    "objects": [{"name": "keys", "color": "silver with a red fob", "size": "palm-sized", "material": "metal",
                 "shape": "unknown", "state": "unknown", "on_or_in": "on the wooden counter",
                 "near": "next to the kettle", "position": "ahead, slightly left", "text": ""}],
    "people": [{"name": "Sam", "clothing": "red hoodie", "position": "by the door"}],
}
FACT = {
    "said": "remember that my passport is in the drawer", "place": "home", "place_detail": "bedroom",
    "fact": {"item": "passport", "statement": "my passport is in the drawer",
             "location": {"name": "top drawer of a dresser", "color": "dark brown", "size": "waist-high",
                          "material": "wood", "shape": "three drawers", "state": "closed",
                          "on_or_in": "in the top drawer", "near": "left of the bed", "text": ""}},
}


def moment(id_: int, cap: dict, ts: int | None = None, place: str | None = None) -> dict:
    return {"id": id_, "ts": ts if ts is not None else id_, "caption_json": json.dumps(cap), "thumb_url": "",
            "place_note": place or cap.get("place", "home")}


def check_strict(schema: dict, path: str) -> None:
    if schema.get("type") == "object":
        assert schema["additionalProperties"] is False, path
        assert set(schema["required"]) == set(schema["properties"]), path
        for k, v in schema["properties"].items():
            check_strict(v, f"{path}.{k}")
    elif schema.get("type") == "array":
        check_strict(schema["items"], f"{path}[]")


def test_schemas() -> None:
    check_strict(captions.CAPTION_SCHEMA, "caption")
    check_strict(captions.REMEMBER_SCHEMA, "remember")
    check_strict(captions.LOOK_SCHEMA, "look")
    assert captions.CAPTION_SCHEMA["properties"]["place"]["enum"] == captions.PLACES
    assert captions.REMEMBER_SCHEMA["properties"]["kind"]["enum"] == ["person", "fact"]


def test_docs() -> None:
    docs = moss_index.to_docs(moment(1000, CAP))
    assert [d.id for d in docs] == ["1000:scene", "1000:o0", "1000:p0"], [d.id for d in docs]
    obj = docs[1]
    assert "silver with a red fob" in obj.text and "next to the kettle" in obj.text, obj.text
    assert "unknown" not in obj.text and "slightly left" not in obj.text, obj.text
    assert obj.metadata == {"moment_id": "1000", "ts": "1000", "place": "home", "kind": "object"}, obj.metadata
    assert "Signs: EXIT." in docs[0].text and "Place: kitchen (home)." in docs[0].text, docs[0].text
    assert docs[2].text.startswith("Sam wearing red hoodie."), docs[2].text

    fact = moss_index.to_docs(moment(2000, FACT))
    assert [d.id for d in fact] == ["2000:fact"] and fact[0].metadata["kind"] == "fact"
    assert "passport" in fact[0].text and "left of the bed" in fact[0].text and "bedroom (home)" in fact[0].text

    intro = {"place": "home", "place_detail": "living room", "scene": "", "objects": [], "text": [],
             "people": [{"name": "Sam", "clothing": "red hoodie", "position": ""}]}
    assert [d.id for d in moss_index.to_docs(moment(3000, intro))] == ["3000:p0"]  # no empty scene doc
    assert moss_index.to_docs({"id": 1, "ts": 1, "caption_json": "not json", "thumb_url": "", "place_note": ""}) == []


def test_refs() -> None:
    assert moss_index.parse_ref("1000:o2") == (1000, "o", 2)
    assert moss_index.parse_ref("5:scene") == (5, "scene", 0)
    assert moss_index.parse_ref("5:fact") == (5, "fact", 0)
    assert moss_index.parse_ref("7:p10") == (7, "p", 10)


def test_timeline() -> None:
    def at(minutes: int, place: str) -> dict:
        return moment(NOON + minutes * MIN, {**CAP, "place": place}, place=place)

    leave = [at(0, "home"), at(2, "home"), at(5, "outside"), at(60, "office")]
    answer, used = service.timeline_answer("when did I leave the house", leave)
    assert answer.startswith("You left home around "), answer
    assert used["ts"] == NOON + 2 * MIN  # the last moment seen at home
    wide = [at(0, "home"), at(120, "outside")]
    assert service.timeline_answer("when did I leave home", wide)[0].startswith("You left home between "), "gap over 15 min"
    assert service.timeline_answer("when did I get home", [at(0, "outside"), at(9, "home")])[0].startswith("You got home around ")
    assert service.timeline_answer("when did I get to the office", leave)[0].startswith("You got to the office around ")
    assert service.timeline_answer("where are my keys", leave) is None
    assert service.timeline_answer("when did I get my keys", leave) is None  # not an arrival question
    assert service.timeline_answer("when did I leave the house", [at(0, "home"), at(2, "home")]) is None  # no change yet


def test_time() -> None:
    assert service.when_phrase(NOON - 30000, NOON) == "just now"
    assert service.when_phrase(NOON - MIN, NOON) == "about 1 minute ago"
    assert service.when_phrase(NOON - 20 * MIN, NOON) == "about 20 minutes ago"
    assert re.fullmatch(r"at \d{1,2}:\d{2} [AP]M", service.when_phrase(NOON - 180 * MIN, NOON))
    assert re.fullmatch(r"on [A-Z][a-z]{2} \d{1,2} at \d{1,2}:\d{2} [AP]M", service.when_phrase(NOON - 2880 * MIN, NOON))


def test_templates() -> None:
    m = moment(NOON - 20 * MIN, CAP)
    assert service.template(m, "o", 0, NOON) == \
        "I last saw the keys on the wooden counter next to the kettle. Silver with a red fob, seen about 20 minutes ago."
    assert service.template(m, "p", 0, NOON) == "Sam was wearing red hoodie. Seen about 20 minutes ago."
    assert service.template(m, "scene", 0, NOON) is None
    f = service.template(moment(NOON - 20 * MIN, FACT), "fact", 0, NOON)
    assert f.startswith("You told me your passport is in the drawer, about 20 minutes ago."), f
    assert "That's the top drawer of a dresser (dark brown, wood, left of the bed)." in f, f
    assert service.to_second_person("I put my wallet on the shelf") == "you put your wallet on the shelf"
    assert service.to_second_person("my keys are mine, I'm sure") == "your keys are yours, you're sure"
    thin = {**CAP, "place_detail": "", "objects": [{**CAP["objects"][0], "on_or_in": "unknown", "near": ""}]}
    assert service.template(moment(NOON, thin), "o", 0, NOON) is None  # no location to speak


def test_look() -> None:
    for q in ("what color was the car that just passed", "what did the store look like", "what did the sign say"):
        assert service.VISUAL.search(q) or service.JUST.search(q), q
    for q in ("where are my keys", "when did I leave the house", "where is my passport"):
        assert not service.VISUAL.search(q) and not service.JUST.search(q), q
    ms = [moment(i, CAP, ts=i * MIN) for i in range(1, 11)]
    ids = lambda frames: [m["id"] for m in frames]
    assert ids(service.look_frames([5], ms, recent=False)) == [4, 5, 6]  # the hit and its neighbours, oldest first
    assert ids(service.look_frames([1, 10], ms, recent=False)) == [1, 2, 9, 10]  # no neighbour past either end
    assert ids(service.look_frames([3], ms, recent=True)) == [2, 3, 4, 7, 8, 9, 10]  # "just": the newest frames too
    assert ids(service.look_frames([2, 9], ms, recent=False, n=3)) == [1, 2, 3]  # the cap keeps the best hit's frames
    assert service.look_frames([99], ms, recent=False) == []  # a hit on a forgotten moment


def test_scenes() -> None:
    jpeg = drive.render_scene("A red door.")
    assert service.scene_of(jpeg) == "A red door."
    assert service.scene_of(drive.render_scene("Cafe sign: Flat white 4.50 — café")) == "Cafe sign: Flat white 4.50 — café"
    service.TEST_SCENES = False
    assert service.scene_of(jpeg) is None  # off outside test mode
    service.TEST_SCENES = True
    assert service.frame_hash("not an image") is None
    assert service._image(jpeg).size == (640, 480)

    texts = list(dict.fromkeys(e["scene"] for e in json.loads((HERE / "mock/script.json").read_text())))
    hashes = [service.frame_hash(drive.render_scene(t)) for t in texts]
    assert service.hash_diff(hashes[0], service.frame_hash(drive.render_scene(texts[0]))) == 0  # the same scene is a duplicate
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            assert service.hash_diff(hashes[i], hashes[j]) > service.DUP_DIFF, (i, j)  # different scenes are not


def test_mock_files() -> None:
    script = json.loads((HERE / "mock/script.json").read_text())
    assert [e["min_ago"] for e in script] == sorted((e["min_ago"] for e in script), reverse=True)  # oldest first
    assert all(e["scene"] for e in script) and len({e["scene"] for e in script}) == len(script) - 1  # one deliberate repeat
    for q in json.loads((HERE / "mock/questions.json").read_text()):
        assert q["q"] and ("expect" in q or re.compile(q["expect_regex"]))


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"all {len(tests)} checks passed")
