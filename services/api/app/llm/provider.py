import hashlib
import json
import re
import time

import httpx

from app.config import settings
from app.llm import simulator
from app.models import AIMetric

RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}

# In-process response cache. Keyed by provider+model+task+prompt so repeated
# analysis of the same document does not re-pay for the same answer.
_RESPONSE_CACHE = {}
_CACHE_MAX_ENTRIES = 200


class LLMResult:
    def __init__(
        self,
        text="",
        provider="mock",
        model="",
        tokens=0,
        latency_ms=0,
        valid=True,
        error="",
        attempts=0,
        cached=False,
        simulated=False,
        schema_valid=True,
    ):
        self.text = text
        self.provider = provider
        self.model = model
        self.tokens = tokens
        self.latency_ms = latency_ms
        self.valid = valid
        self.error = error
        self.attempts = attempts
        self.cached = cached
        self.simulated = simulated
        self.schema_valid = schema_valid

    def __repr__(self):
        return (
            f"LLMResult(provider={self.provider!r}, model={self.model!r}, "
            f"valid={self.valid}, error={self.error!r}, tokens={self.tokens})"
        )


def _cache_key(provider, model, task, system, user, max_tokens):
    digest = hashlib.sha256()
    for part in (provider, model, task, system, user, str(max_tokens)):
        digest.update((part or "").encode("utf-8", errors="ignore"))
        digest.update(b"\x00")
    return digest.hexdigest()


class OpenAICompatibleProvider:
    """Provider for any OpenAI-compatible ``/chat/completions`` endpoint.

    Covers OpenRouter and OpenAI with one implementation. Adds the things a
    production bid system actually needs: bounded retries with backoff,
    per-call timeouts, a response cache, and a stable error taxonomy so
    failures are visible in the AI-quality metrics instead of vanishing.
    """

    def __init__(self, provider_name: str, base_url: str, api_key: str, model: str):
        self.name = provider_name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.enabled = bool(api_key and model)

    def chat(self, system: str, user: str, max_tokens: int = 1200, task: str = "") -> LLMResult:
        started = time.time()
        if not self.enabled:
            return LLMResult(
                provider=self.name,
                model=self.model,
                valid=False,
                error="provider not configured (missing API key or model)",
                attempts=0,
            )

        key = _cache_key(self.name, self.model, task, system, user, max_tokens)
        if settings.llm_cache_enabled and key in _RESPONSE_CACHE:
            cached = _RESPONSE_CACHE[key]
            return LLMResult(
                text=cached["text"],
                provider=self.name,
                model=self.model,
                tokens=0,
                latency_ms=int((time.time() - started) * 1000),
                cached=True,
                attempts=1,
            )

        attempts = 0
        last_error = ""
        for attempt in range(1, settings.llm_max_retries + 2):
            attempts = attempt
            try:
                resp = httpx.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "max_tokens": max_tokens,
                        "temperature": settings.llm_temperature,
                    },
                    timeout=settings.llm_timeout_seconds,
                )
                if resp.status_code >= 400:
                    last_error = f"http {resp.status_code}: {resp.text[:200]}"
                    if resp.status_code in RETRYABLE_STATUS and attempt <= settings.llm_max_retries:
                        time.sleep(min(8.0, 0.75 * (2 ** (attempt - 1))))
                        continue
                    return LLMResult(
                        provider=self.name,
                        model=self.model,
                        valid=False,
                        error=last_error,
                        attempts=attempts,
                        latency_ms=int((time.time() - started) * 1000),
                    )

                data = resp.json()
                text = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                tokens = int(usage.get("total_tokens", 0))
                if settings.llm_cache_enabled:
                    if len(_RESPONSE_CACHE) >= _CACHE_MAX_ENTRIES:
                        _RESPONSE_CACHE.clear()
                    _RESPONSE_CACHE[key] = {"text": text, "tokens": tokens}
                return LLMResult(
                    text=text,
                    provider=self.name,
                    model=self.model,
                    tokens=tokens,
                    latency_ms=int((time.time() - started) * 1000),
                    attempts=attempts,
                )
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt <= settings.llm_max_retries:
                    time.sleep(min(8.0, 0.75 * (2 ** (attempt - 1))))
                    continue
                return LLMResult(
                    text="",
                    provider=self.name,
                    model=self.model,
                    valid=False,
                    error=last_error,
                    attempts=attempts,
                    latency_ms=int((time.time() - started) * 1000),
                )

        return LLMResult(
            provider=self.name,
            model=self.model,
            valid=False,
            error=last_error or "unknown error",
            attempts=attempts,
            latency_ms=int((time.time() - started) * 1000),
        )


class DeterministicProvider:
    """Offline engine that performs the same tasks as the LLM, deterministically.

    It is enabled by default so the whole pipeline — scoring rationale,
    requirement extraction, risk flags and proposal drafting — runs and is
    measured with no API key. Output is flagged ``simulated=True`` in the
    metrics so it is never mistaken for model behaviour.
    """

    def __init__(self):
        self.name = "mock"
        self.model = "deterministic-v1"
        self.enabled = True

    def chat(self, system: str, user: str, max_tokens: int = 1200, task: str = "") -> LLMResult:
        started = time.time()
        text = simulator.simulate(task, system, user)
        if not text:
            return LLMResult(
                provider=self.name,
                model=self.model,
                valid=False,
                error=f"no deterministic output for task={task or 'unknown'}",
                attempts=1,
                simulated=True,
                latency_ms=int((time.time() - started) * 1000),
            )
        return LLMResult(
            text=text,
            provider=self.name,
            model=self.model,
            tokens=simulator.simulated_tokens(text),
            latency_ms=simulator.simulated_latency_ms(user),
            attempts=1,
            simulated=True,
        )


_PROVIDER_CACHE = {}


def get_provider():
    """Return the configured provider. Instances are cached per configuration."""
    if settings.llm_provider == "openrouter":
        key = "openrouter"
        if key not in _PROVIDER_CACHE:
            _PROVIDER_CACHE[key] = OpenAICompatibleProvider(
                "openrouter",
                settings.openrouter_base_url,
                settings.openrouter_api_key,
                settings.llm_model or "openrouter/auto",
            )
        return _PROVIDER_CACHE[key]
    if settings.llm_provider == "openai":
        key = "openai"
        if key not in _PROVIDER_CACHE:
            _PROVIDER_CACHE[key] = OpenAICompatibleProvider(
                "openai",
                settings.openai_base_url,
                settings.openai_api_key,
                settings.llm_model or "gpt-4o-mini",
            )
        return _PROVIDER_CACHE[key]
    if "mock" not in _PROVIDER_CACHE:
        _PROVIDER_CACHE["mock"] = DeterministicProvider()
    return _PROVIDER_CACHE["mock"]


def provider_status() -> dict:
    """Human-readable provider state for the UI and the health endpoint."""
    provider = get_provider()
    return {
        "provider": provider.name,
        "model": provider.model,
        "enabled": provider.enabled,
        "simulated": getattr(provider, "name", "") == "mock",
        "cache_enabled": settings.llm_cache_enabled,
        "timeout_seconds": settings.llm_timeout_seconds,
        "max_retries": settings.llm_max_retries,
        "temperature": settings.llm_temperature,
    }


def record_metric(db, task, result: LLMResult, opportunity_id=None, output_valid=True):
    """Persist one AI call. Called for successes *and* failures.

    A failure that is not recorded is a failure that looks like it never
    happened, so this is always called.
    """
    db.add(
        AIMetric(
            task=task,
            provider=result.provider,
            model=result.model,
            tokens_estimate=result.tokens,
            latency_ms=result.latency_ms,
            output_valid=bool(output_valid and result.valid),
            simulated=bool(result.simulated),
            cached=bool(result.cached),
            error=(result.error or "")[:200],
            attempts=result.attempts or 1,
            opportunity_id=opportunity_id,
        )
    )
    db.commit()


def parse_json_block(text: str):
    """Extract the first JSON object from a model response.

    Tolerates markdown fences and leading/trailing prose, and rejects payloads
    that are not valid JSON rather than guessing.
    """
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(cleaned[start : end + 1])
    except Exception:
        return None
