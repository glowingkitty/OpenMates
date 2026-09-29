"""Direct 2FA mutations require server assurance outside incomplete signup."""
import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException


def _load_route(monkeypatch):
    """Load the route against lightweight service imports for local unit tests."""
    fakes = {
        "backend.core.api.app.services.directus": {"DirectusService": object},
        "backend.core.api.app.services.cache": {"CacheService": object},
        "backend.core.api.app.services.compliance": {"ComplianceService": object},
        "backend.core.api.app.utils.encryption": {"EncryptionService": object},
        "backend.core.api.app.routes.auth_routes.auth_dependencies": {
            "get_directus_service": lambda: None,
            "get_cache_service": lambda: None,
            "get_compliance_service": lambda: None,
            "get_current_user": lambda: None,
        },
        "backend.core.api.app.routes.auth_routes.auth_utils": {
            "verify_allowed_origin": lambda: None,
        },
        "backend.core.api.app.routes.auth_routes.auth_common": {
            "verify_authenticated_user": lambda *_args: None,
        },
        "backend.core.api.app.utils.device_fingerprint": {
            "_extract_client_ip": lambda *_args: "127.0.0.1",
        },
        "backend.core.api.app.routes.auth_routes.auth_2fa_utils": {
            "generate_2fa_secret": lambda **_kwargs: None,
            "hash_backup_code": lambda _code: None,
            "generate_backup_codes": lambda: None,
        },
    }
    with monkeypatch.context() as context:
        for name, members in fakes.items():
            fake = ModuleType(name)
            for member, value in members.items():
                setattr(fake, member, value)
            context.setitem(sys.modules, name, fake)
        name = "backend.core.api.app.routes.auth_routes._test_2fa_assurance"
        path = Path(__file__).parent.parent / "core/api/app/routes/auth_routes/auth_2fa_setup.py"
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


# contract-test: direct surface=rest_api assertions=auth.sensitive-actions.recent-verification,auth.surface.first-party-boundary
def test_reset_backup_codes_direct_call_rejects_unverified_session(monkeypatch):
    route = _load_route(monkeypatch)
    proof = AsyncMock(side_effect=HTTPException(401, "Recent verification required"))
    monkeypatch.setattr(route, "require_recent_strong_proof", proof)
    directus = SimpleNamespace(
        get_user_fields_direct=AsyncMock(return_value={
            "signup_completed": True, "last_opened": "/chat/new",
        }),
        get_user_profile=AsyncMock(), update_user=AsyncMock(),
    )
    cache = SimpleNamespace(delete=AsyncMock())
    request = SimpleNamespace(cookies={"auth_refresh_token": "issued-session"})
    compliance = SimpleNamespace(log_auth_event=lambda **_kwargs: None)

    async def run():
        with pytest.raises(HTTPException) as denied:
            await route.reset_backup_codes(
                request, current_user=SimpleNamespace(id="u1"),
                directus_service=directus, cache_service=cache,
                compliance_service=compliance,
            )
        assert denied.value.status_code == 401
        proof.assert_awaited_once_with(directus, cache, "issued-session", "u1")
        directus.get_user_profile.assert_not_awaited()
        directus.update_user.assert_not_awaited()

    asyncio.run(run())


# contract-test: direct surface=rest_api assertions=auth.sensitive-actions.recent-verification,auth.login.method-convergence
def test_incomplete_signup_2fa_setup_exemption_is_authoritative(monkeypatch):
    route = _load_route(monkeypatch)
    proof = AsyncMock(side_effect=HTTPException(401, "Recent verification required"))
    monkeypatch.setattr(route, "require_recent_strong_proof", proof)
    account = {"signup_completed": False, "last_opened": "/signup/one-time-codes"}
    directus = SimpleNamespace(get_user_fields_direct=AsyncMock(return_value=account))

    async def run():
        await route.require_2fa_change_assurance(directus, object(), "token", "u1")
        proof.assert_not_awaited()
        account["signup_completed"] = True
        with pytest.raises(HTTPException) as denied:
            await route.require_2fa_change_assurance(directus, object(), "token", "u1")
        assert denied.value.status_code == 401

    asyncio.run(run())
