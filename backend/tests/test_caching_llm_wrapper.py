# backend/tests/test_caching_llm_wrapper.py
#
# Purpose: verify the live-mock LLM cache wrapper preserves provider call contracts.
# Providers are awaited by llm_utils and resolve to stream iterators for streaming calls.
# A cached stream must therefore be returned from an awaitable wrapper, not directly.
# This protects Playwright chat specs that run through live mock/cached AI responses.
# See: backend/apps/ai/testing/caching_llm_wrapper.py.

import asyncio

from backend.apps.ai.testing.caching_llm_wrapper import wrap_provider_with_cache
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
