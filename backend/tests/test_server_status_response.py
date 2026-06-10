"""Regression tests for self-host server-status response shape.

Self-hosted installs must not surface cloud payment state. The UI hides billing
from the explicit self-host flag, while cloud/dev deployments may still expose
payment_enabled for their existing settings behavior.
"""

import importlib
import sys
from types import ModuleType, SimpleNamespace

import pytest


def _install_settings_route_dependency_stubs() -> dict[str, ModuleType | None]:
    class _StubLimiter:
        def limit(self, _rate: str):
            def decorator(func):
                return func

            return decorator

    previous_modules: dict[str, ModuleType | None] = {}

    def _stub_module(name: str, **attrs) -> None:
        previous_modules[name] = sys.modules.get(name)
        module = ModuleType(name)
        for key, value in attrs.items():
            setattr(module, key, value)
        sys.modules[name] = module

    _stub_module(
        "backend.core.api.app.services.directus",
        DirectusService=type("DirectusService", (), {}),
    )
    _stub_module(
        "backend.core.api.app.services.cache",
        CacheService=type("CacheService", (), {}),
    )
    _stub_module(
        "backend.core.api.app.utils.encryption",
        EncryptionService=type("EncryptionService", (), {}),
    )
    _stub_module(
        "backend.core.api.app.models.user",
        User=SimpleNamespace,
    )
    _stub_module(
        "backend.core.api.app.routes.auth_routes.auth_dependencies",
        get_directus_service=lambda: None,
        get_cache_service=lambda: None,
        get_compliance_service=lambda: None,
        get_current_user=lambda: None,
        get_encryption_service=lambda: None,
        get_current_user_or_api_key=lambda: None,
        get_current_user_optional=lambda: None,
    )
    _stub_module(
        "backend.core.api.app.routes.auth_routes.auth_utils",
        validate_username=lambda username: username,
    )
    _stub_module(
        "backend.core.api.app.services.directus.user.user_lookup",
        hash_username=lambda username: username,
    )
    _stub_module(
        "backend.core.api.app.utils.newsletter_utils",
        hash_email=lambda email: email,
    )
    _stub_module(
        "backend.core.api.app.utils.invite_code",
        get_signup_requirements=lambda *_args, **_kwargs: {},
    )
    _stub_module(
        "backend.core.api.app.services.compliance",
        ComplianceService=type("ComplianceService", (), {}),
    )
    _stub_module("backend.core.api.app.services.limiter", limiter=_StubLimiter())
    _stub_module(
        "backend.core.api.app.utils.device_fingerprint",
        generate_device_fingerprint_hash=lambda *_args, **_kwargs: "hash",
        _extract_client_ip=lambda *_args, **_kwargs: "127.0.0.1",
    )
    _stub_module(
        "backend.core.api.app.utils.config_manager",
        config_manager=SimpleNamespace(),
        ConfigManager=type("ConfigManager", (), {}),
    )
    _stub_module(
        "backend.apps.reminder.utils",
        format_reminder_time=lambda *_args, **_kwargs: "",
    )
    _stub_module(
        "backend.core.api.app.routes.websockets",
        manager=SimpleNamespace(),
    )
    return previous_modules


def _restore_modules(previous_modules: dict[str, ModuleType | None]) -> None:
    sys.modules.pop("backend.core.api.app.routes.settings", None)
    for name, previous_module in previous_modules.items():
        if previous_module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous_module


def _server_status_response_model():
    previous_modules = _install_settings_route_dependency_stubs()
    try:
        return importlib.import_module("backend.core.api.app.routes.settings").ServerStatusResponse
    finally:
        _restore_modules(previous_modules)


def _settings_route_module():
    previous_modules = _install_settings_route_dependency_stubs()
    return importlib.import_module("backend.core.api.app.routes.settings"), previous_modules


def _request(headers: dict[str, str]):
    return SimpleNamespace(
        headers=headers,
        app=SimpleNamespace(
            state=SimpleNamespace(
                directus_service=object(),
                cache_service=object(),
                encryption_service=object(),
            )
        ),
    )


def test_self_host_server_status_omits_payment_enabled():
    response_model = _server_status_response_model()

    response = response_model(
        is_self_hosted=True,
        is_development=False,
        server_edition="self_hosted",
        domain=None,
        ai_models_configured=False,
    )

    assert "payment_enabled" not in response.model_dump(exclude_none=True)


def test_cloud_server_status_can_include_payment_enabled():
    response_model = _server_status_response_model()

    response = response_model(
        payment_enabled=True,
        is_self_hosted=False,
        is_development=False,
        server_edition="production",
        domain="openmates.org",
        ai_models_configured=True,
    )

    assert response.model_dump(exclude_none=True)["payment_enabled"] is True


@pytest.mark.asyncio
async def test_self_host_server_status_omits_free_testing_credits(monkeypatch):
    settings_module, previous_modules = _settings_route_module()
    try:
        server_mode = importlib.import_module("backend.core.api.app.utils.server_mode")
        promo_service_calls = 0

        class PromoService:
            def __init__(self, **_kwargs):
                nonlocal promo_service_calls
                promo_service_calls += 1

            async def get_public_promotion(self):
                raise AssertionError("self-hosted status must not load cloud-only promotion metadata")

        async def no_ai_models(_request):
            return False

        monkeypatch.setattr(settings_module, "FreeTestingCreditsService", PromoService)
        monkeypatch.setattr(settings_module, "_are_ai_models_configured", no_ai_models)
        monkeypatch.setattr(
            server_mode,
            "validate_request_domain",
            lambda _request: (None, True, "self_hosted"),
        )
        monkeypatch.setattr(server_mode, "get_server_edition", lambda: "self_hosted")

        response = await settings_module.get_server_status(_request({"host": "localhost"}))
        payload = response.model_dump(exclude_none=True)

        assert payload["is_self_hosted"] is True
        assert "payment_enabled" not in payload
        assert "free_testing_credits" not in payload
        assert promo_service_calls == 0
    finally:
        _restore_modules(previous_modules)


@pytest.mark.asyncio
async def test_cloud_server_status_includes_safe_free_testing_credits(monkeypatch):
    settings_module, previous_modules = _settings_route_module()
    try:
        server_mode = importlib.import_module("backend.core.api.app.utils.server_mode")

        class PromoService:
            def __init__(self, **_kwargs):
                pass

            async def get_public_promotion(self):
                return {"active": True, "grant_credits": 1000}

        async def has_ai_models(_request):
            return True

        monkeypatch.setattr(settings_module, "FreeTestingCreditsService", PromoService)
        monkeypatch.setattr(settings_module, "_are_ai_models_configured", has_ai_models)
        monkeypatch.setattr(
            server_mode,
            "validate_request_domain",
            lambda _request: ("openmates.org", False, "production"),
        )
        monkeypatch.setattr(server_mode, "is_payment_enabled", lambda: True)
        monkeypatch.setattr(server_mode, "get_server_edition", lambda: "production")

        response = await settings_module.get_server_status(_request({"origin": "https://openmates.org"}))
        payload = response.model_dump(exclude_none=True)

        assert payload["is_self_hosted"] is False
        assert payload["payment_enabled"] is True
        assert payload["free_testing_credits"] == {"active": True, "grant_credits": 1000}
    finally:
        _restore_modules(previous_modules)
