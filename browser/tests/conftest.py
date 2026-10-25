"""Every test runs on the fake agent: no Chrome, no keys, no network."""
import pytest

import config
import fake_agent
import runner
import tracelog
import work


@pytest.fixture(autouse=True)
def fake_env(monkeypatch, tmp_path):
    for name, value in {
        "FAKE": True, "ANTHROPIC_API_KEY": "", "TYPESAFE_API_KEY": "", "GMAIL_PREFILL": False,
        "VERIFY_CANCEL": False, "DEMO_CONTACTS": "Sam=sam.calhacks.demo@gmail.com", "UNDO_SEND_S": 0,
        "SENT_POLL_S": 1, "TASK_BUDGET_S": 3, "LOG_DIR": tmp_path,
    }.items():
        monkeypatch.setattr(config, name, value)
    monkeypatch.delenv("FAKE_SCRIPT", raising=False)
    fake_agent.reset()
    tracelog.clear()
    work.reset()
    runner.store.pending.clear()
    runner.store.current = None
    yield
