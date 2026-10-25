"""The service end to end over HTTP, on the fake Gmail. Response shapes are checked against core's own models."""
import sys

import pytest
from fastapi.testclient import TestClient

import app as service
import config
import fake_agent
import goals
import guard
import runner
import tracelog

sys.path.insert(0, str(config.HERE.parent / "core"))
from contracts.browser import SayResp as CoreSayResp  # noqa: E402
from contracts.browser import TaskResp as CoreTaskResp  # noqa: E402

EMAIL = "Email Sam that I'm at the Palace of Fine Arts"


@pytest.fixture
def client():
    with TestClient(service.app) as c:
        yield c


def task(client, goal=EMAIL):
    r = client.post("/task", json={"goal": goal})
    assert r.status_code == 200
    return CoreTaskResp.model_validate(r.json())


def confirm(client, task_id, yes):
    r = client.post("/confirm", json={"task_id": task_id, "yes": yes})
    assert r.status_code == 200
    return CoreSayResp.model_validate(r.json()).say


def test_health(client):
    r = client.get("/health").json()
    assert r["ok"] and r["fake"] and r["contacts"] == ["sam"]


def test_email_reads_back_and_sends_nothing(client):
    r = task(client)
    assert r.needs_confirm
    assert r.say == ("Draft to Sam, subject: I'm at the Palace of Fine Arts. "
                     "It says: I'm at the Palace of Fine Arts. Say send, or cancel.")
    assert fake_agent.SENT == []
    assert [e["event"] for e in guard.read_log()] == ["blocked"]


def test_yes_sends_once_and_verifies_in_sent(client):
    r = task(client)
    assert confirm(client, r.task_id, True) == "Sent to Sam. I checked your Sent folder."
    assert len(fake_agent.SENT) == 1 and fake_agent.VIOLATIONS == []
    assert fake_agent.SENT[0]["to"] == "sam.calhacks.demo@gmail.com"
    assert [e["event"] for e in guard.read_log()] == ["blocked", "confirm", "sent", "verified"]


def test_cancel_sends_nothing(client, monkeypatch):
    monkeypatch.setattr(config, "VERIFY_CANCEL", True)
    confirm(client, task(client, "email Sam that an earlier note").task_id, True)   # Sent must have rows to check
    r = task(client)
    assert confirm(client, r.task_id, False) == runner.CANCELLED
    assert len(fake_agent.SENT) == 1
    assert guard.read_log()[-1]["event"] == "cancel_verified"


def test_blocked_after_steps_names_the_last_step():
    agent = fake_agent.FakeAgent("https://mail.google.com/mail/u/0/?view=cm&fs=1&tf=1", "x")
    agent.state["history"] = [{"action": "Subject", "kind": "fill"}, {"action": "Wait", "kind": "wait"}]
    say = runner.explain(runner.Outcome("blocked"), agent, "Gmail", email=True)
    assert say == "I got stuck on Gmail after I type in Subject. Nothing was sent."


def test_unknown_task_id(client):
    assert confirm(client, "nope", True) == runner.EXPIRED


def test_a_new_task_replaces_the_pending_draft(client):
    first = task(client)
    task(client)
    assert confirm(client, first.task_id, True) == runner.EXPIRED
    assert fake_agent.SENT == []


def test_agent_saying_done_still_needs_confirmation(client, monkeypatch):
    monkeypatch.setenv("FAKE_SCRIPT", "done")
    r = task(client)
    assert r.needs_confirm and fake_agent.SENT == []


def test_signed_out_is_spoken(client, monkeypatch):
    monkeypatch.setenv("FAKE_SCRIPT", "signed_out")
    r = task(client)
    assert (r.say, r.needs_confirm) == ("The laptop isn't signed in to email. Nothing was sent.", False)
    assert fake_agent.SENT == []


@pytest.mark.parametrize("script", ["blocked", "wrong_to", "stuck"])
def test_agent_failure_falls_back_to_a_prefilled_draft(client, monkeypatch, script):
    monkeypatch.setenv("FAKE_SCRIPT", script)
    r = task(client)
    assert r.needs_confirm and r.say.startswith("Draft to Sam, subject: I'm at the Palace of Fine Arts.")
    assert "fail" in [e["kind"] for e in tracelog.since(0)]   # the trace says the agent stopped
    assert fake_agent.SENT == []
    assert confirm(client, r.task_id, True) == "Sent to Sam. I checked your Sent folder."
    assert fake_agent.SENT[0]["to"] == "sam.calhacks.demo@gmail.com"


def test_wrong_draft_after_fallback_is_refused(client, monkeypatch):
    monkeypatch.setenv("FAKE_SCRIPT", "wrong_to")
    monkeypatch.setattr(runner, "PREFILL_WAIT_S", 0.2)
    monkeypatch.setattr(runner.gmail, "compose_url", lambda plan=None: "https://mail.google.com/mail/u/0/?view=cm&fs=1&tf=1")
    r = task(client)
    assert (r.say, r.needs_confirm) == ("The draft isn't addressed to Sam, so I won't send it. Please ask me again.", False)
    assert fake_agent.SENT == []


@pytest.mark.parametrize("error,say", [
    ("RuntimeError: Model connection failed; no action executed.", "The browser agent's model isn't responding."),
    ("ValueError: TYPE_TEXT needs TEXT_MODEL_API_KEY; nothing typed.", "The browser agent can't type without its text model key."),
    ("KeyError: 'TYPESAFE_API_KEY'", runner.NO_KEYS),
    ("ValueError: Stopped at the 60-action demo budget", "That took too many steps."),
    ("ValueError: Reached the demo's model-call budget", "That took too many steps."),
    ("OSError: weird", runner.BROKE),
])
def test_agent_errors_become_sentences(error, say):
    assert runner.explain(runner.Outcome("error", error=error), None, "Gmail", email=True) == say + " Nothing was sent."


def test_chrome_down_is_spoken(client, monkeypatch):
    monkeypatch.setattr(runner.agents, "chrome_ready", lambda: False)
    assert task(client).say == runner.CHROME_DOWN


@pytest.mark.parametrize("goal,say", [
    ("email Bob that hi", "I don't have an email address for Bob."),
    ("email Sam", "What should the email to Sam say?"),
    ("buy me a coffee", "I can't buy or pay for things. I can send an email or look something up."),
])
def test_requests_it_wont_run(client, goal, say):
    r = task(client, goal)
    assert (r.say, r.needs_confirm) == (say, False)


def test_lookup_answers_without_confirm(client):
    r = task(client, "when does the hardware store close today?")
    assert (r.say, r.needs_confirm) == ("It's open now and closes at 9 PM.", False)


def test_lookup_without_an_answer_reads_the_results(client):
    r = task(client, "look up the weather in Berkeley")
    assert r.say.startswith("I couldn't find a direct answer. Here are the top results. One: Ace Hardware Polk St.")
    assert not r.needs_confirm


def test_lookup_without_an_answer_says_what_it_searched(client, monkeypatch):
    monkeypatch.setattr(fake_agent, "RESULTS", [])
    r = task(client, "look up the weather in Berkeley")
    assert (r.say, r.needs_confirm) == ("I couldn't find the answer. I searched Google for the weather in Berkeley.", False)
    kinds = [e["kind"] for e in client.get("/trace/latest").json() if e["task_id"] == r.task_id]
    assert "predict" in kinds and kinds[-1] == "fail"


def test_zero_unconfirmed_sends_across_runs(client):
    yes_count = 0
    for i in range(10):
        r = task(client, f"email Sam that test run {i}")
        assert r.needs_confirm and len(fake_agent.SENT) == yes_count
        yes = i % 2 == 0
        confirm(client, r.task_id, yes)
        yes_count += yes
    assert len(fake_agent.SENT) == yes_count == 5
    assert fake_agent.VIOLATIONS == []


def test_trace_shows_each_step(client):
    r = task(client)
    events = client.get("/trace/latest").json()
    kinds = [e["kind"] for e in events if e["task_id"] == r.task_id]
    assert kinds[:2] == ["goal", "plan"] and "guard" in kinds and kinds[-1] == "readback"
    assert kinds.count("act") == 3
    assert client.get("/trace").status_code == 200


def test_work_without_claude(client):
    r = client.post("/work", json={"utterance": "is this right for order 12", "jpeg_b64": "AAAA"})
    assert CoreSayResp.model_validate(r.json()).say == "Work mode needs the Claude key."


async def _spotify_web_plan(_goal):
    return goals.WebPlan(
        url="https://open.spotify.com/search/bohemian%20rhapsody",
        goal="Play the first song result. Never post, buy, pay, sign in or delete anything.",
        site="Spotify",
    )


def test_web_planner_task(client, monkeypatch):
    monkeypatch.setattr(runner.goals, "parse", _spotify_web_plan)
    r = task(client, "open Spotify and play Bohemian Rhapsody")
    assert r.say.startswith("Done on Spotify.")
    assert not r.needs_confirm
