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
# contract-test: supporting surface=rest_api assertions=audio-speak.safety.semantic-safeguard-required
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


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=audio-speak.safety.semantic-safeguard-required,audio-speak.safety.provider-call-after-approval,audio-speak.provider-error.visible
async def test_audio_speech_safeguard_retries_groq_output_parse_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    groq_module = ModuleType("groq")

    class FakeAsyncGroq:
        pass

    groq_module.AsyncGroq = FakeAsyncGroq
    monkeypatch.setitem(sys.modules, "groq", groq_module)

    safeguard = importlib.import_module("backend.shared.providers.groq.safeguard")
    captured_calls = []

    class FakeCompletions:
        async def create(self, **kwargs):
            captured_calls.append(kwargs)
            if len(captured_calls) == 1:
                raise RuntimeError("Error code: 400 - output_parse_failed: Parsing failed")
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
                                            '"severity":"moderate","reasoning":"Ordinary read-aloud",'
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

    result = await client.classify_audio_speech(
        text="OpenMates audio playback is working.",
        voice="warm_neutral",
        accent="en_us",
        style="friendly",
    )

    assert result.approved is True
    assert result.category == "ALLOW_GENERAL"
    assert len(captured_calls) == 2
    assert captured_calls[0]["tool_choice"] == captured_calls[1]["tool_choice"]
