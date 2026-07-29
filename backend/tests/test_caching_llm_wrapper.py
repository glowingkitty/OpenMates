# backend/tests/test_caching_llm_wrapper.py
#
# Purpose: verify the live-mock LLM cache wrapper preserves provider call contracts.
# Providers are awaited by llm_utils and resolve to stream iterators for streaming calls.
# A cached stream must therefore be returned from an awaitable wrapper, not directly.
# This protects Playwright chat specs that run through live mock/cached AI responses.
# See: backend/apps/ai/testing/caching_llm_wrapper.py.

import asyncio

from backend.apps.ai.testing.caching_llm_wrapper import wrap_provider_with_cache
from backend.apps.ai.llm_providers.openai_shared import OpenAIUsageMetadata, ParsedOpenAIToolCall
from backend.shared.testing.api_response_cache import ApiResponseCache
from backend.shared.testing.mock_context import activate_mock_mode, deactivate_mock_mode


class FakeCache:
    def fingerprint_llm_call(self, **_kwargs):
        return "cached-fingerprint"

    def load(self, group_id, category, fingerprint):
        assert group_id == "fork-conversation"
        assert category == "llm/test-model"
        assert fingerprint == "cached-fingerprint"
        return {"response": {"type": "stream", "body": "alpha"}}

    def save(self, **_kwargs):
        raise AssertionError("mock replay should not save cache entries")


class FakeRecordCache(FakeCache):
    def __init__(self):
        self.saved_response = None

    def load(self, group_id, category, fingerprint):
        assert group_id == "fork-conversation"
        assert category == "llm/test-model"
        assert fingerprint == "cached-fingerprint"
        return None

    def save(self, **kwargs):
        self.saved_response = kwargs["response_data"]


class FakeSavedResponseCache(FakeCache):
    def __init__(self, response_data):
        self.response_data = response_data

    def load(self, group_id, category, fingerprint):
        assert group_id == "fork-conversation"
        assert category == "llm/test-model"
        assert fingerprint == "cached-fingerprint"
        return {"response": self.response_data}


class FakeFallbackCache(FakeCache):
    def __init__(self):
        self.fallback_summary = None
        self.excluded_fingerprint = None

    def load(self, group_id, category, fingerprint):
        assert group_id == "fork-conversation"
        assert category == "llm/test-model"
        assert fingerprint == "cached-fingerprint"
        return None

    def load_compatible_llm_response(self, group_id, category, request_summary, excluded_fingerprint=None):
        assert group_id == "fork-conversation"
        assert category == "llm/test-model"
        self.fallback_summary = request_summary
        self.excluded_fingerprint = excluded_fingerprint
        return {"response": {"type": "stream", "body": "fallback"}}


def test_cached_stream_provider_remains_awaitable():
    provider_calls = 0

    async def provider_fn(**_kwargs):
        nonlocal provider_calls
        provider_calls += 1

        async def _stream():
            yield "real"

        return _stream()

    async def exercise_wrapper():
        activate_mock_mode("mock", "fork-conversation")
        try:
            wrapped_provider = wrap_provider_with_cache(provider_fn, FakeCache())
            chunk_stream = await wrapped_provider(
                model="test-model",
                messages=[{"role": "user", "content": "Reply with alpha"}],
                stream=True,
            )
            return [chunk async for chunk in chunk_stream]
        finally:
            deactivate_mock_mode()

    assert asyncio.run(exercise_wrapper()) == ["alpha"]
    assert provider_calls == 0


def test_cached_stream_provider_accepts_model_id_alias():
    provider_calls = 0

    async def provider_fn(**_kwargs):
        nonlocal provider_calls
        provider_calls += 1

        async def _stream():
            yield "real"

        return _stream()

    async def exercise_wrapper():
        activate_mock_mode("mock", "fork-conversation")
        try:
            wrapped_provider = wrap_provider_with_cache(provider_fn, FakeCache())
            chunk_stream = await wrapped_provider(
                model_id="test-model",
                messages=[{"role": "user", "content": "Reply with alpha"}],
                stream=True,
            )
            return [chunk async for chunk in chunk_stream]
        finally:
            deactivate_mock_mode()

    assert asyncio.run(exercise_wrapper()) == ["alpha"]
    assert provider_calls == 0


def test_cached_stream_provider_uses_compatible_fallback_on_fingerprint_miss():
    provider_calls = 0
    cache = FakeFallbackCache()

    async def provider_fn(**_kwargs):
        nonlocal provider_calls
        provider_calls += 1

        async def _stream():
            yield "real"

        return _stream()

    async def exercise_wrapper():
        activate_mock_mode("mock", "fork-conversation")
        try:
            wrapped_provider = wrap_provider_with_cache(provider_fn, cache)
            chunk_stream = await wrapped_provider(
                model="test-model",
                messages=[{"role": "user", "content": "Find 3D printable benchy models"}],
                tools=[{"type": "function"}],
                temperature=0.4,
                tool_choice="auto",
                stream=True,
            )
            return [chunk async for chunk in chunk_stream]
        finally:
            deactivate_mock_mode()

    assert asyncio.run(exercise_wrapper()) == ["fallback"]
    assert provider_calls == 0
    assert cache.excluded_fingerprint == "cached-fingerprint"
    assert cache.fallback_summary == {
        "model": "test-model",
        "messages_count": 1,
        "tools_count": 1,
        "temperature": 0.4,
        "tool_choice": "auto",
        "last_message_preview": {"role": "user", "content": "Find 3D printable benchy models"},
    }


def test_inactive_stream_provider_awaits_real_provider_before_iterating():
    provider_calls = 0

    async def provider_fn(**_kwargs):
        nonlocal provider_calls
        provider_calls += 1

        async def _stream():
            yield "real"

        return _stream()

    async def exercise_wrapper():
        deactivate_mock_mode()
        wrapped_provider = wrap_provider_with_cache(provider_fn, FakeCache())
        chunk_stream = await wrapped_provider(
            model="test-model",
            messages=[{"role": "user", "content": "Reply with alpha"}],
            stream=True,
        )
        return [chunk async for chunk in chunk_stream]

    assert asyncio.run(exercise_wrapper()) == ["real"]
    assert provider_calls == 1


def test_record_stream_provider_awaits_real_provider_before_iterating_and_saving():
    provider_calls = 0
    cache = FakeRecordCache()

    async def provider_fn(**_kwargs):
        nonlocal provider_calls
        provider_calls += 1

        async def _stream():
            yield "rec"
            yield "orded"

        return _stream()

    async def exercise_wrapper():
        activate_mock_mode("record", "fork-conversation")
        try:
            wrapped_provider = wrap_provider_with_cache(provider_fn, cache)
            chunk_stream = await wrapped_provider(
                model="test-model",
                messages=[{"role": "user", "content": "Reply with alpha"}],
                stream=True,
            )
            return [chunk async for chunk in chunk_stream]
        finally:
            deactivate_mock_mode()

    assert asyncio.run(exercise_wrapper()) == ["rec", "orded"]
    assert provider_calls == 1
    assert cache.saved_response == {"type": "stream", "body": "recorded", "chunk_count": 2}


def test_record_stream_provider_saves_mixed_chunks_for_replay():
    cache = FakeRecordCache()
    tool_call = ParsedOpenAIToolCall(
        tool_call_id="tool-1",
        function_name="models3d-search",
        function_arguments_raw='{"requests":[{"query":"dragon"}]}',
        function_arguments_parsed={"requests": [{"query": "dragon"}]},
    )
    usage = OpenAIUsageMetadata(input_tokens=7, output_tokens=5, total_tokens=12)
    marker = {"__provider_marker__": True}

    async def provider_fn(**_kwargs):
        async def _stream():
            yield "before"
            yield tool_call
            yield usage
            yield marker

        return _stream()

    async def record_response():
        activate_mock_mode("record", "fork-conversation")
        try:
            wrapped_provider = wrap_provider_with_cache(provider_fn, cache)
            chunk_stream = await wrapped_provider(
                model="test-model",
                messages=[{"role": "user", "content": "Search 3D dragons"}],
                stream=True,
            )
            return [chunk async for chunk in chunk_stream]
        finally:
            deactivate_mock_mode()

    recorded_chunks = asyncio.run(record_response())

    assert recorded_chunks == ["before", tool_call, usage, marker]
    assert cache.saved_response["type"] == "mixed_stream"
    assert cache.saved_response["body"] == "before"
    assert cache.saved_response["chunk_count"] == 4
    assert [chunk["kind"] for chunk in cache.saved_response["chunks"]] == ["text", "pydantic", "pydantic", "json"]


def test_cached_stream_provider_replays_mixed_chunks_without_real_provider():
    provider_calls = 0
    response_data = {
        "type": "mixed_stream",
        "body": "before",
        "chunk_count": 4,
        "chunk_format_version": 1,
        "chunks": [
            {"kind": "text", "value": "before"},
            {
                "kind": "pydantic",
                "module": "backend.apps.ai.llm_providers.openai_shared",
                "class": "ParsedOpenAIToolCall",
                "value": {
                    "tool_call_id": "tool-1",
                    "function_name": "models3d-search",
                    "function_arguments_raw": '{"requests":[{"query":"dragon"}]}',
                    "function_arguments_parsed": {"requests": [{"query": "dragon"}]},
                    "parsing_error": None,
                },
            },
            {
                "kind": "pydantic",
                "module": "backend.apps.ai.llm_providers.openai_shared",
                "class": "OpenAIUsageMetadata",
                "value": {
                    "input_tokens": 7,
                    "output_tokens": 5,
                    "total_tokens": 12,
                    "user_input_tokens": None,
                    "system_prompt_tokens": None,
                },
            },
            {"kind": "json", "value": {"__provider_marker__": True}},
        ],
    }

    async def provider_fn(**_kwargs):
        nonlocal provider_calls
        provider_calls += 1

        async def _stream():
            yield "real"

        return _stream()

    async def replay_response():
        activate_mock_mode("mock", "fork-conversation")
        try:
            wrapped_provider = wrap_provider_with_cache(provider_fn, FakeSavedResponseCache(response_data))
            chunk_stream = await wrapped_provider(
                model="test-model",
                messages=[{"role": "user", "content": "Search 3D dragons"}],
                stream=True,
            )
            return [chunk async for chunk in chunk_stream]
        finally:
            deactivate_mock_mode()

    chunks = asyncio.run(replay_response())

    assert provider_calls == 0
    assert chunks[0] == "before"
    assert isinstance(chunks[1], ParsedOpenAIToolCall)
    assert chunks[1].function_name == "models3d-search"
    assert isinstance(chunks[2], OpenAIUsageMetadata)
    assert chunks[2].total_tokens == 12
    assert chunks[3] == {"__provider_marker__": True}


def test_cached_stream_provider_replays_google_chunks_without_google_import():
    provider_calls = 0
    response_data = {
        "type": "mixed_stream",
        "body": "",
        "chunk_count": 2,
        "chunk_format_version": 1,
        "chunks": [
            {
                "kind": "pydantic",
                "module": "backend.apps.ai.llm_providers.unavailable_google_client",
                "class": "ParsedGoogleToolCall",
                "value": {
                    "tool_call_id": "tool-1",
                    "function_name": "models3d-search",
                    "function_arguments_raw": '{"requests":[{"query":"benchy"}]}',
                    "function_arguments_parsed": {"requests": [{"query": "benchy"}]},
                    "parsing_error": None,
                    "thought_signature": "cached-signature",
                },
            },
            {
                "kind": "pydantic",
                "module": "backend.apps.ai.llm_providers.unavailable_google_client",
                "class": "GoogleUsageMetadata",
                "value": {
                    "prompt_token_count": 7,
                    "candidates_token_count": 5,
                    "total_token_count": 12,
                    "user_input_tokens": 3,
                    "system_prompt_tokens": 4,
                },
            },
        ],
    }

    async def provider_fn(**_kwargs):
        nonlocal provider_calls
        provider_calls += 1

        async def _stream():
            yield "real"

        return _stream()

    async def replay_response():
        activate_mock_mode("mock", "fork-conversation")
        try:
            wrapped_provider = wrap_provider_with_cache(provider_fn, FakeSavedResponseCache(response_data))
            chunk_stream = await wrapped_provider(
                model="test-model",
                messages=[{"role": "user", "content": "Search 3D benchy"}],
                stream=True,
            )
            return [chunk async for chunk in chunk_stream]
        finally:
            deactivate_mock_mode()

    chunks = asyncio.run(replay_response())

    assert provider_calls == 0
    assert isinstance(chunks[0], ParsedOpenAIToolCall)
    assert chunks[0].function_name == "models3d-search"
    assert chunks[0].thought_signature == "cached-signature"
    assert isinstance(chunks[1], OpenAIUsageMetadata)
    assert chunks[1].input_tokens == 7
    assert chunks[1].output_tokens == 5
    assert chunks[1].total_tokens == 12


def test_api_response_cache_loads_compatible_llm_response(tmp_path):
    cache = ApiResponseCache(root=tmp_path)
    response_data = {"type": "stream", "body": "cached", "chunk_count": 1}
    cache.save(
        group_id="models3d_search_web",
        category="llm/gemini-3.5-flash-lite",
        fingerprint="old-fingerprint",
        request_summary={
            "model": "gemini-3.5-flash-lite",
            "messages_count": 2,
            "tools_count": 3,
            "temperature": 0.4,
            "tool_choice": "auto",
            "last_message_preview": {"role": "user", "content": "Find 3D printable benchy models"},
        },
        response_data=response_data,
    )

    cached = cache.load_compatible_llm_response(
        "models3d_search_web",
        "llm/gemini-3.5-flash-lite",
        {
            "model": "gemini-3.5-flash-lite",
            "messages_count": 3,
            "tools_count": 3,
            "temperature": 0.4,
            "tool_choice": "auto",
            "last_message_preview": {"role": "user", "content": "Find 3D printable benchy models"},
        },
        excluded_fingerprint="new-fingerprint",
    )

    assert cached is not None
    assert cached["fingerprint"] == "old-fingerprint"
    assert cached["response"] == response_data


def test_api_response_cache_loads_compatible_llm_response_with_provider_prefix(tmp_path):
    cache = ApiResponseCache(root=tmp_path)
    response_data = {"type": "stream", "body": "cached", "chunk_count": 1}
    cache.save(
        group_id="models3d_search_web",
        category="llm/gemini-3.5-flash-lite",
        fingerprint="old-fingerprint",
        request_summary={
            "model": "gemini-3.5-flash-lite",
            "messages_count": 2,
            "tools_count": 3,
            "temperature": 0.4,
            "tool_choice": "auto",
            "last_message_preview": {"role": "user", "content": "Find 3D printable benchy models"},
        },
        response_data=response_data,
    )

    cached = cache.load_compatible_llm_response(
        "models3d_search_web",
        "llm/google/gemini-3.5-flash-lite",
        {
            "model": "google/gemini-3.5-flash-lite",
            "messages_count": 3,
            "tools_count": 3,
            "temperature": 0.4,
            "tool_choice": "auto",
            "last_message_preview": {"role": "user", "content": "Find 3D printable benchy models"},
        },
        excluded_fingerprint="new-fingerprint",
    )

    assert cached is not None
    assert cached["fingerprint"] == "old-fingerprint"
    assert cached["response"] == response_data
