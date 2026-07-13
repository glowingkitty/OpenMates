# backend/tests/test_workflow_runtime_python_transactions.py
#
# Python contracts for durable manual acceptance and trusted scheduler ownership.
# These tests keep Directus-only identifiers out of public route responses while
# proving accepted manual runs are dispatched with their pinned version.
#
# Spec: docs/specs/workflows-v1/spec.yml

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from backend.core.api.app.models.user import User
from backend.core.api.app.routes import workflows
from backend.core.api.app.services.workflow_runner import WorkflowRunner
from backend.core.api.app.services.workflow_service import InMemoryWorkflowRepository
from backend.core.api.app.tasks import workflow_tasks
from backend.tests.workflow_test_utils import workflow_service


def manual_graph() -> dict[str, Any]:
    return {
        "version": 1,
        "trigger_node_id": "trigger",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "config": {}},
            {"id": "end", "type": "end", "config": {}},
        ],
        "edges": [{"from": "trigger", "to": "end"}],
    }


class FakeRuntime:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, operation: str, data: dict[str, Any]) -> dict[str, Any]:
        self.events.append("accepted")
        self.calls.append((operation, data))
        return {
            "accepted": True,
            "run_id": "run-accepted",
            "workflow_id": "workflow-1",
            "version_id": "version-pinned",
            "status": "queued",
            "owner_user_id": "must-not-be-public",
        }


class FakeRunDispatcher:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.calls: list[tuple[object, ...]] = []

    def __call__(self, *args: object) -> None:
        self.events.append("dispatched")
        self.calls.append(args)


class ExistingQueuedRuntime(FakeRuntime):
    async def execute(self, operation: str, data: dict[str, Any]) -> dict[str, Any]:
        self.events.append("accepted")
        self.calls.append((operation, data))
        return {
            "accepted": False,
            "run_id": "run-accepted",
            "workflow_id": "workflow-1",
            "version_id": "version-pinned",
            "status": "queued",
        }


@pytest.mark.anyio
async def test_manual_route_accepts_a_pinned_run_before_dispatch_and_hides_scheduler_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    service = workflow_service(repository=InMemoryWorkflowRepository())
    workflow = service.create_workflow("alice", "Manual", manual_graph(), enabled=True)
    events: list[str] = []
    runtime = FakeRuntime(events)
    dispatcher = FakeRunDispatcher(events)
    monkeypatch.setattr(workflows, "_dispatch_accepted_workflow_run", dispatcher)

    response = await workflows.run_workflow(
        workflow.id,
        workflows.WorkflowRunRequest(mode="test", input={}),
        SimpleNamespace(headers={"Idempotency-Key": "request-1"}),
        User(id="alice", username="alice", vault_key_id="test-vault-key"),
        service,
        runtime,
    )

    assert events == ["accepted", "dispatched"]
    assert runtime.calls == [
        (
            "accept_manual_run",
            {
                "workflow_id": workflow.id,
                "hashed_user_id": service.repository.workflow_owner_hash("alice"),
                "trigger_type": "test",
                "idempotency_key": "request-1",
            },
        )
    ]
    assert dispatcher.calls == [(workflow.id, "alice", "run-accepted", "version-pinned", "test", {})]
    assert response["run"]["status"] == "queued"
    assert response["run"]["version_id"] == "version-pinned"
    assert "owner_user_id" not in response["run"]


@pytest.mark.anyio
async def test_manual_route_rejects_an_absent_idempotency_key_before_runtime_acceptance() -> None:
    service = workflow_service(repository=InMemoryWorkflowRepository())
    workflow = service.create_workflow("alice", "Manual", manual_graph(), enabled=True)
    runtime = FakeRuntime([])

    with pytest.raises(HTTPException) as exc_info:
        await workflows.run_workflow(
            workflow.id,
            workflows.WorkflowRunRequest(mode="test", input={}),
            SimpleNamespace(headers={}),
            User(id="alice", username="alice", vault_key_id="test-vault-key"),
            service,
            runtime,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "IDEMPOTENCY_KEY_REQUIRED"
    assert runtime.calls == []


@pytest.mark.anyio
async def test_manual_route_requeues_an_existing_accepted_queued_run(monkeypatch: pytest.MonkeyPatch) -> None:
    service = workflow_service(repository=InMemoryWorkflowRepository())
    workflow = service.create_workflow("alice", "Manual", manual_graph(), enabled=True)
    events: list[str] = []
    runtime = ExistingQueuedRuntime(events)
    dispatcher = FakeRunDispatcher(events)
    monkeypatch.setattr(workflows, "_dispatch_accepted_workflow_run", dispatcher)

    await workflows.run_workflow(
        workflow.id,
        workflows.WorkflowRunRequest(mode="manual", input={}),
        SimpleNamespace(headers={"Idempotency-Key": "request-1"}),
        User(id="alice", username="alice", vault_key_id="test-vault-key"),
        service,
        runtime,
    )

    assert events == ["accepted", "dispatched"]
    assert dispatcher.calls == [(workflow.id, "alice", "run-accepted", "version-pinned", "manual", {})]


class StartRejectedRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, operation: str, data: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((operation, data))
        return {"started": False, "run_id": "run-accepted", "workflow_id": "workflow-1", "version_id": "version-pinned", "status": "running"}


@pytest.mark.anyio
async def test_worker_does_not_execute_side_effects_when_another_delivery_claimed_the_run() -> None:
    runtime = StartRejectedRuntime()

    class Repository:
        @staticmethod
        def workflow_owner_hash(user_id: str) -> str:
            assert user_id == "alice"
            return "owner-hash"

    class Service:
        repository = Repository()

        @staticmethod
        def resolve_user_vault_key_id(user_id: str) -> str:
            raise AssertionError(f"worker loaded Vault state before its run claim: {user_id}")

    result = await workflow_tasks.run_workflow_now(
        "workflow-1",
        "alice",
        "run-accepted",
        "version-pinned",
        "manual",
        {},
        workflow_service=Service(),
        runtime_service=runtime,
    )

    assert result == {"id": "run-accepted", "workflow_id": "workflow-1", "version_id": "version-pinned", "status": "running"}
    assert runtime.calls == [
        (
            "start_accepted_run",
            {"workflow_id": "workflow-1", "run_id": "run-accepted", "hashed_user_id": "owner-hash"},
        )
    ]


@pytest.mark.anyio
def schedule_graph() -> dict[str, Any]:
    return {
        "version": 1,
        "trigger_node_id": "trigger",
        "nodes": [
            {"id": "trigger", "type": "schedule_trigger", "config": {"schedule": {"type": "daily", "time": "08:00", "timezone": "UTC"}}},
            {"id": "weather", "type": "app_skill_action", "config": {"app_id": "weather", "skill_id": "forecast"}},
            {"id": "end", "type": "end", "config": {}},
        ],
        "edges": [{"from": "trigger", "to": "weather"}, {"from": "weather", "to": "end"}],
    }


def test_import_binding_completion_requires_server_evidence_before_enabling() -> None:
    service = workflow_service(repository=InMemoryWorkflowRepository())
    workflow = service.create_workflow("alice", "Imported", schedule_graph(), source="import")
    service.initialize_import_binding_requirements(
        workflow.id,
        "alice",
        [
            {"type": "schedule", "node_id": "trigger"},
            {"type": "app_skill", "node_id": "weather", "app_id": "weather", "skill_id": "forecast"},
        ],
    )

    class Registry:
        @staticmethod
        def is_skill_available(app_id: str, skill_id: str) -> bool:
            return (app_id, skill_id) == ("weather", "forecast")

    schedule_requirement = service.validate_schedule_binding_requirement(workflow.id, "alice", "trigger")
    app_skill_requirement = service.validate_app_skill_binding_requirement(workflow.id, "alice", "weather", Registry())
    service.complete_import_binding_requirement(workflow.id, "alice", schedule_requirement)
    service.complete_import_binding_requirement(workflow.id, "alice", app_skill_requirement)

    assert service.update_workflow(workflow.id, "alice", enabled=True).enabled is True


def test_import_binding_completion_returns_a_typed_reason_when_the_skill_is_unavailable() -> None:
    service = workflow_service(repository=InMemoryWorkflowRepository())
    workflow = service.create_workflow("alice", "Imported", schedule_graph(), source="import")
    service.initialize_import_binding_requirements(
        workflow.id,
        "alice",
        [{"type": "app_skill", "node_id": "weather", "app_id": "weather", "skill_id": "forecast"}],
    )

    class EmptyRegistry:
        @staticmethod
        def is_skill_available(app_id: str, skill_id: str) -> bool:
            return False

    with pytest.raises(Exception, match="APP_SKILL_UNAVAILABLE"):
        service.validate_app_skill_binding_requirement(workflow.id, "alice", "weather", EmptyRegistry())


@pytest.mark.anyio
async def test_binding_completion_endpoint_returns_a_typed_unresolved_reason() -> None:
    service = workflow_service(repository=InMemoryWorkflowRepository())
    workflow = service.create_workflow("alice", "Imported", schedule_graph(), source="import")
    service.initialize_import_binding_requirements(
        workflow.id,
        "alice",
        [{"type": "app_skill", "node_id": "weather", "app_id": "weather", "skill_id": "forecast"}],
    )

    class EmptyRegistry:
        @staticmethod
        def is_skill_available(app_id: str, skill_id: str) -> bool:
            return False

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(skill_registry=EmptyRegistry())))
    with pytest.raises(HTTPException) as exc_info:
        await workflows.complete_workflow_template_binding(
            workflow.id,
            workflows.WorkflowTemplateBindingCompletionRequest(type="app_skill", node_id="weather"),
            request,
            User(id="alice", username="alice", vault_key_id="test-vault-key"),
            service,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == {"code": "UNRESOLVED_WORKFLOW_BINDING", "reason": "APP_SKILL_UNAVAILABLE"}


@pytest.mark.anyio
async def test_runner_rejects_manual_execution_without_a_durable_pinned_run() -> None:
    service = workflow_service(repository=InMemoryWorkflowRepository())
    workflow = service.create_workflow("alice", "Manual", manual_graph())

    with pytest.raises(ValueError, match="must be accepted"):
        await WorkflowRunner(service).run_workflow(workflow, "alice", trigger_type="manual")


def test_trigger_owner_id_is_persisted_internally_but_not_returned_to_service_callers() -> None:
    repository = InMemoryWorkflowRepository()
    service = workflow_service(repository=repository)
    workflow = service.create_workflow("alice", "Manual", manual_graph())

    trigger = repository.get_trigger_for_workflow(workflow.id, "alice")

    assert trigger is not None
    assert "owner_user_id" not in trigger
    assert repository.triggers[trigger["trigger_id"]]["owner_user_id"] == "alice"
