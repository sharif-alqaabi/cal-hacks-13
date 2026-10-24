"""Shared fixtures: every external API faked, memory/browser stubs mounted in-process."""
import pytest

from tests import fakes


@pytest.fixture
def fake(monkeypatch, tmp_path):
    from app import config
    from tests.stubs import browser_stub, memory_stub

    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    memory_stub.state.update(fail=False, log=[])
    browser_stub.state.update(log=[])
    f = fakes.install(monkeypatch.setattr)
    fakes.install_stubs(monkeypatch.setattr)
    return f


@pytest.fixture
def client(fake):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
