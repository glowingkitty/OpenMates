"""Regression tests for Docker/image-mode software update metadata.

These tests cover the self-host GHCR image distribution path where containers
do not mount a Git checkout. Build metadata must come from environment
variables stamped into the image so the settings UI can still identify the
running version.
"""

import asyncio
import importlib
import sys
from types import ModuleType, SimpleNamespace

from backend.shared.python_schemas.software_update import DeploymentMode


def _install_route_dependency_stubs() -> None:
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
    _stub_module("backend.core.api.app.services.limiter", limiter=_StubLimiter())
    _stub_module(
        "backend.core.api.app.routes.auth_routes.auth_dependencies",
        get_current_user=lambda: None,
    )
    _stub_module("backend.core.api.app.models.user", User=SimpleNamespace)


_install_route_dependency_stubs()


def _update_route():
    return importlib.import_module("backend.core.api.app.routes.settings_software_update")


def test_detect_deployment_mode_returns_docker_without_git(monkeypatch):
    update_route = _update_route()
    monkeypatch.delenv("GIT_WORK_DIR", raising=False)
    monkeypatch.setattr(update_route.os.path, "isdir", lambda _path: False)

    assert update_route._detect_deployment_mode() == DeploymentMode.DOCKER


def test_current_commit_info_uses_build_metadata(monkeypatch):
    update_route = _update_route()
    monkeypatch.setenv("BUILD_COMMIT_SHA", "1234567890abcdef")
    monkeypatch.setenv("BUILD_COMMIT_MESSAGE", "feat: publish self-host images")
    monkeypatch.setenv("BUILD_TIMESTAMP", "2026-06-08T13:00:00Z")
    monkeypatch.setenv("BUILD_VERSION_TAG", "v0.11.0-alpha.0")

    commit = asyncio.run(update_route._get_current_commit_info())

    assert commit is not None
    assert commit.sha == "1234567890abcdef"
    assert commit.short_sha == "1234567"
    assert commit.message == "feat: publish self-host images"
    assert commit.date == "2026-06-08T13:00:00Z"
    assert commit.tag == "v0.11.0-alpha.0"
    assert commit.tag_url.endswith("/releases/tag/v0.11.0-alpha.0")
