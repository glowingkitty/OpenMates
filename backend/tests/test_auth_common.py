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

    return importlib.import_module("backend.core.api.app.routes.auth_routes.auth_common")


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
