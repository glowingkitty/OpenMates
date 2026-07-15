# backend/tests/test_workflow_deferred_contracts.py
#
# Focused contracts for the deferred Workflows V1 definition-history and
# cooperative run-cancellation backend slices. These tests intentionally avoid
# Tasks projections because no existing Tasks integration owns workflow runs.
#
# Spec: docs/specs/workflows-v1/spec.yml

from __future__ import annotations

from typing import Any

import pytest

from backend.core.api.app.models.user import User
from backend.core.api.app.services.workflow_models import WorkflowRunDetail, WorkflowRunStatus
from backend.core.api.app.services.workflow_runner import WorkflowRunner
from backend.core.api.app.services.workflow_service import (
    InMemoryWorkflowRepository,
    WORKFLOW_VERSION_HISTORY_LIMIT,
    WorkflowRunNotCancellableError,
)
from backend.tests.test_workflows_models import rain_graph
from backend.tests.workflow_test_utils import workflow_service


def _changed_graph(index: int) -> dict[str, Any]:
    graph = rain_graph()
    graph["nodes"][3]["config"]["body"] = f"Take umbrella number {index}."
    return graph


def _queued_run(workflow_id: str, version_id: str) -> WorkflowRunDetail:
    return WorkflowRunDetail(
        id="run-1",
        workflow_id=workflow_id,
        version_id=version_id,
        trigger_type="schedule",
        status=WorkflowRunStatus.QUEUED,
    )


def test_owner_can_list_capped_immutable_definition_history_and_restore_as_new_version() -> None:
    service = workflow_service(repository=InMemoryWorkflowRepository())
    workflow = service.create_workflow("alice", "Rain alert", _changed_graph(0))
    original_version_id = workflow.current_version_id

    for index in range(1, WORKFLOW_VERSION_HISTORY_LIMIT + 2):
        service.update_workflow(workflow.id, "alice", graph=_changed_graph(index))

    history = service.list_workflow_versions(workflow.id, "alice")

    assert len(history) == WORKFLOW_VERSION_HISTORY_LIMIT
    assert history[0].current is True
    assert history[0].version_number == WORKFLOW_VERSION_HISTORY_LIMIT + 2
    assert original_version_id not in {version.version_id for version in history}
    assert all(version.graph_hash.startswith("sha256:") for version in history)
    with pytest.raises(KeyError):
        service.get_workflow_version(workflow.id, "alice", original_version_id)
    with pytest.raises(KeyError):
        service.list_workflow_versions(workflow.id, "bob")

    historical = history[-1]
    historical_detail = service.get_workflow_version(workflow.id, "alice", historical.version_id)
    restored = service.restore_workflow_version(workflow.id, "alice", historical.version_id)
    restored_history = service.list_workflow_versions(workflow.id, "alice")

    assert restored.current_version_id != historical.version_id
    assert restored.graph == historical_detail.graph
    assert restored_history[0].restored_from_version_id == historical.version_id
    assert restored_history[0].current is True
    assert historical.current is False


@pytest.mark.anyio
async def test_owner_history_routes_return_read_only_version_graph_and_restore_response() -> None:
    from backend.core.api.app.routes import workflows

    service = workflow_service(repository=InMemoryWorkflowRepository())
    workflow = service.create_workflow("alice", "Rain alert", _changed_graph(0))
    service.update_workflow(workflow.id, "alice", graph=_changed_graph(1))
    current_user = User(id="alice", username="alice", vault_key_id="test-vault-key")

    history_response = await workflows.list_workflow_versions(workflow.id, current_user, service)
    version_id = history_response["versions"][-1]["version_id"]
    detail_response = await workflows.get_workflow_version(workflow.id, version_id, current_user, service)
    restored_response = await workflows.restore_workflow_version(workflow.id, version_id, current_user, service)

    assert history_response["retention"] == {"mode": "last_25_versions", "max_versions": WORKFLOW_VERSION_HISTORY_LIMIT}
    assert detail_response["version"]["version_id"] == version_id
    assert detail_response["version"]["graph"]["nodes"][3]["config"]["body"] == "Take umbrella number 0."
    assert restored_response["workflow"]["current_version_id"] != version_id


class _CancellationRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, operation: str, data: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((operation, data))
        return {"run_id": data["run_id"], "status": "cancellation_requested"}


@pytest.mark.anyio
async def test_cancel_route_requests_cancellation_only_for_the_owner_run() -> None:
    from backend.core.api.app.routes import workflows

    service = workflow_service(repository=InMemoryWorkflowRepository())
    workflow = service.create_workflow("alice", "Rain alert", _changed_graph(0))
    runtime = _CancellationRuntime()
    user = User(id="alice", username="alice", vault_key_id="test-vault-key")

    response = await workflows.cancel_workflow_run(workflow.id, "run-1", user, service, runtime)

    assert response == {"run_id": "run-1", "status": "cancellation_requested"}
    assert runtime.calls == [
        (
            "request_run_cancellation",
            {
                "workflow_id": workflow.id,
                "run_id": "run-1",
                "hashed_user_id": service.repository.workflow_owner_hash("alice"),
            },
        )
    ]


class _CancellingAppSkillAdapter:
    def __init__(self, service: Any, workflow_id: str, run_id: str) -> None:
        self._service = service
        self._workflow_id = workflow_id
        self._run_id = run_id
        self.calls: list[tuple[str, str]] = []

    async def execute(self, app_id: str, skill_id: str, request: dict[str, Any], *, user_id: str | None = None) -> dict[str, Any]:
        del request, user_id
        self.calls.append((app_id, skill_id))
        self._service.request_run_cancellation(self._workflow_id, self._run_id, "alice")
        return {"rain_probability": 70}


class _ActionAdapter:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def create_chat_report(self, config: dict[str, Any], context: dict[str, Any], user_id: str) -> dict[str, Any]:
        del config, context, user_id
        self.calls.append("report")
        return {"report_id": "report-1"}

    async def start_new_chat(self, config: dict[str, Any], context: dict[str, Any], user_id: str) -> dict[str, Any]:
        del config, context, user_id
        self.calls.append("chat")
        return {"chat_id": "chat-1"}

    async def send_notification(self, config: dict[str, Any], channel: str, user_id: str) -> dict[str, Any]:
        del config, user_id
        self.calls.append(channel)
        return {"queued": True}


@pytest.mark.anyio
async def test_runner_stops_after_an_in_flight_call_without_mutating_the_started_node() -> None:
    service = workflow_service(repository=InMemoryWorkflowRepository())
    workflow = service.create_workflow("alice", "Rain alert", _changed_graph(0))
    service.save_run("alice", _queued_run(workflow.id, workflow.current_version_id))
    app_adapter = _CancellingAppSkillAdapter(service, workflow.id, "run-1")
    action_adapter = _ActionAdapter()

    run = await WorkflowRunner(service, app_skill_adapter=app_adapter, action_adapter=action_adapter).run_workflow(
        workflow,
        "alice",
        trigger_type="schedule",
        run_id="run-1",
        version_id=workflow.current_version_id,
    )

    assert app_adapter.calls == [("weather", "forecast")]
    assert action_adapter.calls == []
    assert [node.node_id for node in run.node_runs] == ["trigger", "weather"]
    assert run.status == WorkflowRunStatus.CANCELLED
    assert run.version_id == workflow.current_version_id
    with pytest.raises(WorkflowRunNotCancellableError):
        service.request_run_cancellation(workflow.id, "run-1", "alice")
