# backend/tests/test_feature_availability_enforcement.py
#
# Route-level contract tests for simplified feature availability enforcement.
# These tests call lightweight dependency guards directly so they avoid booting
# the full FastAPI app, Redis, Directus, or Celery while still proving disabled
# features are blocked before execution paths run.
#
# Spec: docs/specs/simplified-feature-availability/spec.yml

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.core.api.app.services.feature_availability_guards import (
    ensure_application_preview_enabled,
    ensure_projects_enabled,
)


class FakeConfigManager:
    def __init__(self, config: dict) -> None:
        self.config = config

    def get_backend_config(self) -> dict:
        return self.config


def make_request(config: dict) -> SimpleNamespace:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(config_manager=FakeConfigManager(config))))


def test_application_preview_route_blocks_default_disabled_embed() -> None:
    with pytest.raises(HTTPException) as exc_info:
        ensure_application_preview_enabled(make_request({}))

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "FEATURE_DISABLED"


def test_application_preview_route_allows_admin_enabled_embed() -> None:
    ensure_application_preview_enabled(
        make_request({"feature_overrides": {"enabled": ["embed:code:application"], "disabled": []}})
    )


def test_projects_route_blocks_default_disabled_platform_feature() -> None:
    with pytest.raises(HTTPException) as exc_info:
        ensure_projects_enabled(make_request({}))

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "FEATURE_DISABLED"


def test_projects_route_allows_admin_enabled_platform_feature() -> None:
    ensure_projects_enabled(
        make_request({"feature_overrides": {"enabled": ["platform:projects"], "disabled": []}})
    )
