# backend/tests/test_groq_safeguard_structured_output.py
#
# Contract tests for the Groq safeguard reasoner structured output path.
# The local unit environment may not install the optional groq package, so this
# test stubs the module before importing the provider and verifies the request
# shape without making network calls.
#
# Architecture: docs/architecture/image-safety-pipeline.md

from __future__ import annotations

import importlib
import sys
from types import ModuleType, SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_groq_safeguard_reason_uses_forced_tool_call(monkeypatch: pytest.MonkeyPatch) -> None:
    groq_module = ModuleType("groq")

    class FakeAsyncGroq:
        pass

    groq_module.AsyncGroq = FakeAsyncGroq
    monkeypatch.setitem(sys.modules, "groq", groq_module)

    safeguard = importlib.import_module("backend.shared.providers.groq.safeguard")

    captured_kwargs = {}

    class FakeCompletions:
        async def create(self, **kwargs):
            captured_kwargs.update(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=None,
                            tool_calls=[
                                SimpleNamespace(
                                    function=SimpleNamespace(
                                        arguments=(
                                            '{"decision":"allow","category":"ALLOW_GENERAL",'
                                            '"severity":"moderate","reasoning":"No concerning signals",'
                                            '"discrepancies":""}'
                                        )
                                    )
                                )
                            ],
                        )
                    )
                ]
            )

    client = safeguard.GroqSafeguardClient()
    client._client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))

    verdict = await client.reason(
        policy_markdown="Policy text",
        stage="input",
        user_prompt="Generate a landscape",
        sightengine_json={},
        vlm_json={},
    )

    assert verdict.decision == "allow"
    assert verdict.category == "ALLOW_GENERAL"
    assert "response_format" not in captured_kwargs
    assert captured_kwargs["tool_choice"] == {
        "type": "function",
        "function": {"name": "report_safeguard_verdict"},
    }
    [tool] = captured_kwargs["tools"]
    assert tool["function"]["name"] == "report_safeguard_verdict"
    assert tool["function"]["parameters"]["additionalProperties"] is False
    assert tool["function"]["parameters"]["required"] == [
        "decision",
        "category",
        "severity",
        "reasoning",
        "discrepancies",
    ]
