#!/usr/bin/env python3
# backend/apps/ai/tests/test_anthropic_direct_api.py
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
def test_fable_5_omits_deprecated_temperature():
    """Claude Fable 5 rejects temperature, so the direct client must omit it."""

    @dataclass
    class MockUsage:
        input_tokens: int = 20
        output_tokens: int = 5

    @dataclass
    class MockTextBlock:
        type: str = "text"
        text: str = "Fable 5 is online."

    @dataclass
    class MockResponse:
        usage: MockUsage = field(default_factory=MockUsage)
        content: List[MockTextBlock] = field(default_factory=lambda: [MockTextBlock()])

    async def run():
        mock_client = MagicMock()
        mock_client.messages.create.return_value = MockResponse()

        response = await invoke_direct_api(
            task_id="test-fable-temperature",
            model_id="claude-fable-5",
            messages=[{"role": "user", "content": "test"}],
            anthropic_client=mock_client,
            temperature=0,
            max_tokens=20,
            stream=False,
        )

        assert response.success is True
        request_kwargs = mock_client.messages.create.call_args.kwargs
        assert request_kwargs["model"] == "claude-fable-5"
        assert "temperature" not in request_kwargs

    asyncio.run(run())
