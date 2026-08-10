# backend/tests/test_caching_llm_wrapper.py
#
# Purpose: verify the live-mock LLM cache wrapper preserves provider call contracts.
# Providers are awaited by llm_utils and resolve to stream iterators for streaming calls.
# A cached stream must therefore be returned from an awaitable wrapper, not directly.
# This protects Playwright chat specs that run through live mock/cached AI responses.
# See: backend/apps/ai/testing/caching_llm_wrapper.py.

import asyncio
import copy

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
        "last_message_hash": "5a3782b74653d86b",
        "last_message_preview": {"role": "user", "content": "Find 3D printable benchy models"},
    }


def test_compatible_fallback_remaps_stale_embed_refs_in_body_and_mixed_text_chunks():
    response_data = {
        "type": "mixed_stream",
        "body": (
            "```embeds_results_view\nembeds: event-one-A1A, event-two-B2B\n```\n"
            "[First](embed:event-one-A1A) [Second](embed:event-two-B2B)"
        ),
        "chunks": [
            {"kind": "text", "value": "```embeds_results_view\nembeds: event-one-A"},
            {"kind": "text", "value": "1A, event-two-B2B\n```\n[First](embed:event-one-A1A) "},
            {"kind": "text", "value": "[Second](embed:event-two-B2B)"},
        ],
    }
    original = copy.deepcopy(response_data)
    messages = [{
        "role": "tool",
        "content": "results[2]:\n  - embed_ref: event-two-C3C\n  - embed_ref: event-one-D4D",
    }]

    chunks = asyncio.run(_replay(FakeFallbackCache(response_data), messages))
    replayed = "".join(chunk for chunk in chunks if isinstance(chunk, str))

    assert "embeds: event-one-D4D, event-two-C3C" in replayed
    assert "(embed:event-one-D4D)" in replayed
    assert "(embed:event-two-C3C)" in replayed
    assert "-A1A" not in replayed
    assert "-B2B" not in replayed
    assert response_data == original


def test_compatible_fallback_preserves_duplicate_embed_refs():
    response_data = {
        "type": "stream",
        "body": (
            "```embeds_results_view\nembeds: event-one-AAA, event-one-AAA, event-two-BBB\n```\n"
            "[First](embed:event-one-AAA)"
        ),
    }
    messages = [{
        "role": "tool",
        "content": "embed_ref: event-one-111\nembed_ref: event-one-111\nembed_ref: event-two-222",
    }]

    replayed = "".join(asyncio.run(_replay(FakeFallbackCache(response_data), messages)))

    assert replayed.count("event-one-111") == 3
    assert replayed.count("event-two-222") == 1
    assert "event-one-AAA" not in replayed


def test_exact_cache_hit_does_not_remap_embed_refs():
    response_data = {
        "type": "stream",
        "body": "```embeds_results_view\nembeds: stale-one-AAA\n```",
    }
    messages = [{"role": "tool", "content": "embed_ref: fresh-one-111"}]

    replayed = "".join(asyncio.run(_replay(FakeSavedResponseCache(response_data), messages)))

    assert "stale-one-AAA" in replayed
    assert "fresh-one-111" not in replayed


def test_compatible_fallback_leaves_unmatched_refs_visible_and_warns(caplog):
    response_data = {
        "type": "stream",
        "body": "```embeds_results_view\nembeds: stale-one-AAA, stale-two-BBB\n```",
    }
    messages = [{"role": "tool", "content": "embed_ref: fresh-one-111"}]

    replayed = "".join(asyncio.run(_replay(FakeFallbackCache(response_data), messages)))

    assert "stale-one-AAA, stale-two-BBB" in replayed
    assert "fresh-one-111" not in replayed
    assert "cannot safely remap" in caplog.text


def test_compatible_fallback_remaps_matching_subset_when_current_refs_include_extras():
    response_data = {
        "type": "stream",
        "body": (
            "```embeds_results_view\n"
            "embeds: matching-event-one-AAA, matching-event-two-BBB\n"
            "```"
        ),
    }
    messages = [{
        "role": "tool",
        "content": (
            "embed_ref: unrelated-event-CCC\n"
            "embed_ref: matching-event-one-DDD\n"
            "embed_ref: another-unrelated-event-EEE\n"
            "embed_ref: matching-event-two-FFF"
        ),
    }]

    replayed = "".join(asyncio.run(_replay(FakeFallbackCache(response_data), messages)))

    assert "embeds: matching-event-one-DDD, matching-event-two-FFF" in replayed
    assert "-AAA" not in replayed
    assert "-BBB" not in replayed


def test_compatible_fallback_leaves_ambiguous_prefix_matches_visible_and_warns(caplog):
    response_data = {
        "type": "stream",
        "body": "```embeds_results_view\nembeds: matching-event-AAA\n```",
    }
    messages = [{
        "role": "tool",
        "content": (
            "embed_ref: matching-event-BBB\n"
            "embed_ref: matching-event-CCC"
        ),
    }]

    replayed = "".join(asyncio.run(_replay(FakeFallbackCache(response_data), messages)))

    assert "matching-event-AAA" in replayed
    assert "matching-event-BBB" not in replayed
    assert "matching-event-CCC" not in replayed
    assert "cannot safely remap" in caplog.text


def test_compatible_fallback_does_not_treat_a_domain_as_result_identity(caplog):
    response_data = {
        "type": "stream",
        "body": "```embeds_results_view\nembeds: example.com-A1A\n```",
    }
    messages = [{"role": "tool", "content": "embed_ref: example.com-B2B"}]

    replayed = "".join(asyncio.run(_replay(FakeFallbackCache(response_data), messages)))

    assert "example.com-A1A" in replayed
    assert "example.com-B2B" not in replayed
    assert "cannot safely remap" in caplog.text


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
            "tools_count": 4,
            "temperature": 0.0,
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


def test_api_response_cache_rejects_compatible_llm_response_for_different_prompt(tmp_path):
    cache = ApiResponseCache(root=tmp_path)
    cache.save(
        group_id="embed_diff_code_web",
        category="llm/gemini-3.5-flash-lite",
        fingerprint="old-fingerprint",
        request_summary={
            "model": "gemini-3.5-flash-lite",
            "messages_count": 2,
            "tools_count": 5,
            "temperature": 0.4,
            "tool_choice": "auto",
            "last_message_preview": {"role": "user", "content": "Create average.py"},
        },
        response_data={"type": "stream", "body": "cached", "chunk_count": 1},
    )

    cached = cache.load_compatible_llm_response(
        "embed_diff_code_web",
        "llm/gemini-3.5-flash-lite",
        {
            "model": "gemini-3.5-flash-lite",
            "messages_count": 2,
            "tools_count": 4,
            "temperature": 0.4,
            "tool_choice": "auto",
            "last_message_preview": {"role": "user", "content": "Create totals.py"},
        },
        excluded_fingerprint="new-fingerprint",
    )

    assert cached is None


def test_api_response_cache_rejects_matching_previews_with_different_full_message_hashes(tmp_path):
    cache = ApiResponseCache(root=tmp_path)
    preview = {"role": "user", "content": "x" * 200 + "..."}
    cache.save(
        group_id="long_prompt",
        category="llm/gemini-3.5-flash-lite",
        fingerprint="old-fingerprint",
        request_summary={
            "model": "gemini-3.5-flash-lite",
            "tools_count": 5,
            "temperature": 0.4,
            "tool_choice": "auto",
            "last_message_hash": "first-hash",
            "last_message_preview": preview,
        },
        response_data={"type": "stream", "body": "cached", "chunk_count": 1},
    )

    cached = cache.load_compatible_llm_response(
        "long_prompt",
        "llm/gemini-3.5-flash-lite",
        {
            "model": "gemini-3.5-flash-lite",
            "tools_count": 4,
            "temperature": 0.4,
            "tool_choice": "auto",
            "last_message_hash": "second-hash",
            "last_message_preview": preview,
        },
        excluded_fingerprint="new-fingerprint",
    )

    assert cached is None


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
