# backend/apps/workflows/skills/keep_temporary_skill.py
#
# Assistant-facing keep skill for temporary workflows.
# Converts a chat-created temporary workflow into a persisted reusable workflow
# before its seven-day auto-delete window expires.

import logging
from typing import Any

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.apps.workflows.skills._services import dump_model, get_assistant_service, require_user_id

logger = logging.getLogger(__name__)


class KeepTemporaryResponse(BaseModel):
    success: bool = Field(default=False)
    workflow: dict[str, Any] | None = None
    error: str | None = None


class KeepTemporarySkill(BaseSkill):
    """Keep a temporary workflow as a persisted reusable workflow."""

    async def execute(
        self,
        workflow_id: str,
        user_id: str | None = None,
        workflow_assistant_service: Any = None,
        workflow_service: Any = None,
        **kwargs: Any,
    ) -> KeepTemporaryResponse:
        try:
            assistant = get_assistant_service(workflow_assistant_service, workflow_service)
            workflow = assistant.keep_temporary(require_user_id(user_id), workflow_id)
            return KeepTemporaryResponse(success=True, workflow=dump_model(workflow))
        except Exception as exc:
            logger.error("Workflow keep-temporary skill failed: %s", exc, exc_info=True)
            return KeepTemporaryResponse(success=False, error=str(exc))
