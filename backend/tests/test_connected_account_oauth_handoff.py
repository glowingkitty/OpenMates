# backend/tests/test_connected_account_oauth_handoff.py
#
# Tests for provider-neutral OAuth refresh-token handoffs.
# Provider adapters may briefly receive plaintext refresh tokens during OAuth code
# exchange, but persistence must be encrypted, owner-bound, short-lived, and
# claimable exactly once by the browser for client-side encrypted row storage.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from __future__ import annotations

import json
import sys
from base64 import b64decode, b64encode
from types import SimpleNamespace

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


@pytest.mark.asyncio
async def test_oauth_handoff_stores_encrypted_bundle_and_claims_once() -> None:
    from backend.core.api.app.services.connected_account_oauth_handoff import (
        ConnectedAccountOAuthHandoffService,
        OAUTH_HANDOFF_PREFIX,
    )

    cache = FakeCache()
    service = ConnectedAccountOAuthHandoffService(
        cache_service=cache,
        encryption_service=FakeEncryption(),
        ttl_seconds=90,
    )

    handoff = await service.create_handoff(
        user_id="user-1",
        user_vault_key_id="vault-1",
        provider_id="google_calendar",
        refresh_token_bundle={"refresh_token": "secret-refresh", "provider": "google"},
        account_hint={"label": "Work calendar"},
    )

    cache_key = f"{OAUTH_HANDOFF_PREFIX}{handoff.handoff_id}"
    cached = cache.values[cache_key]
    assert cached["user_id"] == "user-1"
    assert cache.ttls[cache_key] == 90
    assert "secret-refresh" not in json.dumps(cached)
    assert "Work calendar" not in json.dumps(cached)

    claimed = await service.claim_handoff(
        handoff_id=handoff.handoff_id,
        user_id="user-1",
        user_vault_key_id="vault-1",
    )
    assert claimed.provider_id == "google_calendar"
    assert claimed.refresh_token_bundle["refresh_token"] == "secret-refresh"
    assert claimed.account_hint == {"label": "Work calendar"}
    assert cache_key not in cache.values

    with pytest.raises(PermissionError, match="expired or not found"):
        await service.claim_handoff(
            handoff_id=handoff.handoff_id,
            user_id="user-1",
            user_vault_key_id="vault-1",
        )


@pytest.mark.asyncio
async def test_oauth_handoff_rejects_owner_mismatch_without_deleting() -> None:
    from backend.core.api.app.services.connected_account_oauth_handoff import (
        ConnectedAccountOAuthHandoffService,
        OAUTH_HANDOFF_PREFIX,
    )

    cache = FakeCache()
    service = ConnectedAccountOAuthHandoffService(
        cache_service=cache,
        encryption_service=FakeEncryption(),
        ttl_seconds=90,
    )
    handoff = await service.create_handoff(
        user_id="user-1",
        user_vault_key_id="vault-1",
        provider_id="github",
        refresh_token_bundle={"refresh_token": "secret-refresh"},
    )

    with pytest.raises(PermissionError, match="owner mismatch"):
        await service.claim_handoff(
            handoff_id=handoff.handoff_id,
            user_id="user-2",
            user_vault_key_id="vault-2",
        )
    assert f"{OAUTH_HANDOFF_PREFIX}{handoff.handoff_id}" in cache.values


@pytest.mark.asyncio
async def test_oauth_handoff_claim_route_returns_payload_for_owner() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

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
    from backend.core.api.app.models.user import User
    from backend.core.api.app.routes import connected_account_oauth
    from backend.core.api.app.services.connected_account_oauth_handoff import (
        ConnectedAccountOAuthHandoffService,
    )

    cache = FakeCache()
    encryption = FakeEncryption()
    service = ConnectedAccountOAuthHandoffService(
        cache_service=cache,
        encryption_service=encryption,
        ttl_seconds=90,
    )
    handoff = await service.create_handoff(
        user_id="user-1",
        user_vault_key_id="vault-1",
        provider_id="google_calendar",
        refresh_token_bundle={"refresh_token": "secret-refresh", "provider": "google"},
        account_hint={"label": "Work calendar"},
    )

    app = FastAPI()
    app.include_router(connected_account_oauth.router)
    user = User(id="user-1", username="alice", vault_key_id="vault-1")
    app.dependency_overrides[connected_account_oauth.get_current_user] = lambda: user
    app.dependency_overrides[connected_account_oauth.get_cache_service] = lambda: cache
    app.dependency_overrides[connected_account_oauth.get_encryption_service] = lambda: encryption
    client = TestClient(app)

    response = client.post(f"/v1/connected-account-oauth/handoffs/{handoff.handoff_id}/claim")

    assert response.status_code == 200
    assert response.json() == {
        "provider_id": "google_calendar",
        "refresh_token_bundle": {"refresh_token": "secret-refresh", "provider": "google"},
        "account_hint": {"label": "Work calendar"},
        "expires_at": handoff.expires_at,
    }
