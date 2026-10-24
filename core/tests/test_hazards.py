from app.hazards import Box, HazardTracker, all_phrases, direction_for, phrase


def chair(cx=0.5, area=0.1, bottom=0.95, cls="chair", conf=0.9):
    side = area ** 0.5
    return Box(cls, conf, cx - side / 2, bottom - side, cx + side / 2, bottom)


def run(tracker, areas, cx=0.5, dt=0.2, t0=100.0, **kw):
    out = []
    for i, a in enumerate(areas):
        out.append(tracker.decide([chair(cx=cx, area=a, **kw)], t0 + i * dt))
    return out


def grow(n=12, start=0.05, ratio=1.1):
    return [start * ratio ** i for i in range(n)]


def test_growing_centred_box_warns_once():
    out = run(HazardTracker(demo_mode=False, cooldown_s=3), grow())
    warnings = [w for w in out if w]
    assert warnings == ["Stop, chair ahead."]


def test_static_box_does_not_warn():
    assert not any(run(HazardTracker(demo_mode=False), [0.12] * 15))


def test_off_centre_does_not_warn():
    assert not any(run(HazardTracker(demo_mode=False), grow(), cx=0.1))


def test_top_of_frame_does_not_warn():
    assert not any(run(HazardTracker(demo_mode=False), grow(ratio=1.05), bottom=0.3))


def test_cooldown_then_warns_again():
    t = HazardTracker(demo_mode=False, cooldown_s=3)
    first = run(t, grow(), t0=100)
    again = run(t, grow(), t0=100 + 12 * 0.2 + 3.5)
    assert sum(bool(w) for w in first) == 1 and sum(bool(w) for w in again) == 1


def test_very_close_override():
    t = HazardTracker(demo_mode=False)
    assert t.decide([chair(area=0.4)], 100.0) == "Stop, chair ahead."


def test_demo_mode_ignores_person_and_raises_min_area():
    assert not any(run(HazardTracker(demo_mode=True), grow(), cls="person"))
    assert any(run(HazardTracker(demo_mode=False), grow(), cls="person"))
    assert HazardTracker(demo_mode=True).min_area == 0.10


def test_low_confidence_ignored():
    assert not any(run(HazardTracker(demo_mode=False), grow(), conf=0.3))


def test_direction_table():
    assert [direction_for(x) for x in (0.2, 0.4, 0.5, 0.6, 0.8)] == [
        "on your left", "ahead, slightly left", "ahead", "ahead, slightly right", "on your right"]


def test_phrase_wording():
    assert phrase("chair", direction_for(0.42)) == "Stop, chair ahead, slightly left."
    assert "Stop, table on your right." in all_phrases()
    assert len(all_phrases()) == len(set(all_phrases()))
