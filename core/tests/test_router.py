"""Router checks (C-3 target: >= 18/20). Run: python -m pytest tests -q"""
import asyncio

from app import config, router
from app.router import keyword_route

LABELLED = [
    ("what's in front of me", "describe"),
    ("describe the room", "describe"),
    ("what's around me", "describe"),
    ("what does the signal say", "signal"),
    ("is the walk sign on", "signal"),
    ("is it walk", "signal"),
    ("where did I put my keys", "recall"),
    ("where are my keys", "recall"),
    ("what was Sam wearing", "recall"),
    ("who is this", "recall"),
    ("this is my brother Sam", "remember"),
    ("I'm lost", "lost"),
    ("help me", "lost"),
    ("email Sam that I'm at the Palace of Fine Arts", "browser"),
    ("send an email to Sam", "browser"),
    ("yes send it", "confirm"),
    ("no cancel", "confirm"),
    ("nope", "confirm"),
    ("is this the right item", "task"),
    ("check this item", "task"),
]


def test_twenty_phrases():
    assert len(LABELLED) == 20


def test_keyword_router_accuracy():
    wrong = [(t, keyword_route(t), w) for t, w in LABELLED if keyword_route(t) != w]
    assert len(wrong) <= 2, wrong


def test_past_questions_keyword_to_recall():
    for t in ("do you know where my house keys are", "have you seen my wallet", "what else was on the picnic table",
              "do you remember the guy I was talking to", "did I come across a guy just now",
              "when did I last see my house keys", "who was I talking to", "where was I two hours ago"):
        assert keyword_route(t) == "recall", t
    assert keyword_route("what's in front of me") == "describe"
    assert keyword_route("what do you see in front of me") == "describe"
    assert keyword_route("email Sam that I left 5 minutes ago") == "browser"


def test_jev_describe_with_past_words_asks_claude(fake, monkeypatch):
    async def sure_describe(text, pending_confirm=False):
        return "describe", 0.9
    monkeypatch.setattr(router, "jev_route", sure_describe)
    intent, source, _ = asyncio.run(router.route("do you know where my keys are"))  # present tense, so Jev is asked
    assert (intent, source) == ("recall", "claude")
    intent, source, _ = asyncio.run(router.route("what's in front of me"))
    assert (intent, source) == ("describe", "jev")  # a real describe still takes Jev's answer


def test_past_tense_goes_to_recall_before_jev(fake, monkeypatch):
    async def wrong(text, pending_confirm=False):
        return "describe", 0.99
    monkeypatch.setattr(router, "jev_route", wrong)
    for t in ("what color was the car that just passed me", "have you seen my wallet", "what did the sign say",
              "did I leave the stove on", "what was on the table earlier", "who were the people at the cafe",
              "what else was on the picnic table", "how long ago did I see Kevin"):
        assert asyncio.run(router.route(t))[:2] == ("recall", "tense"), t
    # Other intents keep their own route even with a past-tense word in them.
    assert keyword_route("email Sam that I left 5 minutes ago and was late") == "browser"
    assert keyword_route("did the walk sign turn on") == "signal"
    assert keyword_route("I'm lost, I was at the bus stop") == "lost"
    assert keyword_route("this is my friend Sam, I saw him earlier") == "remember"
    # Present tense still asks Jev.
    assert asyncio.run(router.route("what's in front of me"))[:2] == ("describe", "jev")


def test_confirm_short_circuit_when_pending(fake):
    intent, source, _ = asyncio.run(router.route("yes send it", pending_confirm=True))
    assert (intent, source) == ("confirm", "keywords")


YOUTUBE = ["play the latest video from James Hoffmann on YouTube", "find videos about cold brew on YouTube",
           "play number two", "play the second one", "pause", "resume", "pause the video", "search YouTube for lofi"]


def test_youtube_goes_to_browser():
    assert [t for t in YOUTUBE if keyword_route(t) != "browser"] == []


SITES = ["go to Instagram", "open X", "Can you open Twitter please", "go to nytimes.com", "take me to reddit.",
         "open the Exploratorium website", "go to calhacks dot io", "open hacker news", "open a new tab",
         "close this tab", "close the tab please", "open a new tab and go to reddit"]
NOT_SITES = ["go to the kitchen", "open the door", "take me to the bathroom"]


def test_sites_go_to_browser(fake):
    assert [t for t in SITES if keyword_route(t) != "browser"] == []
    for text in SITES:
        intent, source, _ = asyncio.run(router.route(text))
        assert (intent, source) == ("browser", "keywords"), text
    assert [t for t in NOT_SITES if router.SITE_RX.match(t.lower())] == []


def test_youtube_controls_short_circuit(fake):
    for text in ["pause", "play number two", "play lofi music on YouTube"]:
        intent, source, _ = asyncio.run(router.route(text))
        assert (intent, source) == ("browser", "keywords"), text


def test_jev_used_when_confident(fake):
    intent, source, ms = asyncio.run(router.route("where are my keys"))  # present tense: past tense skips Jev
    assert (intent, source) == ("recall", "jev") and ms >= 0


def test_jev_below_threshold_falls_back_to_claude(fake, monkeypatch):
    async def unsure(text, pending_confirm=False):
        return "other", 0.2
    monkeypatch.setattr(router, "jev_route", unsure)
    intent, source, _ = asyncio.run(router.route("where are my keys"))
    assert (intent, source) == ("recall", "claude")


def test_everything_down_uses_keywords(fake, monkeypatch):
    async def none(*a, **k):
        return None
    monkeypatch.setattr(router, "jev_route", none)
    monkeypatch.setattr(router, "claude_route", none)
    intent, source, _ = asyncio.run(router.route("I'm lost"))
    assert (intent, source) == ("lost", "keywords")


def test_real_jev_without_key_is_none(monkeypatch):
    monkeypatch.setattr(config, "TYPESAFE_API_KEY", "")
    assert asyncio.run(router.jev_route("hi")) is None
