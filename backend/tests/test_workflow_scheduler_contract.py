# backend/tests/test_workflow_scheduler_contract.py
#
# Scheduler contract for the atomic accepted-run boundary. Execution side effects
# are permitted only after Directus fences the current claim token and generation.
#
# Spec: docs/specs/workflows-v1/spec.yml (TASK-3, T-PYTEST-006)

import pytest

from backend.core.api.app.services.workflow_scheduler_service import WorkflowSchedulerService
from backend.core.api.app.services.workflow_models import WorkflowRunDetail, WorkflowRunStatus
from backend.core.api.app.services.workflow_runner import WorkflowRunner
from backend.core.api.app.services.workflow_service import InMemoryWorkflowRepository
from backend.tests.workflow_test_utils import workflow_service


class FakeRuntime:
    def __init__(self, claim: dict[str, object], start: dict[str, object]) -> None:
        self.claim = claim
        self.start = start
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.events: list[str] = []

    async def execute(self, operation: str, data: dict[str, object]) -> dict[str, object]:
        self.calls.append((operation, data))
        self.events.append(operation)
        if operation == "claim_due_trigger":
            return self.claim
        if operation == "start_claimed_run":
            return self.start
        if operation == "advance_claimed_trigger":
            return {"trigger_id": "trigger-1", "next_run_at": data["next_run_at"]}
        raise AssertionError(operation)


def scheduled_graph() -> dict[str, object]:
    return {
        "version": 1,
        "trigger_node_id": "trigger",
        "nodes": [
            {
                "id": "trigger",
                "type": "schedule_trigger",
                "config": {"schedule": {"type": "daily", "time": "07:00", "timezone": "UTC"}},
            },
            {"id": "end", "type": "end", "config": {}},
        ],
        "edges": [{"from": "trigger", "to": "end"}],
    }


# contract-test: supporting surface=rest_api assertions=workflows.execution.lifecycle-visible,workflows.surface.semantic-parity
@pytest.mark.anyio
async def test_scheduler_fences_claim_and_advances_recurrence_before_side_effects() -> None:
    runtime = FakeRuntime(
        {
            "accepted": True,
            "run_id": "run-1",
            "workflow_id": "workflow-1",
            "version_id": "version-1",
            "owner_user_id": "alice",
            "encrypted_schedule_config_ref": "blob-schedule-1",
            "claim_token": "claim-token",
            "claim_generation": 2,
        },
        {"started": True, "run_id": "run-1", "workflow_id": "workflow-1", "version_id": "version-1"},
    )
    effects: list[tuple[str, str, str]] = []

    async def decrypt_and_schedule(owner_user_id: str, blob_ref: str) -> int:
        assert owner_user_id == "alice"
        assert blob_ref == "blob-schedule-1"
        return 1_800_000_000

    async def execute_run(run_id: str, workflow_id: str, version_id: str, owner_user_id: str) -> None:
        runtime.events.append("execute_run")
        effects.append((run_id, workflow_id, version_id, owner_user_id))

    result = await WorkflowSchedulerService(runtime).execute_due_trigger(
        "trigger-1", decrypt_and_schedule, execute_run
    )

    assert result == {"accepted": True, "run_id": "run-1", "next_run_at": 1_800_000_000}
    assert effects == [("run-1", "workflow-1", "version-1", "alice")]
    assert [operation for operation, _ in runtime.calls] == [
        "claim_due_trigger",
        "start_claimed_run",
        "advance_claimed_trigger",
    ]
    assert runtime.events == [
        "claim_due_trigger",
        "start_claimed_run",
        "advance_claimed_trigger",
        "execute_run",
    ]


# contract-test: supporting surface=rest_api assertions=workflows.execution.lifecycle-visible,workflows.surface.semantic-parity
@pytest.mark.anyio
async def test_scheduler_does_not_decrypt_or_execute_when_another_worker_owns_claim() -> None:
    runtime = FakeRuntime({"accepted": False, "run_id": "run-1", "version_id": "version-1"}, {})

    async def should_not_run(*_args: object) -> object:
        raise AssertionError("must not run")

    result = await WorkflowSchedulerService(runtime).execute_due_trigger(
        "trigger-1", should_not_run, should_not_run
    )

    assert result == {"accepted": False, "run_id": "run-1"}
    assert runtime.calls == [("claim_due_trigger", {"trigger_id": "trigger-1"})]


# contract-test: supporting surface=rest_api assertions=workflows.execution.lifecycle-visible,workflows.surface.semantic-parity
@pytest.mark.anyio
async def test_scheduler_runs_a_reclaimed_queued_occurrence() -> None:
    runtime = FakeRuntime(
        {
            "accepted": True,
            "recovered": True,
            "run_id": "run-1",
            "workflow_id": "workflow-1",
            "version_id": "version-1",
            "owner_user_id": "alice",
            "encrypted_schedule_config_ref": "blob-schedule-1",
            "claim_token": "claim-token",
            "claim_generation": 2,
        },
        {"started": True, "run_id": "run-1", "workflow_id": "workflow-1", "version_id": "version-1"},
    )

    effects: list[str] = []

    async def decrypt_and_schedule(owner_user_id: str, blob_ref: str) -> int:
        assert (owner_user_id, blob_ref) == ("alice", "blob-schedule-1")
        return 1_800_000_000

    async def execute_run(run_id: str, *_args: object) -> None:
        effects.append(run_id)

    result = await WorkflowSchedulerService(runtime).execute_due_trigger("trigger-1", decrypt_and_schedule, execute_run)

    assert result == {"accepted": True, "run_id": "run-1", "next_run_at": 1_800_000_000}
    assert effects == ["run-1"]


# contract-test: supporting surface=rest_api assertions=workflows.execution.lifecycle-visible,workflows.surface.semantic-parity
@pytest.mark.anyio
async def test_scheduler_advances_a_cancelled_occurrence_without_executing_nodes() -> None:
    runtime = FakeRuntime(
        {
            "accepted": True,
            "recovered": True,
            "run_id": "run-1",
            "workflow_id": "workflow-1",
            "version_id": "version-1",
            "owner_user_id": "alice",
            "encrypted_schedule_config_ref": "blob-schedule-1",
            "claim_token": "claim-token",
            "claim_generation": 2,
        },
        {"started": False, "run_id": "run-1", "workflow_id": "workflow-1", "version_id": "version-1", "status": "cancelled"},
    )

    async def decrypt_and_schedule(owner_user_id: str, blob_ref: str) -> int:
        assert (owner_user_id, blob_ref) == ("alice", "blob-schedule-1")
        return 1_800_000_000

    async def should_not_execute(*_args: object) -> None:
        raise AssertionError("cancelled runs must not execute nodes")

    result = await WorkflowSchedulerService(runtime).execute_due_trigger("trigger-1", decrypt_and_schedule, should_not_execute)

    assert result == {"accepted": True, "run_id": "run-1", "status": "cancelled", "next_run_at": 1_800_000_000}
    assert [operation for operation, _ in runtime.calls] == [
        "claim_due_trigger",
        "start_claimed_run",
        "advance_claimed_trigger",
    ]


# contract-test: supporting surface=rest_api assertions=workflows.execution.lifecycle-visible,workflows.surface.semantic-parity
@pytest.mark.anyio
async def test_scheduler_completes_one_time_occurrence_without_future_requeue() -> None:
    runtime = FakeRuntime(
        {
            "accepted": True,
            "run_id": "run-1",
            "workflow_id": "workflow-1",
            "version_id": "version-1",
            "owner_user_id": "alice",
            "encrypted_schedule_config_ref": "blob-schedule-1",
            "claim_token": "claim-token",
            "claim_generation": 2,
        },
        {"started": True, "run_id": "run-1", "workflow_id": "workflow-1", "version_id": "version-1"},
    )

    async def decrypt_and_schedule(_owner_user_id: str, _blob_ref: str) -> int:
        return WorkflowSchedulerService.next_run_at_from_schedule({"schedule": {"type": "once", "at": "2026-07-12T08:00:00Z"}})

    async def execute_run(_run_id: str, _workflow_id: str, _version_id: str, _owner_user_id: str) -> None:
        return None

    result = await WorkflowSchedulerService(runtime).execute_due_trigger("trigger-1", decrypt_and_schedule, execute_run)

    assert result == {"accepted": True, "run_id": "run-1", "next_run_at": 0}
    assert runtime.calls[-1] == (
        "advance_claimed_trigger",
        {
            "trigger_id": "trigger-1",
            "claim_generation": 2,
            "claim_token": "claim-token",
            "next_run_at": 0,
        },
    )


# contract-test: supporting surface=rest_api assertions=workflows.execution.lifecycle-visible,workflows.surface.semantic-parity
@pytest.mark.anyio
async def test_scheduler_executes_the_claimed_run_id_without_creating_another_run() -> None:
    service = workflow_service(repository=InMemoryWorkflowRepository())
    workflow = service.create_workflow("alice", "Scheduled", scheduled_graph(), enabled=True)
    service.save_run(
        "alice",
        WorkflowRunDetail(
            id="run-accepted",
            workflow_id=workflow.id,
            version_id=workflow.current_version_id,
            trigger_type="schedule",
            status=WorkflowRunStatus.QUEUED,
        ),
    )
    runtime = FakeRuntime(
        {
            "accepted": True,
            "run_id": "run-accepted",
            "workflow_id": workflow.id,
            "version_id": workflow.current_version_id,
            "owner_user_id": "alice",
            "encrypted_schedule_config_ref": "blob-schedule-1",
            "claim_token": "claim-token",
            "claim_generation": 2,
        },
        {"started": True, "run_id": "run-accepted", "workflow_id": workflow.id, "version_id": workflow.current_version_id},
    )

    async def decrypt_and_schedule(owner_user_id: str, blob_ref: str) -> int:
        assert owner_user_id == "alice"
        assert blob_ref == "blob-schedule-1"
        return 1_800_000_000

    async def execute_run(run_id: str, workflow_id: str, version_id: str, owner_user_id: str) -> None:
        assert owner_user_id == "alice"
        detail = service.get_workflow_version(workflow_id, "alice", version_id)
        await WorkflowRunner(service).run_workflow(
            detail,
            "alice",
            trigger_type="schedule",
            run_id=run_id,
            version_id=version_id,
        )

    result = await WorkflowSchedulerService(runtime).execute_due_trigger(
        "trigger-1",
        decrypt_and_schedule,
        execute_run,
    )

    persisted_run = service.get_run(workflow.id, "run-accepted", "alice")
    assert result == {"accepted": True, "run_id": "run-accepted", "next_run_at": 1_800_000_000}
    assert persisted_run.id == "run-accepted"
    assert [run.id for run in service.list_runs(workflow.id, "alice")] == ["run-accepted"]
