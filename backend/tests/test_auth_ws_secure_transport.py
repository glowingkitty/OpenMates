"""WebSocket handshakes never treat URL credentials or internal markers as proof."""
import asyncio
import hashlib
import importlib
import logging
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status


# contract-test: direct surface=rest_api assertions=auth.secrets.lifecycle,auth.session.authoritative-enforcement
def test_raw_query_refresh_token_and_forged_internal_cookie_are_rejected(monkeypatch):
    redis_module = ModuleType("redis")
    redis_asyncio_module = ModuleType("redis.asyncio")
    redis_asyncio_module.Redis = object
    redis_module.asyncio = redis_asyncio_module
    redis_module.exceptions = SimpleNamespace(ConnectionError=ConnectionError)
    monkeypatch.setitem(sys.modules, "redis", redis_module)
    monkeypatch.setitem(sys.modules, "redis.asyncio", redis_asyncio_module)
    directus_module = ModuleType("backend.core.api.app.services.directus")
    directus_module.DirectusService = object
    monkeypatch.setitem(sys.modules, directus_module.__name__, directus_module)
    auth_ws = importlib.import_module("backend.core.api.app.routes.auth_ws")
    monkeypatch.setattr(auth_ws, "verify_ws_token", lambda _token: None)
    monkeypatch.setattr(auth_ws, "get_pair_deadline_hash", AsyncMock(return_value=None))
    monkeypatch.setattr(auth_ws, "get_session_state_cached", AsyncMock(return_value=None))
    monkeypatch.setattr(auth_ws.ComplianceService, "log_auth_event_safe", lambda **_kwargs: None)

    raw_token = "refresh-secret"
    target_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    class Cache:
        SESSION_KEY_PREFIX = "session:"

        def __init__(self):
            self.reads = []

        async def get(self, key):
            self.reads.append(key)
            if key == f"session:{target_hash}":
                return {"user_id": "u1"}
            return None

        async def get_user_by_id(self, _user_id):
            return {"user_id": "u1"}

    class Socket:
        def __init__(self, cache, *, cookie=None, query=None):
            self.app = SimpleNamespace(state=SimpleNamespace(
                cache_service=cache, directus_service=SimpleNamespace(),
            ))
            self.cookies = {"auth_refresh_token": cookie} if cookie else {}
            self.query_params = {"sessionId": "browser-session", **(query or {})}
            self.headers = {}
            self.closes = []

        async def close(self, **kwargs):
            self.closes.append(kwargs)

    async def run():
        cache = Cache()
        raw_query = Socket(cache, query={"token": raw_token})
        assert await auth_ws.get_current_user_ws(raw_query) is None
        assert raw_query.closes
        assert f"session:{target_hash}" not in cache.reads

        marker = Socket(cache, cookie=f"__ws_verified__{target_hash}")
        assert await auth_ws.get_current_user_ws(marker) is None
        assert marker.closes
        assert f"session:{target_hash}" not in cache.reads

    asyncio.run(run())


# contract-test: direct surface=rest_api assertions=auth.session.authoritative-enforcement,auth.session.lifecycle
def test_signed_ws_cache_link_is_enrolled_in_durable_authority_before_admission(monkeypatch):
    auth_ws = importlib.import_module("backend.core.api.app.routes.auth_ws")
    digest = hashlib.sha256(b"issued-cookie").hexdigest()
    monkeypatch.setattr(auth_ws, "verify_ws_token", lambda token: digest if token == "signed-ws-token" else None)
    monkeypatch.setattr(auth_ws, "get_pair_deadline_hash", AsyncMock(return_value=None))
    monkeypatch.setattr(auth_ws, "get_session_state_cached", AsyncMock(return_value=None))
    enroll = AsyncMock(return_value={"user_id": "u1", "expires_at": 4102444800})
    monkeypatch.setattr(auth_ws, "ensure_legacy_session_hash_state", enroll)
    monkeypatch.setattr(
        auth_ws, "generate_device_fingerprint_hash",
        lambda *_args: ("known-device", "connection", None, None, None, None, None, None),
    )
    monkeypatch.setattr(auth_ws.ComplianceService, "log_auth_event_safe", lambda **_kwargs: None)

    class Cache:
        SESSION_KEY_PREFIX = "session:"

        async def get(self, key):
            if key == f"session:{digest}":
                return {"user_id": "u1"}
            if key == "user_tokens:u1":
                return {digest: {"device_hash": "registered-device"}}
            return None

        async def get_user_by_id(self, user_id):
            return {"user_id": user_id}

    class Directus:
        async def get_user_device_hashes(self, user_id):
            assert user_id == "u1"
            return ["known-device", "registered-device"]

    class Socket:
        app = SimpleNamespace(state=SimpleNamespace(
            cache_service=Cache(), directus_service=Directus(),
        ))
        cookies = {}
        query_params = {"token": "signed-ws-token", "sessionId": "browser-session"}
        headers = {}

        async def close(self, **_kwargs):
            raise AssertionError("Valid signed session was closed")

    result = asyncio.run(auth_ws.get_current_user_ws(Socket()))
    assert result["user_id"] == "u1"
    assert result["device_fingerprint_hash"] == "connection"
    assert result["stable_device_fingerprint_hash"] == "registered-device"
    assert result["session_expires_at"] == 4102444800
    enroll.assert_awaited_once_with(Socket.app.state.directus_service,
                                    Socket.app.state.cache_service, digest, "u1")


@pytest.mark.parametrize(
    ("http_status", "expected_close", "expected_log_level"),
    [
        (401, status.WS_1008_POLICY_VIOLATION, "WARNING"),
        (403, status.WS_1008_POLICY_VIOLATION, "WARNING"),
        (503, status.WS_1011_INTERNAL_ERROR, "ERROR"),
    ],
)
# contract-test: direct surface=rest_api assertions=auth.session.authoritative-enforcement,auth.session.lifecycle
def test_session_authority_denial_closes_websocket_with_matching_failure_class(
    monkeypatch, http_status, expected_close, expected_log_level,
):
    auth_ws = importlib.import_module("backend.core.api.app.routes.auth_ws")
    detail = "Session security state unavailable" if http_status == 503 else "Session expired or revoked"
    authority = AsyncMock(side_effect=HTTPException(http_status, detail))
    monkeypatch.setattr(auth_ws, "get_session_state_cached", authority)
    monkeypatch.setattr(auth_ws, "get_pair_deadline_hash", AsyncMock(return_value=None))

    class Cache:
        SESSION_KEY_PREFIX = "session:"

        async def get(self, _key):
            return {"user_id": "u1"}

    class Socket:
        app = SimpleNamespace(state=SimpleNamespace(
            cache_service=Cache(), directus_service=SimpleNamespace(),
        ))
        cookies = {"auth_refresh_token": "issued-cookie"}
        query_params = {"sessionId": "browser-session"}
        headers = {}

        def __init__(self):
            self.closes = []

        async def close(self, **kwargs):
            self.closes.append(kwargs)

    socket = Socket()
    matching_logs = []
    capture_handler = logging.Handler()
    capture_handler.emit = matching_logs.append
    old_level = auth_ws.logger.level
    auth_ws.logger.addHandler(capture_handler)
    auth_ws.logger.setLevel(logging.DEBUG)
    try:
        result = asyncio.run(auth_ws.get_current_user_ws(socket))
    finally:
        auth_ws.logger.removeHandler(capture_handler)
        auth_ws.logger.setLevel(old_level)

    assert result is None
    assert socket.closes == [{
        "code": expected_close,
        "reason": "Invalid session" if http_status in (401, 403) else "Authentication error",
    }]
    authority.assert_awaited_once()
    assert any(record.levelname == expected_log_level for record in matching_logs)
    if http_status in (401, 403):
        assert all(record.levelname != "ERROR" for record in matching_logs)
