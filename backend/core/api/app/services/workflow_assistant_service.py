# backend/core/api/app/services/workflow_assistant_service.py
#
# Assistant-facing workflow operations.
# These methods back future workflow app skills so the assistant can search,
# propose, create, run, cancel, and keep workflows without bypassing validation,
# ownership, lifecycle, or approval/countdown gates.
#
# Spec: docs/specs/workflows-v1/spec.yml

from __future__ import annotations

import time
import uuid
from typing import Any

from backend.core.api.app.services.workflow_models import WorkflowDetail, WorkflowLifecycle
from backend.core.api.app.services.workflow_service import WORKFLOW_TEMPORARY_TTL_SECONDS, WorkflowService


class WorkflowAssistantService:
    """Safe assistant workflow facade used by chat-triggered automation."""

    def __init__(self, workflow_service: WorkflowService) -> None:
        self.workflow_service = workflow_service
        self.pending_runs: dict[str, dict[str, Any]] = {}

    def search(self, user_id: str, query: str, include_temporary: bool = False) -> list[dict[str, Any]]:
        normalized = query.strip().lower()
        workflows = self.workflow_service.list_workflows(user_id)
        if include_temporary:
            workflows = [*workflows, *self.workflow_service.list_temporary_workflows(user_id)]
        return [
            {
                "workflow_id": workflow.id,
                "title": workflow.title,
                "lifecycle": workflow.lifecycle.value,
                "requires_input": any(
                    capability.metadata.get("workflow_id") == workflow.id and capability.metadata.get("requires_input")
                    for capability in self.workflow_service.capabilities(user_id=user_id)
                    if capability.type == "workflow"
                ),
            }
            for workflow in workflows
            if not normalized or normalized in workflow.title.lower()
        ]

    def schedule_once(
        self,
        user_id: str,
        title: str,
        graph: dict[str, Any],
        source_chat_id: str | None = None,
    ) -> WorkflowDetail:
        if _schedule_type(graph) != "once":
            raise ValueError("schedule_once requires a one-time schedule trigger")
        now = int(time.time())
        return self.workflow_service.create_workflow(
            user_id,
            title,
            graph,
            enabled=True,
            lifecycle=WorkflowLifecycle.TEMPORARY,
            source="chat",
            source_chat_id=source_chat_id,
            created_by_assistant=True,
            auto_delete_at=now + WORKFLOW_TEMPORARY_TTL_SECONDS,
        )

    def schedule_recurring(
        self,
        user_id: str,
        title: str,
        graph: dict[str, Any],
        source_chat_id: str | None = None,
    ) -> WorkflowDetail:
        if _schedule_type(graph) == "once":
            raise ValueError("schedule_recurring requires a recurring schedule trigger")
        return self.workflow_service.create_workflow(
            user_id,
            title,
            graph,
            enabled=True,
            lifecycle=WorkflowLifecycle.PERSISTED,
            source="chat",
            source_chat_id=source_chat_id,
            created_by_assistant=True,
        )

    def create_pending_run(
        self,
        user_id: str,
        workflow_id: str,
        input_payload: dict[str, Any] | None = None,
        high_risk: bool = False,
    ) -> dict[str, Any]:
        workflow = self.workflow_service.get_workflow(workflow_id, user_id)
        self.workflow_service.validate_manual_run_input(workflow, input_payload)
        pending_id = str(uuid.uuid4())
        pending = {
            "pending_id": pending_id,
            "workflow_id": workflow_id,
            "user_id": user_id,
            "status": "approval_required" if high_risk else "countdown",
            "requires_approval": high_risk,
            "input": input_payload or {},
            "created_at": int(time.time()),
        }
        self.pending_runs[pending_id] = pending
        return dict(pending)

    def cancel_pending(self, user_id: str, pending_id: str) -> bool:
        pending = self.pending_runs.get(pending_id)
        if pending is None or pending.get("user_id") != user_id:
            return False
        pending["status"] = "cancelled"
        return True

    def keep_temporary(self, user_id: str, workflow_id: str) -> WorkflowDetail:
        return self.workflow_service.keep_temporary_workflow(workflow_id, user_id)


def _schedule_type(graph: dict[str, Any]) -> str | None:
    trigger_id = graph.get("trigger_node_id")
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict) or node.get("id") != trigger_id:
            continue
        schedule = (node.get("config") or {}).get("schedule") or {}
        if isinstance(schedule, dict):
            return schedule.get("type")
    return None
