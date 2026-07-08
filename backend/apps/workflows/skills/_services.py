# backend/apps/workflows/skills/_services.py
#
# Shared service resolution for Workflows app skills.
# Tests and API callers may inject WorkflowService or WorkflowAssistantService;
# otherwise a process-local service is used until Directus-backed persistence is
# wired behind WorkflowService.

from __future__ import annotations

from typing import Any

from backend.core.api.app.services.workflow_assistant_service import WorkflowAssistantService
from backend.core.api.app.services.workflow_service import WorkflowService


_DEFAULT_WORKFLOW_SERVICE = WorkflowService()
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


def dump_model(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return dict(value)
