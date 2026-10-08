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
        chat_id: str | None = None,
        source_chat_id: str | None = None,
        message_destination_overrides: dict[str, str] | None = None,
        return_outputs: dict[str, dict[str, str]] | None = None,
        user_id: str | None = None,
        team_id: str | None = None,
        workflow_assistant_service: Any = None,
        workflow_service: Any = None,
        directus_service: Any = None,
        **kwargs: Any,
    ) -> RunWorkflowResponse:
        try:
            if team_id:
                raise ValueError("Team workflow execution is not supported")
            from types import SimpleNamespace
            from backend.core.api.app.routes.workflows import WorkflowRunRequest, _validated_invocation
            from backend.core.api.app.services.directus.directus import DirectusService
            owner = require_user_id(user_id)
            assistant = get_assistant_service(workflow_assistant_service, workflow_service)
            workflow = assistant.workflow_service.get_workflow(workflow_id, owner)
            # The caller chat comes from the trusted skill context, never model args.
            if source_chat_id is not None and source_chat_id != chat_id:
                raise ValueError("The caller chat cannot be changed by workflow arguments")
            owned_directus = directus_service is None
            directus = directus_service or DirectusService()
            try:
                run_body = WorkflowRunRequest(
                    input=input or {}, source_chat_id=chat_id,
                    message_destination_overrides=message_destination_overrides or {},
                    return_outputs=return_outputs or {},
                )
                invocation = await _validated_invocation(
                    SimpleNamespace(state=SimpleNamespace(auth_source="session")),
                    run_body, workflow.graph, owner, directus,
                )
            finally:
                if owned_directus:
                    await directus.close()
            pending = assistant.create_pending_run(owner, workflow_id, input_payload=input or {}, invocation=invocation)
            return RunWorkflowResponse(success=True, pending_run=pending)
        except Exception as exc:
            logger.error("Workflow run skill failed: %s", exc, exc_info=True)
            return RunWorkflowResponse(success=False, error=str(exc))
