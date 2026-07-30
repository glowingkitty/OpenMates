# backend/core/api/app/services/workflow_task_projection_service.py
#
# Metadata-only task projections for Workflow runs. These derived views let the
# Tasks board surface execution state without copying Workflow records or any
# encrypted Workflow content into user_tasks.
#

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel

from backend.core.api.app.services.workflow_models import WorkflowRunStatus


WORKFLOW_TASK_PROJECTION_RETENTION_SECONDS = 7 * 24 * 60 * 60
_CURRENT_RUN_STATUSES = {
    WorkflowRunStatus.QUEUED,
    WorkflowRunStatus.RUNNING,
    WorkflowRunStatus.WAITING,
    WorkflowRunStatus.CANCELLATION_REQUESTED,
}
_PAST_RUN_STATUSES = {
    WorkflowRunStatus.COMPLETED,
    WorkflowRunStatus.CANCELLED,
    WorkflowRunStatus.FAILED,
}
_BLOCKED_RUN_STATUSES = {
    WorkflowRunStatus.WAITING,
    WorkflowRunStatus.FAILED,
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
    projection_kind: Literal["last_run", "current_run", "next_run"]
    workflow_id: str
    workflow_run_id: str | None = None
    trigger_id: str | None = None
    label: Literal["Workflow run"] = "Workflow run"
    title: str | None = None
    status: Literal["todo", "in_progress", "blocked", "done"]
    run_status: WorkflowRunStatus
    can_cancel: bool
    can_delete: bool = False
    read_only: Literal[True] = True
    due_at: int | None = None
    scheduled_at: int | None = None
    blocked_reason: str | None = None
    blocked_message: str | None = None
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
            workflow_title = workflow.get("title") if isinstance(workflow.get("title"), str) else "Workflow"
            runs = [self._run_with_workflow_title(run, workflow_title) for run in self.workflow_repository.list_runs(workflow_id, user_id)]
            future_projection = self._future_projection_from_workflow(workflow, user_id, runs, current_time)
            if future_projection is not None:
                projections.append(future_projection)
            projections.extend(self._run_projections_from_runs(runs, current_time))
        return sorted(projections, key=lambda projection: projection.updated_at, reverse=True)

    @staticmethod
    def _run_with_workflow_title(run: dict[str, Any], workflow_title: str) -> dict[str, Any]:
        if isinstance(run.get("workflow_title"), str):
            return run
        return {**run, "workflow_title": workflow_title}

    def skip_scheduled_projection(self, user_id: str, task_id: str, *, now: int | None = None) -> dict[str, Any] | None:
        parsed = self._parse_schedule_task_id(task_id)
        if parsed is None:
            return None
        trigger_id, scheduled_at = parsed
        current_time = int(time.time()) if now is None else now
        for workflow in self.workflow_repository.list_workflows(user_id):
            workflow_id = workflow.get("id")
            if not isinstance(workflow_id, str) or not workflow_id:
                continue
            trigger = self.workflow_repository.get_trigger_for_workflow(workflow_id, user_id)
            if not isinstance(trigger, dict) or trigger.get("trigger_id") != trigger_id or trigger.get("next_run_at") != scheduled_at:
                continue
            run_id = f"skipped:{trigger_id}:{scheduled_at}"
            run = {
                "id": run_id,
                "workflow_id": workflow_id,
                "version_id": trigger.get("version_id"),
                "owner_hash": self.workflow_repository.workflow_owner_hash(user_id),
                "trigger_id": trigger_id,
                "trigger_type": "schedule",
                "accepted_at": scheduled_at,
                "finished_at": current_time,
                "scheduled_at": scheduled_at,
                "status": WorkflowRunStatus.SKIPPED_BY_USER.value,
                "cancellation_requested_at": None,
            }
            self.workflow_repository.save_run(run)
            self.workflow_repository.update_trigger_next_run(trigger_id, scheduled_at + 1, current_time)
            return {"run_id": run_id, "workflow_id": workflow_id, "status": WorkflowRunStatus.SKIPPED_BY_USER.value}
        return None

    def _future_projection_from_workflow(
        self,
        workflow: dict[str, Any],
        user_id: str,
        runs: list[dict[str, Any]],
        now: int,
    ) -> WorkflowRunTaskProjection | None:
        if not workflow.get("enabled"):
            return None
        workflow_id = workflow.get("id")
        if not isinstance(workflow_id, str) or not workflow_id:
            return None
        get_trigger = getattr(self.workflow_repository, "get_trigger_for_workflow", None)
        if not callable(get_trigger):
            return None
        trigger = get_trigger(workflow_id, user_id)
        if not isinstance(trigger, dict) or trigger.get("trigger_type") != "schedule" or not trigger.get("enabled"):
            return None
        trigger_id = trigger.get("trigger_id")
        next_run_at = trigger.get("next_run_at")
        if not isinstance(trigger_id, str) or not trigger_id or not isinstance(next_run_at, int):
            return None
        if self._has_run_for_schedule_occurrence(runs, trigger_id, next_run_at):
            return None
        workflow_title = workflow.get("title") if isinstance(workflow.get("title"), str) else "Workflow"
        return WorkflowRunTaskProjection(
            task_id=f"workflow-schedule:{trigger_id}:{next_run_at}",
            projection_kind="next_run",
            workflow_id=workflow_id,
            workflow_run_id=None,
            trigger_id=trigger_id,
            title=f"{workflow_title} - {self._format_task_time(next_run_at)}",
            status="todo",
            run_status=WorkflowRunStatus.PLANNED,
            can_cancel=False,
            can_delete=True,
            due_at=next_run_at,
            scheduled_at=next_run_at,
            created_at=next_run_at,
            updated_at=next_run_at,
            position=next_run_at,
        )

    @staticmethod
    def _parse_schedule_task_id(task_id: str) -> tuple[str, int] | None:
        prefix = "workflow-schedule:"
        if not task_id.startswith(prefix):
            return None
        rest = task_id[len(prefix):]
        trigger_id, separator, scheduled_at_raw = rest.rpartition(":")
        if not separator or not trigger_id:
            return None
        try:
            scheduled_at = int(scheduled_at_raw)
        except ValueError:
            return None
        return trigger_id, scheduled_at

    @classmethod
    def _run_projections_from_runs(cls, runs: list[dict[str, Any]], now: int) -> list[WorkflowRunTaskProjection]:
        current_run = cls._most_recent_run_with_status(runs, _CURRENT_RUN_STATUSES)
        past_run = cls._most_recent_run_with_status(runs, _PAST_RUN_STATUSES)
        projections: list[WorkflowRunTaskProjection] = []
        if current_run is not None:
            projection = cls._projection_from_run(current_run, now, projection_kind="current_run")
            if projection is not None:
                projections.append(projection)
        if past_run is not None:
            projection = cls._projection_from_run(past_run, now, projection_kind="last_run")
            if projection is not None:
                projections.append(projection)
        return projections

    @staticmethod
    def _most_recent_run_with_status(runs: list[dict[str, Any]], statuses: set[WorkflowRunStatus]) -> dict[str, Any] | None:
        candidates: list[dict[str, Any]] = []
        for run in runs:
            try:
                run_status = WorkflowRunStatus(run.get("status"))
            except ValueError:
                continue
            if run_status in statuses:
                candidates.append(run)
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda run: WorkflowTaskProjectionService._timestamp(
                run,
                "finished_at",
                "cancellation_requested_at",
                "started_at",
                "accepted_at",
            ),
        )

    @staticmethod
    def _projection_from_run(
        run: dict[str, Any],
        now: int,
        *,
        projection_kind: Literal["last_run", "current_run"],
    ) -> WorkflowRunTaskProjection | None:
        try:
            run_status = WorkflowRunStatus(run.get("status"))
        except ValueError:
            return None

        run_id = run.get("id")
        workflow_id = run.get("workflow_id")
        if not isinstance(run_id, str) or not run_id or not isinstance(workflow_id, str) or not workflow_id:
            return None

        created_at = WorkflowTaskProjectionService._timestamp(run, "accepted_at", "started_at", "finished_at")
        updated_at = WorkflowTaskProjectionService._timestamp(
            run,
            "finished_at",
            "cancellation_requested_at",
            "started_at",
            "accepted_at",
        )
        if run_status in _PAST_RUN_STATUSES:
            if updated_at < now - WORKFLOW_TASK_PROJECTION_RETENTION_SECONDS:
                return None
            task_status = "blocked" if run_status == WorkflowRunStatus.FAILED else "done"
        elif run_status in _CURRENT_RUN_STATUSES:
            task_status = "blocked" if run_status in _BLOCKED_RUN_STATUSES else "in_progress"
        else:
            return None

        return WorkflowRunTaskProjection(
            task_id=f"workflow-run:{run_id}",
            projection_kind=projection_kind,
            workflow_id=workflow_id,
            workflow_run_id=run_id,
            trigger_id=run.get("trigger_id") if isinstance(run.get("trigger_id"), str) else None,
            title=WorkflowTaskProjectionService._run_title(run, created_at),
            status=task_status,
            run_status=run_status,
            can_cancel=run_status in _CANCELLABLE_RUN_STATUSES,
            blocked_reason=WorkflowTaskProjectionService._blocked_reason(run_status),
            blocked_message=WorkflowTaskProjectionService._blocked_message(run_status, run),
            created_at=created_at,
            updated_at=updated_at,
            position=-updated_at,
        )

    @staticmethod
    def _has_run_for_schedule_occurrence(runs: list[dict[str, Any]], trigger_id: str, next_run_at: int) -> bool:
        for run in runs:
            if run.get("trigger_id") != trigger_id:
                continue
            if WorkflowTaskProjectionService._timestamp(run, "scheduled_at", "started_at", "accepted_at") == next_run_at:
                try:
                    return WorkflowRunStatus(run.get("status")) != WorkflowRunStatus.SKIPPED_BY_USER
                except ValueError:
                    return True
        return False

    @staticmethod
    def _run_title(run: dict[str, Any], created_at: int) -> str:
        title = run.get("workflow_title") if isinstance(run.get("workflow_title"), str) else "Workflow"
        return f"{title} - {WorkflowTaskProjectionService._format_task_time(created_at)}"

    @staticmethod
    def _format_task_time(timestamp: int) -> str:
        return datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    @staticmethod
    def _blocked_reason(run_status: WorkflowRunStatus) -> str | None:
        if run_status == WorkflowRunStatus.WAITING:
            return "needs_user_input"
        if run_status == WorkflowRunStatus.FAILED:
            return "workflow_failed"
        return None

    @staticmethod
    def _blocked_message(run_status: WorkflowRunStatus, run: dict[str, Any]) -> str | None:
        if run_status == WorkflowRunStatus.WAITING:
            return str(run.get("blocked_message") or "Workflow is waiting for user input.")
        if run_status == WorkflowRunStatus.FAILED:
            return str(run.get("error_summary") or "Workflow run failed.")
        return None

    @staticmethod
    def _timestamp(run: dict[str, Any], *keys: str) -> int:
        for key in keys:
            value = run.get(key)
            if isinstance(value, int):
                return value
        return 0
