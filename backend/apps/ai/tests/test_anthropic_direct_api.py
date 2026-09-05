#!/usr/bin/env python3
# backend/apps/ai/tests/test_anthropic_direct_api.py
# contract-test-file: infrastructure
#
# Focused unit tests for the Anthropic direct API adapter.
# These tests guard provider-specific request shaping before calls reach the
# live Anthropic SDK, especially model-specific parameter compatibility.

import asyncio
from dataclasses import dataclass, field
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
