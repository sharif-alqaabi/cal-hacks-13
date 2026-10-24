import json

import pytest

from app.vision import compose_signal
from contracts.stream import AudioMsg, FrameMsg, PttMsg, SayMsg, SnapMsg, TextMsg, parse_inbound


def test_every_inbound_type_parses():
    assert isinstance(parse_inbound(json.dumps({"type": "frame", "ts": 1, "jpeg_b64": "x", "w": 640, "h": 480})), FrameMsg)
    assert isinstance(parse_inbound(json.dumps({"type": "audio", "ts": 1, "pcm16_b64": "", "rate": 16000})), AudioMsg)
    assert parse_inbound(json.dumps({"type": "ptt", "state": "down"})) == PttMsg(state="down")
    assert parse_inbound(json.dumps({"type": "text", "text": "hi"})) == TextMsg(text="hi")
    assert parse_inbound(json.dumps({"type": "frame", "ts": 1, "jpeg_b64": "x", "w": 1, "h": 1, "snap_id": "a"})).snap_id == "a"


def test_unknown_type_raises():
    with pytest.raises(ValueError):
        parse_inbound(json.dumps({"type": "nope"}))


def test_outbound_shapes():
    say = json.loads(SayMsg(id="a", text="t").model_dump_json())
    assert set(say) == {"type", "id", "text", "pcm16_b64", "rate", "urgent"} and say["type"] == "say"
    assert json.loads(SnapMsg(snap_id="s").model_dump_json()) == {"type": "snap", "snap_id": "s"}


@pytest.mark.parametrize("raw,want", [
    ('{"signal":"walk","countdown":null,"vehicles":[]}', ["The walk sign is on."]),
    ('{"signal":"dont_walk","vehicles":[{"motion":"moving","from":"right"}]}',
     ["The signal shows don't walk.", "A car is moving from your right."]),
    ('{"signal":"countdown","countdown":12,"vehicles":[{"motion":"stopped","from":"left"}]}',
     ["The signal is counting down, 12 seconds."]),
    ('{"signal":"walk","vehicles":[{"motion":"moving","from":"left"},{"motion":"moving","from":"right"}]}',
     ["The walk sign is on.", "Cars are moving from your left and right."]),
    ('{"signal":"none"}', ["I don't see a pedestrian signal."]),
    ('```json\n{"signal":"unclear"}\n```', ["I can't read the signal clearly."]),
    ("It is safe to cross", ["I can't read the signal clearly."]),
])
def test_signal_composer(raw, want):
    assert compose_signal(raw) == want
