import time

import pytest

import fake_agent
import gmail
import goals
import guard
import runner

PLAN = goals.EmailPlan("Sam", "I'm at the Palace of Fine Arts.", "I'm at the Palace of Fine Arts",
                       "sam.calhacks.demo@gmail.com")


@pytest.mark.parametrize("label", ["Send \u202a(⌘Enter)\u202c", "Send", "send now", "Submit", "Delete", "Discard draft",
                                   "Place order", "Buy now", "Pay $12.00", "Move to Trash", "Confirm purchase"])
def test_send_like_clicks_are_irreversible(label):
    assert guard.is_irreversible({"kind": "click", "label": label})


@pytest.mark.parametrize("action", [
    {"kind": "click", "label": "Subject"}, {"kind": "click", "label": "Open To recipients"},
    {"kind": "click", "label": "Sent"}, {"kind": "click", "label": "Google Search"},
    {"kind": "click", "label": "Ace Hardware Polk St - Hours"}, {"kind": "fill", "label": "Send to"},
    {"kind": "scroll", "label": "Scroll down"}, {"kind": "wait", "label": "Wait"}, None,
])
def test_ordinary_actions_pass(action):
    assert not guard.is_irreversible(action)


def test_drive_parks_before_send_and_logs_it():
    agent = fake_agent.FakeAgent(gmail.compose_url(), gmail.goal(PLAN))
    out = runner.drive(agent, "t1", time.monotonic() + 5)
    assert out.kind == "parked" and out.action["label"].startswith("Send")
    assert fake_agent.SENT == []
    assert [h["action"] for h in agent.state["history"]] == ["To recipients", "Subject", "Message Body"]
    assert [e["event"] for e in guard.read_log()] == ["blocked"]


def test_dom_layer_swallows_an_unguarded_send_click():
    agent = fake_agent.FakeAgent(gmail.compose_url(PLAN), gmail.goal(PLAN))
    guard.install(agent.browser)
    page = agent.browser.observe()
    agent.browser.act(gmail.find_send(page), page)
    assert fake_agent.SENT == [] and agent.browser.dom_blocked == 1


def test_click_send_opens_the_guard_for_exactly_one_click():
    agent = fake_agent.FakeAgent(gmail.compose_url(PLAN), gmail.goal(PLAN))
    guard.install(agent.browser)
    gmail.click_send(agent.browser)
    assert len(fake_agent.SENT) == 1 and fake_agent.VIOLATIONS == []
    assert agent.browser.guard_open is False


def test_fake_detects_a_send_with_no_guard_at_all():
    """Sanity check of the test double: without either layer, a send is recorded as a violation."""
    agent = fake_agent.FakeAgent(gmail.compose_url(PLAN), gmail.goal(PLAN))
    page = agent.browser.observe()
    agent.browser.act(gmail.find_send(page), page)
    assert len(fake_agent.VIOLATIONS) == 1
