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
        workflow_id: str | None = None,
        include_temporary: bool = False,
        user_id: str | None = None,
        team_id: str | None = None,
        workflow_assistant_service: Any = None,
        workflow_service: Any = None,
        directus_service: Any = None,
        user_vault_key_id: str | None = None,
        **kwargs: Any,
    ) -> SearchWorkflowsResponse:
        try:
            owner = require_user_id(user_id)
            if team_id:
                owned_directus = directus_service is None
                if owned_directus:
                    from backend.core.api.app.services.directus.directus import DirectusService
                    directus_service = DirectusService()
                try:
                    await directus_service.team.require_team_role(team_id, owner, {"owner", "admin", "member", "viewer"})
                finally:
                    if owned_directus:
                        await directus_service.close()
            assistant = get_assistant_service(workflow_assistant_service, workflow_service)
            search_options = {"workflow_id": workflow_id} if workflow_id else {}
            workflows = assistant.search(
                owner,
                query,
                include_temporary=include_temporary,
                vault_key_id=user_vault_key_id,
                **({"team_id": team_id} if team_id else {}),
                **search_options,
            )
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
