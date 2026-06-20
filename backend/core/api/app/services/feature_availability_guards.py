# backend/core/api/app/services/feature_availability_guards.py
#
# Lightweight route guards for feature availability checks. Keep these helpers
# free of Directus, Redis, Celery, and auth imports so route modules and focused
# tests can enforce disabled features without initializing the full app stack.
#
# Spec: docs/specs/simplified-feature-availability/spec.yml

from typing import Any

from fastapi import HTTPException, Request

from backend.core.api.app.services.feature_availability_service import (
    FeatureAvailabilityService,
    FeatureDefinition,
)


def _backend_config_from_request(request: Request) -> dict[str, Any]:
    config_manager = getattr(request.app.state, "config_manager", None)
    return config_manager.get_backend_config() if config_manager else {}


def ensure_application_preview_enabled(request: Request) -> None:
    availability = FeatureAvailabilityService(
        definitions=[FeatureDefinition(id="embed:code:application", kind="embed", default_enabled=False)],
        config=_backend_config_from_request(request),
    )
    if not availability.is_enabled("embed:code:application"):
        raise HTTPException(status_code=403, detail="FEATURE_DISABLED")


def ensure_projects_enabled(request: Request) -> None:
    availability = FeatureAvailabilityService(
        definitions=[FeatureDefinition(id="platform:projects", kind="platform", default_enabled=False)],
        config=_backend_config_from_request(request),
    )
    if not availability.is_enabled("platform:projects"):
        raise HTTPException(status_code=404, detail="FEATURE_DISABLED")
