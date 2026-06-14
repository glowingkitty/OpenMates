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
    async def get(self, key):
        return None


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

    with pytest.raises(HTTPException) as exc_info:
        await settings.delete_account(
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
