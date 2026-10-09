"""OpenAI's reported cache counters are disjoint parts of inclusive input."""

# contract-test-file: infrastructure
# contract-test: supporting surface=rest_api assertions=billing.usage.receipt-token-breakdown

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from backend.apps.ai.llm_providers.openai_client import _build_unified_response, _invoke_openai_direct_api
from backend.apps.ai.llm_providers.openai_responses import _usage as responses_usage
from backend.apps.ai.llm_providers.openai_shared import openai_cache_write_tokens
from backend.apps.ai.processing.model_usage_tracker import build_model_usage_breakdown
from backend.shared.python_schemas.llm_usage import normalize_provider_usage


def test_responses_preserves_reported_write_and_missing_versus_zero() -> None:
    def response(details: dict) -> dict:
        return {"id": "resp_cache", "usage": {"input_tokens": 15000,
                "output_tokens": 5, "total_tokens": 15005,
                "input_tokens_details": details}}

    reported = responses_usage(response({"cached_tokens": 12000, "cache_write_tokens": 2000}))
    missing = responses_usage(response({"cached_tokens": 12000}))
    zero = responses_usage(response({"cached_tokens": 0, "cache_write_tokens": 0}))
    normalized = normalize_provider_usage(reported, model_id="gpt-6.1-sol")
    assert reported.cache_read_input_tokens == 12000
    assert reported.cache_creation_input_tokens == 2000
    assert normalized.input_uncached == 1000
    assert normalized.input_total == 15000
    assert missing.cache_creation_input_tokens is None
    assert zero.cache_creation_input_tokens == 0
    assert openai_cache_write_tokens({"prompt_tokens": 10}) is None


def test_reported_write_is_charged_once_and_missing_write_uses_ordinary_input() -> None:
    catalog = yaml.safe_load((Path(__file__).parents[1] / "providers/openai.yml").read_text())
    model = next(item for item in catalog["models"] if item["id"] == "gpt-6.1-sol")

    def receipt(details: dict) -> dict:
        usage = responses_usage({"usage": {"input_tokens": 15000, "output_tokens": 5,
            "total_tokens": 15005, "input_tokens_details": details}})
        bucket = normalize_provider_usage(
            usage, model_id="openai/gpt-6.1-sol", inference_host="openai",
        ).to_bucket()
        return build_model_usage_breakdown([bucket], lambda _provider, _model: model)["entries"][0]

    reported = receipt({"cached_tokens": 12000, "cache_write_tokens": 2000})
    missing = receipt({"cached_tokens": 12000})
    assert reported["billing_mode"] == "cache_aware"
    assert reported["billed_input_tokens"] == 1000
    assert float(reported["category_credits"]["input"]) == pytest.approx(1000 / 165)
    assert float(reported["category_credits"]["cache_read"]) == pytest.approx(12000 / 3300)
    assert float(reported["category_credits"]["cache_write"]) == pytest.approx(2000 / 132)
    assert missing["billing_mode"] == "ordinary_input"
    assert missing["billed_input_tokens"] == 15000
    assert float(missing["category_credits"]["cache_write"]) == 0


def test_chat_nonstream_preserves_reported_write_and_missing_metric() -> None:
    def response(details: dict) -> dict:
        return {"id": "chat_cache", "choices": [{"message": {"content": "OK"}}],
                "usage": {"prompt_tokens": 15000, "completion_tokens": 5,
                          "total_tokens": 15005, "prompt_tokens_details": details}}

    reported = _build_unified_response("task", "gpt-6-luna", response({
        "cached_tokens": 12000, "cache_write_tokens": 2000,
    })).usage
    missing = _build_unified_response("task", "gpt-6-luna", response({
        "cached_tokens": 12000,
    })).usage
    assert reported.cache_read_input_tokens == 12000
    assert reported.cache_creation_input_tokens == 2000
    assert missing.cache_creation_input_tokens is None


def test_chat_stream_emits_final_usage_with_write_once(monkeypatch) -> None:
    from backend.apps.ai.llm_providers import openai_client

    async def chunks():
        yield SimpleNamespace(id="chat_cache", choices=[], usage=SimpleNamespace(
            prompt_tokens=1000, completion_tokens=1, total_tokens=1001,
            model_dump=lambda **kwargs: {"prompt_tokens_details": {
                "cached_tokens": 500, "cache_write_tokens": 400}},
        ))
        yield SimpleNamespace(id="chat_cache", choices=[], usage=SimpleNamespace(
            prompt_tokens=5285, completion_tokens=5, total_tokens=5290,
            model_dump=lambda **kwargs: {"prompt_tokens_details": {
                "cached_tokens": 5000, "cache_write_tokens": 280}},
        ))

    async def create(**kwargs):
        assert kwargs["stream_options"] == {"include_usage": True}
        return chunks()

    monkeypatch.setattr(openai_client, "_openai_direct_client", SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))))

    async def collect():
        stream = await _invoke_openai_direct_api(
            "task", "gpt-6-luna", [{"role": "user", "content": "Reply OK"}], stream=True,
        )
        return [item async for item in stream]

    items = asyncio.run(collect())
    usages = [item for item in items if item.__class__.__name__ == "OpenAIUsageMetadata"]
    assert len(usages) == 1
    assert usages[0].input_tokens == 5285
    assert usages[0].cache_read_input_tokens == 5000
    assert usages[0].cache_creation_input_tokens == 280
    assert usages[0].usage_source == "provider_reported"
