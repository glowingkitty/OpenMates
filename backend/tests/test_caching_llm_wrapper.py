# backend/tests/test_caching_llm_wrapper.py
# contract-test-file: infrastructure
#
# Purpose: verify the live-mock LLM cache wrapper preserves provider call contracts.
# Providers are awaited by llm_utils and resolve to stream iterators for streaming calls.
# A cached stream must therefore be returned from an awaitable wrapper, not directly.
# This protects Playwright chat specs that run through live mock/cached AI responses.
# See: backend/apps/ai/testing/caching_llm_wrapper.py.

import asyncio
from decimal import Decimal

import pytest

from backend.apps.ai.testing import caching_llm_wrapper as llm_wrapper
from backend.apps.ai.testing.caching_llm_wrapper import wrap_provider_with_cache
from backend.apps.ai.llm_providers.openai_shared import OpenAIUsageMetadata, ParsedOpenAIToolCall
from backend.shared.testing.api_response_cache import ApiResponseCache, MockCacheMiss
from backend.shared.testing.mock_context import (
    MAX_REAL_LLM_OUTPUT_TOKENS,
    activate_mock_mode,
    deactivate_mock_mode,
)


@pytest.fixture
def budgeted_record_mode(monkeypatch):
    monkeypatch.setenv("DAILY_AI_TEST_BUDGET_BACKEND", "memory")
    monkeypatch.setattr(
        llm_wrapper,
        "conservative_llm_reservation_eur",
        lambda *_args, **_kwargs: Decimal("0.001"),
    )


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
    def __init__(self, response_data=None):
        self.fallback_summary = None
        self.excluded_fingerprint = None
        self.response_data = response_data or {"type": "stream", "body": "fallback"}

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
        return {"response": self.response_data}


class FakeNonStreamCache(FakeCache):
    def __init__(self, response_data=None):
        self.response_data = response_data
        self.saved_response = None

    def load(self, group_id, category, fingerprint):
        assert group_id == "fork-conversation"
        assert category == "llm_non_stream/test-model"
        assert fingerprint == "cached-fingerprint"
        if self.response_data is None:
            return None
        return {"response": self.response_data}

    def save(self, **kwargs):
        self.saved_response = kwargs["response_data"]


class FakeNonStreamFallbackCache(FakeFallbackCache):
    def __init__(self):
        super().__init__({
            "type": "non_stream",
            "value": {"kind": "json", "value": {"success": True}},
        })

    def load(self, group_id, category, fingerprint):
        assert group_id == "fork-conversation"
        assert category == "llm_non_stream/test-model"
        assert fingerprint == "cached-fingerprint"
        return None

    def load_compatible_llm_response(self, group_id, category, request_summary, excluded_fingerprint=None):
        assert group_id == "fork-conversation"
        assert category == "llm_non_stream/test-model"
        self.fallback_summary = request_summary
        self.excluded_fingerprint = excluded_fingerprint
        return {"response": self.response_data}


class FakeFailingSaveCache(FakeCache):
    def load(self, group_id, category, fingerprint):
        assert group_id == "fork-conversation"
        assert category in {"llm/test-model", "llm_non_stream/test-model"}
        assert fingerprint == "cached-fingerprint"
        return None

    def save(self, **_kwargs):
        raise PermissionError("cache path is read-only")


async def _replay(cache, messages):
    async def provider_fn(**_kwargs):
        raise AssertionError("mock replay should not call the real provider")

    activate_mock_mode("mock", "fork-conversation")
    try:
        wrapped_provider = wrap_provider_with_cache(provider_fn, cache)
        chunk_stream = await wrapped_provider(
            model="test-model",
            messages=messages,
            stream=True,
        )
        return [chunk async for chunk in chunk_stream]
    finally:
        deactivate_mock_mode()


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


def test_cached_non_stream_provider_replays_cached_response_without_real_provider():
    provider_calls = 0
    cache = FakeNonStreamCache({
        "type": "non_stream",
        "value": {
            "kind": "pydantic",
            "module": "backend.apps.ai.llm_providers.openai_shared",
            "class": "OpenAIUsageMetadata",
            "value": {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5},
        },
    })

    async def provider_fn(**_kwargs):
        nonlocal provider_calls
        provider_calls += 1
        return {"success": True}

    async def exercise_wrapper():
        activate_mock_mode("mock", "fork-conversation")
        try:
            wrapped_provider = wrap_provider_with_cache(provider_fn, cache)
            return await wrapped_provider(
                model="test-model",
                messages=[{"role": "user", "content": "Classify this request"}],
                stream=False,
            )
        finally:
            deactivate_mock_mode()

    response = asyncio.run(exercise_wrapper())

    assert provider_calls == 0
    assert isinstance(response, OpenAIUsageMetadata)
    assert response.total_tokens == 5


def test_record_non_stream_provider_saves_response_for_replay(budgeted_record_mode):
    provider_calls = 0
    observed_max_tokens = None
    cache = FakeNonStreamCache()

    async def provider_fn(**kwargs):
        nonlocal provider_calls, observed_max_tokens
        provider_calls += 1
        observed_max_tokens = kwargs.get("max_tokens")
        return {"success": True, "category": "web/read"}

    async def exercise_wrapper():
        activate_mock_mode("record", "fork-conversation")
        try:
            wrapped_provider = wrap_provider_with_cache(provider_fn, cache)
            return await wrapped_provider(
                model="test-model",
                messages=[{"role": "user", "content": "Classify this request"}],
                stream=False,
                max_tokens=999_999,
            )
        finally:
            deactivate_mock_mode()

    response = asyncio.run(exercise_wrapper())

    assert provider_calls == 1
    assert observed_max_tokens == MAX_REAL_LLM_OUTPUT_TOKENS
    assert response == {"success": True, "category": "web/read"}
    assert cache.saved_response == {
        "type": "non_stream",
        "value": {"kind": "json", "value": {"success": True, "category": "web/read"}},
    }


def test_record_non_stream_provider_raises_when_cache_save_fails(budgeted_record_mode):
    provider_calls = 0

    async def provider_fn(**_kwargs):
        nonlocal provider_calls
        provider_calls += 1
        return {"success": True, "category": "events/search"}

    async def exercise_wrapper():
        activate_mock_mode("record", "fork-conversation")
        try:
            wrapped_provider = wrap_provider_with_cache(provider_fn, FakeFailingSaveCache())
            with pytest.raises(PermissionError, match="cache path is read-only"):
                await wrapped_provider(
                    model="test-model",
                    messages=[{"role": "user", "content": "Classify this request"}],
                    stream=False,
                )
        finally:
            deactivate_mock_mode()

    asyncio.run(exercise_wrapper())

    assert provider_calls == 1


def test_cached_stream_provider_raises_on_fingerprint_miss_without_real_provider():
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
            with pytest.raises(MockCacheMiss):
                return [chunk async for chunk in chunk_stream]
        finally:
            deactivate_mock_mode()

    asyncio.run(exercise_wrapper())
    assert provider_calls == 0
    assert cache.excluded_fingerprint is None
    assert cache.fallback_summary is None


def test_cached_non_stream_provider_raises_on_fingerprint_miss_without_real_provider():
    provider_calls = 0
    cache = FakeNonStreamFallbackCache()

    async def provider_fn(**_kwargs):
        nonlocal provider_calls
        provider_calls += 1
        return {"success": True}

    async def exercise_wrapper():
        activate_mock_mode("mock", "fork-conversation")
        try:
            wrapped_provider = wrap_provider_with_cache(provider_fn, cache)
            with pytest.raises(MockCacheMiss):
                await wrapped_provider(
                    model="test-model",
                    messages=[{"role": "user", "content": "Classify this request"}],
                    stream=False,
                )
        finally:
            deactivate_mock_mode()

    asyncio.run(exercise_wrapper())
    assert provider_calls == 0
    assert cache.excluded_fingerprint is None
    assert cache.fallback_summary is None


def test_exact_cache_hit_does_not_remap_embed_refs():
    response_data = {
        "type": "stream",
        "body": "```embeds_results_view\nembeds: stale-one-AAA\n```",
    }
    messages = [{"role": "tool", "content": "embed_ref: fresh-one-111"}]

    replayed = "".join(asyncio.run(_replay(FakeSavedResponseCache(response_data), messages)))

    assert "stale-one-AAA" in replayed
    assert "fresh-one-111" not in replayed


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


def test_record_stream_provider_awaits_real_provider_before_iterating_and_saving(budgeted_record_mode):
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


def test_record_stream_provider_writes_candidate_without_reading_canonical_cache(tmp_path, budgeted_record_mode):
    canonical_root = tmp_path / "canonical"
    candidate_root = tmp_path / "candidate"
    cache = ApiResponseCache(root=canonical_root)
    group_id = "fork-conversation"
    category = "llm/test-model"
    messages = [{"role": "user", "content": "Reply with alpha"}]
    fingerprint = cache.fingerprint_llm_call(model="test-model", messages=messages)
    cache.save(
        group_id=group_id,
        category=category,
        fingerprint=fingerprint,
        request_summary={"model": "test-model"},
        response_data={"type": "stream", "body": "canonical", "chunk_count": 1},
    )
    provider_calls = 0

    async def provider_fn(**_kwargs):
        nonlocal provider_calls
        provider_calls += 1

        async def _stream():
            yield "candidate"

        return _stream()

    async def exercise_wrapper():
        activate_mock_mode("record", group_id, candidate_root)
        try:
            wrapped_provider = wrap_provider_with_cache(provider_fn, cache)
            chunk_stream = await wrapped_provider(model="test-model", messages=messages, stream=True)
            return [chunk async for chunk in chunk_stream]
        finally:
            deactivate_mock_mode()

    assert asyncio.run(exercise_wrapper()) == ["candidate"]
    assert provider_calls == 1
    canonical = cache.load(group_id, category, fingerprint)
    candidate = ApiResponseCache(root=candidate_root).load(group_id, category, fingerprint)
    assert canonical is not None
    assert canonical["response"]["body"] == "canonical"
    assert candidate is not None
    assert candidate["response"]["body"] == "candidate"


def test_record_stream_provider_raises_when_cache_save_fails(budgeted_record_mode):
    provider_calls = 0

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
            wrapped_provider = wrap_provider_with_cache(provider_fn, FakeFailingSaveCache())
            chunk_stream = await wrapped_provider(
                model="test-model",
                messages=[{"role": "user", "content": "Reply with alpha"}],
                stream=True,
            )
            with pytest.raises(PermissionError, match="cache path is read-only"):
                return [chunk async for chunk in chunk_stream]
        finally:
            deactivate_mock_mode()

    assert asyncio.run(exercise_wrapper()) is None
    assert provider_calls == 1


def test_record_stream_provider_saves_mixed_chunks_for_replay(budgeted_record_mode):
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
