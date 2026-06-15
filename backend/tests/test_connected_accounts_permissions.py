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


@pytest.mark.asyncio
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
