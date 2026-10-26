"""The model call must never hold a request open longer than it is allowed.

The host this runs on caps a request at 60 seconds. A model that hangs would
otherwise be waited on three times over — the timeout, plus two retries —
which is longer than the whole request is allowed to take. These tests pin
the budget behaviour so that cannot regress.
"""

import time

import httpx
import pytest

from app.config import settings
from app.llm import provider as llm


class _Response:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload


def _provider(monkeypatch, handler, **kwargs):
    """An OpenAI-compatible provider whose transport is a test double."""
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return handler(len(calls))

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    monkeypatch.setattr(settings, "llm_timeout_seconds", 25)
    monkeypatch.setattr(settings, "llm_max_retries", 2)
    # The cache is shared between calls, and the prompts in these tests are
    # deliberately the same, so it has to be cleared for each one.
    llm._RESPONSE_CACHE.clear()
    monkeypatch.setattr(settings, "llm_cache_enabled", False)
    provider = llm.OpenAICompatibleProvider(
        "openrouter", "https://example.test/v1", "key", "openrouter/free"
    )
    return provider, calls


def test_a_deadline_in_the_past_makes_no_call(monkeypatch):
    provider, calls = _provider(monkeypatch, lambda n: _Response(payload={}))

    result = provider.chat("s", "u", task="score", deadline=time.monotonic() - 1)

    assert calls == []
    assert result.valid is False
    assert result.error


def test_the_timeout_given_to_the_transport_is_the_time_left(monkeypatch):
    """The request must not be allowed to run past the caller's deadline."""
    provider, calls = _provider(
        monkeypatch,
        lambda n: _Response(payload={"choices": [{"message": {"content": "ok"}}]}),
    )

    provider.chat("s", "u", task="score", deadline=time.monotonic() + 6)

    assert calls, "the transport was never called"
    assert calls[0]["timeout"] <= 6


def test_a_hanging_model_is_given_only_the_remaining_budget(monkeypatch):
    """A slow answer must not be waited on for longer than the budget."""

    def handler(n):
        raise httpx.ReadTimeout("too slow")

    provider, calls = _provider(monkeypatch, handler)

    started = time.monotonic()
    result = provider.chat("s", "u", task="score", deadline=time.monotonic() + 4)
    elapsed = time.monotonic() - started

    assert result.valid is False
    assert result.error
    # The whole call stays inside the budget. It used to be able to spend the
    # timeout three times over, which is longer than the request it was
    # running inside.
    assert elapsed < 7, f"the call took {elapsed:.1f}s against a 4s budget"
    # And no single attempt was handed more than the time that was left.
    for call in calls:
        assert call["timeout"] <= 4


def test_a_retry_is_skipped_when_there_is_no_time_left(monkeypatch):
    provider, calls = _provider(monkeypatch, lambda n: _Response(status_code=429, text="slow down"))

    provider.chat("s", "u", task="score", deadline=time.monotonic() + 0.7)

    # The attempt fails immediately. A retry needs a pause first, and there is
    # no room for the pause, so it is not made.
    assert len(calls) == 1


def test_a_fast_failure_is_retried_while_there_is_time(monkeypatch):
    def handler(n):
        if n == 1:
            return _Response(status_code=429, text="slow down")
        return _Response(payload={"choices": [{"message": {"content": "recovered"}}]})

    provider, calls = _provider(monkeypatch, handler)

    result = provider.chat("s", "u", task="score")

    assert len(calls) == 2
    assert result.text == "recovered"
    assert result.attempts == 2


def test_an_empty_answer_is_not_a_valid_answer(monkeypatch):
    """A model that says nothing has not answered, and the panel should say so."""
    provider, _ = _provider(
        monkeypatch,
        lambda n: _Response(
            payload={"model": "some/free-model", "choices": [{"message": {"content": ""}}]}
        ),
    )

    result = provider.chat("s", "u", task="score")

    assert result.valid is False
    assert result.text == ""
    assert "empty response" in result.error


def test_the_model_that_answered_is_the_one_recorded(monkeypatch):
    """A router may answer with a different model than the one asked for."""
    provider, _ = _provider(
        monkeypatch,
        lambda n: _Response(
            payload={
                "model": "vendor/actually-served:free",
                "choices": [{"message": {"content": "hello"}}],
            }
        ),
    )

    result = provider.chat("s", "u", task="score")

    assert result.model == "vendor/actually-served:free"


def test_a_model_that_ran_out_of_budget_says_so(monkeypatch):
    """A model cut off while reasoning has not answered, and the reason matters.

    The answer is not missing, it was never written: the model spent the
    whole output budget thinking. That is a different problem from a model
    that said nothing, and it is fixed by a bigger budget.
    """
    provider, _ = _provider(
        monkeypatch,
        lambda n: _Response(
            payload={
                "model": "vendor/reasoner:free",
                "choices": [{"finish_reason": "length", "message": {"content": ""}}],
            }
        ),
    )

    result = provider.chat("s", "u", task="score")

    assert result.valid is False
    assert "cut off" in result.error
    assert "output budget" in result.error


def test_an_empty_answer_is_not_cached(monkeypatch):
    """An empty entry in the cache would stop the tender being asked again."""
    monkeypatch.setattr(settings, "llm_cache_enabled", True)
    llm._RESPONSE_CACHE.clear()

    provider, calls = _provider(
        monkeypatch,
        lambda n: _Response(payload={"choices": [{"message": {"content": ""}}]}),
    )

    provider.chat("s", "u", task="score")
    provider.chat("s", "u", task="score")

    assert len(calls) == 2, "the second call was answered from an empty cache entry"
    assert "s" not in llm._RESPONSE_CACHE


def test_the_deterministic_provider_answers_within_the_budget(monkeypatch):
    """Both providers answer the same call, so both take the same argument."""
    monkeypatch.setattr(settings, "llm_provider", "mock")
    provider = llm.DeterministicProvider()

    result = provider.chat("s", "u", task="score", deadline=time.monotonic() + 5)

    assert result.simulated is True
    assert result.text
