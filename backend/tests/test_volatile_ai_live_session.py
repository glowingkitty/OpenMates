"""Authenticated WebSocket presence for volatile incognito execution."""

import asyncio
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

from starlette.websockets import WebSocketState

from backend.core.api.app.routes.connection_manager import (
    ConnectionManager,
    VOLATILE_AI_LIVE_TTL_SECONDS,
    refresh_volatile_ai_live_session,
    register_volatile_ai_live_session,
    revoke_volatile_ai_live_session,
    volatile_ai_live_key,
)


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.ttls = {}
        self.available = True

    async def set(self, key, value, *, ex, nx):
        if not self.available:
            raise RuntimeError("redis unavailable")
        if nx and key in self.values:
            return False
        self.values[key] = value
        self.ttls[key] = ex
        return True

    async def get(self, key):
        if not self.available:
            raise RuntimeError("redis unavailable")
        return self.values.get(key)

    async def expire(self, key, ttl):
        if not self.available:
            raise RuntimeError("redis unavailable")
        if key not in self.values:
            return False
        self.ttls[key] = ttl
        return True

    async def delete(self, key):
        if not self.available:
            raise RuntimeError("redis unavailable")
        self.values.pop(key, None)
        self.ttls.pop(key, None)
        return 1


class FakeCache:
    def __init__(self, redis):
        self.redis = redis

    @property
    async def client(self):
        return self.redis


def socket():
    return SimpleNamespace(
        accept=AsyncMock(),
        application_state=WebSocketState.CONNECTED,
    )


# contract-test: supporting surface=gui.web assertions=chats.completion.recovery-takeover
def test_server_nonce_is_owner_bound_confirmed_and_refreshed_for_90_seconds():
    async def scenario():
        redis = FakeRedis()
        cache = FakeCache(redis)
        manager = ConnectionManager()
        websocket = socket()
        nonce = await manager.connect(websocket, "owner-1", "browser-1")

        assert len(nonce) >= 32
        assert manager.get_volatile_session_nonce("owner-1", "browser-1") is None
        assert await register_volatile_ai_live_session(cache, nonce, "owner-1") is True
        assert manager.confirm_volatile_session(websocket, "client-chosen") is False
        assert manager.confirm_volatile_session(websocket, nonce) is True
        assert manager.get_volatile_session_nonce("owner-1", "browser-1") == nonce

        key = volatile_ai_live_key(nonce)
        assert redis.values[key] == hashlib.sha256(b"owner-1").hexdigest()
        assert redis.ttls[key] == VOLATILE_AI_LIVE_TTL_SECONDS == 90
        redis.ttls[key] = 1
        assert await refresh_volatile_ai_live_session(cache, nonce, "owner-1") is True
        assert redis.ttls[key] == 90
        assert await refresh_volatile_ai_live_session(cache, nonce, "owner-2") is False

    asyncio.run(scenario())


# contract-test: supporting surface=gui.web assertions=chats.completion.recovery-takeover
def test_disconnect_revokes_nonce_before_connection_grace_finishes():
    async def scenario():
        redis = FakeRedis()
        cache = FakeCache(redis)
        manager = ConnectionManager()
        websocket = socket()
        nonce = await manager.connect(
            websocket,
            "owner-1",
            "browser-1",
            volatile_session_revoker=lambda value: revoke_volatile_ai_live_session(
                cache, value,
            ),
        )
        await register_volatile_ai_live_session(cache, nonce, "owner-1")
        manager.confirm_volatile_session(websocket, nonce)

        manager.disconnect(websocket, reason="test")
        grace = manager.grace_period_tasks[("owner-1", "browser-1")]
        try:
            assert manager.get_volatile_session_nonce("owner-1", "browser-1") is None
            await asyncio.sleep(0)
            assert volatile_ai_live_key(nonce) not in redis.values
            assert manager.is_user_active("owner-1") is True
        finally:
            grace.cancel()
            await asyncio.gather(grace, return_exceptions=True)

    asyncio.run(scenario())


# contract-test: supporting surface=gui.web assertions=chats.completion.recovery-takeover
def test_reconnect_mints_new_nonce_and_removes_old_presence():
    async def scenario():
        redis = FakeRedis()
        cache = FakeCache(redis)
        manager = ConnectionManager()
        first = socket()
        first_nonce = await manager.connect(
            first,
            "owner-1",
            "browser-1",
            volatile_session_revoker=lambda value: revoke_volatile_ai_live_session(
                cache, value,
            ),
        )
        await register_volatile_ai_live_session(cache, first_nonce, "owner-1")
        manager.confirm_volatile_session(first, first_nonce)

        replacement = socket()
        second_nonce = await manager.connect(
            replacement,
            "owner-1",
            "browser-1",
            volatile_session_revoker=lambda value: revoke_volatile_ai_live_session(
                cache, value,
            ),
        )
        assert first_nonce != second_nonce
        assert volatile_ai_live_key(first_nonce) not in redis.values
        assert manager.get_volatile_session_nonce("owner-1", "browser-1") is None
        await register_volatile_ai_live_session(cache, second_nonce, "owner-1")
        assert manager.confirm_volatile_session(replacement, second_nonce) is True

    asyncio.run(scenario())


# contract-test: supporting surface=gui.web assertions=chats.completion.recovery-takeover
def test_missing_or_unavailable_redis_fails_live_authority_closed():
    async def scenario():
        redis = FakeRedis()
        cache = FakeCache(redis)
        manager = ConnectionManager()
        websocket = socket()
        nonce = await manager.connect(websocket, "owner-1", "browser-1")
        await register_volatile_ai_live_session(cache, nonce, "owner-1")
        manager.confirm_volatile_session(websocket, nonce)

        await revoke_volatile_ai_live_session(cache, nonce)
        assert await refresh_volatile_ai_live_session(cache, nonce, "owner-1") is False
        manager.mark_volatile_session_unavailable(websocket)
        assert manager.get_volatile_session_nonce("owner-1", "browser-1") is None

        redis.available = False
        try:
            await refresh_volatile_ai_live_session(cache, nonce, "owner-1")
        except RuntimeError as exc:
            assert str(exc) == "redis unavailable"
        else:
            raise AssertionError("Redis outage must not authorize volatile work")

    asyncio.run(scenario())


# contract-test: supporting surface=gui.web assertions=chats.completion.recovery-takeover
def test_redis_outage_does_not_transfer_old_nonce_to_replacement_socket():
    async def scenario():
        manager = ConnectionManager()
        first = socket()

        async def unavailable_revoke(_nonce):
            raise RuntimeError("redis unavailable")

        first_nonce = await manager.connect(
            first, "owner-1", "browser-1",
            volatile_session_revoker=unavailable_revoke,
        )
        manager.confirm_volatile_session(first, first_nonce)
        replacement = socket()
        second_nonce = await manager.connect(
            replacement, "owner-1", "browser-1",
            volatile_session_revoker=unavailable_revoke,
        )

        assert second_nonce != first_nonce
        assert manager.get_volatile_session_nonce("owner-1", "browser-1") is None
        assert manager.confirm_volatile_session(replacement, first_nonce) is False

    asyncio.run(scenario())
