# backend/apps/workflows/skills/cancel_pending_skill.py
#
# Assistant-facing cancellation skill for pending workflow runs.
# Cancels countdown or approval states before the workflow runner starts.

import logging
from typing import Any

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.apps.workflows.skills._services import get_assistant_service, require_user_id

logger = logging.getLogger(__name__)


class CancelPendingResponse(BaseModel):
    success: bool = Field(default=False)
    cancelled: bool = False
    error: str | None = None


class CancelPendingSkill(BaseSkill):
    """Cancel a pending workflow countdown or approval gate."""

    async def execute(
        self,
        pending_id: str,
        user_id: str | None = None,
        workflow_assistant_service: Any = None,
        workflow_service: Any = None,
        **kwargs: Any,
    ) -> CancelPendingResponse:
        try:
            assistant = get_assistant_service(workflow_assistant_service, workflow_service)
            cancelled = assistant.cancel_pending(require_user_id(user_id), pending_id)
            return CancelPendingResponse(success=True, cancelled=cancelled)
        except Exception as exc:
            logger.error("Workflow cancel-pending skill failed: %s", exc, exc_info=True)
            return CancelPendingResponse(success=False, error=str(exc))
