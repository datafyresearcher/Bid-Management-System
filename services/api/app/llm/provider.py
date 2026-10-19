import json
import time

import httpx

from app.config import settings
from app.models import AIMetric


class LLMResult:
    def __init__(self, text="", provider="mock", model="", tokens=0, latency_ms=0, valid=True):
        self.text = text
        self.provider = provider
        self.model = model
        self.tokens = tokens
        self.latency_ms = latency_ms
        self.valid = valid


class OpenAICompatibleProvider:
    def __init__(self, provider_name: str, base_url: str, api_key: str, model: str):
        self.name = provider_name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.enabled = bool(api_key and model)

    def chat(self, system: str, user: str, max_tokens: int = 1200) -> LLMResult:
        started = time.time()
        if not self.enabled:
            return LLMResult(provider=self.name, valid=False)
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
                    "temperature": 0.2,
                },
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            tokens = int(usage.get("total_tokens", 0))
            return LLMResult(
                text=text,
                provider=self.name,
                model=self.model,
                tokens=tokens,
                latency_ms=int((time.time() - started) * 1000),
            )
        except Exception as exc:
            return LLMResult(text="", provider=self.name, model=self.model, valid=False, latency_ms=int((time.time() - started) * 1000))


class MockProvider:
    def __init__(self):
        self.name = "mock"
        self.model = "deterministic"
        self.enabled = False

    def chat(self, system: str, user: str, max_tokens: int = 1200) -> LLMResult:
        return LLMResult(provider="mock", model="deterministic", valid=True)


def get_provider():
    if settings.llm_provider == "openrouter":
        return OpenAICompatibleProvider(
            "openrouter",
            settings.openrouter_base_url,
            settings.openrouter_api_key,
            settings.llm_model or "openrouter/auto",
        )
    if settings.llm_provider == "openai":
        return OpenAICompatibleProvider(
            "openai",
            settings.openai_base_url,
            settings.openai_api_key,
            settings.llm_model or "gpt-4o-mini",
        )
    return MockProvider()


def record_metric(db, task, result: LLMResult, opportunity_id=None, output_valid=True):
    db.add(
        AIMetric(
            task=task,
            provider=result.provider,
            model=result.model,
            tokens_estimate=result.tokens,
            latency_ms=result.latency_ms,
            output_valid=output_valid and result.valid,
            opportunity_id=opportunity_id,
        )
    )
    db.commit()


def parse_json_block(text: str):
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(cleaned[start : end + 1])
    except Exception:
        return None
