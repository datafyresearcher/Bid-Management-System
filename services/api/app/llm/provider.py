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

    @staticmethod
    def _read_text(data) -> str:
        """The text of a response, whatever shape the provider answered in.

        A model that has nothing to say sometimes answers with an empty body
        or a null content, and a provider that routes to an unusual model can
        answer with a different shape altogether. None of that is worth
        failing the whole call over — an empty answer is an empty answer, and
        the caller falls back to the deterministic output.
        """
        try:
            choices = data.get("choices") or []
            if not choices:
                return ""
            message = choices[0].get("message") or {}
            content = message.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                # Some providers answer with a list of content blocks.
                parts = []
                for block in content:
                    if isinstance(block, dict):
                        parts.append(str(block.get("text") or ""))
                    elif isinstance(block, str):
                        parts.append(block)
                return "".join(parts)
            return ""
        except Exception:
            return ""

    def chat(
        self,
        system: str,
        user: str,
        max_tokens: int = 1200,
        task: str = "",
        deadline: float | None = None,
    ) -> LLMResult:
        """Call the model, inside a time budget.

        ``deadline`` is an absolute ``time.monotonic()`` value. When it is
        given, the call is cut short at that point: the per-attempt timeout is
        shortened to whatever time is left, and a retry is only made if there
        is still room for it.

        This matters more than it looks. The host this runs on caps a request
        at 60 seconds, and a model that hangs would otherwise be waited on
        three times over — 25 seconds a try, plus the pauses between tries —
        before the request itself gave out. A tender that cannot be narrated
        is still worth scoring: the score is deterministic, so the request
        falls back to the deterministic rationale and carries on.
        """
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

        # The whole call gets one budget. Without this, a call that times out
        # is tried again from scratch, and the caller waits for the sum of
        # every attempt rather than for one.
        budget = float(settings.llm_timeout_seconds)
        if deadline is not None:
            budget = min(budget, max(0.0, deadline - time.monotonic()))
        hard_stop = time.monotonic() + budget

        attempts = 0
        last_error = ""
        for attempt in range(1, settings.llm_max_retries + 2):
            remaining = hard_stop - time.monotonic()
            if remaining <= 0.5:
                last_error = last_error or "call budget exhausted"
                break
            attempts = attempt
            attempt_timeout = max(1.0, min(float(settings.llm_timeout_seconds), remaining))
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
                    timeout=attempt_timeout,
                )
                if resp.status_code >= 400:
                    last_error = f"http {resp.status_code}: {resp.text[:200]}"
                    if resp.status_code in RETRYABLE_STATUS and attempt <= settings.llm_max_retries:
                        delay = min(8.0, 0.75 * (2 ** (attempt - 1)))
                        if time.monotonic() + delay >= hard_stop:
                            break
                        time.sleep(delay)
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
                text = self._read_text(data)
                usage = data.get("usage") or {}
                tokens = int(usage.get("total_tokens", 0) or 0)
                choices = data.get("choices") or []
                finish_reason = choices[0].get("finish_reason") if choices else None
                # A router such as OpenRouter's free router picks the model
                # that actually served the call, and it is often not the one
                # that was asked for. Recording the model that answered is the
                # only way to see what the router is really doing.
                served_model = str(data.get("model") or self.model)[:120]
                if not text.strip():
                    # The call succeeded and said nothing. That is not a valid
                    # answer, and it is not worth keeping either: an empty
                    # entry in the cache would stop the same tender from ever
                    # being asked again while the instance is alive.
                    if finish_reason == "length":
                        # The model used its whole output budget thinking and
                        # was cut off before it answered. A bigger budget is
                        # the fix; the answer itself is not missing, it was
                        # never written.
                        reason = (
                            f"{served_model} used its whole output budget "
                            f"reasoning and was cut off before answering"
                        )
                    else:
                        reason = f"empty response from {served_model}"
                    return LLMResult(
                        text="",
                        provider=self.name,
                        model=served_model,
                        tokens=tokens,
                        valid=False,
                        error=reason,
                        attempts=attempts,
                        latency_ms=int((time.time() - started) * 1000),
                    )
                if settings.llm_cache_enabled:
                    if len(_RESPONSE_CACHE) >= _CACHE_MAX_ENTRIES:
                        _RESPONSE_CACHE.clear()
                    _RESPONSE_CACHE[key] = {"text": text, "tokens": tokens}
                return LLMResult(
                    text=text,
                    provider=self.name,
                    model=served_model,
                    tokens=tokens,
                    latency_ms=int((time.time() - started) * 1000),
                    attempts=attempts,
                )
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt <= settings.llm_max_retries:
                    delay = min(8.0, 0.75 * (2 ** (attempt - 1)))
                    if time.monotonic() + delay >= hard_stop:
                        break
                    time.sleep(delay)
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

    def chat(
        self,
        system: str,
        user: str,
        max_tokens: int = 1200,
        task: str = "",
        deadline: float | None = None,
    ) -> LLMResult:
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


def _strip_fences(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _balanced_value(text: str, start: int):
    """The complete JSON value that begins at `start`, with its brackets matched.

    Matching the brackets rather than slicing from the first brace to the last
    one is what tells an array answer apart from an object answer, and it does
    not get confused by a brace that appears inside a string.
    """
    opener = text[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def parse_json_block(text: str, array_key: str = ""):
    """Extract the JSON payload from a model response.

    Tolerates markdown fences and leading/trailing prose, and rejects payloads
    that are not valid JSON rather than guessing.

    A model that answers with a bare array instead of the object it was asked
    for is a common enough answer that it is worth keeping: the array is
    wrapped under the key the caller expects rather than thrown away. The
    caller still validates the result, so nothing reaches the database that
    has not been checked.
    """
    if not text:
        return None
    cleaned = _strip_fences(text)

    # The answer, read with its brackets matched.
    positions = [i for i in (cleaned.find("{"), cleaned.find("[")) if i != -1]
    for start in sorted(positions):
        candidate = _balanced_value(cleaned, start)
        if not candidate:
            continue
        try:
            payload = json.loads(candidate)
        except Exception:
            continue
        if isinstance(payload, list):
            return {array_key: payload} if array_key else None
        return payload

    # The loose reading, for an answer buried in prose that contains braces
    # of its own before it.
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        payload = json.loads(cleaned[start : end + 1])
    except Exception:
        return None
    if isinstance(payload, list):
        return {array_key: payload} if array_key else None
    return payload
