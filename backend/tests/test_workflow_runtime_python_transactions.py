# backend/tests/test_workflow_runtime_python_transactions.py
#
# Python contracts for durable manual acceptance and trusted scheduler ownership.
# These tests keep Directus-only identifiers out of public route responses while
# proving accepted manual runs are dispatched with their pinned version.
#
# Spec: docs/specs/workflows-v1/spec.yml

from __future__ import annotations

import hashlib
import json
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
            {"id": "send", "type": "send_chat_message", "config": {"message": "Manual workflow result"}},
            {"id": "end", "type": "end", "config": {}},
        ],
        "edges": [{"from": "trigger", "to": "send"}, {"from": "send", "to": "end"}],
    }


def manual_app_skill_graph() -> dict[str, Any]:
    return {
        "version": 1,
        "trigger_node_id": "trigger",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "config": {}},
            {
                "id": "search",
                "type": "app_skill_action",
                "config": {
                    "app_id": "web",
                    "skill_id": "search",
                    "input": {"requests": [{"query": "workflow safety dependencies"}]},
                },
            },
            {"id": "send", "type": "send_chat_message", "config": {"message": "{{nodes.search.output.summary}}"}},
            {"id": "end", "type": "end", "config": {}},
        ],
        "edges": [{"from": "trigger", "to": "search"}, {"from": "search", "to": "send"}, {"from": "send", "to": "end"}],
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
# contract-test: supporting surface=rest_api assertions=workflows.execution.lifecycle-visible,workflows.access.boundaries
async def test_manual_route_accepts_a_pinned_run_before_dispatch_and_hides_scheduler_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    service = workflow_service(repository=InMemoryWorkflowRepository())
    workflow = service.create_workflow("alice", "Manual", manual_graph(), enabled=False)
    assert workflow.enabled is False
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
    invocation = {"source_chat_id": None, "message_destination_overrides": {}, "return_outputs": {}, "input": {}}
    invocation_ref = runtime.calls[0][1]["encrypted_invocation_ref"]
    assert service._load_encrypted_blob(invocation_ref, "test-vault-key") == invocation
    assert runtime.calls == [
        (
            "accept_manual_run",
            {
                "workflow_id": workflow.id,
                "hashed_user_id": service.repository.workflow_owner_hash("alice"),
                "trigger_type": "test",
                "idempotency_key": "request-1",
                "encrypted_invocation_ref": invocation_ref,
                "invocation_hash": hashlib.sha256(json.dumps(invocation, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest(),
            },
        )
    ]
    assert dispatcher.calls == [(workflow.id, "alice", "run-accepted", "version-pinned", "test", {}, invocation)]
    assert response["run"]["status"] == "queued"
    assert response["run"]["version_id"] == "version-pinned"
    assert "owner_user_id" not in response["run"]


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=workflows.execution.lifecycle-visible,workflows.access.boundaries
async def test_manual_route_rejects_an_absent_idempotency_key_before_runtime_acceptance() -> None:
    service = workflow_service(repository=InMemoryWorkflowRepository())
    workflow = service.create_workflow("alice", "Manual", manual_graph(), enabled=False)
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
# contract-test: supporting surface=rest_api assertions=workflows.execution.lifecycle-visible,workflows.access.boundaries
async def test_manual_route_requeues_an_existing_accepted_queued_run(monkeypatch: pytest.MonkeyPatch) -> None:
    service = workflow_service(repository=InMemoryWorkflowRepository())
    workflow = service.create_workflow("alice", "Manual", manual_graph(), enabled=False)
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
    assert dispatcher.calls == [(workflow.id, "alice", "run-accepted", "version-pinned", "manual", {},
        {"source_chat_id": None, "message_destination_overrides": {}, "return_outputs": {}, "input": {}})]


class StartRejectedRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, operation: str, data: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((operation, data))
        return {"started": False, "run_id": "run-accepted", "workflow_id": "workflow-1", "version_id": "version-pinned", "status": "running"}


class StartAcceptedRuntime:
    def __init__(self, workflow_id: str, version_id: str) -> None:
        self.workflow_id = workflow_id
        self.version_id = version_id

    async def execute(self, operation: str, data: dict[str, Any]) -> dict[str, Any]:
        assert operation == "start_accepted_run"
        return {
            "started": True,
            "run_id": data["run_id"],
            "workflow_id": self.workflow_id,
            "version_id": self.version_id,
            "status": "running",
        }


class RecordingAppSkillAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any], str | None]] = []

    async def execute(
        self,
        app_id: str,
        skill_id: str,
        request: dict[str, Any],
        *,
        user_id: str | None = None,
        billing_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del billing_context
        self.calls.append((app_id, skill_id, request, user_id))
        return {"summary": "workflow app skill ok"}


@pytest.mark.anyio
@pytest.mark.parametrize("definition_fails", [False, True])
# contract-test: supporting surface=rest_api assertions=workflows.chat.embedded-lifecycle,workflows.chat.invocation
async def test_chat_definition_is_queued_before_workflow_effects(
    monkeypatch: pytest.MonkeyPatch, definition_fails: bool,
) -> None:
    from backend.core.api.app.services.workflow_models import WorkflowRunStatus

    events: list[str] = []
    accepted_run = SimpleNamespace(id="run-accepted", workflow_id="workflow-1")
    completed_run = SimpleNamespace(
        status=WorkflowRunStatus.COMPLETED,
        model_dump=lambda **kwargs: {"id": "run-accepted", "status": "completed"},
    )
    service = SimpleNamespace(
        repository=SimpleNamespace(workflow_owner_hash=lambda user_id: "owner-hash"),
        resolve_user_vault_key_id=lambda user_id: "vault-key",
        load_run_invocation=lambda *args: {"source_chat_id": "chat-1"},
        get_workflow_version=lambda *args: object(),
        get_run=lambda *args: accepted_run,
    )

    class Runner:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.action_adapter = self

        async def deliver_chat_definition(self, run: Any, user_id: str, invocation: dict[str, Any]) -> None:
            assert run is accepted_run
            assert invocation == {"source_chat_id": "chat-1"}
            events.append("definition")
            if definition_fails:
                raise RuntimeError("storage unavailable")

        async def run_workflow(self, *args: Any, **kwargs: Any) -> Any:
            events.append("effects")
            return completed_run

        async def deliver_caller_result(self, *args: Any) -> None:
            events.append("result")

    monkeypatch.setattr(workflow_tasks, "WorkflowRunner", Runner)
    execute = workflow_tasks.run_workflow_now(
        "workflow-1", "alice", "run-accepted", "version-pinned", "manual", {},
        workflow_service=service,
        runtime_service=StartAcceptedRuntime("workflow-1", "version-pinned"),
    )
    if definition_fails:
        with pytest.raises(workflow_tasks.WorkflowCallerDeliveryPending):
            await execute
        assert events == ["definition"]
    else:
        assert (await execute)["status"] == "completed"
        assert events == ["definition", "effects", "result"]


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=workflows.execution.lifecycle-visible,workflows.access.boundaries
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
            {"workflow_id": "workflow-1", "run_id": "run-accepted", "hashed_user_id": "owner-hash",
             "reclaim_after_seconds": workflow_tasks.WORKFLOW_ACTIVE_RUN_TIMEOUT_SECONDS + 60},
        )
    ]


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=workflows.execution.lifecycle-visible,workflows.access.boundaries
async def test_worker_uses_supplied_app_skill_adapter_for_accepted_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    service = workflow_service(repository=InMemoryWorkflowRepository())
    workflow = service.create_workflow("alice", "Manual app skill", manual_app_skill_graph(), enabled=False)
    adapter = RecordingAppSkillAdapter()
    delivered: list[tuple[str, str]] = []

    class MessageAdapter:
        async def send_chat_message(self, config: dict[str, Any], context: dict[str, Any], user_id: str) -> dict[str, Any]:
            delivered.append((context["nodes"]["search"]["output"]["summary"], user_id))
            return {"status": "completed", "chat_id": "test-chat"}

    monkeypatch.setattr(workflow_tasks, "WorkflowRunner", lambda service, **kwargs:
        WorkflowRunner(service, action_adapter=MessageAdapter(), **kwargs))
    service.repository.save_run(
        {
            "id": "run-accepted",
            "workflow_id": workflow.id,
            "version_id": workflow.current_version_id,
            "owner_hash": service.repository.workflow_owner_hash("alice"),
            "trigger_type": "manual",
            "status": "queued",
        }
    )

    result = await workflow_tasks.run_workflow_now(
        workflow.id,
        "alice",
        "run-accepted",
        workflow.current_version_id,
        "manual",
        {},
        workflow_service=service,
        runtime_service=StartAcceptedRuntime(workflow.id, workflow.current_version_id),
        app_skill_adapter=adapter,
    )

    assert result["status"] == "completed"
    assert delivered == [("workflow app skill ok", "alice")]
    assert adapter.calls == [
        (
            "web",
            "search",
            {"requests": [{"query": "workflow safety dependencies"}]},
            "alice",
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
            {"id": "send", "type": "send_chat_message", "config": {"message": "Weather report"}},
            {"id": "end", "type": "end", "config": {}},
        ],
        "edges": [{"from": "trigger", "to": "weather"}, {"from": "weather", "to": "send"}, {"from": "send", "to": "end"}],
    }


# contract-test: supporting surface=rest_api assertions=workflows.execution.lifecycle-visible,workflows.access.boundaries
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


# contract-test: supporting surface=rest_api assertions=workflows.execution.lifecycle-visible,workflows.access.boundaries
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
# contract-test: supporting surface=rest_api assertions=workflows.execution.lifecycle-visible,workflows.access.boundaries
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
# contract-test: supporting surface=rest_api assertions=workflows.execution.lifecycle-visible,workflows.access.boundaries
async def test_runner_rejects_manual_execution_without_a_durable_pinned_run() -> None:
    service = workflow_service(repository=InMemoryWorkflowRepository())
    workflow = service.create_workflow("alice", "Manual", manual_graph())

    with pytest.raises(ValueError, match="must be accepted"):
        await WorkflowRunner(service).run_workflow(workflow, "alice", trigger_type="manual")


# contract-test: supporting surface=rest_api assertions=workflows.execution.lifecycle-visible,workflows.access.boundaries
def test_trigger_owner_id_is_persisted_internally_but_not_returned_to_service_callers() -> None:
    repository = InMemoryWorkflowRepository()
    service = workflow_service(repository=repository)
    workflow = service.create_workflow("alice", "Manual", manual_graph())

    trigger = repository.get_trigger_for_workflow(workflow.id, "alice")

    assert trigger is not None
    assert "owner_user_id" not in trigger
    assert repository.triggers[trigger["trigger_id"]]["owner_user_id"] == "alice"
