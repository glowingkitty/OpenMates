"""Regression tests for self-host server-status response shape.

Self-hosted installs must not surface cloud payment state. The UI hides billing
from the explicit self-host flag, while cloud/dev deployments may still expose
payment_enabled for their existing settings behavior.
"""

import importlib
import sys
from types import ModuleType, SimpleNamespace


def _install_settings_route_dependency_stubs() -> None:
    class _StubLimiter:
        def limit(self, _rate: str):
            def decorator(func):
                return func

            return decorator

    def _stub_module(name: str, **attrs) -> None:
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
    )
    _stub_module(
        "backend.apps.reminder.utils",
        format_reminder_time=lambda *_args, **_kwargs: "",
    )
    _stub_module(
        "backend.core.api.app.routes.websockets",
        manager=SimpleNamespace(),
    )


def _settings_route():
    _install_settings_route_dependency_stubs()
    return importlib.import_module("backend.core.api.app.routes.settings")


def test_self_host_server_status_omits_payment_enabled():
    route = _settings_route()

    response = route.ServerStatusResponse(
        is_self_hosted=True,
        is_development=False,
        server_edition="self_hosted",
        domain=None,
        ai_models_configured=False,
    )

    assert "payment_enabled" not in response.model_dump(exclude_none=True)


def test_cloud_server_status_can_include_payment_enabled():
    route = _settings_route()

    response = route.ServerStatusResponse(
        payment_enabled=True,
        is_self_hosted=False,
        is_development=False,
        server_edition="production",
        domain="openmates.org",
        ai_models_configured=True,
    )

    assert response.model_dump(exclude_none=True)["payment_enabled"] is True
