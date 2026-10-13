"""One-use first-party WebSocket Personal Memory snapshot contract."""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from backend.core.api.app.routes import websockets


REQUEST_ID = "49c6fabb-8871-4fd0-bf79-277cc3fa541a"
SESSION_HASH = "a" * 64


class FakeCache:
    def __init__(self, *, owner="owner", country="DE"):
        self.owner = owner
        self.country = country
        self.reads = []
        self.redis = FakeRedis()

    @property
    async def client(self):
        return self.redis

    async def get(self, key):
        self.reads.append(key)
        if key == f"session:{SESSION_HASH}":
            return {"user_id": self.owner} if self.owner else None
        if key == "user_tokens:owner":
            return {SESSION_HASH: {"security_country_code": self.country}}
        return None


class FakeRedis:
    def __init__(self):
        self.counts = {}
        self.calls = []
        self.error = None

    async def eval(self, script, key_count, session_key, user_key):
        if self.error:
            raise self.error
        assert key_count == 2
        assert "EXPIRE" in script and "INCR" in script
        self.calls.append((session_key, user_key))
        self.counts[session_key] = self.counts.get(session_key, 0) + 1
        self.counts[user_key] = self.counts.get(user_key, 0) + 1
        return int(self.counts[session_key] <= 30 and self.counts[user_key] <= 60)


class FakeDirectus:
    def __init__(self, devices=None):
        self.devices = ["device"] if devices is None else devices
        self.device_reads = 0

    async def get_user_fields_direct(self, user_id, fields, *, no_cache=False):
        assert user_id == "owner"
        assert fields == ["id", "connected_devices"]
        assert no_cache is True
        self.device_reads += 1
        return {"id": user_id, "connected_devices": self.devices}


class FakeSocket:
    def __init__(self):
        self.frames = []

    async def send_json(self, frame):
        self.frames.append(frame)


def auth_data(**changes):
    return {
        "user_id": "owner", "session_hash": SESSION_HASH,
        "upgrade_device_hash": "device", "upgrade_country_code": "DE",
        "session_expires_at": int(time.time()) + 60,
        "pair_expires_at": None,
        **changes,
    }


def install_authority(monkeypatch, *, ledger=None, pair=None):
    ledger_read = AsyncMock(return_value={"user_id": "owner"} if ledger is None else ledger)
    pair_read = AsyncMock(return_value=pair)
    monkeypatch.setattr(websockets, "get_session_state_cached", ledger_read)
    monkeypatch.setattr(websockets, "get_pair_deadline_hash", pair_read)
    return ledger_read, pair_read


# contract-test: direct surface=rest_api assertions=auth.session.authoritative-enforcement,auth.session.isolation
@pytest.mark.parametrize("condition", ["revoked", "risk_pending", "missing_owner", "wrong_owner", "device_removed", "expired", "pair_expired", "country_changed", "nan_deadline", "infinite_deadline", "malformed_deadline"])
def test_snapshot_denies_fresh_authority_failure(monkeypatch, condition):
    cache = FakeCache(owner="other" if condition == "wrong_owner" else (None if condition == "missing_owner" else "owner"),
                      country="FI" if condition == "country_changed" else "DE")
    directus = FakeDirectus(devices=[] if condition == "device_removed" else None)
    deadline_override = {
        "expired": int(time.time()) - 1,
        "nan_deadline": float("nan"),
        "infinite_deadline": float("inf"),
        "malformed_deadline": "not-a-deadline",
    }
    data = auth_data(**({"session_expires_at": deadline_override[condition]}
                        if condition in deadline_override else {}))
    ledger_read, _ = install_authority(monkeypatch, pair=int(time.time()) - 1 if condition == "pair_expired" else None)
    if condition in ("revoked", "risk_pending"):
        ledger_read.side_effect = HTTPException(401, "Session expired or revoked")
    snapshot = AsyncMock()
    monkeypatch.setattr(websockets, "_load_fresh_personal_memories", snapshot)
    socket = FakeSocket()

    asyncio.run(websockets.handle_personal_memory_snapshot(
        websocket=socket, payload={"request_id": REQUEST_ID}, auth_data=data,
        cache_service=cache, directus_service=directus,
    ))

    assert socket.frames == [{"type": "personal_memory_snapshot_result", "payload": {
        "request_id": REQUEST_ID, "success": False, "error": {"code": "unauthorized"},
    }}]
    snapshot.assert_not_awaited()
    if condition not in ("missing_owner", "wrong_owner", "expired", "nan_deadline", "infinite_deadline", "malformed_deadline"):
        ledger_read.assert_awaited_once()


# contract-test: direct surface=rest_api assertions=auth.session.authoritative-enforcement,auth.session.isolation
def test_snapshot_returns_only_fresh_owner_ciphertext_on_same_socket(monkeypatch):
    cache, directus, socket = FakeCache(), FakeDirectus(), FakeSocket()
    ledger_read, pair_read = install_authority(monkeypatch)
    snapshot = AsyncMock(return_value=SimpleNamespace(model_dump=lambda mode: {
        "encrypted_settings": "opaque-settings", "memories": [{"id": "row-1", "encrypted_item_json": "opaque-row"}],
    }))
    monkeypatch.setattr(websockets, "_load_fresh_personal_memories", snapshot)

    asyncio.run(websockets.handle_personal_memory_snapshot(
        websocket=socket, payload={"request_id": REQUEST_ID}, auth_data=auth_data(),
        cache_service=cache, directus_service=directus,
    ))

    assert socket.frames == [{"type": "personal_memory_snapshot_result", "payload": {
        "request_id": REQUEST_ID, "success": True,
        "personal_memories": {"encrypted_settings": "opaque-settings", "memories": [
            {"id": "row-1", "encrypted_item_json": "opaque-row"},
        ]},
    }}]
    ledger_read.assert_awaited_once_with(directus, cache, SESSION_HASH, user_id="owner", allow_risk=False)
    pair_read.assert_awaited_once_with(directus, cache, SESSION_HASH)
    snapshot.assert_awaited_once_with(directus, "owner")
    assert cache.reads == [f"session:{SESSION_HASH}", "user_tokens:owner"]
    assert directus.device_reads == 1


# contract-test: direct surface=rest_api assertions=auth.session.isolation
@pytest.mark.parametrize("payload", [None, {}, {"request_id": REQUEST_ID, "team_id": "team"},
                                    {"request_id": REQUEST_ID, "user_id": "other"},
                                    {"request_id": "not-a-uuid"}])
def test_snapshot_rejects_malformed_or_team_scoped_request_before_auth(monkeypatch, payload):
    ledger_read, _ = install_authority(monkeypatch)
    snapshot = AsyncMock()
    monkeypatch.setattr(websockets, "_load_fresh_personal_memories", snapshot)
    socket = FakeSocket()
    asyncio.run(websockets.handle_personal_memory_snapshot(
        websocket=socket, payload=payload, auth_data=auth_data(),
        cache_service=FakeCache(), directus_service=FakeDirectus(),
    ))
    assert socket.frames[0]["payload"]["error"] == {"code": "invalid_request"}
    assert socket.frames[0]["payload"]["success"] is False
    ledger_read.assert_not_awaited()
    snapshot.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=auth.session.authoritative-enforcement
def test_snapshot_fails_closed_when_ledger_unavailable(monkeypatch):
    ledger_read, _ = install_authority(monkeypatch)
    ledger_read.side_effect = HTTPException(503, "Session verification temporarily unavailable")
    snapshot = AsyncMock()
    monkeypatch.setattr(websockets, "_load_fresh_personal_memories", snapshot)
    socket = FakeSocket()
    asyncio.run(websockets.handle_personal_memory_snapshot(
        websocket=socket, payload={"request_id": REQUEST_ID}, auth_data=auth_data(),
        cache_service=FakeCache(), directus_service=FakeDirectus(),
    ))
    assert socket.frames[0]["payload"]["error"] == {"code": "unavailable"}
    snapshot.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=auth.session.authoritative-enforcement
def test_second_snapshot_request_on_one_socket_never_rechecks_or_reads(monkeypatch):
    ledger_read, _ = install_authority(monkeypatch)
    snapshot = AsyncMock()
    monkeypatch.setattr(websockets, "_load_fresh_personal_memories", snapshot)
    socket = FakeSocket()
    asyncio.run(websockets.handle_personal_memory_snapshot(
        websocket=socket, payload={"request_id": REQUEST_ID}, auth_data=auth_data(),
        cache_service=FakeCache(), directus_service=FakeDirectus(), already_used=True,
    ))
    assert socket.frames[0]["payload"]["error"] == {"code": "already_used"}
    ledger_read.assert_not_awaited()
    snapshot.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=auth.session.authoritative-enforcement
def test_reconnects_share_session_budget_and_reject_before_database_reads(monkeypatch):
    cache, directus = FakeCache(), FakeDirectus()
    ledger_read, _ = install_authority(monkeypatch)
    snapshot = AsyncMock(return_value=SimpleNamespace(model_dump=lambda mode: {
        "encrypted_settings": None, "memories": [],
    }))
    monkeypatch.setattr(websockets, "_load_fresh_personal_memories", snapshot)

    outcomes = []
    for _ in range(31):
        # Each call represents a fresh, one-use socket after reconnect.
        socket = FakeSocket()
        asyncio.run(websockets.handle_personal_memory_snapshot(
            websocket=socket, payload={"request_id": REQUEST_ID}, auth_data=auth_data(),
            cache_service=cache, directus_service=directus,
        ))
        outcomes.append(socket.frames[0]["payload"])

    assert all(frame["success"] is True for frame in outcomes[:30])
    assert outcomes[30]["error"] == {"code": "rate_limited"}
    assert len(cache.redis.calls) == 31
    assert ledger_read.await_count == 30
    assert directus.device_reads == 30
    assert snapshot.await_count == 30


# contract-test: direct surface=rest_api assertions=auth.session.authoritative-enforcement
@pytest.mark.parametrize("failure", ["missing_client", "redis_error"])
def test_unavailable_shared_limiter_fails_closed_before_database_reads(monkeypatch, failure):
    cache, directus, socket = FakeCache(), FakeDirectus(), FakeSocket()
    if failure == "missing_client":
        cache.redis = None
    else:
        cache.redis.error = RuntimeError("Redis unavailable")
    ledger_read, _ = install_authority(monkeypatch)
    snapshot = AsyncMock()
    monkeypatch.setattr(websockets, "_load_fresh_personal_memories", snapshot)

    asyncio.run(websockets.handle_personal_memory_snapshot(
        websocket=socket, payload={"request_id": REQUEST_ID}, auth_data=auth_data(),
        cache_service=cache, directus_service=directus,
    ))

    assert socket.frames[0]["payload"]["error"] == {"code": "unavailable"}
    assert cache.reads == []
    ledger_read.assert_not_awaited()
    assert directus.device_reads == 0
    snapshot.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=auth.session.authoritative-enforcement
def test_user_budget_spans_distinct_session_hashes():
    cache = FakeCache()
    outcomes = [asyncio.run(websockets._personal_snapshot_rate_admission(
        cache, auth_data(session_hash=f"{index:064x}"),
    )) for index in range(1, 62)]
    assert outcomes == ["accepted"] * 60 + ["rate_limited"]
    assert len({user_key for _, user_key in cache.redis.calls}) == 1
