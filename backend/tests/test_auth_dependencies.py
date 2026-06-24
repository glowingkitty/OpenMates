"""Authentication dependency regression tests.

Purpose: cover unified session/API-key auth behavior without starting FastAPI.
Scope: narrow dependency-level contracts that previously regressed in SDK flows.
Security: API-key auth must preserve explicit device-approval denials.
Run: python3 -m pytest backend/tests/test_auth_dependencies.py
"""

import sys
import types
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.core.api.app.utils import api_key_auth


def _stub_auth_dependency_imports(monkeypatch: pytest.MonkeyPatch) -> None:
    for module_name in [
        "backend.core.api.app.routes.auth_routes.auth_dependencies",
        "backend.core.api.app.routes.auth_routes.auth_common",
        "backend.core.api.app.routes.auth_routes.auth_utils",
        "backend.core.api.app.services.cache_config",
        "backend.core.api.app.services.directus",
        "backend.core.api.app.services.cache",
        "backend.core.api.app.models.user",
        "backend.core.api.app.utils.directus_cookies",
    ]:
        monkeypatch.delitem(sys.modules, module_name, raising=False)

    cache_config_module = types.ModuleType("backend.core.api.app.services.cache_config")
    cache_config_module.ACCESS_TOKEN_TTL_SECONDS = 900

    auth_common_module = types.ModuleType("backend.core.api.app.routes.auth_routes.auth_common")
    auth_common_module.preserve_rotated_session_metadata = None

    auth_utils_module = types.ModuleType("backend.core.api.app.routes.auth_routes.auth_utils")
    auth_utils_module.get_cookie_domain = lambda request: None

    directus_cookies_module = types.ModuleType("backend.core.api.app.utils.directus_cookies")
    directus_cookies_module.extract_directus_refresh_token = lambda cookies: None

    directus_module = types.ModuleType("backend.core.api.app.services.directus")
    directus_module.DirectusService = object

    cache_module = types.ModuleType("backend.core.api.app.services.cache")
    cache_module.CacheService = object

    user_module = types.ModuleType("backend.core.api.app.models.user")
    user_module.User = object

    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.cache_config", cache_config_module)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.routes.auth_routes.auth_common", auth_common_module)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.routes.auth_routes.auth_utils", auth_utils_module)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.utils.directus_cookies", directus_cookies_module)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.directus", directus_module)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.cache", cache_module)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.models.user", user_module)


@pytest.mark.asyncio
async def test_unified_auth_preserves_api_key_device_approval_error(monkeypatch):
    _stub_auth_dependency_imports(monkeypatch)
    from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user_or_api_key

    class FakeApiKeyAuthService:
        async def authenticate_api_key(self, api_key, request=None):
            raise api_key_auth.DeviceNotApprovedError("New device detected. Please confirm this device.")

    monkeypatch.setattr(
        api_key_auth,
        "get_api_key_auth_service",
        lambda request: FakeApiKeyAuthService(),
    )

    request = SimpleNamespace(
        headers={"Authorization": "Bearer sk-api-test"},
        app=SimpleNamespace(state=SimpleNamespace()),
    )

    with pytest.raises(HTTPException) as exc:
        await get_current_user_or_api_key(
            request=request,
            response=SimpleNamespace(),
            directus_service=SimpleNamespace(),
            cache_service=SimpleNamespace(),
            refresh_token=None,
        )

    assert exc.value.status_code == 403
    assert exc.value.detail == "New device detected. Please confirm this device."
