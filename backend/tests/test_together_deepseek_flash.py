# contract-test-file: infrastructure
"""Together V4.1 numeric effort, reasoning replay and cache usage on the wire."""
import asyncio
import json
from pathlib import Path

import httpx
import pytest
import yaml

from backend.apps.ai.llm_providers import together_client
from backend.apps.ai.llm_providers.openai_shared import OpenAIUsageMetadata, ParsedOpenAIToolCall
from backend.apps.ai.llm_providers.types import StreamChunkType, UnifiedStreamChunk
from backend.apps.ai.utils.model_reasoning import resolve_reasoning_parameters
from backend.shared.python_utils.billing_utils import calculate_cache_aware_supplier_cost

MODEL = "deepseek-ai/DeepSeek-V4.1-Flash-1017"


def catalog():
    provider = yaml.safe_load((Path(__file__).parents[1] / "providers/deepseek.yml").read_text())
    return next(model for model in provider["models"] if model["id"] == "deepseek-v4.1-flash")


@pytest.mark.parametrize("level,native", [("LOW", 1), ("MEDIUM", 25), ("HIGH", 50), ("EXTRA_HIGH", 100)])
def test_declared_effort_reaches_together_as_integer(monkeypatch, level, native):
    captured = []

    def handle(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 2, "total_tokens": 102}})

    original = httpx.AsyncClient
    monkeypatch.setattr(together_client.httpx, "AsyncClient",
                        lambda **kw: original(**kw, transport=httpx.MockTransport(handle)))
    result = asyncio.run(together_client.invoke_together_api("test", MODEL,
        [{"role": "user", "content": "hello"}], api_key="test-only",
        **resolve_reasoning_parameters(catalog(), "together", level)))
    assert result.success
    assert type(captured[0]["reasoning_effort"]) is int
    assert captured[0]["reasoning_effort"] == native


@pytest.mark.parametrize("effort", [0, 101, True, 1.5, "high", "-1"])
def test_invalid_v41_effort_is_rejected_before_network(effort):
    with pytest.raises(ValueError, match="integer from 1 to 100"):
        asyncio.run(together_client.invoke_together_api("test", MODEL, [], "test-only", reasoning_effort=effort))


@pytest.mark.parametrize("reasoning_field", ["reasoning_content", "reasoning"])
def test_stream_preserves_tool_reasoning_and_usage_only_cache_event(monkeypatch, reasoning_field):
    captured = []

    def handle(request):
        captured.append(json.loads(request.content))
        chunks = [
            {"choices": [{"delta": {reasoning_field: "Private tool reasoning"}}]},
            {"choices": [{"delta": {"tool_calls": [{"id": "call-1", "index": 0, "type": "function",
                "function": {"name": "check", "arguments": "{}"}}]}, "finish_reason": "tool_calls"}]},
            {"choices": [], "usage": {"prompt_tokens": 11000, "completion_tokens": 20,
                "total_tokens": 11020, "prompt_tokens_details": {"cached_tokens": 10800}}},
        ]
        return httpx.Response(200, text="".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks)
                              + "data: [DONE]\n\n")

    original = httpx.AsyncClient
    monkeypatch.setattr(together_client.httpx, "AsyncClient",
                        lambda **kw: original(**kw, transport=httpx.MockTransport(handle)))

    async def run():
        stream = await together_client.invoke_together_api("test", MODEL, [], "test-only",
            stream=True, prompt_cache_key="opaque-root", reasoning_effort="1")
        return [chunk async for chunk in stream]

    chunks = asyncio.run(run())
    thought = next(chunk for chunk in chunks if isinstance(chunk, UnifiedStreamChunk))
    assert thought.type == StreamChunkType.THINKING and thought.content == "Private tool reasoning"
    assert next(chunk for chunk in chunks if isinstance(chunk, ParsedOpenAIToolCall)).function_name == "check"
    usage = next(chunk for chunk in chunks if isinstance(chunk, OpenAIUsageMetadata))
    assert usage.cache_read_input_tokens == 10800 and usage.output_tokens == 20
    assert captured[0]["stream_options"] == {"include_usage": True}
    assert captured[0]["prompt_cache_key"] == "opaque-root"


def test_supplier_cache_cost_retains_host_specific_rates():
    model = catalog()
    usage = {"input_tokens": 1_000_000, "output_tokens": 0, "cache_read_input_tokens": 1_000_000,
             "cache_creation_input_tokens": 0, "usage_source": "provider_reported", "provider_kind": "openai"}
    values = {host: calculate_cache_aware_supplier_cost(usage=usage,
        model_pricing_details=model, inference_host=host) for host in ("together", "baseten", "openrouter")}
    assert values["together"]["cost_usd"] == "0.006"
    assert values["baseten"]["cost_usd"] == values["openrouter"]["cost_usd"] == "0.007"
