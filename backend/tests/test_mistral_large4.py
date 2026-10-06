# contract-test-file: infrastructure
"""Mistral Large 4 catalog, native reasoning, tool replay, and accounting."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest
import yaml

from backend.apps.ai.llm_providers import mistral_client
from backend.apps.ai.llm_providers.types import StreamChunkType, UnifiedStreamChunk


def _model():
    provider = yaml.safe_load((Path(__file__).parents[1] / "providers/mistral.yml").read_text())
    return next(model for model in provider["models"] if model["id"] == "mistral-large-4")


def _thinking(text):
    return {"type": "thinking", "thinking": [{"type": "text", "text": text}]}


def _mock_client(monkeypatch, handler):
    original_client = httpx.AsyncClient
    monkeypatch.setattr(mistral_client, "MISTRAL_API_KEY", "test-placeholder")
    monkeypatch.setattr(mistral_client.config_manager, "get_model_pricing", lambda provider, model: _model())
    monkeypatch.setattr(mistral_client.httpx, "AsyncClient", lambda **kwargs: original_client(
        **kwargs, transport=httpx.MockTransport(handler)
    ))


def test_catalog_routes_preview_with_authoritative_discounted_costs():
    model = _model()
    assert model["name"] == "Mistral Large 4"
    assert model["release_date"] == "2026-10-06"
    assert model["capability_level"] == "max"
    assert model["reasoning"] is True
    assert model["reasoning_effort"] == "high"
    assert model["input_types"] == ["text", "image"]
    assert model["default_server"] == "mistral"
    assert model["servers"] == [{"id": "mistral", "name": "Mistral", "model_id": "mistral-large-4", "region": "EU"}]
    for direction, expected in [("input", 0.68), ("output", 2.09)]:
        cost = model["costs"][f"{direction}_per_million_token"]
        assert cost["price"] == expected
        assert cost["max_context"] == 1000000
        charged = 1000 / model["pricing"]["tokens"][direction]["per_credit_unit"]
        assert 3 <= charged / expected <= 3.1


def test_reasoning_setting_preserves_legacy_models_and_rejects_invalid_values(monkeypatch):
    monkeypatch.setattr(mistral_client.config_manager, "get_model_pricing", lambda *_: {})
    assert mistral_client._get_mistral_reasoning_effort("mistral-small-latest") is None
    monkeypatch.setattr(mistral_client.config_manager, "get_model_pricing", lambda *_: {"reasoning_effort": "none"})
    assert mistral_client._get_mistral_reasoning_effort("mistral-large-4") == "none"
    monkeypatch.setattr(mistral_client.config_manager, "get_model_pricing", lambda *_: {"reasoning_effort": "max"})
    with pytest.raises(ValueError, match="Invalid Mistral reasoning_effort"):
        mistral_client._get_mistral_reasoning_effort("mistral-large-4")


def test_non_stream_response_keeps_answer_separate_from_thinking(monkeypatch):
    payloads = []

    def handle(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={
            "id": "test-completion", "object": "chat.completion", "created": 1, "model": "mistral-large-4",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": [
                _thinking("Internal reasoning"), {"type": "text", "text": "391"}
            ]}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        })

    _mock_client(monkeypatch, handle)
    result = asyncio.run(mistral_client.invoke_mistral_chat_completions(
        "test", "mistral-large-4", [{"role": "user", "content": "What is 17 times 23?"}]
    ))
    assert result.success
    assert result.direct_message_content == "391"
    assert result.usage.completion_tokens == 20
    assert payloads[0]["reasoning_effort"] == "high"


def test_stream_handles_mixed_deltas_and_replays_thinking_with_tool_results(monkeypatch):
    payloads = []
    tool = {"id": "call-weather", "function": {"name": "weather", "arguments": '{"city":"Berlin"}'}}

    def handle(request):
        payloads.append(json.loads(request.content))
        deltas = [
            {"choices": [{"delta": {"content": [_thinking("Think ")]}}]},
            {"choices": [{"delta": {"content": [_thinking("carefully"), {"type": "text", "text": "Checking."}]}}]},
            {"choices": [{"delta": {"tool_calls": [tool]}, "finish_reason": "tool_calls"}]},
            {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 40, "total_tokens": 50}},
        ] if len(payloads) == 1 else [
            {"choices": [{"delta": {"content": "Sunny."}, "finish_reason": "stop"}],
             "usage": {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60}}
        ]
        return httpx.Response(200, text="".join(f"data: {json.dumps(delta)}\n\n" for delta in deltas) + "data: [DONE]\n\n")

    _mock_client(monkeypatch, handle)

    async def run():
        messages = [{"role": "user", "content": "Weather in Berlin?"}]
        stream = await mistral_client.invoke_mistral_chat_completions("test", "mistral-large-4", messages, stream=True)
        chunks = [chunk async for chunk in stream]
        thinking = [chunk for chunk in chunks if isinstance(chunk, UnifiedStreamChunk)]
        assert all(chunk.type == StreamChunkType.THINKING for chunk in thinking)
        assert "".join(chunk.content for chunk in thinking) == "Think carefully"
        assert [chunk for chunk in chunks if isinstance(chunk, str)] == ["Checking."]
        call = next(chunk for chunk in chunks if isinstance(chunk, mistral_client.ParsedMistralToolCall))
        assert call.function_arguments_parsed == {"city": "Berlin"}
        assert "provider_transport_state" not in call.model_dump()
        usage = next(chunk for chunk in chunks if isinstance(chunk, mistral_client.MistralUsage))
        assert usage.completion_tokens == 40
        messages.extend([
            {"role": "assistant", "content": "Checking.", "tool_calls": [{
                **tool, "type": "function", "provider_transport_state": call.provider_transport_state
            }]},
            {"role": "tool", "tool_call_id": "call-weather", "content": "Sunny"},
        ])
        stream = await mistral_client.invoke_mistral_chat_completions("test", "mistral-large-4", messages, stream=True)
        assert "Sunny." in [chunk async for chunk in stream]
        replay = payloads[1]["messages"][1]
        assert replay["content"] == [_thinking("Think carefully"), {"type": "text", "text": "Checking."}]
        assert "provider_transport_state" not in replay["tool_calls"][0]
        assert "provider_transport_state" in messages[1]["tool_calls"][0]

    asyncio.run(run())


def test_foreign_provider_state_is_not_sent_to_mistral_or_replayed():
    messages = [{"role": "assistant", "content": "Answer", "tool_calls": [{
        "id": "foreign", "type": "function", "function": {"name": "search", "arguments": "{}"},
        "thought_signature": "google-only", "provider_transport_state": [{"type": "reasoning", "text": "foreign"}],
    }]}]
    prepared = mistral_client._prepare_mistral_messages(messages)
    assert prepared[0]["content"] == "Answer"
    assert "thought_signature" not in prepared[0]["tool_calls"][0]
    assert "provider_transport_state" not in prepared[0]["tool_calls"][0]
    assert "provider_transport_state" in messages[0]["tool_calls"][0]


def test_plain_string_content_still_streams_unchanged():
    assert mistral_client._mistral_content_chunks("Answer") == ["Answer"]
    assert mistral_client._mistral_content_chunks(None) == []


def test_openai_responses_does_not_replay_mistral_thinking_as_provider_items():
    from backend.apps.ai.llm_providers.openai_responses import responses_input

    items = responses_input([{"role": "assistant", "content": "Checking", "tool_calls": [{
        "id": "search-1", "type": "function", "function": {"name": "search", "arguments": "{}"},
        "provider_transport_state": mistral_client._mistral_thinking_state("Private Mistral reasoning"),
    }]}])
    assert items == [
        {"role": "assistant", "content": "Checking"},
        {"type": "function_call", "call_id": "search-1", "name": "search", "arguments": "{}"},
    ]
