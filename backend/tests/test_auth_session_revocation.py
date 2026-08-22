# backend/tests/test_auth_session_revocation.py
# Regression coverage for targeted session revocation events.
# These tests call the FastAPI route function directly with fake services.
# No real cookies, credentials, Redis, Directus, or WebSocket clients are used.
# Access model: authenticated first-party session management REST surface.

import hashlib
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


USER_ID = "user-session-revoke"
CURRENT_REFRESH_TOKEN = "current-refresh-token"
TARGET_REFRESH_TOKEN = "target-refresh-token"
OTHER_REFRESH_TOKEN = "other-refresh-token"
CURRENT_TOKEN_HASH = hashlib.sha256(CURRENT_REFRESH_TOKEN.encode()).hexdigest()
TARGET_TOKEN_HASH = hashlib.sha256(TARGET_REFRESH_TOKEN.encode()).hexdigest()
OTHER_TOKEN_HASH = hashlib.sha256(OTHER_REFRESH_TOKEN.encode()).hexdigest()
CURRENT_CONNECTION_HASH = "a" * 64
TARGET_CONNECTION_HASH = "b" * 64
OTHER_CONNECTION_HASH = "c" * 64


class FakeCache:
    def __init__(self, tokens_map: dict):
        self.values = {f"user_tokens:{USER_ID}": tokens_map}
        self.deleted: list[str] = []
        self.published: list[tuple[str, dict]] = []
        self.set_calls: list[tuple[str, dict, int | None]] = []

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value: dict, ttl: int | None = None):
        self.values[key] = value
        self.set_calls.append((key, value, ttl))

    async def delete(self, key: str):
        self.deleted.append(key)
        self.values.pop(key, None)

    async def publish_event(self, *, channel: str, event_data: dict):
        self.published.append((channel, event_data))


class FakeCompliance:
    def __init__(self):
        self.events: list[dict] = []

    def log_auth_event_safe(self, **kwargs):
        self.events.append(kwargs)


def _request():
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(directus_service=SimpleNamespace())))


def _user():
    return SimpleNamespace(id=USER_ID)


def _stub_auth_session_imports(monkeypatch: pytest.MonkeyPatch):
    for module_name in [
        "backend.core.api.app.routes.auth_routes.auth_sessions",
        "backend.core.api.app.routes.auth_routes.auth_dependencies",
        "backend.core.api.app.services.directus",
        "backend.core.api.app.services.cache",
        "backend.core.api.app.services.compliance",
        "backend.core.api.app.services.chat_recovery_service",
        "backend.core.api.app.models.user",
        "backend.core.api.app.routes.handlers.websocket_handlers.chat_recovery_job_handlers",
    ]:
        monkeypatch.delitem(sys.modules, module_name, raising=False)

    auth_dependencies_module = types.ModuleType(
        "backend.core.api.app.routes.auth_routes.auth_dependencies"
    )
    auth_dependencies_module.get_directus_service = lambda: None
    auth_dependencies_module.get_cache_service = lambda: None
    auth_dependencies_module.get_current_user = lambda: None
    auth_dependencies_module.get_compliance_service = lambda: None

    directus_module = types.ModuleType("backend.core.api.app.services.directus")
    directus_module.DirectusService = object

    cache_module = types.ModuleType("backend.core.api.app.services.cache")
    cache_module.CacheService = object

    compliance_module = types.ModuleType("backend.core.api.app.services.compliance")
    compliance_module.ComplianceService = object

    recovery_module = types.ModuleType("backend.core.api.app.services.chat_recovery_service")

    class ChatRecoveryProtocolError(Exception):
        status_code = 500

    recovery_module.ChatRecoveryProtocolError = ChatRecoveryProtocolError

    handlers_module = types.ModuleType(
        "backend.core.api.app.routes.handlers.websocket_handlers.chat_recovery_job_handlers"
    )
    handlers_module.invalidate_recovery_leases_for_device = AsyncMock()

    user_module = types.ModuleType("backend.core.api.app.models.user")
    user_module.User = object

    monkeypatch.setitem(sys.modules, auth_dependencies_module.__name__, auth_dependencies_module)
    monkeypatch.setitem(sys.modules, directus_module.__name__, directus_module)
    monkeypatch.setitem(sys.modules, cache_module.__name__, cache_module)
    monkeypatch.setitem(sys.modules, compliance_module.__name__, compliance_module)
    monkeypatch.setitem(sys.modules, recovery_module.__name__, recovery_module)
    monkeypatch.setitem(sys.modules, handlers_module.__name__, handlers_module)
    monkeypatch.setitem(sys.modules, user_module.__name__, user_module)


def _revoke_session(monkeypatch: pytest.MonkeyPatch):
    _stub_auth_session_imports(monkeypatch)
    from backend.core.api.app.routes.auth_routes.auth_sessions import revoke_session

    return revoke_session


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=auth.session.lifecycle
async def test_revoke_session_targets_revoked_connection_hash(monkeypatch):
    revoke_session = _revoke_session(monkeypatch)
    cache = FakeCache({
        CURRENT_TOKEN_HASH: {"connection_hash": CURRENT_CONNECTION_HASH},
        TARGET_TOKEN_HASH: {"connection_hash": TARGET_CONNECTION_HASH},
        OTHER_TOKEN_HASH: {"connection_hash": OTHER_CONNECTION_HASH},
    })
    compliance = FakeCompliance()

    response = await revoke_session(
        _request(),
        TARGET_TOKEN_HASH[:12],
        current_user=_user(),
        cache_service=cache,
        compliance_service=compliance,
        refresh_token=CURRENT_REFRESH_TOKEN,
    )

    assert response.success is True
    assert f"session:{TARGET_TOKEN_HASH}" in cache.deleted
    assert set(cache.values[f"user_tokens:{USER_ID}"].keys()) == {
        CURRENT_TOKEN_HASH,
        OTHER_TOKEN_HASH,
    }
    assert len(cache.published) == 1
    channel, event = cache.published[0]
    assert channel == f"user_updates::{USER_ID}"
    assert event["event_for_client"] == "force_logout"
    assert event["target_device_fingerprint_hash"] == TARGET_CONNECTION_HASH
    assert event["payload"] == {
        "reason": "session_revoked",
        "revoked_session_id": TARGET_TOKEN_HASH[:12],
    }


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=auth.session.lifecycle
async def test_revoke_session_without_target_hash_does_not_broadcast_to_other_sessions(monkeypatch):
    revoke_session = _revoke_session(monkeypatch)
    cache = FakeCache({
        CURRENT_TOKEN_HASH: {"connection_hash": CURRENT_CONNECTION_HASH},
        TARGET_TOKEN_HASH: {},
        OTHER_TOKEN_HASH: {"connection_hash": OTHER_CONNECTION_HASH},
    })

    response = await revoke_session(
        _request(),
        TARGET_TOKEN_HASH[:12],
        current_user=_user(),
        cache_service=cache,
        compliance_service=FakeCompliance(),
        refresh_token=CURRENT_REFRESH_TOKEN,
    )

    assert response.success is True
    assert f"session:{TARGET_TOKEN_HASH}" in cache.deleted
    assert set(cache.values[f"user_tokens:{USER_ID}"].keys()) == {
        CURRENT_TOKEN_HASH,
        OTHER_TOKEN_HASH,
    }
    assert cache.published == []
