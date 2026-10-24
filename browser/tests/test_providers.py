"""OpenRouter routing for Claude and Jev, without network calls."""
import asyncio

import agents
import config
import llm

OPENROUTER_KEY = "sk-or-v1-test"


def test_openrouter_key_picks_openrouter(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    assert config._base_url("ANTHROPIC_BASE_URL", OPENROUTER_KEY, "https://api.anthropic.com") == "https://openrouter.ai/api"
    assert config._base_url("ANTHROPIC_BASE_URL", "sk-ant-x", "https://api.anthropic.com") == "https://api.anthropic.com"
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://example.test/")
    assert config._base_url("ANTHROPIC_BASE_URL", OPENROUTER_KEY, "https://api.anthropic.com") == "https://example.test"


def test_claude_model_ids(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_BASE_URL", "https://openrouter.ai/api")
    assert llm.model_id("claude-sonnet-5-5") == "anthropic/claude-sonnet-5.5"
    assert llm.model_id("claude-haiku-5-5") == "anthropic/claude-haiku-5.5"
    assert llm.model_id("~anthropic/claude-sonnet-latest") == "~anthropic/claude-sonnet-latest"
    monkeypatch.setattr(config, "ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    assert llm.model_id("claude-sonnet-5-5") == "claude-sonnet-5-5"


def test_no_upfront_thinking():
    assert llm.thinking("claude-sonnet-5-5") == {"thinking": {"type": "between_tools"}, "output_config": {"effort": "low"}}
    assert llm.thinking("claude-haiku-5-5") == {"thinking": {"type": "disabled"}}


def test_claude_request_through_openrouter(monkeypatch):
    sent = {}

    class Messages:
        async def create(self, **kw):
            sent.update(kw)

            class Block:
                type, text = "text", "It closes at 9 PM."
            return type("Msg", (), {"content": [type("Thinking", (), {"type": "thinking"})(), Block()]})()

    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", OPENROUTER_KEY)
    monkeypatch.setattr(config, "ANTHROPIC_BASE_URL", "https://openrouter.ai/api")
    monkeypatch.setattr(llm, "_client", type("C", (), {"messages": Messages()})())
    assert asyncio.run(llm.ask("sys", "q")) == "It closes at 9 PM."
    assert sent["model"] == "anthropic/claude-sonnet-5.5"
    assert sent["extra_body"]["thinking"] == {"type": "between_tools"}


def test_openrouter_client_uses_bearer_auth(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", OPENROUTER_KEY)
    monkeypatch.setattr(config, "ANTHROPIC_BASE_URL", "https://openrouter.ai/api")
    monkeypatch.setattr(llm, "_client", None)
    client = llm._anthropic()
    assert str(client.base_url).startswith("https://openrouter.ai/api")
    assert client.auth_headers == {"Authorization": f"Bearer {OPENROUTER_KEY}"}
    monkeypatch.setattr(llm, "_client", None)


def test_jev_calls_go_to_the_configured_endpoint(monkeypatch):
    from jev_ultrafast import model

    calls = []
    monkeypatch.setattr(model, "post_json", lambda url, key, body: calls.append(url) or {})
    monkeypatch.setattr(config, "TYPESAFE_BASE_URL", "https://openrouter.ai/api")
    agents.route_jev()
    model.post_json(agents.TYPESAFE_URL, OPENROUTER_KEY, {})
    model.post_json("https://openrouter.ai/api/v1/chat/completions", OPENROUTER_KEY, {})
    assert calls == ["https://openrouter.ai/api/v1/systemone", "https://openrouter.ai/api/v1/chat/completions"]
    agents.route_jev()   # idempotent: wrapping twice would still give one rewrite
    assert getattr(model.post_json, "routed", False)


def test_direct_typesafe_url_is_unchanged(monkeypatch):
    from jev_ultrafast import model

    calls = []
    monkeypatch.setattr(model, "post_json", lambda url, key, body: calls.append(url) or {})
    monkeypatch.setattr(config, "TYPESAFE_BASE_URL", "https://api.typesafe.ai")
    agents.route_jev()
    model.post_json(agents.TYPESAFE_URL, "ts-key", {})
    assert calls == [agents.TYPESAFE_URL]
