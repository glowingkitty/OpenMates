# backend/tests/test_google_calendar_oauth_adapter.py
#
# Tests for the Google Calendar connected-account OAuth adapter.
# The adapter is the first provider implementation of the generic OAuth handoff
# architecture: confidential code exchange on backend, one-time handoff to
# browser, then client-side encrypted connected-account row storage.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from __future__ import annotations

import sys
from base64 import b64decode, b64encode
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


class FakeCache:
    def __init__(self) -> None:
        self.values: dict[str, dict] = {}
        self.ttls: dict[str, int] = {}

    async def set(self, key: str, value: dict, ttl: int | None = None) -> bool:
        self.values[key] = dict(value)
        self.ttls[key] = int(ttl or 0)
        return True

    async def get(self, key: str):
        return self.values.get(key)

    async def delete(self, key: str) -> bool:
        return self.values.pop(key, None) is not None


class FakeEncryption:
    async def encrypt_with_user_key(self, plaintext: str, vault_key_id: str):
        return f"enc:{vault_key_id}:{b64encode(plaintext.encode()).decode()}", vault_key_id

    async def decrypt_with_user_key(self, ciphertext: str, vault_key_id: str):
        prefix = f"enc:{vault_key_id}:"
        if not ciphertext.startswith(prefix):
            raise ValueError("wrong vault key")
        return b64decode(ciphertext[len(prefix):].encode()).decode()


class FakeSecretsManager:
    vault_token = "vault-token"
    vault_url = "http://vault:8200"

    def __init__(self, values: dict[tuple[str, str], str]) -> None:
        self.values = values

    async def initialize(self) -> bool:
        return True

    async def get_secret(self, secret_path: str, secret_key: str, log_missing: bool = True):
        return self.values.get((secret_path, secret_key))


def import_route_module():
    sys.modules.setdefault(
        "backend.core.api.app.services.directus",
        SimpleNamespace(DirectusService=object),
    )
    sys.modules.setdefault(
        "backend.core.api.app.services.directus.directus",
        SimpleNamespace(DirectusService=object),
    )
    sys.modules.setdefault(
        "backend.core.api.app.services.cache",
        SimpleNamespace(CacheService=object),
    )
    from backend.core.api.app.routes import provider_oauth_google_calendar

    return provider_oauth_google_calendar


def make_client(cache: FakeCache, encryption: FakeEncryption | None = None):
    from backend.core.api.app.models.user import User

    route = import_route_module()
    app = FastAPI()
    app.include_router(route.router)
    user = User(id="user-1", username="alice", vault_key_id="vault-1")
    app.dependency_overrides[route.get_current_user] = lambda: user
    app.dependency_overrides[route.get_cache_service] = lambda: cache
    app.dependency_overrides[route.get_encryption_service] = lambda: encryption or FakeEncryption()
    return TestClient(app), route


def test_google_calendar_start_uses_minimal_read_scope(monkeypatch) -> None:
    monkeypatch.setenv("SECRET__GOOGLE__OAUTH_CLIENT_ID", "client-123")
    monkeypatch.setenv("SECRET__GOOGLE__OAUTH_CLIENT_SECRET", "secret-123")
    monkeypatch.setenv("GOOGLE_CALENDAR_OAUTH_REDIRECT_URI", "https://api.dev.openmates.org/v1/provider-oauth/google/calendar/callback")
    cache = FakeCache()
    client, route = make_client(cache)

    response = client.post(
        "/v1/provider-oauth/google/calendar/start",
        json={"capabilities": ["read"], "return_path": "/#settings/app_store/calendar"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["scopes"] == [route.CALENDAR_READ_SCOPE]
    parsed = urlparse(payload["authorization_url"])
    params = parse_qs(parsed.query)
    assert parsed.netloc == "accounts.google.com"
    assert params["client_id"] == ["client-123"]
    assert params["access_type"] == ["offline"]
    assert params["prompt"] == ["consent"]
    assert params["scope"] == [route.CALENDAR_READ_SCOPE]
    state = params["state"][0]
    state_key = route._state_key(state)
    assert cache.values[state_key]["user_id"] == "user-1"
    assert cache.values[state_key]["scopes"] == [route.CALENDAR_READ_SCOPE]


@pytest.mark.anyio
async def test_google_oauth_credentials_fall_back_to_vault(monkeypatch) -> None:
    from backend.shared.providers.google_calendar.oauth import get_google_oauth_credentials

    for env_var_name in (
        "GOOGLE_CALENDAR_CLIENT_ID",
        "GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_CALENDAR_CLIENT_SECRET",
        "GOOGLE_OAUTH_CLIENT_SECRET",
        "SECRET__GOOGLE__OAUTH_CLIENT_ID",
        "SECRET__GOOGLE__OAUTH_CLIENT_SECRET",
        "SECRET__GOOGLE_CALENDAR__OAUTH_CLIENT_ID",
        "SECRET__GOOGLE_CALENDAR__OAUTH_CLIENT_SECRET",
    ):
        monkeypatch.delenv(env_var_name, raising=False)

    secrets_manager = FakeSecretsManager(
        {
            ("kv/data/providers/google_calendar", "oauth_client_id"): "vault-client-id",
            ("kv/data/providers/google_calendar", "oauth_client_secret"): "vault-client-secret",
        }
    )

    assert await get_google_oauth_credentials(secrets_manager) == (
        "vault-client-id",
        "vault-client-secret",
    )


@pytest.mark.anyio
async def test_google_oauth_credentials_prefer_generic_google_env(monkeypatch) -> None:
    from backend.shared.providers.google_calendar.oauth import get_google_oauth_credentials

    monkeypatch.setenv("SECRET__GOOGLE__OAUTH_CLIENT_ID", "generic-client-id")
    monkeypatch.setenv("SECRET__GOOGLE__OAUTH_CLIENT_SECRET", "generic-client-secret")
    monkeypatch.setenv("SECRET__GOOGLE_CALENDAR__OAUTH_CLIENT_ID", "calendar-client-id")
    monkeypatch.setenv("SECRET__GOOGLE_CALENDAR__OAUTH_CLIENT_SECRET", "calendar-client-secret")

    assert await get_google_oauth_credentials(FakeSecretsManager({})) == (
        "generic-client-id",
        "generic-client-secret",
    )


def test_google_calendar_start_uses_events_scope_for_write_or_delete(monkeypatch) -> None:
    monkeypatch.setenv("SECRET__GOOGLE__OAUTH_CLIENT_ID", "client-123")
    monkeypatch.setenv("SECRET__GOOGLE__OAUTH_CLIENT_SECRET", "secret-123")
    cache = FakeCache()
    client, route = make_client(cache)

    response = client.post(
        "/v1/provider-oauth/google/calendar/start",
        json={"capabilities": ["read", "write", "delete"]},
    )

    assert response.status_code == 200
    assert response.json()["scopes"] == [route.CALENDAR_EVENTS_SCOPE]


@pytest.mark.anyio
async def test_google_calendar_callback_creates_encrypted_handoff_and_redirects(monkeypatch) -> None:
    monkeypatch.setenv("SECRET__GOOGLE__OAUTH_CLIENT_ID", "client-123")
    monkeypatch.setenv("SECRET__GOOGLE__OAUTH_CLIENT_SECRET", "secret-123")
    monkeypatch.setenv("WEBAPP_URL", "https://app.dev.openmates.org")
    cache = FakeCache()
    encryption = FakeEncryption()
    client, route = make_client(cache, encryption)

    async def fake_exchange_google_authorization_code(*, code: str, redirect_uri: str):
        assert code == "code-123"
        assert redirect_uri == "https://api.dev.openmates.org/oauth/google/calendar/callback"
        return {
            "refresh_token": "secret-refresh-token",
            "token_type": "Bearer",
            "scope": route.CALENDAR_READ_SCOPE,
        }

    monkeypatch.setattr(route, "exchange_google_authorization_code", fake_exchange_google_authorization_code)
    await cache.set(
        route._state_key("state-123"),
        {
            "user_id": "user-1",
            "capabilities": ["read"],
            "scopes": [route.CALENDAR_READ_SCOPE],
            "redirect_uri": "https://api.dev.openmates.org/oauth/google/calendar/callback",
            "return_path": "/#settings/app_store/calendar",
            "expires_at": 999,
        },
        ttl=600,
    )

    response = client.get(
        "/v1/provider-oauth/google/calendar/callback?code=code-123&state=state-123",
        follow_redirects=False,
    )

    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("https://app.dev.openmates.org/?oauth_handoff_id=oauth_handoff_")
    assert location.endswith("#settings/app_store/calendar")
    assert "secret-refresh-token" not in location
    assert route._state_key("state-123") not in cache.values

    handoff_keys = [key for key in cache.values if key.startswith("connected_account:oauth_handoff:")]
    assert len(handoff_keys) == 1
    cached_handoff = cache.values[handoff_keys[0]]
    assert cached_handoff["user_id"] == "user-1"
    assert "secret-refresh-token" not in str(cached_handoff)


def test_google_calendar_callback_rejects_owner_mismatch(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_CALENDAR_CLIENT_ID", "client-123")
    cache = FakeCache()
    client, route = make_client(cache)

    cache.values[route._state_key("state-123")] = {
        "user_id": "other-user",
        "scopes": [route.CALENDAR_READ_SCOPE],
        "redirect_uri": "https://api.dev.openmates.org/oauth/google/calendar/callback",
    }

    response = client.get(
        "/v1/provider-oauth/google/calendar/callback?code=code-123&state=state-123",
        follow_redirects=False,
    )

    assert response.status_code == 403
