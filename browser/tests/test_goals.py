import asyncio

import pytest

import goals


@pytest.mark.parametrize("text,name,message", [
    ("email Sam that I'm at the Palace of Fine Arts", "Sam", "I'm at the Palace of Fine Arts."),
    ("Email Sam that I'm at the Palace of Fine Arts.", "Sam", "I'm at the Palace of Fine Arts."),
    ("Send an email to Sam saying I'm running late", "Sam", "I'm running late."),
    ("can you email sam I'm running late", "Sam", "I'm running late."),
    ("please send a message to Sam: dinner is at 7", "Sam", "Dinner is at 7."),
    ("tell Sam by email that the meeting moved", "Sam", "The meeting moved."),
])
def test_email_rules(text, name, message):
    p = goals.parse_regex(text)
    assert isinstance(p, goals.EmailPlan)
    assert (p.to_name, p.message, p.to_addr) == (name, message, "sam.calhacks.demo@gmail.com")
    assert p.subject and len(p.subject.split()) <= 10


def test_subject_from_message():
    assert goals.parse_regex("email Sam that I am at the Palace of Fine Arts").subject == "I am at the Palace of Fine Arts"
    long = goals.parse_regex("email Sam that the train is delayed so I will be about twenty minutes late tonight")
    assert long.subject == "The train is delayed so I will ..."


def test_unknown_contact_has_no_address():
    p = goals.parse_regex("email Bob that hi")
    assert isinstance(p, goals.EmailPlan) and p.to_name == "Bob" and p.to_addr is None


def test_email_without_message():
    p = goals.parse_regex("email Sam")
    assert isinstance(p, goals.EmailPlan) and p.message == ""


@pytest.mark.parametrize("text,query", [
    ("when does the hardware store close today?", "when does the hardware store close today"),
    ("look up the weather in Berkeley", "the weather in Berkeley"),
    ("can you search for Ace Hardware hours", "Ace Hardware hours"),
])
def test_lookup_rules(text, query):
    p = goals.parse_regex(text)
    assert isinstance(p, goals.LookupPlan) and p.query == query


@pytest.mark.parametrize("text,say", [
    ("buy me a coffee", goals.NO_MONEY),
    ("order a pizza", goals.NO_MONEY),
    ("turn up the volume", goals.NOT_SUPPORTED),
])
def test_unsupported(text, say):
    p = goals.parse_regex(text)
    assert isinstance(p, goals.Unsupported) and p.say == say


def test_parse_without_claude_uses_rules():
    p = asyncio.run(goals.parse("email Sam that I'm at the Palace of Fine Arts"))
    assert isinstance(p, goals.EmailPlan) and p.to_addr == "sam.calhacks.demo@gmail.com"


def test_contacts_parsing(monkeypatch):
    import config
    monkeypatch.setattr(config, "DEMO_CONTACTS", "Sam=a@x.com, Mom = m@x.com")
    assert goals.contacts() == {"sam": "a@x.com", "mom": "m@x.com"}
    assert goals.resolve("mom") == "m@x.com" and goals.resolve("b@y.com") == "b@y.com"


# ---- loose wording: Claude's JSON maps onto the same plans the rules make --------

import inbox  # noqa: E402
import youtube  # noqa: E402
from sites import NavPlan, SitePlan, TabPlan  # noqa: E402


@pytest.mark.parametrize("j,plan", [
    ({"kind": "youtube", "action": "play", "query": "lofi beats"}, youtube.YouTubePlan("play", query="lofi beats")),
    ({"kind": "youtube", "action": "pause"}, youtube.YouTubePlan("pause")),
    ({"kind": "youtube", "action": "", "query": "cooking"}, youtube.YouTubePlan("search", query="cooking")),
    ({"kind": "youtube"}, youtube.YouTubePlan("open")),
    ({"kind": "pick", "pick": 2}, youtube.YouTubePlan("pick", pick=2)),
    ({"kind": "inbox", "action": "list"}, inbox.InboxPlan("list")),
    ({"kind": "inbox", "action": "read", "sender": "Sam"}, inbox.InboxPlan("read", sender="Sam")),
    ({"kind": "inbox", "action": "read", "pick": "3"}, inbox.InboxPlan("read", pick=3)),
    ({"kind": "inbox", "action": "read"}, inbox.InboxPlan("list")),
    ({"kind": "site", "site": "instagram"}, SitePlan("https://www.instagram.com/", "Instagram")),
    ({"kind": "site", "site": "nytimes.com"}, SitePlan("https://nytimes.com", "The New York Times")),
    ({"kind": "site", "site": "the exploratorium"}, SitePlan("", "Exploratorium")),
    ({"kind": "new_tab", "site": "reddit"}, TabPlan("new", SitePlan("https://www.reddit.com/", "Reddit"))),
    ({"kind": "new_tab"}, TabPlan("new")),
    ({"kind": "close_tab"}, TabPlan("close")),
    ({"kind": "back"}, NavPlan("back")),
    ({"kind": "search", "query": "tacos near me"}, goals.LookupPlan("tacos near me", listing=True)),
    ({"kind": "lookup", "query": "ace hardware hours"}, goals.LookupPlan("ace hardware hours")),
])
def test_claude_json_to_plan(j, plan):
    assert goals.from_claude("whatever was said", j) == plan


def test_claude_email_resolves_contact():
    p = goals.from_claude("let sam know I'm outside", {"kind": "email", "to_name": "sam", "message": "I'm outside"})
    assert isinstance(p, goals.EmailPlan) and p.to_addr == "sam.calhacks.demo@gmail.com" and p.message == "I'm outside."


@pytest.mark.parametrize("j", [{}, {"kind": "nonsense"}, {"kind": "lookup"}, {"kind": "pick", "pick": 7},
                               {"kind": "site", "site": ""}, {"kind": "email"}])
def test_unusable_claude_json_falls_back_to_rules(j):
    assert goals.from_claude("whatever", j) is None


def test_inbox_refusal_survives_claude():
    p = goals.from_claude("get rid of all the spam", {"kind": "inbox", "action": "list"})
    assert p == goals.Unsupported(inbox.REFUSE)
    p = goals.from_claude("anything new from Mark?", {"kind": "inbox", "action": "read", "sender": "Mark"})
    assert p == inbox.InboxPlan("read", sender="Mark")


def test_loose_wording_goes_through_claude(monkeypatch):
    import config
    import llm
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "x")
    seen = []

    async def fake_json(system, content, **kw):
        seen.append(content)
        return {"kind": "youtube", "action": "play", "query": "lofi hip hop"}
    monkeypatch.setattr(llm, "ask_json", fake_json)
    p = asyncio.run(goals.parse("I kinda want some lofi on in the background"))
    assert p == youtube.YouTubePlan("play", query="lofi hip hop") and seen
    seen.clear()   # exact phrases still skip Claude
    assert asyncio.run(goals.parse("pause")) == youtube.YouTubePlan("pause") and not seen


def test_claude_down_still_uses_rules(monkeypatch):
    import config
    import llm
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "x")

    async def down(*a, **kw):
        return None
    monkeypatch.setattr(llm, "ask_json", down)
    p = asyncio.run(goals.parse("email Sam that I'm at the Palace of Fine Arts"))
    assert isinstance(p, goals.EmailPlan)
