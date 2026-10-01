# backend/apps/workflows/skills/_services.py
#
# Shared service resolution for Workflows app skills.
# Tests and API callers may inject WorkflowService or WorkflowAssistantService;
# Chat authoring uses the Directus-backed input service so its result reflects
# an owner-scoped durable commit.

from __future__ import annotations

from typing import Any

from backend.core.api.app.services.workflow_assistant_service import WorkflowAssistantService
from backend.core.api.app.services.workflow_service import DirectusWorkflowRepository, WorkflowService


_DEFAULT_WORKFLOW_SERVICE = WorkflowService(repository=DirectusWorkflowRepository())
_DEFAULT_ASSISTANT_SERVICE = WorkflowAssistantService(_DEFAULT_WORKFLOW_SERVICE)


def require_user_id(user_id: str | None) -> str:
    if not user_id:
        raise ValueError("Workflow skills require an authenticated user")
    return user_id


def get_assistant_service(
    workflow_assistant_service: WorkflowAssistantService | None = None,
    workflow_service: WorkflowService | None = None,
) -> WorkflowAssistantService:
    if workflow_assistant_service is not None:
        return workflow_assistant_service
    if workflow_service is not None:
        return WorkflowAssistantService(workflow_service)
    return _DEFAULT_ASSISTANT_SERVICE


def get_workflow_input_service_for_skill(
    *, secrets_manager: Any, workflow_service: WorkflowService | None = None,
) -> Any:
    """Build the same durable input boundary used by the Workflow REST routes."""
    from backend.core.api.app.services.workflow_input_service import (
        DirectusWorkflowInputRepository, WorkflowInputService,
    )
    from backend.core.api.app.services.workflow_registry_planner import WorkflowRegistryPlanner
    from backend.core.api.app.services.workflow_service import DirectusWorkflowRepository

    service = workflow_service or WorkflowService(repository=DirectusWorkflowRepository())
    return WorkflowInputService(
        workflow_service=service,
        planner=WorkflowRegistryPlanner(secrets_manager=secrets_manager, workflow_service=service),
        repository=DirectusWorkflowInputRepository(payload_cipher=service.payload_cipher),
    )


def dump_model(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return dict(value)
