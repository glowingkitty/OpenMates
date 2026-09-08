# contract-test-file: infrastructure
# Tests Astra's stateless Responses transport at the provider boundary.
# Synthetic SDK events exercise real request conversion and stream handling.
# Opaque reasoning must survive tool continuation without provider storage.
# Real dev inference remains a separate required verification gate.
# contract-test: supporting surface=gui.web assertions=ai-model-routing.catalog.capability-recommendation-variants

import asyncio
from types import SimpleNamespace

import pytest
import yaml
from pathlib import Path

from backend.apps.ai.llm_providers.openai_responses import invoke_responses, responses_input
from backend.apps.ai.llm_providers.openai_shared import ParsedOpenAIToolCall, OpenAIUsageMetadata


@pytest.mark.parametrize("stream", [False, True])
def test_astra_reasoning_tool_roundtrip(stream, monkeypatch):
    from backend.apps.ai.llm_providers import openai_client
    provider = yaml.safe_load((Path(__file__).parents[1] / "providers/openai.yml").read_text())
    models = {m["id"]: m for m in provider["models"]}
    monkeypatch.setattr(openai_client.config_manager, "get_model_pricing", lambda provider, model: models.get(model))
    opaque = {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "opaque"}
    call = {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "lookup", "arguments": '{"query":"test"}'}
    response = {"status": "completed", "output": [opaque, call], "usage": {"input_tokens": 10, "output_tokens": 7, "total_tokens": 17}}
    captured = {}

    async def create(**kwargs):
        captured.update(kwargs)
        if not stream:
            return response
        async def events():
            yield {"type": "response.completed", "response": response}
        return events()

    async def run():
        monkeypatch.setattr(openai_client, "_openai_direct_client", SimpleNamespace(responses=SimpleNamespace(create=create)))
        result = await openai_client._invoke_openai_direct_api(task_id="test", model_id="gpt-6-astra", messages=[{"role": "user", "content": "Build an app"}], tools=[{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}], tool_choice="required", max_tokens=100, stream=stream)
        if stream:
            chunks = [chunk async for chunk in result]
            assert isinstance(chunks[-1], OpenAIUsageMetadata)
            assert chunks[-1].output_tokens == 7
            return next(c for c in chunks if isinstance(c, ParsedOpenAIToolCall))
        assert result.success
        return result.tool_calls_made[0]

    tool = asyncio.run(run())
    assert captured["model"] == "gpt-6-astra"
    assert captured["reasoning"] == {"effort": "xhigh"}
    assert captured["store"] is False
    assert "previous_response_id" not in captured
    assert captured["tools"][0]["strict"] is False
    assert captured["max_output_tokens"] == 100
    assert tool.tool_call_id == "call_1"
    assert "provider_transport_state" not in tool.model_dump()
    assert "opaque" not in repr(tool)
    history = [{"role": "assistant", "content": None, "tool_calls": [{"id": tool.tool_call_id, "function": {"name": tool.function_name, "arguments": tool.function_arguments_raw}, "provider_transport_state": tool.provider_transport_state}]}, {"role": "tool", "tool_call_id": "call_1", "content": "result"}]
    assert responses_input(history) == [opaque, call, {"type": "function_call_output", "call_id": "call_1", "output": "result"}]


def test_incomplete_stream_is_not_success():
    async def create(**kwargs):
        async def events():
            yield {"type": "response.incomplete", "response": {"status": "incomplete"}}
        return events()
    async def run():
        result = await invoke_responses(client=SimpleNamespace(responses=SimpleNamespace(create=create)), task_id="test", model_id="gpt-6-astra", messages=[], reasoning_effort="xhigh", stream=True)
        return [chunk async for chunk in result]
    with pytest.raises(RuntimeError, match="incomplete"):
        asyncio.run(run())


def test_stream_text_multiple_calls_and_cleanup():
    closed = []
    response = {"status": "completed", "output": [{"type": "function_call", "call_id": name, "name": name, "arguments": "{}"} for name in ["first", "second"]], "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3}}
    class Events:
        def __aiter__(self):
            async def values():
                yield {"type": "response.output_text.delta", "delta": "Checking"}
                yield {"type": "response.completed", "response": response}
            return values()
        async def close(self):
            closed.append(True)
    async def create(**kwargs):
        return Events()
    async def run():
        result = await invoke_responses(client=SimpleNamespace(responses=SimpleNamespace(create=create)), task_id="test", model_id="gpt-6-astra", messages=[], reasoning_effort="xhigh", stream=True)
        return [chunk async for chunk in result]
    chunks = asyncio.run(run())
    assert chunks[0] == "Checking"
    assert [c.tool_call_id for c in chunks if isinstance(c, ParsedOpenAIToolCall)] == ["first", "second"]
    assert chunks[1].provider_transport_state == response["output"]
    assert chunks[2].provider_transport_state is None
    assert closed == [True]
