# backend/apps/workflows/skills/schedule_once_skill.py
#
# Assistant-facing one-time workflow scheduling skill.
# Creates temporary chat-sourced workflows that remain inspectable for seven days
# unless the user keeps them.

import logging
from typing import Any

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.apps.workflows.skills._services import dump_model, get_assistant_service, require_user_id

logger = logging.getLogger(__name__)


class ScheduleOnceResponse(BaseModel):
    success: bool = Field(default=False)
    workflow: dict[str, Any] | None = None
    error: str | None = None


class ScheduleOnceSkill(BaseSkill):
    """Create a temporary one-time workflow from assistant-provided graph input."""

    async def execute(
        self,
        title: str,
        graph: dict[str, Any],
        source_chat_id: str | None = None,
        user_id: str | None = None,
        chat_id: str | None = None,
        workflow_assistant_service: Any = None,
        workflow_service: Any = None,
        **kwargs: Any,
    ) -> ScheduleOnceResponse:
        try:
            assistant = get_assistant_service(workflow_assistant_service, workflow_service)
            workflow = assistant.schedule_once(require_user_id(user_id), title, graph, source_chat_id=source_chat_id or chat_id)
            return ScheduleOnceResponse(success=True, workflow=dump_model(workflow))
        except Exception as exc:
            logger.error("Workflow schedule-once skill failed: %s", exc, exc_info=True)
            return ScheduleOnceResponse(success=False, error=str(exc))
