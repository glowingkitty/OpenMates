# backend/apps/workflows/skills/run_skill.py
#
# Assistant-facing workflow run skill.
# Creates a pending countdown or approval gate instead of immediately executing
# a workflow from chat.

import logging
from typing import Any

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.apps.workflows.skills._services import get_assistant_service, require_user_id

logger = logging.getLogger(__name__)


class RunWorkflowResponse(BaseModel):
    success: bool = Field(default=False)
    pending_run: dict[str, Any] | None = None
    error: str | None = None


class RunSkill(BaseSkill):
    """Prepare an existing workflow for assistant-triggered execution."""

    async def execute(
        self,
        workflow_id: str,
        input: dict[str, Any] | None = None,
        high_risk: bool = False,
        user_id: str | None = None,
        workflow_assistant_service: Any = None,
        workflow_service: Any = None,
        **kwargs: Any,
    ) -> RunWorkflowResponse:
        try:
            assistant = get_assistant_service(workflow_assistant_service, workflow_service)
            pending = assistant.create_pending_run(require_user_id(user_id), workflow_id, input_payload=input or {}, high_risk=high_risk)
            return RunWorkflowResponse(success=True, pending_run=pending)
        except Exception as exc:
            logger.error("Workflow run skill failed: %s", exc, exc_info=True)
            return RunWorkflowResponse(success=False, error=str(exc))
