from __future__ import annotations

import json

from nightshift.extract import Extractor
from nightshift.llm import CircuitBreaker, LLMError, select_backend
from nightshift.models import Item


class FailingBackend:
    name = "fake"

    def __init__(self):
        self.calls = 0

    def complete(self, prompt: str) -> str:
        self.calls += 1
        raise LLMError("boom")


class GoodBackend:
    name = "fake-good"

    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    def complete(self, prompt: str) -> str:
        self.calls += 1
        return self.reply


def _item(i=0):
    return Item(id=f"id{i}", source="t", title="t", transcript="I use Claude and n8n every day.")


def test_breaker_opens_after_threshold():
    b = CircuitBreaker(5)
    for _ in range(4):
        b.record_failure()
    assert b.allow()
    b.record_failure()
    assert not b.allow() and b.is_open


def test_breaker_success_resets_counter():
    b = CircuitBreaker(3)
    b.record_failure()
    b.record_failure()
    b.record_success()
    b.record_failure()
    b.record_failure()
    assert b.allow()


def test_extractor_stops_calling_after_five_failures():
    backend = FailingBackend()
    ex = Extractor(backend, CircuitBreaker(5))
    for i in range(12):
        data, used = ex.extract(_item(i))
        assert used == "regex"
        assert {t["name"] for t in data["tools"]} == {"Claude", "n8n"}
    assert backend.calls == 5
    assert ex.breaker.is_open


def test_unparseable_reply_counts_as_failure():
    backend = GoodBackend("I cannot answer that")
    ex = Extractor(backend, CircuitBreaker(2))
    for i in range(4):
        ex.extract(_item(i))
    assert backend.calls == 2


def test_llm_result_merged_with_regex_tools():
    reply = json.dumps({"summary": "S", "tools": [{"name": "Claude", "category": "llm"}],
                        "ideas": [], "prompts": [], "techniques": []})
    ex = Extractor(GoodBackend(reply))
    data, used = ex.extract(_item())
    assert used == "fake-good"
    assert data["summary"] == "S"
    assert {t["name"] for t in data["tools"]} == {"Claude", "n8n"}


def test_select_backend_regex_without_cli_or_key():
    assert select_backend({"backend": "auto"}) is None
    assert select_backend({"backend": "regex"}) is None
    assert select_backend({"backend": "anthropic-api"}) is None


def test_select_backend_api_from_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-placeholder")
    b = select_backend({"backend": "auto", "api_model": "claude-sonnet-5"})
    assert b is not None and b.name == "anthropic-api" and b.model == "claude-sonnet-5"
    assert "test-placeholder" not in repr(vars(b).get("model"))
