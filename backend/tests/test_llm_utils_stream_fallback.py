# backend/tests/test_llm_utils_stream_fallback.py
#
# Purpose: cover main-stream fallback behavior when a provider stream connects
# but returns no text or tool calls.
# Architecture: verifies backend/apps/ai/utils/llm_utils.py keeps empty streams
# on the server side and falls back before stream_consumer emits a user error.
# Docs: docs/architecture/logging/ and docs/architecture/health-checks/.
# Test refs: backend/apps/ai/utils/llm_utils.py, issue ef17cb0d-a1bd-4898-a27b-09ee2d2c8102.

import asyncio

import pytest

try:
    from backend.apps.ai.llm_providers.google_client import GoogleUsageMetadata
    from backend.apps.ai.utils import llm_utils
except ImportError:
    pytestmark = pytest.mark.skip(reason="Backend AI dependencies not installed (google-genai, tiktoken, etc.)")
    AllServersFailedError = None  # type: ignore[assignment]
    GoogleUsageMetadata = None  # type: ignore[assignment, misc]
    llm_utils = None  # type: ignore[assignment]
else:
    AllServersFailedError = llm_utils.AllServersFailedError


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
    assert chunks[0] == "Recovered answer"
    assert isinstance(chunks[1], GoogleUsageMetadata)
    assert chunks[1].candidates_token_count == 4
    assert len(chunks) == 2


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


def test_call_main_llm_stream_strips_google_thought_signatures_for_non_google_fallback(monkeypatch):
    calls = []
    captured_messages_by_provider = {}

    async def google_ai_studio_provider(**kwargs):
        calls.append("google_ai_studio")
        captured_messages_by_provider["google_ai_studio"] = kwargs["messages"]
        raise ValueError("timeout waiting for first chunk")

    async def fallback_provider(**kwargs):
        calls.append("fallback")
        captured_messages_by_provider["fallback"] = kwargs["messages"]

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
        )
        async for chunk in stream:
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(consume_stream())

    assert chunks == ["Recovered answer"]
    assert calls == ["google_ai_studio", "fallback"]
    assert (
        captured_messages_by_provider["google_ai_studio"][1]["tool_calls"][0]["thought_signature"]
        == "google-only-signature"
    )
    assert "thought_signature" not in captured_messages_by_provider["fallback"][1]["tool_calls"][0]
