"""Decide whether a cloud Project command runs in the chat's hosted Project sandbox."""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import HTTPException

from backend.core.api.app.services import e2b_upload_consent

logger = logging.getLogger(__name__)


async def sandbox_applies_to_command(
    *, user_id: str, focus: Optional[dict], directus_service: Any, log_prefix: str = "",
) -> bool:
    """Same rule as the Project file tools: E2B consent `allowed`, a hosted Project, no machine source.

    The command itself is `target e2b`, so the caller has already ruled out a connected machine;
    a focus naming a source stays on its own executor.
    """
    if not focus or not focus.get("project_id") or focus.get("source_id"):
        return False
    try:
        consent = await e2b_upload_consent.get_decision(user_id, directus_service)
    except HTTPException as exc:
        logger.warning("%s Sandbox command skipped: consent unavailable (status %s)", log_prefix, exc.status_code)
        return False
    return consent.get("decision") == "allowed"
