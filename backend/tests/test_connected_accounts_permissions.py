# backend/tests/test_connected_accounts_permissions.py
#
# Contract tests for the connected-account permission platform.
# These tests cover the privacy-preserving connected account row validator,
# REST/API-key exclusion for client-mediated provider skills, and capability
# decisions before the Calendar app implementation is wired into UI flows.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from __future__ import annotations

import sys
from types import SimpleNamespace
import hashlib

import pytest


def test_connected_account_row_rejects_plaintext_provider_identity() -> None:
    from backend.core.api.app.services.connected_accounts_service import (
        ConnectedAccountRow,
    )

    with pytest.raises(ValueError, match="plaintext"):
        ConnectedAccountRow.validate_for_storage(
            {
                "id": "acct-1",
                "hashed_user_id": "hash-user",
                "encrypted_provider_type": "enc:google",
                "provider_type_hash": "hmac-provider",
                "encrypted_account_label": "enc:work",
                "encrypted_refresh_token_bundle": "enc:refresh",
                "encrypted_capabilities": "enc:caps",
                "encrypted_app_permissions": "enc:perms",
                "provider_email": "alice@example.com",
            }
        )


def test_connected_account_row_requires_encrypted_fields() -> None:
    from backend.core.api.app.services.connected_accounts_service import (
        ConnectedAccountRow,
    )

    valid = ConnectedAccountRow.validate_for_storage(
        {
            "id": "acct-1",
            "hashed_user_id": "hash-user",
            "encrypted_provider_type": "enc:google",
            "provider_type_hash": "hmac-provider",
            "encrypted_account_label": "enc:work",
            "encrypted_refresh_token_bundle": "enc:refresh",
            "encrypted_capabilities": "enc:caps",
            "encrypted_app_permissions": "enc:perms",
        }
    )

    assert valid.id == "acct-1"
    assert valid.server_access_enabled is False

    with pytest.raises(ValueError, match="encrypted_refresh_token_bundle"):
        ConnectedAccountRow.validate_for_storage(
            {
                "id": "acct-1",
                "hashed_user_id": "hash-user",
                "encrypted_provider_type": "enc:google",
                "provider_type_hash": "hmac-provider",
                "encrypted_account_label": "enc:work",
                "encrypted_capabilities": "enc:caps",
                "encrypted_app_permissions": "enc:perms",
            }
        )


def test_websocket_connected_account_payload_rejects_plaintext_secrets(monkeypatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "backend.core.api.app.services.cache",
        SimpleNamespace(CacheService=object),
    )
    monkeypatch.setitem(
        sys.modules,
        "backend.core.api.app.services.directus.directus",
        SimpleNamespace(DirectusService=object),
    )
    from backend.core.api.app.routes.handlers.websocket_handlers.message_received_handler import (
        _sanitize_connected_account_directory,
        _sanitize_connected_account_token_refs,
    )

    clean_directory = _sanitize_connected_account_directory(
        [
            {
                "connected_account_id": "acct-1",
                "app_id": "calendar",
                "account_ref": "calendar-account-1",
                "label": "Work calendar",
                "capabilities": ["read"],
            }
        ]
    )
    clean_refs = _sanitize_connected_account_token_refs(
        [
            {
                "connected_account_id": "acct-1",
                "app_id": "calendar",
                "turn_token_ref": "tref_123",
                "allowed_actions": ["read"],
            }
        ]
    )

    assert clean_directory[0]["account_ref"] == "calendar-account-1"
    assert clean_refs[0]["turn_token_ref"] == "tref_123"

    with pytest.raises(ValueError, match="refresh_token"):
        _sanitize_connected_account_token_refs(
            [{"turn_token_ref": "tref_123", "refresh_token": "secret"}]
        )
    with pytest.raises(ValueError, match="provider_email"):
        _sanitize_connected_account_directory(
            [{"connected_account_id": "acct-1", "provider_email": "user@example.com"}]
        )


def test_connected_account_skill_rest_execution_requires_offline_grant() -> None:
    from backend.apps.ai.processing.permission_broker import (
        ConnectedAccountAction,
        assert_rest_connected_account_execution_allowed,
    )

    action = ConnectedAccountAction(
        app_id="calendar",
        action="read",
        account_ref="google-work",
        runtime_mode="allow_automatically",
    )

    with pytest.raises(PermissionError, match="client-held refresh tokens"):
        assert_rest_connected_account_execution_allowed(action, offline_grant=None)

    assert_rest_connected_account_execution_allowed(
        action,
        offline_grant={
            "app_id": "calendar",
            "actions": ["read"],
            "account_ref": "google-work",
            "expires_at": 4_102_444_800,
            "revoked": False,
        },
    )


@pytest.mark.anyio
async def test_connected_accounts_routes_store_only_owned_encrypted_rows() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    sys.modules.setdefault(
        "backend.core.api.app.services.cache",
        SimpleNamespace(CacheService=object),
    )
    sys.modules.setdefault(
        "backend.core.api.app.services.directus",
        SimpleNamespace(DirectusService=object),
    )
    sys.modules.setdefault(
        "backend.core.api.app.services.directus.directus",
        SimpleNamespace(DirectusService=object),
    )
    from backend.core.api.app.routes import connected_accounts
    from backend.core.api.app.models.user import User

    class FakeDirectus:
        def __init__(self) -> None:
            self.rows: dict[str, dict] = {}

        async def get_items(self, _collection: str, params: dict | None = None):
            hashed_user_id = (params or {}).get("filter[hashed_user_id][_eq]")
            account_id = (params or {}).get("filter[id][_eq]")
            rows = [row for row in self.rows.values() if row.get("hashed_user_id") == hashed_user_id]
            if account_id:
                rows = [row for row in rows if row.get("id") == account_id]
            return rows

        async def create_item(self, _collection: str, payload: dict):
            self.rows[payload["id"]] = dict(payload)
            return True, dict(payload)

        async def update_item(self, _collection: str, item_id: str, payload: dict):
            self.rows[item_id].update(payload)
            return dict(self.rows[item_id])

    fake_directus = FakeDirectus()
    user = User(id="user-1", username="alice", vault_key_id="vault-1")
    hashed_user_id = hashlib.sha256(user.id.encode()).hexdigest()
    app = FastAPI()
    app.include_router(connected_accounts.router)
    app.dependency_overrides[connected_accounts.get_current_user] = lambda: user
    app.dependency_overrides[connected_accounts.get_directus_service] = lambda: fake_directus
    client = TestClient(app)

    row = {
        "id": "acct-1",
        "hashed_user_id": hashed_user_id,
        "encrypted_provider_type": "enc:google",
        "provider_type_hash": "hash:google",
        "encrypted_account_label": "enc:work",
        "encrypted_refresh_token_bundle": "enc:refresh",
        "encrypted_capabilities": "enc:caps",
        "encrypted_app_permissions": "enc:perms",
    }

    create_response = client.post("/v1/connected-accounts", json=row)
    assert create_response.status_code == 200
    assert create_response.json()["id"] == "acct-1"

    list_response = client.get("/v1/connected-accounts")
    assert list_response.status_code == 200
    assert list_response.json()["rows"][0]["id"] == "acct-1"

    patch_response = client.patch(
        "/v1/connected-accounts/acct-1",
        json={"encrypted_account_label": "enc:renamed"},
    )
    assert patch_response.status_code == 200
    assert fake_directus.rows["acct-1"]["encrypted_account_label"] == "enc:renamed"

    bad_owner_response = client.post(
        "/v1/connected-accounts",
        json={**row, "id": "acct-2", "hashed_user_id": "wrong"},
    )
    assert bad_owner_response.status_code == 403

    plaintext_response = client.patch(
        "/v1/connected-accounts/acct-1",
        json={"provider_email": "user@example.com"},
    )
    assert plaintext_response.status_code == 400


@pytest.mark.anyio
async def test_rest_skill_helper_blocks_hidden_connected_account_skill() -> None:
    from fastapi import HTTPException

    from backend.core.api.app.services.rest_skill_execution_policy import (
        assert_rest_skill_execution_allowed,
    )

    class FakeRegistry:
        def get_metadata(self, app_id: str):
            return SimpleNamespace(
                id=app_id,
                skills=[
                    SimpleNamespace(
                        id="get-events",
                        api_config=SimpleNamespace(expose_post=False),
                    )
                ],
            )

    with pytest.raises(HTTPException) as exc_info:
        assert_rest_skill_execution_allowed(FakeRegistry(), "calendar", "get-events")

    assert exc_info.value.status_code == 403
