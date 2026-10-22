# contract-test-file: infrastructure
# backend/tests/test_llm_utils_stream_fallback.py
#
# Purpose: cover main-stream fallback behavior when a provider stream connects
# but returns no text or tool calls.
# Architecture: verifies backend/apps/ai/utils/llm_utils.py keeps empty streams
# on the server side and falls back before stream_consumer emits a user error.
# Docs: docs/architecture/logging/ and docs/architecture/health-checks/.
# Test refs: backend/apps/ai/utils/llm_utils.py, issue ef17cb0d-a1bd-4898-a27b-09ee2d2c8102.

import asyncio
from types import SimpleNamespace
from pathlib import Path

import pytest
import yaml

try:
    from backend.apps.ai.llm_providers.google_client import (
        GOOGLE_THOUGHT_SIGNATURE_PROVIDER_STATE_KEY,
        GoogleUsageMetadata,
        _parse_streamed_google_tool_call,
    )
    from backend.apps.ai.llm_providers.types import StreamChunkType, UnifiedStreamChunk
    from backend.apps.ai.utils import llm_utils
except ImportError:
    pytestmark = pytest.mark.skip(reason="Backend AI dependencies not installed (google-genai, tiktoken, etc.)")
    AllServersFailedError = None  # type: ignore[assignment]
    GoogleUsageMetadata = None  # type: ignore[assignment, misc]
    StreamChunkType = None  # type: ignore[assignment, misc]
    UnifiedStreamChunk = None  # type: ignore[assignment, misc]
    llm_utils = None  # type: ignore[assignment]
else:
    AllServersFailedError = llm_utils.AllServersFailedError


# contract-test: supporting surface=rest_api assertions=ai-model-routing.defaults.google-tier-profiles
@pytest.mark.parametrize("server_id,expected_level", [
    ("google_ai_studio/gemini-3.8-flash", "LOW"),
    ("google/gemini-3.8-flash", "LOW"),
    ("google_ai_studio/gemini-3.5-flash-lite", None),
    ("openrouter/google/gemini-3.8-flash", None),
])
def test_main_stream_forwards_profile_only_to_matching_native_google_server(
    monkeypatch, server_id, expected_level,
) -> None:
    calls = []

    async def provider(**kwargs):
        calls.append(kwargs)

        async def stream():
            yield "Answer"

        return stream()

    monkeypatch.setattr(llm_utils, "_get_provider_client", lambda _provider: provider)
    monkeypatch.setattr(llm_utils, "resolve_default_server_from_provider_config",
                        lambda _model: (server_id.split("/", 1)[0], server_id))
    monkeypatch.setattr(llm_utils, "resolve_fallback_servers_from_provider_config", lambda _model: [])
    monkeypatch.setattr(llm_utils, "_transform_message_history_for_llm", lambda history: history)
    monkeypatch.setattr(llm_utils, "_is_reasoning_model", lambda _model: False)

    async def run():
        return [chunk async for chunk in llm_utils.call_main_llm_stream(
            task_id="task", model_id="google/gemini-3.8-flash", system_prompt="system",
            message_history=[{"role": "user", "content": "hello"}], temperature=1.0,
            thinking_level="LOW",
        )]

    assert asyncio.run(run()) == ["Answer"]
    assert len(calls) == 1
    assert calls[0].get("thinking_level") == expected_level


def test_call_main_llm_stream_falls_back_after_empty_provider_stream(monkeypatch):
    calls = []

    async def primary_provider(**_kwargs):
        async def _stream():
            yield GoogleUsageMetadata(
                prompt_token_count=10,
                candidates_token_count=0,
                total_token_count=10,
                user_input_tokens=5,
                system_prompt_tokens=5,
            )

        return _stream()

    async def fallback_provider(**_kwargs):
        async def _stream():
            yield "Recovered answer"
            yield GoogleUsageMetadata(
                prompt_token_count=12,
                candidates_token_count=4,
                total_token_count=16,
                user_input_tokens=6,
                system_prompt_tokens=6,
            )

        return _stream()

    def fake_get_provider_client(provider_prefix):
        calls.append(provider_prefix)
        if provider_prefix == "primary":
            return primary_provider
        if provider_prefix == "fallback":
            return fallback_provider
        raise AssertionError(f"Unexpected provider prefix: {provider_prefix}")

    monkeypatch.setattr(llm_utils, "_get_provider_client", fake_get_provider_client)
    monkeypatch.setattr(
        llm_utils,
        "resolve_default_server_from_provider_config",
        lambda model_id: (
            ("primary", "primary/model-a") if model_id == "google/model-a" else (None, None)
        ),
    )
    monkeypatch.setattr(
        llm_utils,
        "resolve_fallback_servers_from_provider_config",
        lambda model_id: ["fallback/model-a"] if model_id == "google/model-a" else [],
    )
    monkeypatch.setattr(llm_utils, "_transform_message_history_for_llm", lambda message_history: message_history)
    monkeypatch.setattr(llm_utils, "_is_reasoning_model", lambda _model_id: False)

    async def consume_stream():
        chunks = []
        stream = llm_utils.call_main_llm_stream(
            task_id="task-1",
            model_id="google/model-a",
            system_prompt="system",
            message_history=[{"role": "user", "content": "hello"}],
            temperature=0.2,
            tools=None,
            tool_choice="auto",
        )
        async for chunk in stream:
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(consume_stream())

    assert calls == ["primary", "fallback"]
    assert isinstance(chunks[0], GoogleUsageMetadata)
    assert chunks[0].candidates_token_count == 0
    assert chunks[1] == "Recovered answer"
    assert isinstance(chunks[2], GoogleUsageMetadata)
    assert chunks[2].candidates_token_count == 4
    assert chunks[0]._normalized_llm_usage.attempt_id != chunks[2]._normalized_llm_usage.attempt_id
    assert len(chunks) == 3


def test_failed_server_is_not_retried_in_same_turn(monkeypatch):
    calls = []
    failed_servers = set()

    async def primary_provider(**_kwargs):
        calls.append("primary")

        async def stream():
            raise TimeoutError("first chunk timed out")
            yield "unreachable"

        return stream()

    async def fallback_provider(**_kwargs):
        calls.append("fallback")

        async def stream():
            yield "Answer"

        return stream()

    monkeypatch.setattr(llm_utils, "_get_provider_client", lambda provider: {
        "primary": primary_provider, "fallback": fallback_provider,
    }[provider])
    monkeypatch.setattr(llm_utils, "resolve_default_server_from_provider_config",
                        lambda _model: ("primary", "primary/model-a"))
    monkeypatch.setattr(llm_utils, "resolve_fallback_servers_from_provider_config",
                        lambda _model: ["fallback/model-a"])
    monkeypatch.setattr(llm_utils, "_transform_message_history_for_llm", lambda history: history)
    monkeypatch.setattr(llm_utils, "_is_reasoning_model", lambda _model: False)

    async def run_once():
        return [chunk async for chunk in llm_utils.call_main_llm_stream(
            task_id="task", model_id="logical/model-a", system_prompt="system",
            message_history=[{"role": "user", "content": "hello"}], temperature=1.0,
            failed_servers_in_turn=failed_servers,
        )]

    assert asyncio.run(run_once()) == ["Answer"]
    assert asyncio.run(run_once()) == ["Answer"]
    assert calls == ["primary", "fallback", "fallback"]
    assert failed_servers == {"primary/model-a"}


def test_call_main_llm_stream_falls_back_after_provider_error_marker(monkeypatch):
    calls = []

    async def primary_provider(**_kwargs):
        async def _stream():
            yield "[ERROR: OpenAI streaming error: Error code: 429 - quota exceeded]"

        return _stream()

    async def fallback_provider(**_kwargs):
        async def _stream():
            yield "Recovered after provider error"

        return _stream()

    def fake_get_provider_client(provider_prefix):
        calls.append(provider_prefix)
        if provider_prefix == "openai":
            return primary_provider
        if provider_prefix == "fallback":
            return fallback_provider
        raise AssertionError(f"Unexpected provider prefix: {provider_prefix}")

    monkeypatch.setattr(llm_utils, "_get_provider_client", fake_get_provider_client)
    monkeypatch.setattr(llm_utils, "resolve_default_server_from_provider_config", lambda _model_id: (None, None))
    monkeypatch.setattr(
        llm_utils,
        "resolve_fallback_servers_from_provider_config",
        lambda model_id: ["fallback/gpt-5.4"] if model_id == "openai/gpt-5.4" else [],
    )
    monkeypatch.setattr(llm_utils, "_transform_message_history_for_llm", lambda message_history: message_history)
    monkeypatch.setattr(llm_utils, "_is_reasoning_model", lambda _model_id: False)

    async def consume_stream():
        chunks = []
        stream = llm_utils.call_main_llm_stream(
            task_id="task-openai-429",
            model_id="openai/gpt-5.4",
            system_prompt="system",
            message_history=[{"role": "user", "content": "hello"}],
            temperature=0.2,
            tools=None,
            tool_choice="auto",
        )
        async for chunk in stream:
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(consume_stream())

    assert calls == ["openai", "fallback"]
    assert chunks == ["Recovered after provider error"]


def test_call_main_llm_stream_falls_back_after_bedrock_image_validation_error(monkeypatch):
    calls = []

    async def primary_provider(**_kwargs):
        raise ValueError(
            "AWS Bedrock API error (ValidationException): The model returned the following "
            "errors: Could not process image."
        )

    async def fallback_provider(**_kwargs):
        async def _stream():
            yield "Recovered via direct Anthropic"

        return _stream()

    def fake_get_provider_client(provider_prefix):
        calls.append(provider_prefix)
        if provider_prefix == "aws_bedrock":
            return primary_provider
        if provider_prefix == "anthropic":
            return fallback_provider
        raise AssertionError(f"Unexpected provider prefix: {provider_prefix}")

    monkeypatch.setattr(llm_utils, "_get_provider_client", fake_get_provider_client)
    monkeypatch.setattr(
        llm_utils,
        "resolve_default_server_from_provider_config",
        lambda model_id: (
            ("aws_bedrock", "aws_bedrock/eu.anthropic.claude-haiku-4-5-20251001-v1:0")
            if model_id == "anthropic/claude-haiku-4-5-20251001"
            else (None, None)
        ),
    )
    monkeypatch.setattr(
        llm_utils,
        "resolve_fallback_servers_from_provider_config",
        lambda model_id: ["anthropic/claude-haiku-4-5-20251001"]
        if model_id == "anthropic/claude-haiku-4-5-20251001"
        else [],
    )
    monkeypatch.setattr(llm_utils, "_transform_message_history_for_llm", lambda message_history: message_history)
    monkeypatch.setattr(llm_utils, "_is_reasoning_model", lambda _model_id: False)

    async def consume_stream():
        chunks = []
        stream = llm_utils.call_main_llm_stream(
            task_id="task-image",
            model_id="anthropic/claude-haiku-4-5-20251001",
            system_prompt="system",
            message_history=[{"role": "user", "content": "look at image"}],
            temperature=0.2,
            tools=None,
            tool_choice="auto",
        )
        async for chunk in stream:
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(consume_stream())

    assert calls == ["aws_bedrock", "anthropic"]
    assert chunks == ["Recovered via direct Anthropic"]


def test_call_main_llm_stream_falls_back_after_gemini_malformed_function_call(monkeypatch):
    calls = []

    async def google_ai_studio_provider(**_kwargs):
        async def _stream():
            yield UnifiedStreamChunk(type=StreamChunkType.THINKING, content="thinking only")
            raise IOError(
                "Google API Unexpected Streaming Error: Gemini returned MALFORMED_FUNCTION_CALL "
                "for model 'gemini-3-flash-preview'. Triggering model fallback."
            )

        return _stream()

    async def google_vertex_provider(**_kwargs):
        async def _stream():
            yield "Recovered via Vertex"

        return _stream()

    def fake_get_provider_client(provider_prefix):
        calls.append(provider_prefix)
        if provider_prefix == "google_ai_studio":
            return google_ai_studio_provider
        if provider_prefix == "google":
            return google_vertex_provider
        raise AssertionError(f"Unexpected provider prefix: {provider_prefix}")

    monkeypatch.setattr(llm_utils, "_get_provider_client", fake_get_provider_client)
    monkeypatch.setattr(
        llm_utils,
        "resolve_default_server_from_provider_config",
        lambda model_id: (
            ("google_ai_studio", "google_ai_studio/gemini-3-flash-preview")
            if model_id == "google/gemini-3-flash-preview"
            else (None, None)
        ),
    )
    monkeypatch.setattr(
        llm_utils,
        "resolve_fallback_servers_from_provider_config",
        lambda model_id: ["google/gemini-3-flash-preview"]
        if model_id == "google/gemini-3-flash-preview"
        else [],
    )
    monkeypatch.setattr(llm_utils, "_transform_message_history_for_llm", lambda message_history: message_history)
    monkeypatch.setattr(llm_utils, "_is_reasoning_model", lambda _model_id: True)

    async def consume_stream():
        chunks = []
        stream = llm_utils.call_main_llm_stream(
            task_id="task-gemini-malformed",
            model_id="google/gemini-3-flash-preview",
            system_prompt="system",
            message_history=[{"role": "user", "content": "hello"}],
            temperature=0.2,
            tools=[{"type": "function", "function": {"name": "web-search", "parameters": {"type": "object"}}}],
            tool_choice="auto",
        )
        async for chunk in stream:
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(consume_stream())

    assert calls == ["google_ai_studio", "google"]
    assert chunks[0].type == StreamChunkType.THINKING
    assert chunks[1] == "Recovered via Vertex"


def test_call_main_llm_stream_skips_stripped_signature_retry_on_google_only_servers(monkeypatch):
    calls = []
    captured_messages = []

    async def google_ai_studio_provider(**kwargs):
        calls.append("google_ai_studio")
        captured_messages.append(kwargs["messages"])
        raise ValueError(
            "Google API Error: 400 Bad Request. Function call web-read is missing or has invalid thought signature."
        )

    async def google_provider(**kwargs):
        calls.append("google")
        captured_messages.append(kwargs["messages"])
        raise AssertionError("Native Google fallback should not receive stripped thought signatures")

    def fake_get_provider_client(provider_prefix):
        if provider_prefix == "google_ai_studio":
            return google_ai_studio_provider
        if provider_prefix == "google":
            return google_provider
        raise AssertionError(f"Unexpected provider prefix: {provider_prefix}")

    monkeypatch.setattr(llm_utils, "_get_provider_client", fake_get_provider_client)
    monkeypatch.setattr(
        llm_utils,
        "resolve_default_server_from_provider_config",
        lambda model_id: (
            ("google_ai_studio", "google_ai_studio/gemini-3-flash-preview")
            if model_id == "google/gemini-3-flash-preview"
            else (None, None)
        ),
    )
    monkeypatch.setattr(
        llm_utils,
        "resolve_fallback_servers_from_provider_config",
        lambda model_id: ["google/gemini-3-flash-preview"]
        if model_id == "google/gemini-3-flash-preview"
        else [],
    )
    monkeypatch.setattr(llm_utils, "_transform_message_history_for_llm", lambda message_history: message_history)
    monkeypatch.setattr(llm_utils, "_is_reasoning_model", lambda _model_id: True)

    message_history = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "web-read-1",
                    "type": "function",
                    "function": {"name": "web-read", "arguments": "{}"},
                    "thought_signature": "valid-until-google-rejects-it",
                }
            ],
        },
        {"role": "tool", "tool_call_id": "web-read-1", "name": "web-read", "content": "{}"},
    ]

    async def consume_stream():
        stream = llm_utils.call_main_llm_stream(
            task_id="task-thought-sig",
            model_id="google/gemini-3-flash-preview",
            system_prompt="system",
            message_history=message_history,
            temperature=0.2,
            tools=[{"type": "function", "function": {"name": "web-read", "parameters": {"type": "object"}}}],
            tool_choice="auto",
        )
        async for _chunk in stream:
            pass

    with pytest.raises(AllServersFailedError):
        asyncio.run(consume_stream())

    assert calls == ["google_ai_studio"]
    assert captured_messages[0][1]["tool_calls"][0]["thought_signature"] == "valid-until-google-rejects-it"


def test_google_streamed_tool_call_records_signature_provider_affinity():
    tool_call = _parse_streamed_google_tool_call(
        SimpleNamespace(name="events-search", args={"location": "Berlin"}),
        function_call_thought_signature=b"vertex-signature",
        candidate_thought_signature=None,
        signature_provider_id="google",
    )

    assert tool_call.thought_signature == "dmVydGV4LXNpZ25hdHVyZQ=="
    assert tool_call.provider_transport_state == {
        GOOGLE_THOUGHT_SIGNATURE_PROVIDER_STATE_KEY: "google"
    }


def test_call_main_llm_stream_routes_signed_tool_continuation_to_origin_server(monkeypatch):
    calls = []
    captured_messages = []

    async def google_vertex_provider(**kwargs):
        calls.append("google")
        captured_messages.append(kwargs["messages"])

        async def _stream():
            yield "Recovered on signature origin"

        return _stream()

    def fake_get_provider_client(provider_prefix):
        if provider_prefix == "google_ai_studio":
            raise AssertionError("AI Studio must not receive a Vertex thought signature")
        if provider_prefix == "google":
            return google_vertex_provider
        raise AssertionError(f"Unexpected provider prefix: {provider_prefix}")

    monkeypatch.setattr(llm_utils, "_get_provider_client", fake_get_provider_client)
    monkeypatch.setattr(
        llm_utils,
        "resolve_default_server_from_provider_config",
        lambda model_id: (
            ("google_ai_studio", "google_ai_studio/gemini-3-flash-preview")
            if model_id == "google/gemini-3-flash-preview"
            else (None, None)
        ),
    )
    monkeypatch.setattr(
        llm_utils,
        "resolve_fallback_servers_from_provider_config",
        lambda model_id: ["google/gemini-3-flash-preview"]
        if model_id == "google/gemini-3-flash-preview"
        else [],
    )
    monkeypatch.setattr(llm_utils, "_is_reasoning_model", lambda _model_id: True)

    message_history = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "events-search-1",
                    "type": "function",
                    "function": {"name": "events-search", "arguments": "{}"},
                    "thought_signature": "vertex-signature",
                    "provider_transport_state": {
                        GOOGLE_THOUGHT_SIGNATURE_PROVIDER_STATE_KEY: "google"
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "events-search-1",
            "name": "events-search",
            "content": "{}",
        },
    ]

    async def consume_stream():
        chunks = []
        stream = llm_utils.call_main_llm_stream(
            task_id="task-vertex-affinity",
            model_id="google/gemini-3-flash-preview",
            system_prompt="system",
            message_history=message_history,
            temperature=0.2,
            tools=[{"type": "function", "function": {"name": "events-search", "parameters": {"type": "object"}}}],
            tool_choice="auto",
        )
        async for chunk in stream:
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(consume_stream())

    assert chunks == ["Recovered on signature origin"]
    assert calls == ["google"]
    assert captured_messages[0][1]["tool_calls"][0]["thought_signature"] == "vertex-signature"


def test_call_main_llm_stream_strips_google_thought_signatures_for_non_google_fallback(monkeypatch):
    calls = []
    captured_messages_by_provider = {}
    admissions = []
    admitted_limits = {}
    resolved_hosts = []

    def get_pricing(_provider, _model, *, inference_host, region):
        resolved_hosts.append((inference_host, region))
        return {"pricing": {"tokens": {"input": {"per_credit_unit": 1000},
                                        "output": {"per_credit_unit": 100}}}}

    monkeypatch.setattr(llm_utils.config_manager, "get_model_pricing", get_pricing)

    async def admit(server_model_id, current_limit, *, tariff_snapshot, region):
        assert tariff_snapshot["pricing"]["tokens"]["input"]["per_credit_unit"] == 1000
        assert region is None
        admissions.append(server_model_id)
        return 5 if server_model_id.startswith("fallback/") else current_limit

    async def google_ai_studio_provider(**kwargs):
        calls.append("google_ai_studio")
        captured_messages_by_provider["google_ai_studio"] = kwargs["messages"]
        admitted_limits["google_ai_studio"] = kwargs["max_tokens"]
        raise ValueError("Thought signature is not valid")

    async def fallback_provider(**kwargs):
        calls.append("fallback")
        captured_messages_by_provider["fallback"] = kwargs["messages"]
        admitted_limits["fallback"] = kwargs["max_tokens"]

        async def _stream():
            yield "Recovered answer"

        return _stream()

    def fake_get_provider_client(provider_prefix):
        if provider_prefix == "google_ai_studio":
            return google_ai_studio_provider
        if provider_prefix == "fallback":
            return fallback_provider
        raise AssertionError(f"Unexpected provider prefix: {provider_prefix}")

    monkeypatch.setattr(llm_utils, "_get_provider_client", fake_get_provider_client)
    monkeypatch.setattr(
        llm_utils,
        "resolve_default_server_from_provider_config",
        lambda model_id: (
            ("google_ai_studio", "google_ai_studio/gemini-3-flash-preview")
            if model_id == "google/gemini-3-flash-preview"
            else (None, None)
        ),
    )
    monkeypatch.setattr(
        llm_utils,
        "resolve_fallback_servers_from_provider_config",
        lambda model_id: ["fallback/neutral-model"] if model_id == "google/gemini-3-flash-preview" else [],
    )
    monkeypatch.setattr(llm_utils, "_transform_message_history_for_llm", lambda message_history: message_history)
    monkeypatch.setattr(llm_utils, "_is_reasoning_model", lambda _model_id: True)

    message_history = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "web-read-1",
                    "type": "function",
                    "function": {"name": "web-read", "arguments": "{}"},
                    "thought_signature": "google-only-signature",
                }
            ],
        },
        {"role": "tool", "tool_call_id": "web-read-1", "name": "web-read", "content": "{}"},
    ]

    async def consume_stream():
        chunks = []
        stream = llm_utils.call_main_llm_stream(
            task_id="task-non-google-fallback",
            model_id="google/gemini-3-flash-preview",
            system_prompt="system",
            message_history=message_history,
            temperature=0.2,
            tools=[{"type": "function", "function": {"name": "web-read", "parameters": {"type": "object"}}}],
            tool_choice="auto",
            max_tokens=10,
            pre_dispatch_admission=admit,
        )
        async for chunk in stream:
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(consume_stream())

    assert chunks == ["Recovered answer"]
    assert calls == ["google_ai_studio", "fallback"]
    assert admissions == ["google_ai_studio/gemini-3-flash-preview", "fallback/neutral-model"]
    assert resolved_hosts == [("google_ai_studio", None), ("fallback", None)]
    assert admitted_limits == {"google_ai_studio": 10, "fallback": 5}
    assert (
        captured_messages_by_provider["google_ai_studio"][1]["tool_calls"][0]["thought_signature"]
        == "google-only-signature"
    )
    assert "thought_signature" not in captured_messages_by_provider["fallback"][1]["tool_calls"][0]
    assert "provider_transport_state" not in captured_messages_by_provider["fallback"][1]["tool_calls"][0]


@pytest.mark.parametrize("fallback", ["openai", "openrouter", "google_ai_studio"])
def test_mistral_thinking_replay_is_removed_for_foreign_fallback(monkeypatch, fallback):
    captured = {}

    async def primary(**kwargs):
        captured["mistral"] = kwargs["messages"]
        raise ValueError("timeout waiting for first chunk")

    async def recovered(**kwargs):
        captured[fallback] = kwargs["messages"]

        async def stream():
            yield "Recovered answer"

        return stream()

    monkeypatch.setattr(llm_utils, "_get_provider_client", lambda provider: primary if provider == "mistral" else recovered)
    monkeypatch.setattr(llm_utils, "resolve_default_server_from_provider_config", lambda _: ("mistral", "mistral/mistral-large-4"))
    monkeypatch.setattr(llm_utils, "resolve_fallback_servers_from_provider_config", lambda _: [f"{fallback}/model"])
    monkeypatch.setattr(llm_utils, "_is_reasoning_model", lambda _: True)

    state = {"mistral_thinking": [{"type": "thinking", "thinking": [{"type": "text", "text": "Reasoning"}]}]}
    messages = [
        {"role": "assistant", "content": "Checking", "tool_calls": [{
            "id": "search-1", "type": "function", "function": {"name": "search", "arguments": "{}"},
            "provider_transport_state": state,
        }]},
        {"role": "tool", "tool_call_id": "search-1", "content": "Result"},
    ]

    async def run():
        return [chunk async for chunk in llm_utils.call_main_llm_stream(
            task_id="mistral-fallback", model_id="mistral/mistral-large-4", system_prompt="system",
            message_history=messages, temperature=0.2, tools=None, tool_choice="auto",
        )]

    assert asyncio.run(run()) == ["Recovered answer"]
    assert captured["mistral"][1]["tool_calls"][0]["provider_transport_state"] == state
    assert "provider_transport_state" not in captured[fallback][1]["tool_calls"][0]
    assert messages[0]["tool_calls"][0]["provider_transport_state"] == state


# contract-test: supporting surface=rest_api assertions=billing.models.scheduled-temporary-tariffs,billing.models.immutable-attempt-tariffs
def test_stream_fallback_freezes_actual_host_tariff_before_each_dispatch(monkeypatch):
    prices = []
    snapshots = []
    admitted_snapshots = []
    admitted_quotes = []
    mutable_pricing = {
        "pricing": {"tokens": {"input": {"per_credit_unit": 1000},
                                 "output": {"per_credit_unit": 100}}},
        "costs": {},
        "features": {"max_output_tokens": 1000},
        "active_temporary_price": {"id": "intro"},
    }

    def pricing(_provider, _model, *, inference_host, region):
        assert _provider == "google"
        assert _model == "gemini-4-argon"
        prices.append((inference_host, region))
        mutable_pricing["pricing"]["tokens"]["output"]["per_credit_unit"] = (
            200 if inference_host == "google_ai_studio" else 100
        )
        return mutable_pricing

    async def admit(server_model_id, current_limit, *, tariff_snapshot, region):
        from backend.apps.ai.processing.main_processor import _quote_ai_iteration_credits

        assert region == "global"
        # Reload rates inside admission, before its reservation quote is built.
        mutable_pricing["pricing"]["tokens"]["output"]["per_credit_unit"] = 1
        admitted_snapshots.append(tariff_snapshot)
        admitted_quotes.append(_quote_ai_iteration_credits(
            model_id="google/gemini-4-argon", system_prompt="system",
            message_history=[{"role": "user", "content": "hello"}], tools=[],
            output_token_limit=current_limit,
            inference_host=server_model_id.split("/", 1)[0],
            tariff_snapshot=tariff_snapshot, region=region,
        ))
        return current_limit

    def provider(host):
        async def invoke(**_kwargs):
            assert prices[-1] == (host, "global")
            # An offer ending or a hot reload after dispatch cannot change receipts.
            mutable_pricing["pricing"]["tokens"]["output"]["per_credit_unit"] = 1

            async def stream():
                yield GoogleUsageMetadata(prompt_token_count=10, candidates_token_count=5)
                if host == "google_ai_studio":
                    yield "[ERROR 503 provider failed]"
                else:
                    yield "Recovered"

            return stream()
        return invoke

    monkeypatch.setattr(llm_utils.config_manager, "get_model_pricing", pricing)
    monkeypatch.setattr(llm_utils, "_configured_server_region", lambda *_args: "global")
    monkeypatch.setattr(llm_utils, "_get_provider_client", provider)
    monkeypatch.setattr(llm_utils, "resolve_default_server_from_provider_config",
                        lambda _: ("google_ai_studio", "google_ai_studio/gemini-4-argon"))
    monkeypatch.setattr(llm_utils, "resolve_fallback_servers_from_provider_config",
                        lambda _: ["google/gemini-4-argon"])
    monkeypatch.setattr(llm_utils, "_transform_message_history_for_llm", lambda history: history)
    monkeypatch.setattr(llm_utils, "_is_reasoning_model", lambda _: True)

    async def run():
        return [chunk async for chunk in llm_utils.call_main_llm_stream(
            task_id="task", model_id="google/gemini-4-argon", system_prompt="system",
            message_history=[{"role": "user", "content": "hello"}], temperature=1.0,
            max_tokens=1000, pre_dispatch_admission=admit,
        )]

    chunks = asyncio.run(run())
    for chunk in chunks:
        if isinstance(chunk, GoogleUsageMetadata):
            snapshots.append(chunk._normalized_llm_usage.tariff_snapshot)
    assert prices == [("google_ai_studio", "global"), ("google", "global")]
    assert [snapshot["pricing"]["tokens"]["output"]["per_credit_unit"]
            for snapshot in snapshots] == [200, 100]
    assert all(snapshot["active_temporary_price"] == {"id": "intro"} for snapshot in snapshots)
    assert snapshots == admitted_snapshots
    assert admitted_quotes == [5, 10]


@pytest.mark.parametrize("host,level,expected", [
    ("google_ai_studio", "LOW", "LOW"), ("google", "MEDIUM", "MEDIUM"),
    ("google", "HIGH", "HIGH"), ("openrouter/google", "LOW", None),
])
def test_argon_explicit_thinking_levels_only_reach_matching_native_route(host, level, expected):
    assert llm_utils._google_profile_thinking_level(
        "google/gemini-4-argon", f"{host}/gemini-4-argon", level,
    ) == expected


# contract-test: supporting surface=rest_api assertions=billing.models.immutable-attempt-tariffs
def test_non_chat_scope_retains_resolved_temporary_tariff_identity():
    pricing = {
        "pricing": {"tokens": {"input": {"per_credit_unit": 2000},
                                 "output": {"per_credit_unit": 200}}},
        "cache_pricing": {"enabled": True},
        "pricing_version": "resolved-introductory-price",
        "active_temporary_price": {"id": "intro", "ends_on": "2026-11-30"},
    }
    frozen = llm_utils._snapshot_for_customer_scope(pricing, cache_pricing_enabled=False)
    assert frozen["pricing"]["tokens"]["input"]["per_credit_unit"] == 2000
    assert frozen["cache_pricing"]["enabled"] is False
    assert frozen["pricing_version"] == "resolved-introductory-price"
    assert frozen["active_temporary_price"] == pricing["active_temporary_price"]
    assert pricing["cache_pricing"]["enabled"] is True


@pytest.mark.parametrize("phase", ["credentials", "metadata"])
def test_mercury_first_output_deadline_includes_setup_and_ignores_metadata(phase):
    closed = []
    async def provider(**_):
        if phase == "credentials":
            try:
                await asyncio.sleep(1)
            finally:
                closed.append("credentials")
        async def stream():
            try:
                while True:
                    yield UnifiedStreamChunk(type=StreamChunkType.THINKING, content="reasoning")
                    await asyncio.sleep(.005)
            finally:
                closed.append("stream")
        return stream()
    async def run():
        with pytest.raises(TimeoutError):
            _ = [chunk async for chunk in llm_utils._dispatch_with_substantive_deadline(provider, {}, .025)]
    asyncio.run(run())
    assert closed == ["credentials" if phase == "credentials" else "stream"]


def test_mercury_deadline_stops_after_substantive_output_and_closes_on_cancel():
    closed = []
    async def provider(**_):
        async def stream():
            try:
                yield "first"
                await asyncio.sleep(.03)
                yield "later"
            finally:
                closed.append(True)
        return stream()
    async def run():
        return [chunk async for chunk in llm_utils._dispatch_with_substantive_deadline(provider, {}, .01)]
    assert asyncio.run(run()) == ["first", "later"]
    assert closed == [True]
    closed.clear()
    async def cancel():
        stream = llm_utils._dispatch_with_substantive_deadline(provider, {}, .01)
        assert await anext(stream) == "first"
        await stream.aclose()
    asyncio.run(cancel())
    assert closed == [True]


@pytest.fixture
def reasoning_catalog(monkeypatch):
    """Use source capabilities independently of container-only config mounts."""
    providers = Path(__file__).resolve().parents[1] / "providers"
    monkeypatch.setattr(llm_utils.config_manager, "_provider_configs", {
        provider: yaml.safe_load((providers / f"{provider}.yml").read_text())
        for provider in ("google", "inception")
    })


@pytest.mark.parametrize("requested,native", [(None, "medium"), ("LOW", "low"), ("MEDIUM", "medium"), ("HIGH", "high"), ("EXTRA_HIGH", "high")])
def test_mercury_timeout_preserves_usage_and_enables_gemini_low_fallback(monkeypatch, reasoning_catalog, requested, native):
    from backend.apps.ai.llm_providers.openai_shared import OpenAIUsageMetadata
    closed, calls, chunks = [], [], []
    async def provider(**arguments):
        calls.append(arguments)
        async def stream():
            try:
                yield OpenAIUsageMetadata(input_tokens=7, output_tokens=0, total_tokens=7)
                await asyncio.sleep(1)
            finally:
                closed.append(True)
        return stream()
    monkeypatch.setattr(llm_utils, "_get_provider_client", lambda _: provider)
    monkeypatch.setattr(llm_utils, "resolve_default_server_from_provider_config", lambda _: ("inception", "inception/mercury-3"))
    monkeypatch.setattr(llm_utils, "resolve_fallback_servers_from_provider_config", lambda _: [])
    monkeypatch.setattr(llm_utils, "_transform_message_history_for_llm", lambda history: history)
    async def run():
        with pytest.raises(AllServersFailedError):
            async for chunk in llm_utils.call_main_llm_stream(
                task_id="task", model_id="inception/mercury-3", system_prompt="system",
                message_history=[{"role": "user", "content": "hello"}], temperature=.7,
                first_substantive_timeout_seconds=.025, requested_reasoning_level=requested,
            ):
                chunks.append(chunk)
    asyncio.run(run())
    assert calls[0]["reasoning_effort"] == native
    assert closed == [True]
    assert len(chunks) == 1 and chunks[0].input_tokens == 7
    assert chunks[0]._normalized_llm_usage.model_id == "inception/mercury-3"
    assert llm_utils._google_profile_thinking_level("google/gemini-3.8-flash", "google_ai_studio/gemini-3.8-flash", "LOW") == "LOW"


def test_mercury_failure_after_text_does_not_trigger_clean_model_restart(monkeypatch):
    calls = []
    async def provider(**arguments):
        calls.append(arguments)
        async def stream():
            yield "published prefix"
            raise IOError("transport failure")
        return stream()
    monkeypatch.setattr(llm_utils, "_get_provider_client", lambda _: provider)
    monkeypatch.setattr(llm_utils, "resolve_default_server_from_provider_config", lambda _: ("inception", "inception/mercury-3"))
    monkeypatch.setattr(llm_utils, "resolve_fallback_servers_from_provider_config", lambda _: [])
    monkeypatch.setattr(llm_utils, "_transform_message_history_for_llm", lambda history: history)
    async def run():
        return [chunk async for chunk in llm_utils.call_main_llm_stream(
            task_id="task", model_id="inception/mercury-3", system_prompt="system",
            message_history=[{"role": "user", "content": "hello"}], temperature=.7,
            first_substantive_timeout_seconds=.025,
        )]
    chunks = asyncio.run(run())
    assert chunks[0] == "published prefix"
    assert chunks[1] == llm_utils.STANDARDIZED_USER_ERROR_MESSAGE
    assert len(calls) == 1


def test_automatic_low_dispatch_never_uses_disabled_google_server(monkeypatch):
    calls = []
    async def provider(**arguments):
        async def stream():
            yield "allowed answer"
        return stream()
    def get_provider(prefix):
        async def selected(**arguments):
            calls.append((prefix, arguments))
            return await provider(**arguments)
        return selected
    monkeypatch.setattr(llm_utils, "_get_provider_client", get_provider)
    monkeypatch.setattr(llm_utils, "resolve_default_server_from_provider_config", lambda _: ("google_ai_studio", "google_ai_studio/gemini-3.8-flash"))
    monkeypatch.setattr(llm_utils, "resolve_fallback_servers_from_provider_config", lambda _: ["google/gemini-3.8-flash"])
    monkeypatch.setattr(llm_utils, "_transform_message_history_for_llm", lambda history: history)
    async def run(allowed):
        return [chunk async for chunk in llm_utils.call_main_llm_stream(
            task_id="test", model_id="google/gemini-3.8-flash", system_prompt="system",
            message_history=[{"role": "user", "content": "hello"}], temperature=.7,
            thinking_level="LOW", allowed_server_ids=allowed,
        )]
    assert asyncio.run(run({"google"})) == ["allowed answer"]
    assert len(calls) == 1 and calls[0][0] == "google"
    calls.clear()
    with pytest.raises(AllServersFailedError, match="No permitted"):
        asyncio.run(run(set()))
    assert calls == []


def test_automatic_mercury_missing_key_returns_clean_model_fallback_signal(monkeypatch):
    from backend.apps.ai.llm_providers.inception_client import invoke_inception_chat_completions
    from unittest.mock import AsyncMock
    monkeypatch.delenv("SECRET__INCEPTION_LABS__API_KEY", raising=False)
    class NoHealthCache:
        @property
        async def client(self):
            return None
    monkeypatch.setattr(llm_utils, "CacheService", NoHealthCache)
    monkeypatch.setattr(llm_utils, "_get_provider_client", lambda _: invoke_inception_chat_completions)
    monkeypatch.setattr(llm_utils, "resolve_default_server_from_provider_config", lambda _: ("inception", "inception/mercury-3"))
    monkeypatch.setattr(llm_utils, "resolve_fallback_servers_from_provider_config", lambda _: [])
    monkeypatch.setattr(llm_utils, "_transform_message_history_for_llm", lambda history: history)
    secrets = SimpleNamespace(get_secret=AsyncMock(return_value=None))
    async def run():
        return [chunk async for chunk in llm_utils.call_main_llm_stream(
            task_id="test", model_id="inception/mercury-3", system_prompt="system",
            message_history=[{"role": "user", "content": "Hello"}], temperature=.7,
            secrets_manager=secrets, first_substantive_timeout_seconds=5,
        )]
    with pytest.raises(AllServersFailedError):
        asyncio.run(run())
    secrets.get_secret.assert_awaited_once_with(secret_path="kv/data/providers/inception_labs", secret_key="api_key")


# contract-test: supporting surface=rest_api assertions=ai-model-routing.reasoning.preprocessor-recommendation
@pytest.mark.parametrize("model,server,recommendation,expected", [
    ("inception/mercury-3", "inception/mercury-3", None, {"reasoning_effort": "medium"}),
    ("inception/mercury-3", "inception/mercury-3", "EXTRA_HIGH", {"reasoning_effort": "high"}),
    ("google/gemini-3.8-flash", "google_ai_studio/gemini-3.8-flash", "EXTRA_HIGH", {"thinking_level": "HIGH"}),
    ("google/gemini-3.8-flash", "google/gemini-3.8-flash", "LOW", {"thinking_level": "LOW"}),
    ("google/gemini-3.8-flash", "openrouter/google/gemini-3.8-flash", "EXTRA_HIGH", {}),
])
def test_main_reasoning_recommendation_is_resolved_per_actual_server(monkeypatch, reasoning_catalog, model, server, recommendation, expected):
    calls = []
    async def provider(**kwargs):
        calls.append(kwargs)
        async def stream():
            yield "Answer"
        return stream()
    monkeypatch.setattr(llm_utils, "_get_provider_client", lambda _: provider)
    monkeypatch.setattr(llm_utils, "resolve_default_server_from_provider_config", lambda _: (server.split("/", 1)[0], server))
    monkeypatch.setattr(llm_utils, "resolve_fallback_servers_from_provider_config", lambda _: [])
    monkeypatch.setattr(llm_utils, "_transform_message_history_for_llm", lambda history: history)
    async def run():
        return [chunk async for chunk in llm_utils.call_main_llm_stream(
            task_id="task", model_id=model, system_prompt="system", message_history=[],
            temperature=.7, requested_reasoning_level=recommendation,
        )]
    assert asyncio.run(run()) == ["Answer"]
    assert {key: calls[0][key] for key in ("reasoning_effort", "thinking_level") if key in calls[0]} == expected


def test_mercury_high_deadline_is_not_shortened_by_generic_watchdogs(monkeypatch, reasoning_catalog):
    observed = []
    async def provider(**_):
        async def stream():
            yield "answer"
        return stream()
    async def watchdog(stream, first, inter):
        observed.append((first, inter))
        async for chunk in stream:
            yield chunk
    monkeypatch.setattr(llm_utils, "_get_provider_client", lambda _: provider)
    monkeypatch.setattr(llm_utils, "resolve_default_server_from_provider_config", lambda _: ("inception", "inception/mercury-3"))
    monkeypatch.setattr(llm_utils, "resolve_fallback_servers_from_provider_config", lambda _: [])
    monkeypatch.setattr(llm_utils, "get_first_chunk_timeout_seconds", lambda **_: 15.)
    monkeypatch.setattr(llm_utils, "get_inter_chunk_timeout_seconds", lambda **_: 45.)
    monkeypatch.setattr(llm_utils, "stream_with_first_chunk_timeout", watchdog)
    async def run():
        return [chunk async for chunk in llm_utils.call_main_llm_stream(
            task_id="test", model_id="inception/mercury-3", system_prompt="system", message_history=[],
            temperature=.7, requested_reasoning_level="HIGH", first_substantive_timeout_seconds=60.,
        )]
    assert asyncio.run(run()) == ["answer"]
    assert observed == [(60., 60.)]
