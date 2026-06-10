# backend/tests/test_cache_pubsub_reconnect.py
#
# Regression tests for Redis pub/sub listener durability.
# WebSocket fan-out tasks consume Redis pub/sub forever; if Dragonfly closes a
# pub/sub connection and the generator exits, AI chunks keep being published by
# workers but never reach browsers. These tests keep that contract explicit.

import asyncio
import json
import sys
from types import ModuleType
from types import SimpleNamespace


class FakeConnectionError(Exception):
    pass


fake_redis = ModuleType("redis")
fake_redis.__path__ = []
fake_redis.exceptions = SimpleNamespace(ConnectionError=FakeConnectionError)
fake_redis_asyncio = ModuleType("redis.asyncio")
fake_redis_asyncio.Redis = object
fake_redis.asyncio = fake_redis_asyncio
sys.modules.setdefault("redis", fake_redis)
sys.modules.setdefault("redis.asyncio", fake_redis_asyncio)


class FakePubSub:
    def __init__(self, messages, fail_after_messages=False):
        self.messages = list(messages)
        self.fail_after_messages = fail_after_messages
        self.closed = False
        self.subscribed_patterns = []
        self.unsubscribed_patterns = []

    async def psubscribe(self, pattern):
        self.subscribed_patterns.append(pattern)

    async def get_message(self, ignore_subscribe_messages=True, timeout=0.1):
        if self.messages:
            return self.messages.pop(0)
        if self.fail_after_messages:
            self.fail_after_messages = False
            raise FakeConnectionError("Connection closed by server")
        await asyncio.sleep(0)
        return None

    async def punsubscribe(self, pattern):
        self.unsubscribed_patterns.append(pattern)

    async def close(self):
        self.closed = True


class FakeClient:
    def __init__(self, pubsub):
        self._pubsub = pubsub

    def pubsub(self):
        return self._pubsub


def test_subscribe_to_channel_reconnects_after_pubsub_connection_error():
    from backend.core.api.app.services.cache_base import CacheServiceBase

    first_pubsub = FakePubSub(
        [
            {
                "type": "pmessage",
                "channel": b"chat_stream::first",
                "data": json.dumps({"event": "first"}).encode(),
            }
        ],
        fail_after_messages=True,
    )
    second_pubsub = FakePubSub(
        [
            {
                "type": "pmessage",
                "channel": b"chat_stream::second",
                "data": json.dumps({"event": "second"}).encode(),
            }
        ]
    )

    class ReconnectingCache(CacheServiceBase):
        _PUBSUB_RECONNECT_DELAY_SECONDS = 0.0

        def __init__(self, clients):
            self.clients = list(clients)
            self._client = None
            self._connection_error = False

        @property
        async def client(self):
            return self.clients.pop(0) if self.clients else None

    async def run_test():
        cache = ReconnectingCache([FakeClient(first_pubsub), FakeClient(second_pubsub)])
        messages = cache.subscribe_to_channel("chat_stream::*")
        try:
            first = await asyncio.wait_for(messages.__anext__(), timeout=1)
            second = await asyncio.wait_for(messages.__anext__(), timeout=1)
        finally:
            await messages.aclose()
        return first, second

    first, second = asyncio.run(run_test())

    assert first == {"channel": "chat_stream::first", "data": {"event": "first"}}
    assert second == {"channel": "chat_stream::second", "data": {"event": "second"}}
    assert first_pubsub.closed is True
    assert first_pubsub.unsubscribed_patterns == ["chat_stream::*"]
    assert second_pubsub.subscribed_patterns == ["chat_stream::*"]
