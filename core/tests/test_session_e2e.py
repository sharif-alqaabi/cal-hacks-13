"""In-process end to end: TestClient opens /stream like the phone; every API faked, stubs in-process."""
import base64
import json
import time
import wave
from pathlib import Path

import pytest

from app import safety
from app.clients import memory
from tests.stubs import browser_stub, memory_stub

FIX = Path(__file__).resolve().parent / "fixtures"
needs_fixtures = pytest.mark.skipif(not (FIX / "chair_walk").exists(), reason="run python -m tests.make_fixtures")


def frame(path: Path, snap_id=None) -> str:
    msg = {"type": "frame", "ts": time.time(), "jpeg_b64": base64.b64encode(path.read_bytes()).decode(),
           "w": 640, "h": 480}
    if snap_id:
        msg["snap_id"] = snap_id
    return json.dumps(msg)


def says(ws, n: int, answer_snaps: Path | None = None) -> list[dict]:
    """Receive until n say messages; answer snap requests with answer_snaps (or ignore them)."""
    out = []
    while len(out) < n:
        m = ws.receive_json()
        if m["type"] == "snap":
            if answer_snaps:
                ws.send_text(frame(answer_snaps, m["snap_id"]))
        elif m["type"] == "say":
            out.append(m)
    return out


def text(ws, t: str) -> None:
    ws.send_text(json.dumps({"type": "text", "text": t}))


def test_text_recall(client):
    with client.websocket_connect("/stream") as ws:
        text(ws, "where did I put my keys")
        [s] = says(ws, 1)
        assert s["text"] == "Your keys are on the table, 3:42 PM." and s["pcm16_b64"] and not s["urgent"]


@needs_fixtures
def test_ptt_wav_to_reply(client):
    with wave.open(str(FIX / "audio" / "keys.wav")) as w:
        pcm, rate = w.readframes(w.getnframes()), w.getframerate()
    with client.websocket_connect("/stream") as ws:
        ws.send_text(json.dumps({"type": "ptt", "state": "down"}))
        step = rate * 2 // 10
        for i in range(0, len(pcm), step):
            ws.send_text(json.dumps({"type": "audio", "ts": time.time(), "rate": rate,
                                     "pcm16_b64": base64.b64encode(pcm[i:i + step]).decode()}))
        ws.send_text(json.dumps({"type": "ptt", "state": "up"}))
        [s] = says(ws, 1)
        assert "keys" in s["text"]


def test_ptt_unknown_audio_says_not_heard(client):
    with client.websocket_connect("/stream") as ws:
        ws.send_text(json.dumps({"type": "ptt", "state": "down"}))
        ws.send_text(json.dumps({"type": "audio", "ts": 0, "rate": 8000, "pcm16_b64": base64.b64encode(b"\1" * 1600).decode()}))
        ws.send_text(json.dumps({"type": "ptt", "state": "up"}))
        [s] = says(ws, 1)
        assert s["text"] == "Sorry, I couldn't hear that."


@needs_fixtures
def test_describe_two_says_in_order_with_snap(client):
    with client.websocket_connect("/stream") as ws:
        ws.send_text(frame(FIX / "room.jpg"))
        text(ws, "what's in front of me")
        s = says(ws, 2, answer_snaps=FIX / "room.jpg")
        assert [x["text"] for x in s] == ["A chair is ahead, slightly left.", "A table is on your right."]


@needs_fixtures
def test_describe_snap_timeout_uses_latest_frame(client):
    with client.websocket_connect("/stream") as ws:
        ws.send_text(frame(FIX / "room.jpg"))
        t0 = time.time()
        text(ws, "what's in front of me")
        s = says(ws, 2, answer_snaps=None)
        assert s[0]["text"].startswith("A chair") and time.time() - t0 >= 1.1


def test_describe_without_frame(client):
    with client.websocket_connect("/stream") as ws:
        text(ws, "what's in front of me")
        [s] = says(ws, 1, answer_snaps=None)
        assert s["text"] == "I can't see anything from the glasses right now."


@needs_fixtures
def test_signal_composed(client):
    with client.websocket_connect("/stream") as ws:
        ws.send_text(frame(FIX / "crosswalk.jpg"))
        text(ws, "what does the signal say")
        s = says(ws, 2, answer_snaps=FIX / "crosswalk.jpg")
        assert [x["text"] for x in s] == ["The walk sign is on.", "A car is moving from your left."]


def test_browser_task_and_yes(client):
    with client.websocket_connect("/stream") as ws:
        text(ws, "email Sam that I'm at the Palace of Fine Arts")
        a, b = says(ws, 2)
        assert a["text"] == "Working on it." and "send" in b["text"].lower()
        text(ws, "yes send it")
        [c] = says(ws, 1)
        assert c["text"] == "Sent."
    confirms = [e for e in browser_stub.state["log"] if e["endpoint"] == "/confirm"]
    assert confirms and confirms[-1]["body"]["yes"] is True


def test_confirm_with_nothing_pending(client):
    with client.websocket_connect("/stream") as ws:
        text(ws, "yes send it")
        [s] = says(ws, 1)
        assert s["text"] == "There's nothing waiting for a yes right now."


def test_lost_alerts_family(client):
    with client.websocket_connect("/stream") as ws:
        text(ws, "I'm lost")
        [s] = says(ws, 1)
        assert "family" in s["text"]
    alerts = [e for e in memory_stub.state["log"] if e["endpoint"] == "/alert"]
    assert alerts[-1]["body"] == {"kind": "lost", "note": "I'm lost"}


def test_memory_down(client):
    memory_stub.state["fail"] = True
    with client.websocket_connect("/stream") as ws:
        text(ws, "where did I put my keys")
        [s] = says(ws, 1)
        assert s["text"] == memory.UNAVAILABLE


def test_banned_phrase_filtered(client, fake):
    fake["llm"].bad = True
    with client.websocket_connect("/stream") as ws:
        text(ws, "tell me a joke")
        [s] = says(ws, 1)
        assert s["text"] == safety.FALLBACK


@needs_fixtures
def test_hazard_frames_give_urgent_say(client):
    with client.websocket_connect("/stream") as ws:
        for p in sorted((FIX / "chair_walk").glob("*.jpg")):
            ws.send_text(frame(p))
            time.sleep(0.2)
        [s] = says(ws, 1)
        assert s["urgent"] and s["text"] == "Chair ahead, slightly left."


@needs_fixtures
def test_scene_change_triggers_extra_ingest(client):
    frames = sorted((FIX / "scene_cut").glob("*.jpg"))
    with client.websocket_connect("/stream") as ws:
        for p in frames[:7]:          # one colour for 1.4 s: ingest once at the start
            ws.send_text(frame(p))
            time.sleep(0.2)
        ws.send_text(frame(frames[15]))   # cut to the other colour, < 3 s after the first ingest
        time.sleep(0.3)
        text(ws, "where did I put my keys")   # round trip so the ingest task has run
        says(ws, 1)
    ingests = [e for e in memory_stub.state["log"] if e["endpoint"] == "/ingest"]
    assert len(ingests) == 2


def test_headless_session_via_mirror_text(client):
    with client.websocket_connect("/mirror/ws") as m:
        m.send_text(json.dumps({"text": "I'm lost"}))
        while True:
            ev = m.receive_json()
            if ev["kind"] == "say":
                assert "family" in ev["text"]
                break


def test_health(client):
    h = client.get("/health").json()
    assert h["ok"] and h["active_session"] == "headless" and h["hazards"] is True
