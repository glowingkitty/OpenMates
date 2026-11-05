"""Authentication common regression tests.

Purpose: cover session-auth helpers without importing the full API runtime.
Scope: narrow cache-hit behavior for auth_common.verify_authenticated_user.
Security: stale Redis profile data must not hide active server-admin records.
Run: python3 -m pytest backend/tests/test_auth_common.py
"""

# contract-test-file: infrastructure

import importlib
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers


def _import_auth_common(monkeypatch: pytest.MonkeyPatch):
    module_names = [
        "backend.core.api.app.routes.auth_routes.auth_common",
        "backend.core.api.app.services.directus",
        "backend.core.api.app.services.cache",
        "backend.core.api.app.utils.device_fingerprint",
        "backend.core.api.app.services.cache_config",
        "backend.core.api.app.utils.directus_cookies",
    ]
    for module_name in module_names:
        monkeypatch.delitem(sys.modules, module_name, raising=False)

    directus_module = types.ModuleType("backend.core.api.app.services.directus")
    directus_module.DirectusService = object

    cache_module = types.ModuleType("backend.core.api.app.services.cache")
    cache_module.CacheService = object

    device_module = types.ModuleType("backend.core.api.app.utils.device_fingerprint")
    device_module.generate_device_fingerprint_hash = lambda *args, **kwargs: (
        "device-hash",
        "connection-hash",
        "Linux",
        "Local",
        None,
        None,
        None,
        None,
    )

    cache_config_module = types.ModuleType("backend.core.api.app.services.cache_config")
    cache_config_module.ACCESS_TOKEN_TTL_SECONDS = 900

    directus_cookies_module = types.ModuleType("backend.core.api.app.utils.directus_cookies")
    directus_cookies_module.extract_directus_refresh_token = lambda cookies: None

    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.directus", directus_module)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.cache", cache_module)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.utils.device_fingerprint", device_module)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.cache_config", cache_config_module)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.utils.directus_cookies", directus_cookies_module)

    module = importlib.import_module("backend.core.api.app.routes.auth_routes.auth_common")
    async def existing_credential(_cache, _directus, token, **_kwargs):
        return token
    monkeypatch.setattr(module, "resolve_session_credential", existing_credential)
    monkeypatch.setattr(module, "ensure_legacy_session_state", AsyncMock())
    return module


@pytest.mark.asyncio
async def test_verify_authenticated_user_repairs_stale_cached_admin_status(monkeypatch):
    auth_common = _import_auth_common(monkeypatch)
    cached_user = {
        "user_id": "admin-user-id",
        "username": "adminuser",
        "vault_key_id": "vault-key",
        "is_admin": False,
    }

    async def repair_admin_status(user_id, user_data):
        user_data["is_admin"] = True
        return True

    cache_service = SimpleNamespace(get_user_by_token=AsyncMock(return_value=cached_user))
    directus_service = SimpleNamespace(
        admin=SimpleNamespace(
            repair_cached_admin_status=AsyncMock(side_effect=repair_admin_status)
        )
    )
    request = MagicMock()
    request.cookies = {"auth_refresh_token": "refresh-token"}
    request.headers = Headers({})

    success, user_data, refresh_token, auth_status = await auth_common.verify_authenticated_user(
        request=request,
        cache_service=cache_service,
        directus_service=directus_service,
        require_known_device=False,
    )

    assert success is True
    assert auth_status is None
    assert refresh_token == "refresh-token"
    assert user_data["is_admin"] is True
    directus_service.admin.repair_cached_admin_status.assert_awaited_once_with(
        "admin-user-id", cached_user
    )


@pytest.mark.asyncio
async def test_session_common_owner_assertion_refuses_before_success_or_cookie_publication(monkeypatch):
    auth = _import_auth_common(monkeypatch)
    owner_a = "11111111-1111-4111-8111-111111111111"
    owner_b = "22222222-2222-4222-8222-222222222222"
    request = MagicMock()
    request.cookies = {"auth_refresh_token": "cookie-b"}
    request.headers = Headers({"X-OpenMates-Expected-Principal": owner_a})
    cache = SimpleNamespace(get_user_by_token=AsyncMock(return_value={"user_id": owner_b, "username": "synthetic", "vault_key_id": "synthetic"}))
    directus = SimpleNamespace(admin=SimpleNamespace(repair_cached_admin_status=AsyncMock()))
    publish = AsyncMock()
    monkeypatch.setattr(auth, "queue_rotated_session_cookie", publish)
    with pytest.raises(HTTPException) as error:
        await auth.verify_authenticated_user(request, cache, directus, require_known_device=False)
    assert error.value.status_code == 403
    assert error.value.detail == {"error": "session_principal_mismatch"}
    publish.assert_not_awaited()
