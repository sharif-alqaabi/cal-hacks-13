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
