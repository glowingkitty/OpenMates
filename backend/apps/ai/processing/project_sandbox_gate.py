"""Admission to the persistent hosted Project sandbox for assistant tools."""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import HTTPException

from backend.core.api.app.services import e2b_upload_consent
from backend.core.api.app.services.directus.team_key_rotation_methods import TeamKeyRotationMethods
from backend.core.api.app.services.directus.team_methods import TeamPermissionError

logger = logging.getLogger(__name__)


async def sandbox_applies_to_project(
    *, user_id: str, focus: Optional[dict], directus_service: Any, log_prefix: str = "",
) -> bool:
    """Use the persistent sandbox only when its Project key can open stored revisions."""
    if not focus or not focus.get("project_id") or focus.get("source_id"):
        return False
    try:
        consent = await e2b_upload_consent.get_decision(user_id, directus_service)
    except HTTPException as exc:
        logger.warning("%s Sandbox command skipped: consent unavailable (status %s)", log_prefix, exc.status_code)
        return False
    if consent.get("decision") != "allowed":
        return False
    team_id = focus.get("team_id")
    if not team_id:
        return True
    try:
        return await TeamKeyRotationMethods(directus_service.team).allows_legacy_project_sandbox(team_id)
    except TeamPermissionError:
        logger.info("%s Project sandbox skipped: Team key state unavailable", log_prefix)
        return False
