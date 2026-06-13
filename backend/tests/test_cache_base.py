# backend/tests/test_cache_base.py
#
# Regression tests for the shared Redis/Dragonfly cache service wrapper.
# Health checks and Celery tasks create several short-lived CacheService
# instances in parallel, so connection failures must remain visible without
# flooding degraded-service reports with duplicate warnings in the same sweep.

import pytest

try:
    from backend.core.api.app.services import cache_base
    from backend.core.api.app.services.cache_base import CacheServiceBase
except ImportError as _exc:
    pytestmark = pytest.mark.skip(reason=f"Backend cache dependencies not installed: {_exc}")


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_cache_connection_warning_is_throttled(monkeypatch):
    class FailingRedis:
        async def ping(self):
            raise TimeoutError("Timeout connecting to server")

    monkeypatch.setattr(cache_base.redis, "Redis", lambda **_kwargs: FailingRedis())
    monkeypatch.setattr(CacheServiceBase, "_next_connection_retry_at", 0.0)
    monkeypatch.setattr(CacheServiceBase, "_last_connection_warning_at", -1000.0)
    warning_messages = []
    monkeypatch.setattr(cache_base.logger, "warning", warning_messages.append)

    assert await CacheServiceBase().client is None
    assert await CacheServiceBase().client is None

    assert warning_messages == ["Failed to connect to cache at cache:6379: Timeout connecting to server"]


@pytest.mark.anyio
async def test_pipeline_chat_cache_operations_use_current_key_schema(monkeypatch):
    class FakePipeline:
        def __init__(self):
            self.commands = []

        def zadd(self, key, mapping):
            self.commands.append(("zadd", key, mapping))

        def expire(self, key, ttl):
            self.commands.append(("expire", key, ttl))

        def hset(self, key, *args, mapping=None):
            self.commands.append(("hset", key, args, mapping))

        def hsetnx(self, key, field, value):
            self.commands.append(("hsetnx", key, field, value))

        def eval(self, script, numkeys, key, field, value):
            self.commands.append(("eval", key, field, value))

        async def execute(self):
            return [1] * len(self.commands)

    class FakeClient:
        def __init__(self):
            self.pipe = FakePipeline()

        def pipeline(self):
            return self.pipe

    class Payload:
        def __init__(self, data):
            self.data = data

        def model_dump(self, **_kwargs):
            return dict(self.data)

    service = CacheServiceBase()
    fake_client = FakeClient()
    service._client = fake_client

    monkeypatch.setattr(service, "_get_user_chat_ids_versions_key", lambda user_id: f"user:{user_id}:chat_ids_versions", raising=False)
    monkeypatch.setattr(service, "_get_chat_versions_key", lambda user_id, chat_id: f"user:{user_id}:chat:{chat_id}:versions", raising=False)
    monkeypatch.setattr(service, "_get_chat_list_item_data_key", lambda user_id, chat_id: f"user:{user_id}:chat:{chat_id}:list_item_data", raising=False)
    monkeypatch.setattr(service, "_get_user_chat_draft_key", lambda user_id, chat_id: f"user:{user_id}:chat:{chat_id}:draft", raising=False)
    monkeypatch.setattr(service, "_SET_IF_GREATER_LUA", "return 1", raising=False)

    result = await service.execute_pipeline_operations([
        ("add_chat_to_ids_versions", "user-1", "chat-1", 123),
        ("set_chat_versions", "user-1", "chat-1", Payload({"messages_v": 1, "title_v": 2})),
        ("set_chat_version_component", "user-1", "chat-1", "user_draft_v:user-1", 3),
        ("set_chat_list_item_data", "user-1", "chat-1", Payload({"title": "enc", "unread_count": 0, "pinned": False})),
        ("update_user_draft_in_cache", "user-1", "chat-1", None, 4),
    ])

    assert result is True
    keys = [command[1] for command in fake_client.pipe.commands]
    assert "user:user-1:chat_ids_versions" in keys
    assert "user:user-1:chat:chat-1:versions" in keys
    assert "user:user-1:chat:chat-1:list_item_data" in keys
    assert "user:user-1:chat:chat-1:draft" in keys
    assert not any(key.startswith("chat_versions:") for key in keys)
    assert not any(key.startswith("chat_list:") for key in keys)
