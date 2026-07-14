# backend/core/api/app/services/workflow_task_projection_service.py
#
# Metadata-only task projections for Workflow runs. These derived views let the
# Tasks board surface execution state without copying Workflow records or any
# encrypted Workflow content into user_tasks.
#

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel

from backend.core.api.app.services.workflow_models import WorkflowRunStatus


WORKFLOW_TASK_PROJECTION_RETENTION_SECONDS = 7 * 24 * 60 * 60
_ACTIVE_RUN_STATUSES = {
    WorkflowRunStatus.QUEUED,
    WorkflowRunStatus.RUNNING,
    WorkflowRunStatus.CANCELLATION_REQUESTED,
}
_TERMINAL_RUN_STATUSES = {
    WorkflowRunStatus.COMPLETED,
    WorkflowRunStatus.FAILED,
    WorkflowRunStatus.CANCELLED,
}
_CANCELLABLE_RUN_STATUSES = {
    WorkflowRunStatus.QUEUED,
    WorkflowRunStatus.RUNNING,
    WorkflowRunStatus.WAITING,
}


class WorkflowRunTaskProjection(BaseModel):
    """Redacted, read-only Workflow run metadata rendered in Tasks."""

    task_id: str
    source: Literal["workflow_run"] = "workflow_run"
    workflow_id: str
    workflow_run_id: str
    label: Literal["Workflow run"] = "Workflow run"
    status: Literal["in_progress", "blocked", "done"]
    run_status: WorkflowRunStatus
    can_cancel: bool
    read_only: Literal[True] = True
    created_at: int
    updated_at: int
    position: int


class WorkflowTaskProjectionService:
    """Build owner-scoped Tasks views directly from Workflow run metadata."""

    def __init__(self, workflow_repository: Any) -> None:
        self.workflow_repository = workflow_repository

    def list_projections(self, user_id: str, *, now: int | None = None) -> list[WorkflowRunTaskProjection]:
        current_time = int(time.time()) if now is None else now
        projections: list[WorkflowRunTaskProjection] = []
        for workflow in self.workflow_repository.list_workflows(user_id):
            workflow_id = workflow.get("id")
            if not isinstance(workflow_id, str) or not workflow_id:
                continue
            for run in self.workflow_repository.list_runs(workflow_id, user_id):
                projection = self._projection_from_run(run, current_time)
                if projection is not None:
                    projections.append(projection)
        return sorted(projections, key=lambda projection: projection.updated_at, reverse=True)

    @staticmethod
    def _projection_from_run(run: dict[str, Any], now: int) -> WorkflowRunTaskProjection | None:
        try:
            run_status = WorkflowRunStatus(run.get("status"))
        except ValueError:
            return None

        run_id = run.get("id")
        workflow_id = run.get("workflow_id")
        if not isinstance(run_id, str) or not run_id or not isinstance(workflow_id, str) or not workflow_id:
            return None

        finished_at = run.get("finished_at")
        if run_status in _TERMINAL_RUN_STATUSES:
            if not isinstance(finished_at, int) or finished_at < now - WORKFLOW_TASK_PROJECTION_RETENTION_SECONDS:
                return None
            task_status = "done"
        elif run_status == WorkflowRunStatus.WAITING:
            task_status = "blocked"
        elif run_status in _ACTIVE_RUN_STATUSES:
            task_status = "in_progress"
        else:
            return None

        created_at = WorkflowTaskProjectionService._timestamp(run, "accepted_at", "started_at", "finished_at")
        updated_at = WorkflowTaskProjectionService._timestamp(
            run,
            "finished_at",
            "cancellation_requested_at",
            "started_at",
            "accepted_at",
        )
        return WorkflowRunTaskProjection(
            task_id=f"workflow-run:{run_id}",
            workflow_id=workflow_id,
            workflow_run_id=run_id,
            status=task_status,
            run_status=run_status,
            can_cancel=run_status in _CANCELLABLE_RUN_STATUSES,
            created_at=created_at,
            updated_at=updated_at,
            position=-updated_at,
        )

    @staticmethod
    def _timestamp(run: dict[str, Any], *keys: str) -> int:
        for key in keys:
            value = run.get(key)
            if isinstance(value, int):
                return value
        return 0
