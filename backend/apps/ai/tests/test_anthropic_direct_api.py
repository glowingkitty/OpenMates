#!/usr/bin/env python3
# backend/apps/ai/tests/test_anthropic_direct_api.py
# contract-test-file: infrastructure
#
# Focused unit tests for the Anthropic direct API adapter.
# These tests guard provider-specific request shaping before calls reach the
# live Anthropic SDK, especially model-specific parameter compatibility.

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import List
from unittest.mock import MagicMock

import pytest

try:
    from backend.apps.ai.llm_providers.anthropic_direct_api import invoke_direct_api

    HAS_ANTHROPIC_DIRECT_API = True
except ImportError:
    HAS_ANTHROPIC_DIRECT_API = False


@pytest.mark.skipif(
    not HAS_ANTHROPIC_DIRECT_API,
    reason="Anthropic direct API dependencies not installed",
)
@pytest.mark.parametrize(
    "model_id, expected_text",
    [
        ("claude-fable-5-1", "Fable 5.1 is online."),
        ("claude-fable-5", "Fable 5 is online."),
        ("claude-opus-5", "Opus 5 is online."),
        ("claude-sonnet-5", "Sonnet 5 is online."),
        ("claude-opus-4-8", "Opus 4.8 is online."),
    ],
)
def test_adaptive_thinking_models_omit_deprecated_temperature(model_id, expected_text):
    """Adaptive-thinking Claude models reject temperature, so the client must omit it."""

    @dataclass
    class MockUsage:
        input_tokens: int = 20
        output_tokens: int = 5

    @dataclass
    class MockTextBlock:
        type: str = "text"
        text: str = expected_text

    @dataclass
    class MockResponse:
        usage: MockUsage = field(default_factory=MockUsage)
        content: List[MockTextBlock] = field(default_factory=lambda: [MockTextBlock()])

    async def run():
        mock_client = MagicMock()
        mock_client.messages.create.return_value = MockResponse()

        response = await invoke_direct_api(
            task_id="test-opus48-temperature",
            model_id=model_id,
            messages=[{"role": "user", "content": "test"}],
            anthropic_client=mock_client,
            temperature=0,
            max_tokens=20,
            stream=False,
        )

        assert response.success is True
        request_kwargs = mock_client.messages.create.call_args.kwargs
        assert request_kwargs["model"] == model_id
        assert "temperature" not in request_kwargs

    asyncio.run(run())


@pytest.mark.skipif(
    not HAS_ANTHROPIC_DIRECT_API,
    reason="Anthropic direct API dependencies not installed",
)
def test_stream_accumulates_indexed_tool_json_and_yields_each_tool_once():
    """Anthropic streams tool arguments after an empty tool-use start block."""

    events = [
        SimpleNamespace(
            type="content_block_delta",
            index=9,
            delta=SimpleNamespace(type="text_delta", text="Checking "),
        ),
        SimpleNamespace(
            type="content_block_start",
            index=0,
            content_block=SimpleNamespace(
                type="tool_use", id="tool-weather", name="weather", input={}
            ),
        ),
        SimpleNamespace(
            type="content_block_delta",
            index=0,
            delta=SimpleNamespace(type="input_json_delta", partial_json='{"location":"Lon'),
        ),
        SimpleNamespace(
            type="content_block_delta",
            index=0,
            delta=SimpleNamespace(type="input_json_delta", partial_json='don"}'),
        ),
        SimpleNamespace(type="content_block_stop", index=0),
        SimpleNamespace(
            type="content_block_start",
            index=1,
            content_block=SimpleNamespace(
                type="tool_use", id="tool-time", name="time", input={}
            ),
        ),
        SimpleNamespace(
            type="content_block_delta",
            index=1,
            delta=SimpleNamespace(type="input_json_delta", partial_json='{"utc_offset":"+01:00"}'),
        ),
        SimpleNamespace(type="content_block_stop", index=1),
    ]

    async def run():
        mock_client = MagicMock()
        mock_client.messages.create.return_value = events
        stream = await invoke_direct_api(
            task_id="test-streamed-tool-json",
            model_id="claude-sonnet-5",
            messages=[{"role": "user", "content": "Weather and time in London"}],
            anthropic_client=mock_client,
            stream=True,
        )
        return [item async for item in stream]

    output = asyncio.run(run())
    tool_calls = [item for item in output if hasattr(item, "tool_call_id")]

    assert output[0] == "Checking "
    assert [call.tool_call_id for call in tool_calls] == ["tool-weather", "tool-time"]
    assert [call.function_arguments_parsed for call in tool_calls] == [
        {"location": "London"},
        {"utc_offset": "+01:00"},
    ]
    assert [call.function_arguments_raw for call in tool_calls] == [
        '{"location":"London"}',
        '{"utc_offset":"+01:00"}',
    ]
    assert output[-1].total_tokens >= output[-1].output_tokens > 0


@pytest.mark.skipif(
    not HAS_ANTHROPIC_DIRECT_API,
    reason="Anthropic direct API dependencies not installed",
)
def test_streamed_tool_with_malformed_json_fails_visibly():
    events = [
        SimpleNamespace(
            type="content_block_start",
            index=3,
            content_block=SimpleNamespace(
                type="tool_use", id="tool-weather", name="weather", input={}
            ),
        ),
        SimpleNamespace(
            type="content_block_delta",
            index=3,
            delta=SimpleNamespace(type="input_json_delta", partial_json='{"location":'),
        ),
        SimpleNamespace(type="content_block_stop", index=3),
    ]

    async def run():
        mock_client = MagicMock()
        mock_client.messages.create.return_value = events
        stream = await invoke_direct_api(
            task_id="test-malformed-streamed-tool-json",
            model_id="claude-sonnet-5",
            messages=[{"role": "user", "content": "Weather in London"}],
            anthropic_client=mock_client,
            stream=True,
        )
        return [item async for item in stream]

    with pytest.raises(IOError, match="emitted invalid JSON arguments"):
        asyncio.run(run())
