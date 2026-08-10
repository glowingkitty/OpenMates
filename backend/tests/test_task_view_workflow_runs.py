"""Tests for Workflow run projections in the Tasks view.

Workflow runs appear as read-only task-view cards without copying workflow data
into user_tasks. The projection contains only safe run metadata and applies the
default seven-day Done visibility window used by the Tasks board.
"""

from backend.core.api.app.services.workflow_models import WorkflowRunStatus
from backend.core.api.app.services.workflow_task_projection_service import WorkflowTaskProjectionService


class FakeWorkflowRepository:
    def __init__(self) -> None:
        self.workflow_calls: list[str] = []
        self.run_calls: list[tuple[str, str]] = []

    def list_workflows(self, user_id: str) -> list[dict[str, object]]:
        self.workflow_calls.append(user_id)
        return [{"id": "workflow-1"}, {"id": "workflow-2"}]

    def list_runs(self, workflow_id: str, user_id: str) -> list[dict[str, object]]:
        self.run_calls.append((workflow_id, user_id))
        if workflow_id == "workflow-2":
            return [
                {
                    "id": "run-waiting",
                    "workflow_id": workflow_id,
                    "status": WorkflowRunStatus.WAITING.value,
                    "accepted_at": 604700,
                    "started_at": 604710,
                }
            ]
        return [
            {
                "id": "run-active",
                "workflow_id": workflow_id,
                "status": WorkflowRunStatus.RUNNING.value,
                "accepted_at": 604800,
                "started_at": 604810,
            },
            {
                "id": "run-complete-recent",
                "workflow_id": workflow_id,
                "status": WorkflowRunStatus.COMPLETED.value,
                "accepted_at": 604700,
                "finished_at": 604850,
            },
            {
                "id": "run-complete-old",
                "workflow_id": workflow_id,
                "status": WorkflowRunStatus.COMPLETED.value,
                "accepted_at": 1,
                "finished_at": 10,
            },
        ]


def test_workflow_run_projections_map_statuses_and_read_only_actions() -> None:
    repository = FakeWorkflowRepository()

    projections = WorkflowTaskProjectionService(repository).list_projections("user-1", now=604900)

    by_id = {projection.workflow_run_id: projection for projection in projections}
    assert set(by_id) == {"run-active", "run-complete-recent", "run-waiting"}
    assert by_id["run-active"].status == "in_progress"
    assert by_id["run-active"].can_cancel is True
    assert by_id["run-complete-recent"].status == "done"
    assert by_id["run-complete-recent"].can_cancel is False
    assert by_id["run-waiting"].status == "blocked"
    assert by_id["run-waiting"].can_cancel is True
    assert all(projection.read_only is True for projection in projections)
    assert all(projection.task_id.startswith("workflow-run:") for projection in projections)


def test_workflow_run_projections_are_owner_scoped_and_sorted_recent_first() -> None:
    repository = FakeWorkflowRepository()

    projections = WorkflowTaskProjectionService(repository).list_projections("user-1", now=604900)

    assert repository.workflow_calls == ["user-1"]
    assert repository.run_calls == [("workflow-1", "user-1"), ("workflow-2", "user-1")]
    assert [projection.workflow_run_id for projection in projections] == [
        "run-complete-recent",
        "run-active",
        "run-waiting",
    ]
