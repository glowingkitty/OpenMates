# backend/core/api/app/routes/features.py
#
# Public feature availability endpoint for clients. The backend remains the
# source of truth; clients use this only to hide disabled entry points.
#
# Spec: docs/specs/simplified-feature-availability/spec.yml

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel
import yaml

from backend.core.api.app.services.feature_availability_service import (
    FeatureAvailabilityService,
    PLATFORM_FEATURES,
    collect_feature_definitions_from_app_config,
)


APPS_DIR = os.getenv("BACKEND_APPS_DIR", "/app/backend/apps")
router = APIRouter(prefix="/v1/features", tags=["Features"])


class FeatureAvailabilityItem(BaseModel):
    id: str
    kind: str
    default_enabled: bool
    enabled: bool
    override: str | None = None
    parent_id: str | None = None
    source: str | None = None


class FeatureAvailabilityResponse(BaseModel):
    features: list[FeatureAvailabilityItem]


def _definitions_from_discovered_metadata(discovered_apps: dict[str, Any]) -> list[Any]:
    definitions = list(PLATFORM_FEATURES)
    for app_id, app_metadata in discovered_apps.items():
        if hasattr(app_metadata, "model_dump"):
            raw_config = app_metadata.model_dump(by_alias=True, exclude_none=True)
        elif isinstance(app_metadata, dict):
            raw_config = app_metadata
        else:
            continue
        definitions.extend(collect_feature_definitions_from_app_config(app_id, raw_config, source="discovered_metadata"))
    return definitions


def _definitions_from_raw_manifests(apps_dir: str = APPS_DIR) -> list[Any]:
    definitions = list(PLATFORM_FEATURES)
    if not os.path.isdir(apps_dir):
        return definitions

    for app_id in sorted(os.listdir(apps_dir)):
        app_yml_path = os.path.join(apps_dir, app_id, "app.yml")
        if not os.path.isfile(app_yml_path):
            continue
        try:
            with open(app_yml_path, "r") as file:
                raw_config = yaml.safe_load(file)
        except Exception:
            continue
        if isinstance(raw_config, dict):
            definitions.extend(collect_feature_definitions_from_app_config(app_id, raw_config, source=app_yml_path))
    return definitions


@router.get("/availability", response_model=FeatureAvailabilityResponse)
async def get_feature_availability(request: Request) -> FeatureAvailabilityResponse:
    definitions = _definitions_from_raw_manifests()
    if len(definitions) == len(PLATFORM_FEATURES):
        discovered_apps = getattr(request.app.state, "discovered_apps_metadata", {}) or {}
        definitions = _definitions_from_discovered_metadata(discovered_apps)
    config_manager = getattr(request.app.state, "config_manager", None)
    config = config_manager.get_backend_config() if config_manager else {}
    service = FeatureAvailabilityService(definitions, config)
    return FeatureAvailabilityResponse(
        features=[
            FeatureAvailabilityItem(
                id=item.id,
                kind=item.kind,
                default_enabled=item.default_enabled,
                enabled=item.effective_enabled,
                override=item.override,
                parent_id=item.parent_id,
                source=item.source,
            )
            for item in service.list_features()
        ]
    )
