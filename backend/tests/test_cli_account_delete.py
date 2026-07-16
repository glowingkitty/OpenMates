"""
CLI account deletion contract tests.

The public web deletion flow can use email OTP as one authentication method.
The CLI has a stricter dedicated command: every deletion requires a verified
email code, and accounts with 2FA must also provide a current TOTP code.
These tests verify the backend fail-closed flag before any destructive task.

Execution:
  /OpenMates/.venv/bin/python3 -m pytest backend/tests/test_cli_account_delete.py
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend.core.api.app.routes import settings


def fake_request():
    return Request({"type": "http", "method": "POST", "path": "/v1/settings/delete-account", "headers": [], "client": ("127.0.0.1", 12345)})


class FakeDeleteCache:
    def __init__(self, values=None):
        self.values = values or {}

    async def get(self, key):
        return self.values.get(key)

    async def delete(self, key):
        self.values.pop(key, None)


class FakePasskeyDeleteDirectus:
    async def get_passkey_by_credential_id(self, credential_id):
        return {"id": "passkey-1", "user_id": "user-1", "credential_id": credential_id}


class FakePreviewCache:
    updated_user = None

    async def get_user_by_id(self, user_id):
        return None

    async def update_user(self, user_id, data):
        self.updated_user = (user_id, data)
        return True


class FakePreviewDirectus:
    async def get_user_fields_direct(self, user_id, fields):
        return {"credits": "0"}

    async def get_items(self, collection, params):
        raise AssertionError("Zero-balance delete previews must not query refund collections")


@pytest.mark.anyio
async def test_cli_delete_requires_verified_email_code_before_auth(monkeypatch):
    async def fake_preview(**kwargs):
        return SimpleNamespace()

    monkeypatch.setattr(settings, "_calculate_delete_account_preview", fake_preview)
    monkeypatch.setattr(
        settings,
        "generate_device_fingerprint_hash",
        lambda *args, **kwargs: ("device-hash", None, None, None, None, None, None, None),
    )

    delete_account_route = getattr(settings.delete_account, "__wrapped__", settings.delete_account)
    with pytest.raises(HTTPException) as exc_info:
        await delete_account_route(
            request=fake_request(),
            delete_request=settings.DeleteAccountRequest(
                confirm_data_deletion=True,
                auth_method="email_otp",
                require_email_verification=True,
            ),
            current_user=SimpleNamespace(id="user-1", vault_key_id="vault-key-1"),
            directus_service=SimpleNamespace(),
            encryption_service=SimpleNamespace(),
            compliance_service=SimpleNamespace(),
            cache_service=FakeDeleteCache(),
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Email verification required"


@pytest.mark.anyio
async def test_delete_account_passkey_requires_recent_webauthn_proof(monkeypatch):
    async def fake_preview(**kwargs):
        return SimpleNamespace()

    monkeypatch.setattr(settings, "_calculate_delete_account_preview", fake_preview)
    monkeypatch.setattr(
        settings,
        "generate_device_fingerprint_hash",
        lambda *args, **kwargs: ("device-hash", None, None, None, None, None, None, None),
    )

    delete_account_route = getattr(settings.delete_account, "__wrapped__", settings.delete_account)
    with pytest.raises(HTTPException) as exc_info:
        await delete_account_route(
            request=fake_request(),
            delete_request=settings.DeleteAccountRequest(
                confirm_data_deletion=True,
                auth_method="passkey",
                auth_code="credential-1",
            ),
            current_user=SimpleNamespace(id="user-1", vault_key_id="vault-key-1"),
            directus_service=FakePasskeyDeleteDirectus(),
            encryption_service=SimpleNamespace(),
            compliance_service=SimpleNamespace(),
            cache_service=FakeDeleteCache(),
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid passkey authentication"


@pytest.mark.anyio
async def test_delete_preview_zero_balance_skips_refund_collection_queries():
    cache = FakePreviewCache()

    preview = await settings._calculate_delete_account_preview(
        user_id="user-1",
        user_id_hash="hash-1",
        vault_key_id="vault-key-1",
        directus_service=FakePreviewDirectus(),
        encryption_service=SimpleNamespace(),
        cache_service=cache,
    )

    assert preview.total_credits == 0
    assert preview.has_refundable_credits is False
    assert preview.auto_refunds["eligible_invoices"] == []
    assert cache.updated_user == ("user-1", {"credits": 0})
