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


GROQ_MALFORMED_OUTPUT_ERRORS = [
    "Error code: 400 - output_parse_failed: Parsing failed",
    "Error code: 400 - {'error': {'message': 'Tool choice is required, but model did not call a tool', "
    "'type': 'invalid_request_error', 'code': 'tool_use_failed'}}",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("first_error", GROQ_MALFORMED_OUTPUT_ERRORS)
# contract-test: supporting surface=rest_api assertions=audio-speak.safety.semantic-safeguard-required,audio-speak.safety.provider-call-after-approval,audio-speak.provider-error.visible
async def test_audio_speech_safeguard_retries_groq_output_parse_failure(
    monkeypatch: pytest.MonkeyPatch, first_error: str,
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
                raise RuntimeError(first_error)
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
                                            '"severity":"low","reasoning":"Ordinary text-to-speech",'
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
    assert result.severity == "low"
    assert len(captured_calls) == 2
    assert captured_calls[0]["tool_choice"] == captured_calls[1]["tool_choice"]
    severity_enum = captured_calls[0]["tools"][0]["function"]["parameters"]["properties"]["severity"][
        "enum"
    ]
    assert "low" in severity_enum


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=audio-speak.safety.semantic-safeguard-required,audio-speak.safety.provider-call-after-approval,audio-speak.provider-error.visible
async def test_audio_speech_safeguard_blocks_when_retry_also_skips_the_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    groq_module = ModuleType("groq")

    class FakeAsyncGroq:
        pass

    groq_module.AsyncGroq = FakeAsyncGroq
    monkeypatch.setitem(sys.modules, "groq", groq_module)

    safeguard = importlib.import_module("backend.shared.providers.groq.safeguard")
    calls = []

    class FakeCompletions:
        async def create(self, **kwargs):
            calls.append(kwargs)
            raise RuntimeError(GROQ_MALFORMED_OUTPUT_ERRORS[1])

    client = safeguard.GroqSafeguardClient()
    client._client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))

    result = await client.classify_audio_speech(
        text="OpenMates audio playback is working.",
        voice="warm_neutral",
        accent="en_us",
        style="friendly",
    )

    # One retry only; a second malformed answer still fails closed.
    assert len(calls) == 2
    assert result.approved is False
    assert result.category == "safeguard_error"


class _GroqToolUseFailed(RuntimeError):
    """Shape of groq.BadRequestError: message plus the parsed JSON ``body``."""

    def __init__(self, failed_generation: str) -> None:
        super().__init__("Error code: 400 - tool_use_failed")
        self.body = {"error": {"code": "tool_use_failed", "failed_generation": failed_generation}}


@pytest.mark.asyncio
@pytest.mark.parametrize(("generation", "approved"), [
    ('{"name": "report_audio_speech_safety", "arguments": {\n  "category": "credential_harvesting",\n'
     '  "decision": "block",\n  "reasoning": "The text claims', False),
    ('{"name": "report_audio_speech_safety", "arguments": {"decision": "allow", "category": "news"', True),
])
# contract-test: supporting surface=rest_api assertions=audio-speak.safety.semantic-safeguard-required,audio-speak.safety.provider-call-after-approval
async def test_audio_speech_safeguard_uses_decision_from_malformed_tool_call(
    monkeypatch: pytest.MonkeyPatch, generation: str, approved: bool,
) -> None:
    groq_module = ModuleType("groq")

    class FakeAsyncGroq:
        pass

    groq_module.AsyncGroq = FakeAsyncGroq
    monkeypatch.setitem(sys.modules, "groq", groq_module)

    safeguard = importlib.import_module("backend.shared.providers.groq.safeguard")
    calls = []

    class FakeCompletions:
        async def create(self, **kwargs):
            calls.append(kwargs)
            raise _GroqToolUseFailed(generation)

    client = safeguard.GroqSafeguardClient()
    client._client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))

    result = await client.classify_audio_speech(
        text="Police arrested suspects in a phishing scam.", voice="warm_neutral",
        accent="en_us", style="natural", trusted_narration=True,
    )

    # The model's own readable decision is honoured without a paid retry.
    assert len(calls) == 1
    assert result.approved is approved
    assert result.raw_decision == ("allow" if approved else "block")


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=audio-speak.safety.semantic-safeguard-required
async def test_audio_speech_safeguard_rejects_ambiguous_malformed_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    groq_module = ModuleType("groq")

    class FakeAsyncGroq:
        pass

    groq_module.AsyncGroq = FakeAsyncGroq
    monkeypatch.setitem(sys.modules, "groq", groq_module)

    safeguard = importlib.import_module("backend.shared.providers.groq.safeguard")
    calls = []

    class FakeCompletions:
        async def create(self, **kwargs):
            calls.append(kwargs)
            raise _GroqToolUseFailed('{"decision": "allow"} {"decision": "block"}')

    client = safeguard.GroqSafeguardClient()
    client._client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))

    result = await client.classify_audio_speech(
        text="OpenMates audio playback is working.", voice="warm_neutral",
        accent="en_us", style="natural",
    )

    # Conflicting decisions are unreadable: one retry, then fail closed.
    assert len(calls) == 2
    assert result.approved is False
    assert result.category == "safeguard_error"
