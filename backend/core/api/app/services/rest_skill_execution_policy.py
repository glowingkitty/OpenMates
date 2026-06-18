# backend/core/api/app/services/rest_skill_execution_policy.py
#
# REST skill execution policy checks shared by app API routes and tests.
# These checks prevent hidden or client-mediated skills from being executed by
# stateless REST/API-key paths even if a caller reaches the dispatch helper.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from __future__ import annotations

from typing import Any

from fastapi import HTTPException


def assert_rest_skill_execution_allowed(registry: Any, app_id: str, skill_id: str) -> None:
    """Block REST helper execution for skills whose POST endpoint is disabled."""

    get_metadata = getattr(registry, "get_metadata", None)
    if not callable(get_metadata):
        return
    app_metadata = get_metadata(app_id)
    if app_metadata is None:
        return
    for skill in app_metadata.skills or []:
        if skill.id != skill_id:
            continue
        if skill.api_config and not skill.api_config.expose_post:
            raise HTTPException(
                status_code=403,
                detail="This skill requires an interactive client permission flow and cannot be executed via the REST API.",
            )
        return
