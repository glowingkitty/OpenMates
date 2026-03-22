# backend/tests/test_llm_utils_stream_fallback.py
#
# Purpose: cover main-stream fallback behavior when a provider stream connects
# but returns no text or tool calls.
# Architecture: verifies backend/apps/ai/utils/llm_utils.py keeps empty streams
# on the server side and falls back before stream_consumer emits a user error.
# Docs: docs/architecture/logging/ and docs/architecture/health-checks/.
# Test refs: backend/apps/ai/utils/llm_utils.py, issue ef17cb0d-a1bd-4898-a27b-09ee2d2c8102.

import asyncio

from backend.apps.ai.llm_providers.google_client import GoogleUsageMetadata
from backend.apps.ai.utils import llm_utils


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
