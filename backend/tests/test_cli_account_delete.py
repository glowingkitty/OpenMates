"""
CLI account deletion contract tests.

The public web deletion flow can use email OTP as one authentication method.
The CLI has a stricter dedicated command: every deletion requires a verified
email code, and accounts with 2FA must also provide a current TOTP code.
These tests verify the backend fail-closed flag before any destructive task.

Execution:
  /OpenMates/.venv/bin/python3 -m pytest backend/tests/test_cli_account_delete.py
"""

import sys
import re
import types
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

if "redis" not in sys.modules:
    redis_module = types.ModuleType("redis")
    redis_asyncio_module = types.ModuleType("redis.asyncio")

    class FakeRedisClient:
        pass

    redis_asyncio_module.Redis = FakeRedisClient
    redis_module.asyncio = redis_asyncio_module
    redis_module.exceptions = SimpleNamespace(RedisError=Exception, ConnectionError=Exception, TimeoutError=Exception)
    sys.modules["redis"] = redis_module
    sys.modules["redis.asyncio"] = redis_asyncio_module

if "aiohttp" not in sys.modules:
    aiohttp_module = types.ModuleType("aiohttp")

    class FakeClientSession:
        pass

    aiohttp_module.ClientSession = FakeClientSession
    sys.modules["aiohttp"] = aiohttp_module

if "regex" not in sys.modules:
    regex_module = types.ModuleType("regex")
    regex_module.compile = re.compile
    regex_module.match = re.match
    regex_module.search = re.search
    regex_module.sub = re.sub
    regex_module.IGNORECASE = re.IGNORECASE
    sys.modules["regex"] = regex_module

if "slowapi" not in sys.modules:
    slowapi_module = types.ModuleType("slowapi")
    slowapi_util_module = types.ModuleType("slowapi.util")

    class FakeLimiter:
        def __init__(self, *args, **kwargs):
            pass

        def limit(self, *_args, **_kwargs):
            def decorator(route_handler):
                return route_handler

            return decorator

    slowapi_module.Limiter = FakeLimiter
    slowapi_util_module.get_remote_address = lambda request: "test-client"
    sys.modules["slowapi"] = slowapi_module
    sys.modules["slowapi.util"] = slowapi_util_module

if "backend.core.api.app.tasks.celery_config" not in sys.modules:
    tasks_module = types.ModuleType("backend.core.api.app.tasks")
    celery_config_module = types.ModuleType("backend.core.api.app.tasks.celery_config")
    celery_config_module.app = SimpleNamespace(send_task=lambda **_kwargs: None)
    tasks_module.__path__ = []
    sys.modules["backend.core.api.app.tasks"] = tasks_module
    sys.modules["backend.core.api.app.tasks.celery_config"] = celery_config_module

if "backend.core.api.app.routes.websockets" not in sys.modules:
    websockets_module = types.ModuleType("backend.core.api.app.routes.websockets")

    async def fake_broadcast_to_user_specific_event(**_kwargs):
        return None

    websockets_module.manager = SimpleNamespace(
        broadcast_to_user_specific_event=fake_broadcast_to_user_specific_event,
    )
    sys.modules["backend.core.api.app.routes.websockets"] = websockets_module

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
def test_sensitive_action_email_codes_allow_team_delete_step_up():
    assert "delete_account" in settings.ALLOWED_VERIFICATION_ACTIONS
    assert "delete_team" in settings.ALLOWED_VERIFICATION_ACTIONS


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
