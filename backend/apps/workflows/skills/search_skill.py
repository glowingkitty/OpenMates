# backend/apps/workflows/skills/search_skill.py
#
# Assistant-facing workflow search skill.
# Returns owner-scoped persisted workflows by default and only includes
# temporary workflows when the assistant explicitly requests them.

import logging
from typing import Any

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.apps.workflows.skills._services import get_assistant_service, require_user_id

logger = logging.getLogger(__name__)


class SearchWorkflowsResponse(BaseModel):
    success: bool = Field(default=False)
    app_id: str = "workflows"
    skill_id: str = "search"
    status: str = "finished"
    workflows: list[dict[str, Any]] = Field(default_factory=list)
    results: list[dict[str, Any]] = Field(default_factory=list)
    total_count: int = 0
    result_count: int = 0
    requires_connected_client: bool = False
    error: str | None = None


class SearchSkill(BaseSkill):
    """Search user-owned workflows that the assistant may propose running."""

    async def execute(
        self,
        query: str = "",
        include_temporary: bool = False,
        user_id: str | None = None,
        workflow_assistant_service: Any = None,
        workflow_service: Any = None,
        **kwargs: Any,
    ) -> SearchWorkflowsResponse:
        try:
            assistant = get_assistant_service(workflow_assistant_service, workflow_service)
            workflows = assistant.search(require_user_id(user_id), query, include_temporary=include_temporary)
            results = [_workflow_embed_result(workflow) for workflow in workflows]
            return SearchWorkflowsResponse(
                success=True,
                workflows=workflows,
                results=results,
                total_count=len(workflows),
                result_count=len(results),
            )
        except Exception as exc:
            logger.error("Workflow search skill failed: %s", exc, exc_info=True)
            return SearchWorkflowsResponse(success=False, error=str(exc))


def _workflow_embed_result(workflow: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "workflow",
        "parent_app_skill_type": "app_skill_use",
        "workflow_id": workflow.get("workflow_id") or workflow.get("id"),
        "title": workflow.get("title") or "",
        "status": workflow.get("status") or "draft",
    }
