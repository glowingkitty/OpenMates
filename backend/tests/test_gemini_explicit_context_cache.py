"""Explicit Gemini context cache: hit/miss planning, request shape, expiry recovery."""
import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest
from google.genai import errors as google_errors
from google.genai import types

from backend.apps.ai.llm_providers import gemini_context_cache as gcc
from backend.apps.ai.llm_providers import google_client

PREFIX = "stable system prefix. " * 1000  # well above the minimum size
SUFFIX = "clock: 12:00"


class FakeRedis:
    def __init__(self, entries=None):
        self.store = dict(entries or {})
        self.deleted = []

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def delete(self, key):
        self.deleted.append(key)
        self.store.pop(key, None)


@pytest.fixture
def fake_redis(monkeypatch):
    redis = FakeRedis()
    class _Svc:
        @property
        async def client(self_inner):
            return redis

    monkeypatch.setattr(gcc, "_cache_service", _Svc())
    return redis


def _plan(prefix=PREFIX, system=None):
    return gcc.plan_request(
        model_id="gemini-3.8-flash", system_prompt=system if system is not None else prefix + SUFFIX,
        cacheable_system_prefix=prefix, google_tools=None, tool_config={"function_calling_config": {"mode": "AUTO"}},
    )


# contract-test: supporting surface=rest_api assertions=billing.models.verified-host-prices
@pytest.mark.asyncio
async def test_hit_builds_cached_config_with_suffix_first(fake_redis):
    key = gcc.compute_cache_key("gemini-3.8-flash", PREFIX, None, {"function_calling_config": {"mode": "AUTO"}})
    fake_redis.store[key] = b"cachedContents/abc"
    plan = await _plan()
    assert plan.is_hit
    config = types.GenerateContentConfig(system_instruction="x", tools=[types.Tool(function_declarations=[])],
                                         tool_config={"function_calling_config": {"mode": "AUTO"}})
    history = [types.Content(role="user", parts=[types.Part(text="hello")])]
    hit_config, hit_contents = gcc.build_hit_request(config, history, plan)
    assert hit_config.cached_content == "cachedContents/abc"
    assert hit_config.system_instruction is None and hit_config.tools is None and hit_config.tool_config is None
    assert hit_contents[0].parts[0].text.startswith(gcc.SUFFIX_CONTEXT_LABEL)
    assert SUFFIX in hit_contents[0].parts[0].text
    assert hit_contents[1].parts[0].text == "hello"


# contract-test: supporting surface=rest_api assertions=billing.models.verified-host-prices
@pytest.mark.asyncio
async def test_miss_schedules_exactly_one_background_create(fake_redis):
    first, second = await _plan(), await _plan()
    assert first.status == "miss_creating" and second.status == "miss_locked"
    created = MagicMock(name="cached", usage_metadata=MagicMock(total_token_count=5000))
    created.name = "cachedContents/new"
    client = MagicMock()
    client.aio.caches.create = AsyncMock(return_value=created)
    get_client = AsyncMock(return_value=(client, None))
    close_client = AsyncMock()
    assert gcc.schedule_create(second, get_client, close_client) is None
    task = gcc.schedule_create(first, get_client, close_client)
    await task
    client.aio.caches.create.assert_awaited_once()
    assert fake_redis.store[first.key] == "cachedContents/new"
    close_client.assert_awaited_once()


# contract-test: supporting surface=rest_api assertions=billing.models.verified-host-prices
@pytest.mark.asyncio
async def test_below_threshold_and_prefix_mismatch_skip(fake_redis):
    small = await _plan(prefix="short prefix")
    assert (small.status, small.reason) == ("skipped", "below_threshold")
    mismatch = await _plan(system="different " + PREFIX)
    assert (mismatch.status, mismatch.reason) == ("skipped", "prefix_mismatch")
    assert not fake_redis.store


# contract-test: supporting surface=rest_api assertions=billing.models.verified-host-prices
@pytest.mark.asyncio
async def test_expired_cache_drops_entry_and_retries_once_uncached(fake_redis, monkeypatch):
    key = gcc.compute_cache_key("gemini-3.8-flash", PREFIX, None, {"function_calling_config": {"mode": "AUTO"}})
    fake_redis.store[key] = b"cachedContents/gone"
    expired = google_errors.ClientError(403, {"error": {"message": "CachedContent not found (or permission denied)"}})
    assert gcc.is_cached_content_missing(expired)
    plan = await _plan()
    await gcc.drop_entry(plan)
    assert key in fake_redis.deleted
    assert not gcc.is_cached_content_missing(google_errors.ClientError(400, {"error": {"message": "bad schema"}}))

    # End to end through the client: first call uses cache and fails, second is uncached.
    calls = []

    async def fake_generate(model, contents, config):
        calls.append(config.cached_content)
        if config.cached_content:
            raise expired
        return MagicMock(usage_metadata=None, function_calls=None, text="ok", response_id=None)

    # A request without tools has no tool config, so the client keys the cache with None.
    fake_redis.store[gcc.compute_cache_key("gemini-3.8-flash", PREFIX, None, None)] = b"cachedContents/gone"
    client = MagicMock()
    client.aio.models.generate_content = fake_generate
    monkeypatch.setattr(google_client, "_get_google_ai_studio_api_key", AsyncMock(return_value="k"))
    monkeypatch.setattr(google_client, "_get_loop_google_client", AsyncMock(return_value=(client, None)))
    monkeypatch.setattr(google_client, "_close_google_client", AsyncMock())
    result = await google_client.invoke_google_ai_studio_chat_completions(
        task_id="t", model_id="gemini-3.8-flash",
        messages=[{"role": "system", "content": PREFIX + SUFFIX}, {"role": "user", "content": "hi"}],
        cacheable_system_prefix=PREFIX, stream=False,
    )
    assert result.success
    assert calls == ["cachedContents/gone", None]


# contract-test: supporting surface=rest_api assertions=billing.models.verified-host-prices
def test_llm_utils_passes_prefix_for_google_ai_studio():
    from backend.apps.ai.utils import llm_utils
    source = inspect.getsource(llm_utils)
    assert source.count('== "google_ai_studio" and sanitized_cacheable_prefix') == 2
    assert "cacheable_system_prefix" in inspect.signature(
        google_client.invoke_google_ai_studio_chat_completions).parameters
