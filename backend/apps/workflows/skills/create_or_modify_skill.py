# backend/apps/workflows/skills/create_or_modify_skill.py
#
# Assistant-facing workflow create/modify skill. Unlike task creation, workflow
# creation is intentionally single-record per call because validation, approval,
# editing, and rollback are substantially more complex.

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.apps.workflows.skills._services import dump_model, get_assistant_service, require_user_id

logger = logging.getLogger(__name__)


class CreateOrModifyWorkflowResponse(BaseModel):
    success: bool = Field(default=False)
    app_id: str = "workflows"
    skill_id: str = "create-or-modify"
    status: str = "finished"
    workflow: dict[str, Any] | None = None
    results: list[dict[str, Any]] = Field(default_factory=list)
    result_count: int = 0
    error: str | None = None


class CreateOrModifySkill(BaseSkill):
    """Create or modify exactly one workflow from assistant-provided input."""

    async def execute(
        self,
        title: str | None = None,
        graph: dict[str, Any] | None = None,
        workflow_id: str | None = None,
        workflows: list[dict[str, Any]] | None = None,
        user_id: str | None = None,
        chat_id: str | None = None,
        workflow_assistant_service: Any = None,
        workflow_service: Any = None,
        **kwargs: Any,
    ) -> CreateOrModifyWorkflowResponse:
        try:
            if workflows is not None:
                raise ValueError("Workflow create-or-modify accepts exactly one workflow per skill call")
            workflow_title = str(title or "").strip()
            if not workflow_title:
                raise ValueError("Workflow create-or-modify requires a title")
            assistant = get_assistant_service(workflow_assistant_service, workflow_service)
            workflow = assistant.create_or_modify(
                require_user_id(user_id),
                title=workflow_title,
                graph=graph,
                workflow_id=workflow_id,
                source_chat_id=chat_id,
            )
            workflow_dict = dump_model(workflow)
            result = _workflow_embed_result(workflow_dict)
            return CreateOrModifyWorkflowResponse(
                success=True,
                workflow=workflow_dict,
                results=[result],
                result_count=1,
            )
        except Exception as exc:
            logger.error("Workflow create-or-modify skill failed: %s", exc, exc_info=True)
            return CreateOrModifyWorkflowResponse(success=False, error=str(exc))


def _workflow_embed_result(workflow: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "workflow",
        "parent_app_skill_type": "app_skill_use",
        "workflow_id": workflow.get("workflow_id") or workflow.get("id"),
        "title": workflow.get("title") or "",
        "status": workflow.get("status") or "draft",
        "source_chat_id": workflow.get("source_chat_id"),
    }
