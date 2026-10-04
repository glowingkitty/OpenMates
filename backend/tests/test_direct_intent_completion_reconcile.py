"""Bounded maintenance recovery for canonical direct-skill completion."""

from __future__ import annotations

import pytest

from backend.core.api.app.routes.handlers.websocket_handlers import (
    chat_recovery_job_handlers,
)


CURSOR_KEY = "chat_recovery:direct_completion_reconcile_cursor:v1"
FIRST_ID = "11111111-1111-4111-8111-111111111111"


class FakeRedis:
    def __init__(self, cursor=None):
        self.values = {} if cursor is None else {CURSOR_KEY: cursor}
        self.sets = []
        self.deletes = []

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value):
        self.values[key] = value
        self.sets.append((key, value))

    async def delete(self, key):
        self.values.pop(key, None)
        self.deletes.append(key)


class FakeCache:
    def __init__(self, redis):
        self.redis = redis

    @property
    async def client(self):
        return self.redis


class FakeRecoveryService:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = []

    async def execute(self, operation, data):
        self.calls.append((operation, data))
        result = next(self.results)
        if isinstance(result, Exception):
            raise result
        return result


# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover
@pytest.mark.asyncio
async def test_lost_callback_is_reconciled_in_bounded_round_robin_pages(monkeypatch):
    redis = FakeRedis()
    service = FakeRecoveryService([
        {
            "scanned": 1, "completed": 1, "pending": 0, "blocked": 0,
            "next_cursor": FIRST_ID,
        },
        {
            "scanned": 0, "completed": 0, "pending": 0, "blocked": 0,
            "next_cursor": None,
        },
    ])
    monkeypatch.setattr(
        chat_recovery_job_handlers,
        "ChatRecoveryService",
        lambda _directus: service,
    )

    first = await chat_recovery_job_handlers.reconcile_authorized_direct_completions(
        directus_service=object(), cache_service=FakeCache(redis),
    )
    second = await chat_recovery_job_handlers.reconcile_authorized_direct_completions(
        directus_service=object(), cache_service=FakeCache(redis),
    )

    assert first["completed"] == 1
    assert second["scanned"] == 0
    assert service.calls == [
        (
            "reconcile_authorized_direct_completions",
            {"protocol_version": 1, "limit": 100},
        ),
        (
            "reconcile_authorized_direct_completions",
            {"protocol_version": 1, "limit": 100, "after_id": FIRST_ID},
        ),
    ]
    assert redis.sets == [(CURSOR_KEY, FIRST_ID)]
    assert CURSOR_KEY in redis.deletes
    assert CURSOR_KEY not in redis.values


# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover
@pytest.mark.asyncio
async def test_reconcile_error_preserves_cursor_and_pending_authority(monkeypatch):
    redis = FakeRedis(cursor=FIRST_ID)
    service = FakeRecoveryService([RuntimeError("transaction unavailable")])
    monkeypatch.setattr(
        chat_recovery_job_handlers,
        "ChatRecoveryService",
        lambda _directus: service,
    )

    with pytest.raises(RuntimeError, match="transaction unavailable"):
        await chat_recovery_job_handlers.reconcile_authorized_direct_completions(
            directus_service=object(), cache_service=FakeCache(redis),
        )

    assert redis.values[CURSOR_KEY] == FIRST_ID
    assert redis.sets == []
    assert redis.deletes == []
    assert service.calls[0][1] == {
        "protocol_version": 1, "limit": 100, "after_id": FIRST_ID,
    }
