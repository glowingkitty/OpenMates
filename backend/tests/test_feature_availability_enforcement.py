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
    ensure_plans_enabled,
    ensure_projects_enabled,
    ensure_tasks_enabled,
    ensure_workflows_enabled,
)


class FakeConfigManager:
    def __init__(self, config: dict) -> None:
        self.config = config

    def get_backend_config(self) -> dict:
        return self.config


def make_request(config: dict) -> SimpleNamespace:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(config_manager=FakeConfigManager(config))))


def test_application_preview_route_allows_default_enabled_embed() -> None:
    ensure_application_preview_enabled(make_request({}))


def test_application_preview_route_allows_admin_enabled_embed() -> None:
    ensure_application_preview_enabled(
        make_request({"feature_overrides": {"enabled": ["embed:code:application"], "disabled": []}})
    )


def test_application_preview_route_blocks_admin_disabled_embed() -> None:
    with pytest.raises(HTTPException) as exc_info:
        ensure_application_preview_enabled(
            make_request({"feature_overrides": {"enabled": [], "disabled": ["embed:code:application"]}})
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "FEATURE_DISABLED"


def test_projects_route_blocks_default_disabled_platform_feature() -> None:
    with pytest.raises(HTTPException) as exc_info:
        ensure_projects_enabled(make_request({}))

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "FEATURE_DISABLED"


def test_projects_route_allows_admin_enabled_platform_feature() -> None:
    ensure_projects_enabled(
        make_request({"feature_overrides": {"enabled": ["platform:projects"], "disabled": []}})
    )


@pytest.mark.parametrize(
    ("guard", "feature_id"),
    [
        (ensure_projects_enabled, "platform:projects"),
        (ensure_plans_enabled, "platform:plans"),
        (ensure_workflows_enabled, "platform:workflows"),
        (ensure_tasks_enabled, "platform:tasks"),
    ],
)
def test_unfinished_platform_guards_block_by_default_and_allow_admin_override(guard, feature_id: str) -> None:
    with pytest.raises(HTTPException) as exc_info:
        guard(make_request({}))

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "FEATURE_DISABLED"

    guard(make_request({"feature_overrides": {"enabled": [feature_id], "disabled": []}}))
