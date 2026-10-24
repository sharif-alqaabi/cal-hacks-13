"""Router accuracy check (C-3 target: >= 18/20). Run: python -m pytest tests -q

Uses keyword routing only so it runs offline. TODO: add a variant that hits Jev + Claude.
"""
from app.router import keyword_route
from app.safety import filter_reply, FALLBACK

LABELLED = [
    ("what's in front of me", "describe"),
    ("describe the room", "describe"),
    ("what does the signal say", "signal"),
    ("is the walk sign on", "signal"),
    ("where did I put my keys", "recall"),
    ("what was Sam wearing", "recall"),
    ("this is my brother Sam", "remember"),
    ("I'm lost", "lost"),
    ("help", "lost"),
    ("email Sam that I'm at the Palace of Fine Arts", "browser"),
    ("yes send it", "confirm"),
    ("no cancel", "confirm"),
    ("is this the right item", "task"),
    # TODO: fill to 20 with the team's real demo phrasings
]


def test_keyword_router_accuracy():
    correct = sum(keyword_route(t) == want for t, want in LABELLED)
    assert correct >= len(LABELLED) - 2, [(t, keyword_route(t), w) for t, w in LABELLED if keyword_route(t) != w]


def test_safety_filter_blocks_banned_phrases():
    assert filter_reply("It is safe to cross now.") == FALLBACK
    assert filter_reply("The walk sign is on. A car is turning from your left.").startswith("The walk sign")
