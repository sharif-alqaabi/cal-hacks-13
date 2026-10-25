"""The Claude Haiku fallback agent, on the fake browser with a scripted fake model."""
import asyncio
import copy

import pytest

import claude_agent
import config
import fake_agent
import gmail
import goals
import guard
import runner
import tracelog


class Script:
    """Fake model: returns the scripted tool calls in order and records what it was shown."""

    def __init__(self, *calls):
        self.calls = list(calls)
        self.seen = []

    def __call__(self, system, tools, messages, timeout):
        self.seen.append(copy.deepcopy(messages))
        name, args = self.calls.pop(0)
        return {"id": f"toolu_{len(self.seen)}", "name": name, "input": args}


@pytest.fixture
def model(monkeypatch):
    monkeypatch.setattr(config, "AGENT_FALLBACK", True)

    def use(*calls):
        s = Script(*calls)
        monkeypatch.setattr(claude_agent, "MODEL", s)
        return s
    yield use


def run(goal):
    return asyncio.run(runner.run_task(goal))


def test_off_without_model_or_key():
    assert not claude_agent.enabled()
    assert run("click the first link on the page")["say"] == goals.NOT_SUPPORTED


def test_unmatched_request_goes_to_the_agent(model):
    m = model(("type", {"id": "e1", "text": "ace hardware", "enter": True}),
              ("click", {"id": "e2"}),
              ("done", {"say": "Ace Hardware on Polk St is open until 9 PM."}))
    run("look up ace hardware hours")   # a lookup: never reaches the agent
    assert m.seen == []
    r = run("click the first link on the page")
    assert r["say"] == "Ace Hardware on Polk St is open until 9 PM."
    assert not r["needs_confirm"]
    first = m.seen[0][0]["content"]
    assert first.startswith("Request: click the first link on the page") and "e2 link" in first
    # only the latest page is kept: the first message is trimmed once a step has run
    assert m.seen[-1][0]["content"] == "Request: click the first link on the page"
    kinds = [e["kind"] for e in tracelog.since(0)]
    assert "predict" in kinds and "act" in kinds


def test_known_goals_still_skip_the_agent(model):
    m = model()
    for goal in ("open youtube", "pause", "go to reddit", "email Sam that I'm late", "buy me a laptop"):
        run(goal)
    assert m.seen == []


def test_send_is_never_pressed(model):
    agent = fake_agent.FakeAgent(gmail.compose_url(goals.EmailPlan("Sam", "Hi.", "Hi", "sam.calhacks.demo@gmail.com")),
                                 "x")
    runner.store.adopt(agent)
    m = model(("click", {"id": "e4"}), ("done", {"say": "Sent!"}))
    r = run("hit the button that says send on this page")
    assert r["say"].startswith("I stopped before pressing Send")
    assert fake_agent.SENT == [] and len(m.calls) == 1
    assert any(e["event"] == "blocked" for e in guard.read_log())


def test_step_cap(model, monkeypatch):
    monkeypatch.setattr(config, "AGENT_MAX_STEPS", 3)
    model(*[("scroll", {"direction": "down"})] * 5)
    assert run("click the first link on the page")["say"].startswith("That took too many steps")


def test_bad_id_is_reported_back(model):
    m = model(("click", {"id": "e99"}), ("done", {"say": "ok"}))
    assert run("click the first link on the page")["say"] == "ok"
    last = m.seen[-1][-1]["content"][0]["content"][0]["text"]
    assert "No element 'e99'" in last


def test_enter_only_in_search_fields():
    b = fake_agent.FakeBrowser(gmail.compose_url(goals.EmailPlan("Sam", "Hi.", "Hi", "sam.calhacks.demo@gmail.com")))
    page = b.observe(screenshot=False)
    out = claude_agent.act(b, page, "type", {"id": "e3", "text": "hello", "enter": True}, "t")
    assert "wasn't pressed" in out


def test_render_is_compact():
    page = {"url": "https://x.test/", "title": "X", "text": "a\n" * 5000,
            "actions": [{"id": f"e{i}", "kind": "click", "role": "link", "label": "L" * 300} for i in range(1, 300)]}
    text = claude_agent.render(page)
    assert len(text) < 12000 and "more elements below" in text
