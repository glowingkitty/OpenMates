# backend/core/api/app/services/workflow_capability_registry.py
#
# Workflow capability registry facade.
# This isolates callers from WorkflowService internals while the capability
# surface grows to include built-in nodes, app skills, platform actions, and
# owner-scoped user workflows.
#
# Spec: docs/specs/workflows-v1/spec.yml

from __future__ import annotations

from backend.core.api.app.services.workflow_models import WorkflowCapability
from backend.core.api.app.services.workflow_service import WorkflowService


class WorkflowCapabilityRegistry:
    """Return the normalized workflow capability list for a user/session."""

    def __init__(self, workflow_service: WorkflowService) -> None:
        self.workflow_service = workflow_service

    def list_capabilities(self, user_id: str | None = None) -> list[WorkflowCapability]:
        return self.workflow_service.capabilities(user_id=user_id)
