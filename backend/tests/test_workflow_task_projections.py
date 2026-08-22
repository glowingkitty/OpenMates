# backend/tests/test_workflow_task_projections.py
#
# Focused contracts for Workflow run views rendered by Tasks. Projections are
# derived from owner-scoped workflow_runs metadata and never create user_tasks
# rows or expose encrypted Workflow content.
#

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.responses import Response

from backend.core.api.app.services.directus.user_task_methods import UserTaskMethods
from backend.core.api.app.services.workflow_models import WorkflowRunStatus
from backend.core.api.app.services.workflow_service import InMemoryWorkflowRepository
from backend.core.api.app.services.workflow_task_projection_service import WorkflowTaskProjectionService
from backend.core.api.app.services.user_task_service import UserTaskService
from backend.tests.test_workflows_models import rain_graph
from backend.tests.workflow_test_utils import workflow_service


NOW = 1_000_000


def _save_run(
    repository: InMemoryWorkflowRepository,
    *,
    run_id: str,
    workflow_id: str,
    owner_id: str,
    status: WorkflowRunStatus,
    accepted_at: int | None = None,
    started_at: int | None = None,
    finished_at: int | None = None,
    trigger_id: str | None = None,
    scheduled_at: int | None = None,
) -> None:
    repository.save_run(
        {
            "id": run_id,
            "workflow_id": workflow_id,
            "version_id": "version-1",
            "owner_hash": repository.workflow_owner_hash(owner_id),
            "trigger_id": trigger_id,
            "status": status.value,
            "accepted_at": NOW - 50 if accepted_at is None else accepted_at,
            "started_at": started_at,
            "finished_at": finished_at,
            "scheduled_at": scheduled_at,
            "cancellation_requested_at": None,
        }
    )


def _set_trigger_next_run(repository: InMemoryWorkflowRepository, workflow_id: str, *, next_run_at: int) -> str:
    trigger = next(record for record in repository.triggers.values() if record["workflow_id"] == workflow_id)
    trigger["next_run_at"] = next_run_at
    trigger["enabled"] = True
    repository.save_trigger(trigger)
    return trigger["trigger_id"]


# contract-test: direct surface=rest_api assertions=tasks.workflow-projections.read-only
def test_active_schedule_projects_exactly_one_future_todo_task() -> None:
    repository = InMemoryWorkflowRepository()
    service = workflow_service(repository=repository)
    workflow = service.create_workflow("alice", "Morning rain", rain_graph(), enabled=True)
    trigger_id = _set_trigger_next_run(repository, workflow.id, next_run_at=NOW + 3_600)

    projections = WorkflowTaskProjectionService(repository).list_projections("alice", now=NOW)

    future_tasks = [projection for projection in projections if projection.status == "todo"]
    assert len(future_tasks) == 1
    future = future_tasks[0]
    assert future.task_id == f"workflow-schedule:{trigger_id}:{NOW + 3_600}"
    assert future.projection_kind == "next_run"
    assert future.workflow_id == workflow.id
    assert future.workflow_run_id is None
    assert future.run_status == WorkflowRunStatus.PLANNED
    assert future.due_at == NOW + 3_600
    assert future.scheduled_at == NOW + 3_600
    assert future.can_cancel is False
    assert future.can_delete is True
    assert future.read_only is True


# contract-test: direct surface=rest_api assertions=tasks.workflow-projections.read-only
def test_deleting_future_schedule_projection_marks_run_skipped_and_advances_trigger() -> None:
    repository = InMemoryWorkflowRepository()
    service = workflow_service(repository=repository)
    workflow = service.create_workflow("alice", "Morning rain", rain_graph(), enabled=True)
    trigger_id = _set_trigger_next_run(repository, workflow.id, next_run_at=NOW + 3_600)
    projection_service = WorkflowTaskProjectionService(repository)
    task_id = f"workflow-schedule:{trigger_id}:{NOW + 3_600}"

    skipped = projection_service.skip_scheduled_projection("alice", task_id, now=NOW)

    assert skipped == {
        "run_id": f"skipped:{trigger_id}:{NOW + 3_600}",
        "workflow_id": workflow.id,
        "status": WorkflowRunStatus.SKIPPED_BY_USER.value,
    }
    skipped_run = repository.runs[f"skipped:{trigger_id}:{NOW + 3_600}"]
    assert skipped_run["status"] == WorkflowRunStatus.SKIPPED_BY_USER.value
    assert skipped_run["scheduled_at"] == NOW + 3_600
    assert repository.triggers[trigger_id]["next_run_at"] == NOW + 3_601
    assert task_id not in {projection.task_id for projection in projection_service.list_projections("alice", now=NOW)}


# contract-test: direct surface=rest_api assertions=tasks.workflow-projections.read-only
def test_active_scheduled_run_suppresses_duplicate_future_projection_for_same_occurrence() -> None:
    repository = InMemoryWorkflowRepository()
    service = workflow_service(repository=repository)
    workflow = service.create_workflow("alice", "Morning rain", rain_graph(), enabled=True)
    trigger_id = _set_trigger_next_run(repository, workflow.id, next_run_at=NOW + 3_600)
    _save_run(
        repository,
        run_id="scheduled-running",
        workflow_id=workflow.id,
        owner_id="alice",
        status=WorkflowRunStatus.RUNNING,
        started_at=NOW + 3_600,
        trigger_id=trigger_id,
    )

    projections = WorkflowTaskProjectionService(repository).list_projections("alice", now=NOW)

    assert [projection.status for projection in projections].count("todo") == 0
    running = next(projection for projection in projections if projection.workflow_run_id == "scheduled-running")
    assert running.projection_kind == "current_run"
    assert running.status == "in_progress"


# contract-test: direct surface=rest_api assertions=tasks.workflow-projections.read-only
def test_running_scheduled_workflow_projects_current_run_and_next_todo() -> None:
    repository = InMemoryWorkflowRepository()
    service = workflow_service(repository=repository)
    workflow = service.create_workflow("alice", "Morning rain", rain_graph(), enabled=True)
    trigger_id = _set_trigger_next_run(repository, workflow.id, next_run_at=NOW + 3_600)
    _save_run(
        repository,
        run_id="scheduled-running",
        workflow_id=workflow.id,
        owner_id="alice",
        status=WorkflowRunStatus.RUNNING,
        started_at=NOW,
        trigger_id=trigger_id,
        scheduled_at=NOW,
    )

    projections = WorkflowTaskProjectionService(repository).list_projections("alice", now=NOW)

    linked = [projection for projection in projections if projection.workflow_id == workflow.id]
    assert {projection.projection_kind for projection in linked} == {"current_run", "next_run"}
    assert {projection.status for projection in linked} == {"in_progress", "todo"}
    assert len(linked) == 2
    running = next(projection for projection in linked if projection.projection_kind == "current_run")
    todo = next(projection for projection in linked if projection.projection_kind == "next_run")
    assert running.task_id == "workflow-run:scheduled-running"
    assert running.workflow_run_id == "scheduled-running"
    assert running.trigger_id == trigger_id
    assert todo.task_id == f"workflow-schedule:{trigger_id}:{NOW + 3_600}"
    assert todo.workflow_run_id is None
    assert todo.due_at == NOW + 3_600
    assert todo.can_delete is True


# contract-test: direct surface=rest_api assertions=tasks.workflow-projections.read-only
def test_task_projections_are_owner_scoped_redacted_and_do_not_persist_user_tasks() -> None:
    repository = InMemoryWorkflowRepository()
    service = workflow_service(repository=repository)
    alice_workflow = service.create_workflow("alice", "Customer confidential workflow", rain_graph())
    bob_workflow = service.create_workflow("bob", "Bob private workflow", rain_graph())
    _save_run(repository, run_id="alice-running", workflow_id=alice_workflow.id, owner_id="alice", status=WorkflowRunStatus.RUNNING, started_at=NOW - 10)
    _save_run(repository, run_id="bob-running", workflow_id=bob_workflow.id, owner_id="bob", status=WorkflowRunStatus.RUNNING, started_at=NOW - 10)

    projections = WorkflowTaskProjectionService(repository).list_projections("alice", now=NOW)

    assert [projection.workflow_run_id for projection in projections] == ["alice-running"]
    projection = projections[0]
    assert projection.source == "workflow_run"
    assert projection.task_id == "workflow-run:alice-running"
    assert projection.status == "in_progress"
    assert projection.can_cancel is True
    assert projection.label == "Workflow run"
    assert projection.title.startswith("Workflow - ")
    dumped_projection = str(projection.model_dump())
    assert "Customer confidential workflow" not in dumped_projection
    assert "Bob private workflow" not in dumped_projection
    assert not hasattr(repository, "user_tasks")


# contract-test: direct surface=rest_api assertions=tasks.workflow-projections.read-only
def test_task_projections_limit_workflow_to_current_last_and_next_entries() -> None:
    repository = InMemoryWorkflowRepository()
    service = workflow_service(repository=repository)
    workflow = service.create_workflow("alice", "Private workflow", rain_graph(), enabled=True)
    trigger_id = _set_trigger_next_run(repository, workflow.id, next_run_at=NOW + 3_600)
    _save_run(repository, run_id="completed-newest", workflow_id=workflow.id, owner_id="alice", status=WorkflowRunStatus.COMPLETED, finished_at=NOW - 1)
    _save_run(repository, run_id="cancelled-older", workflow_id=workflow.id, owner_id="alice", status=WorkflowRunStatus.CANCELLED, finished_at=NOW - 2)
    _save_run(repository, run_id="failed-older", workflow_id=workflow.id, owner_id="alice", status=WorkflowRunStatus.FAILED, finished_at=NOW - 3)
    _save_run(repository, run_id="expired", workflow_id=workflow.id, owner_id="alice", status=WorkflowRunStatus.COMPLETED, finished_at=NOW - 604_801)
    _save_run(repository, run_id="waiting", workflow_id=workflow.id, owner_id="alice", status=WorkflowRunStatus.WAITING, started_at=NOW - 4)

    projections = WorkflowTaskProjectionService(repository).list_projections("alice", now=NOW)
    by_kind = {projection.projection_kind: projection for projection in projections}

    assert set(by_kind) == {"last_run", "current_run", "next_run"}
    assert len(projections) == 3
    assert by_kind["last_run"].workflow_run_id == "completed-newest"
    assert by_kind["last_run"].status == "done"
    assert by_kind["last_run"].can_cancel is False
    assert by_kind["current_run"].workflow_run_id == "waiting"
    assert by_kind["current_run"].status == "blocked"
    assert by_kind["current_run"].blocked_reason == "needs_user_input"
    assert by_kind["current_run"].blocked_message == "Workflow is waiting for user input."
    assert by_kind["current_run"].can_cancel is True
    assert by_kind["next_run"].task_id == f"workflow-schedule:{trigger_id}:{NOW + 3_600}"
    assert by_kind["next_run"].workflow_run_id is None


# contract-test: direct surface=rest_api assertions=tasks.workflow-projections.read-only
def test_failed_recent_past_run_projects_as_last_run_blocked() -> None:
    repository = InMemoryWorkflowRepository()
    service = workflow_service(repository=repository)
    workflow = service.create_workflow("alice", "Private workflow", rain_graph(), enabled=False)
    _save_run(repository, run_id="failed", workflow_id=workflow.id, owner_id="alice", status=WorkflowRunStatus.FAILED, finished_at=NOW - 3)

    projections = WorkflowTaskProjectionService(repository).list_projections("alice", now=NOW)

    assert len(projections) == 1
    projection = projections[0]
    assert projection.projection_kind == "last_run"
    assert projection.workflow_run_id == "failed"
    assert projection.status == "blocked"
    assert projection.blocked_reason == "workflow_failed"
    assert projection.blocked_message == "Workflow run failed."


# contract-test: direct surface=rest_api assertions=tasks.workflow-projections.read-only
@pytest.mark.anyio
async def test_tasks_route_merges_workflow_run_projection_without_user_task_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.core.api.app.routes import user_tasks

    repository = InMemoryWorkflowRepository()
    workflow = workflow_service(repository=repository).create_workflow("alice", "Private workflow", rain_graph())
    _save_run(repository, run_id="run-1", workflow_id=workflow.id, owner_id="alice", status=WorkflowRunStatus.QUEUED)
    directus = SimpleNamespace(get_items=AsyncMock(return_value=[{"task_id": "user-task"}]))

    async def current_user(_request: object, _response: Response) -> SimpleNamespace:
        return SimpleNamespace(id="alice")

    monkeypatch.setattr(user_tasks, "_current_user", current_user)
    response = await user_tasks.list_user_tasks.__wrapped__(
        request=SimpleNamespace(),
        response=Response(),
        service=UserTaskService(UserTaskMethods(directus)),
        workflow_projection_service=WorkflowTaskProjectionService(repository),
    )

    assert [task["task_id"] for task in response["tasks"]] == ["user-task", "workflow-run:run-1"]
    assert response["tasks"][1]["source"] == "workflow_run"
    directus.get_items.assert_awaited_once()

    contextual_response = await user_tasks.list_user_tasks.__wrapped__(
        request=SimpleNamespace(),
        response=Response(),
        chat_id="chat-1",
        service=UserTaskService(UserTaskMethods(directus)),
        workflow_projection_service=WorkflowTaskProjectionService(repository),
    )

    assert [task["task_id"] for task in contextual_response["tasks"]] == ["user-task"]


# contract-test: direct surface=rest_api assertions=tasks.workflow-projections.read-only
@pytest.mark.anyio
async def test_tasks_delete_route_skips_future_workflow_projection_without_user_task_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.core.api.app.routes import user_tasks

    repository = InMemoryWorkflowRepository()
    workflow = workflow_service(repository=repository).create_workflow("alice", "Private workflow", rain_graph(), enabled=True)
    trigger_id = _set_trigger_next_run(repository, workflow.id, next_run_at=NOW + 3_600)
    directus = SimpleNamespace(delete_item=AsyncMock(return_value=True))

    async def current_user(_request: object, _response: Response) -> SimpleNamespace:
        return SimpleNamespace(id="alice")

    monkeypatch.setattr(user_tasks, "_current_user", current_user)
    task_id = f"workflow-schedule:{trigger_id}:{NOW + 3_600}"

    response = await user_tasks.delete_user_task.__wrapped__(
        request=SimpleNamespace(),
        response=Response(),
        task_id=task_id,
        version=1,
        service=UserTaskService(UserTaskMethods(directus)),
        workflow_projection_service=WorkflowTaskProjectionService(repository),
    )

    assert response["deleted"] is True
    assert response["task_id"] == task_id
    assert response["workflow_run"]["status"] == WorkflowRunStatus.SKIPPED_BY_USER.value
    directus.delete_item.assert_not_called()
