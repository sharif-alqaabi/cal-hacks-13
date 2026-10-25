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
    intent, source, ms = asyncio.run(router.route("where did I put my keys"))
    assert (intent, source) == ("recall", "jev") and ms >= 0


def test_jev_below_threshold_falls_back_to_claude(fake, monkeypatch):
    async def unsure(text, pending_confirm=False):
        return "other", 0.2
    monkeypatch.setattr(router, "jev_route", unsure)
    intent, source, _ = asyncio.run(router.route("where did I put my keys"))
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
