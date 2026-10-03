"""Chat-owned one-time workflow and owner-scoped invocation contracts."""

from __future__ import annotations

from types import SimpleNamespace
import time

import pytest
from fastapi import HTTPException

from backend.core.api.app.routes import workflows as workflow_routes
from backend.core.api.app.routes.workflows import WorkflowRunOnceRequest, WorkflowRunRequest, _validated_invocation
from backend.core.api.app.services.workflow_models import WorkflowGraph, WorkflowLifecycle
from backend.core.api.app.services.workflow_action_adapter import WorkflowActionAdapter
from backend.core.api.app.services import workflow_action_adapter as workflow_action_adapter_module
from backend.core.api.app.services.workflow_assistant_service import WorkflowAssistantService
from backend.core.api.app.services.workflow_chat_delivery_service import WorkflowChatDeliveryService
from backend.core.api.app.services.workflow_models import WorkflowRunDetail
from backend.core.api.app.services.workflow_service import InMemoryWorkflowRepository, validate_workflow_return_outputs
from backend.tests.workflow_test_utils import workflow_service


def _manual_graph() -> dict:
    return {"version": 1, "trigger_node_id": "trigger", "nodes": [
        {"id": "trigger", "type": "manual_trigger", "config": {}},
        {"id": "send", "type": "send_chat_message", "config": {"message": "Done", "chat_id": "chat-original"}},
        {"id": "end", "type": "end", "config": {}},
    ], "edges": [{"from": "trigger", "to": "send"}, {"from": "send", "to": "end"}]}


def _caller_return_graph() -> dict:
    """Exact no-Send For-each shape used by the composition E2E."""
    return {"version": 2, "trigger_node_id": "start", "nodes": [
        {"id": "start", "type": "manual_trigger", "config": {"required_start_input_schema": {
            "type": "object", "required": ["results"], "properties": {"results": {
                "type": "array", "items": {"type": "object", "properties": {"keep": {"type": "boolean"}},
                                            "required": ["keep"]},
            }},
        }}},
        {"id": "loop", "type": "for_each", "config": {"items": "trigger.results", "max_items": 3}},
        {"id": "check", "type": "check", "config": {"mode": "exact", "predicate": {
            "left": "$items.loop.item.keep", "op": "eq", "right": True,
        }}},
    ], "edges": [{"from": "start", "to": "loop"}, {"from": "loop", "to": "check", "branch": "body"}]}


# contract-test: supporting surface=rest_api assertions=workflows.chat.result-return,workflows.control.for-each
def test_caller_return_projection_requires_declared_reachable_output_and_type() -> None:
    graph = WorkflowGraph.model_validate(_caller_return_graph())
    valid = {"processed": {"ref": "$nodes.loop.output.completed_count", "type": "integer"}}
    validate_workflow_return_outputs(graph, valid)
    for ref, value_type, error in (
        ("$nodes.loop.output.nonexistent", "integer", "not declared"),
        ("$nodes.loop.output.completed_count", "string", "selected type does not match"),
        ("$nodes.check.output.matched", "boolean", "For each aggregate"),
    ):
        with pytest.raises(ValueError, match=error):
            validate_workflow_return_outputs(graph, {"processed": {"ref": ref, "type": value_type}})


# contract-test: supporting surface=rest_api assertions=workflows.chat.result-return,workflows.access.boundaries
def test_caller_return_projection_uses_unique_root_for_triggerless_workflow() -> None:
    send = {"id": "send", "type": "send_chat_message", "config": {"chat_id": "chat-1", "message": "Done"}}
    selected = {"message": {"ref": "$nodes.send.output.message", "type": "string"}}
    single_root = WorkflowGraph.model_validate({
        "version": 1, "nodes": [send, {"id": "end", "type": "end", "config": {}}],
        "edges": [{"from": "send", "to": "end"}],
    })
    validate_workflow_return_outputs(single_root, selected)

    ambiguous = WorkflowGraph.model_validate({
        "version": 1, "nodes": [send, {"id": "other", "type": "end", "config": {}}],
        "edges": [],
    })
    with pytest.raises(ValueError, match="reachable graph node"):
        validate_workflow_return_outputs(ambiguous, selected)


# contract-test: supporting surface=rest_api assertions=workflows.access.boundaries,workflows.content.encrypted-retained
def test_chat_embed_has_no_deadline_and_copy_is_independent() -> None:
    service = workflow_service(repository=InMemoryWorkflowRepository())
    chat = service.create_workflow("alice", "One-off", _manual_graph(), lifecycle=WorkflowLifecycle.CHAT_EMBED,
                                   source_chat_id="chat-1", source="chat_run_once")
    assert chat.auto_delete_at is None
    assert chat.enabled is False
    assert service.list_workflows("alice") == []
    assert service.list_temporary_workflows("alice") == []
    saved = service.save_chat_embed_as_reusable(chat.id, "alice", "save-click-1")
    assert saved.id != chat.id
    assert saved.lifecycle == WorkflowLifecycle.PERSISTED
    assert saved.source_chat_id is None
    assert saved.graph == chat.graph
    assert service.save_chat_embed_as_reusable(chat.id, "alice", "save-click-1").id == saved.id
    assert service.cleanup_chat_owned_workflows("alice", "chat-1") == 1
    assert service.cleanup_chat_owned_workflows("alice", "chat-1") == 0
    assert service.get_workflow(saved.id, "alice").id == saved.id


# contract-test: supporting surface=rest_api assertions=workflows.access.boundaries
def test_chat_embed_rejects_schedule_expiry_and_mutation() -> None:
    service = workflow_service(repository=InMemoryWorkflowRepository())
    with pytest.raises(ValueError, match="source chat"):
        service.create_workflow("alice", "Missing", _manual_graph(), lifecycle="chat_embed")
    with pytest.raises(ValueError, match="expiry"):
        service.create_workflow("alice", "Expiring", _manual_graph(), lifecycle="chat_embed",
                                source_chat_id="chat-1", auto_delete_at=1)
    chat = service.create_workflow("alice", "Fixed", _manual_graph(), lifecycle="chat_embed", source_chat_id="chat-1")
    with pytest.raises(ValueError, match="immutable"):
        service.update_workflow(chat.id, "alice", title="Changed")


class _Chat:
    async def check_chat_ownership(self, chat_id: str, user_id: str) -> bool:
        return user_id == "alice" and chat_id in {"chat-1", "chat-2"}


# contract-test: supporting surface=rest_api assertions=workflows.access.boundaries,workflows.execution.lifecycle-visible
@pytest.mark.anyio
async def test_invocation_validates_selected_send_node_and_all_chat_owners() -> None:
    graph = WorkflowGraph.model_validate(_manual_graph())
    directus = SimpleNamespace(chat=_Chat())
    request = SimpleNamespace(state=SimpleNamespace(auth_source="session"))
    body = WorkflowRunRequest(
        source_chat_id="chat-1", message_destination_overrides={"send": "chat-2"},
        return_outputs={"result": {"ref": "$nodes.send.output.message", "type": "string"}},
    )
    invocation = await _validated_invocation(request, body, graph, "alice", directus)
    assert invocation["message_destination_overrides"] == {"send": "chat-2"}
    with pytest.raises(ValueError, match="Send node"):
        await _validated_invocation(request, body.model_copy(update={"message_destination_overrides": {"end": "chat-2"}}), graph, "alice", directus)
    with pytest.raises(HTTPException) as exc:
        await _validated_invocation(request, body.model_copy(update={"message_destination_overrides": {"send": "bob-chat"}}), graph, "alice", directus)
    assert exc.value.status_code == 403


# contract-test: supporting surface=rest_api assertions=workflows.content.encrypted-retained,workflows.access.boundaries
@pytest.mark.anyio
async def test_accepted_run_stores_only_encrypted_invocation_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    service = workflow_service(repository=InMemoryWorkflowRepository())
    workflow = service.create_workflow("alice", "Run", _manual_graph())
    accepted: list[dict] = []
    dispatched: list[tuple] = []

    class _Runtime:
        async def execute(self, operation: str, data: dict) -> dict:
            assert operation == "accept_manual_run"
            accepted.append(data)
            return {"accepted": True, "run_id": "run-1", "version_id": workflow.current_version_id, "status": "queued"}

    monkeypatch.setattr(workflow_routes, "_dispatch_accepted_workflow_run", lambda *args: dispatched.append(args))
    request = SimpleNamespace(state=SimpleNamespace(auth_source="session"), headers={"Idempotency-Key": "run-click-1"})
    body = WorkflowRunRequest(source_chat_id="chat-1", message_destination_overrides={"send": "chat-2"})
    result = await workflow_routes._accept_workflow_run(
        workflow.id, body, request, SimpleNamespace(id="alice", vault_key_id=None),
        service, _Runtime(), SimpleNamespace(chat=_Chat()), workflow,
    )
    assert result["id"] == "run-1"
    assert accepted[0]["encrypted_invocation_ref"].startswith("vault://workflows/workflow_run_invocation/")
    assert "chat-1" not in str(accepted[0])
    assert dispatched[0][-1]["source_chat_id"] == "chat-1"


# contract-test: supporting surface=rest_api assertions=workflows.chat.invocation,workflows.chat.result-return,workflows.control.for-each
@pytest.mark.anyio
async def test_run_once_accepts_no_send_graph_only_with_validated_return_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    service = workflow_service(repository=InMemoryWorkflowRepository())
    dispatched: list[tuple] = []
    accepted: list[dict] = []

    class _Runtime:
        async def execute(self, operation: str, data: dict) -> dict:
            assert operation == "accept_manual_run"
            accepted.append(data)
            record = service.repository.get_workflow(data["workflow_id"], "alice")
            return {"accepted": True, "run_id": "run-1", "version_id": record["current_version_id"], "status": "queued"}

    monkeypatch.setattr(workflow_routes, "_dispatch_accepted_workflow_run", lambda *args: dispatched.append(args))
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace()),
        state=SimpleNamespace(auth_source="session"),
        headers={"Idempotency-Key": "once"},
    )
    user = SimpleNamespace(id="alice", vault_key_id=None)
    body = WorkflowRunOnceRequest(
        title="Chat-owned list", graph=_caller_return_graph(), source_chat_id="chat-1",
        input={"results": [{"keep": True}, {"keep": False}, {"keep": True}]},
        return_outputs={"processed": {"ref": "$nodes.loop.output.completed_count", "type": "integer"}},
    )
    with pytest.raises(HTTPException) as exc:
        await workflow_routes.run_workflow_once(
            body.model_copy(update={"return_outputs": {}}), request, user, service, _Runtime(),
            SimpleNamespace(chat=_Chat()))
    assert exc.value.status_code == 400
    assert exc.value.detail == "Workflow readiness requires a reachable qualifying effect"
    result = await workflow_routes.run_workflow_once(
        body, request, user, service, _Runtime(), SimpleNamespace(chat=_Chat()))
    assert result["workflow"]["lifecycle"] == "chat_embed"
    assert result["run"]["status"] == "queued"
    assert len(accepted) == 1
    assert dispatched[0][-1]["return_outputs"] == body.return_outputs


# contract-test: supporting surface=rest_api assertions=workflows.chat.result-return,workflows.control.for-each
@pytest.mark.anyio
@pytest.mark.parametrize("newly_accepted", [True, False])
async def test_assistant_countdown_accepts_no_send_only_with_validated_caller_projection(
    newly_accepted: bool, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.core.api.app.tasks import workflow_assistant_tasks, workflow_tasks

    service = workflow_service(repository=InMemoryWorkflowRepository())
    workflow = service.create_workflow("alice", "Chat list", _caller_return_graph())
    assistant = WorkflowAssistantService(service, enqueue_run_after_countdown=lambda *_: None)
    input_payload = {"results": [{"keep": True}, {"keep": False}]}
    projection = {"processed": {"ref": "$nodes.loop.output.completed_count", "type": "integer"}}

    with pytest.raises(ValueError, match="reachable qualifying effect"):
        assistant.create_pending_run("alice", workflow.id, input_payload, invocation={"source_chat_id": "chat-1"})
    with pytest.raises(ValueError, match="graph node output"):
        assistant.create_pending_run("alice", workflow.id, input_payload, invocation={"return_outputs": {
            "processed": {"ref": "$nodes.missing.output.completed_count", "type": "integer"},
        }})
    pending = assistant.create_pending_run(
        "alice", workflow.id, input_payload,
        invocation={"source_chat_id": "chat-1", "return_outputs": projection},
    )
    dispatched: list[tuple] = []
    monkeypatch.setattr(workflow_tasks.run_workflow_task, "delay", lambda *args: dispatched.append(args))

    class _Runtime:
        _directus = SimpleNamespace(chat=_Chat())

        async def execute(self, operation: str, data: dict) -> dict:
            assert operation == "accept_manual_run"
            assert data["encrypted_invocation_ref"].startswith("vault://workflows/workflow_run_invocation/")
            return {"accepted": newly_accepted, "run_id": "run-1", "version_id": workflow.current_version_id, "status": "queued"}

    completed = await assistant.execute_after_countdown(
        "alice", pending["proposal_id"], _Runtime(), workflow_assistant_tasks._enqueue_accepted_workflow_run,
        now=pending["countdown_ends_at"],
    )
    assert completed["status"] == "approved"
    assert dispatched[0][:6] == (workflow.id, "alice", "run-1", workflow.current_version_id, "manual", input_payload)
    assert dispatched[0][-1]["return_outputs"] == projection
    assert dispatched[0][-1]["source_chat_id"] == "chat-1"


# contract-test: supporting surface=rest_api assertions=workflows.chat-delivery.client-encrypted,workflows.chat.embedded-lifecycle,workflows.execution.lifecycle-visible
@pytest.mark.anyio
async def test_caller_terminal_delivery_is_owner_checked_and_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    workflow_owner = workflow_service(repository=InMemoryWorkflowRepository())
    definition = workflow_owner.create_workflow("alice", "One-off", _manual_graph(), lifecycle="chat_embed", source_chat_id="chat-1")
    class _Cipher:
        def encrypt_delivery(self, *, owner_id: str, delivery_id: str, payload: dict) -> str:
            assert owner_id == "alice"
            if payload["title"] == "Workflow definition":
                assert "[!](embed:" in payload["message"]
                assert "View workflow run" in payload["message"]
                assert payload["embeds"][0]["content_type"] == "workflows-workflow"
                assert payload["embeds"][0]["content"]["graph"] == definition.graph.model_dump(mode="json", by_alias=True)
                assert payload["embeds"][0]["content"]["lifecycle"] == "chat_embed"
                assert payload["embeds"][0]["content"]["run_id"] == "run-1"
            else:
                assert payload["title"] == "Workflow result"
                assert "count" in payload["message"]
                assert payload.get("embeds", []) == []
            return f"encrypted:{delivery_id}"

    class _Closable:
        async def close(self) -> None:
            pass

    current_time = [int(time.time())]
    chat_service = WorkflowChatDeliveryService(cipher=_Cipher(), clock=lambda: current_time[0])
    adapter = WorkflowActionAdapter(chat_delivery_service=chat_service, workflow_service=workflow_owner)
    monkeypatch.setattr(adapter, "_get_cache_service", lambda: _Closable())
    monkeypatch.setattr(adapter, "_get_directus_service", lambda cache: SimpleNamespace(chat=_Chat(), close=_Closable().close))
    run = WorkflowRunDetail(id="run-1", workflow_id=definition.id, version_id=definition.current_version_id,
                            trigger_type="manual", status="completed",
                            output_summary={"returned_outputs": {"count": {"type": "integer", "value": 2}}})
    first = await adapter.deliver_caller_result(run, "alice", {"source_chat_id": "chat-1"})
    second = await adapter.deliver_caller_result(run, "alice", {"source_chat_id": "chat-1"})
    assert first == second
    assert first["chat_id"] == "chat-1"
    assert first["status"] == "delivery_pending"
    pending = chat_service.list_pending_for_owner(owner_id="alice")
    assert len(pending) == 2
    definition_delivery = next(item for item in pending if item.node_id == "__chat_definition__")
    assert definition_delivery.run_id is None
    assert definition_delivery.expires_at is None
    assert next(item for item in pending if item.node_id == "__caller_result__").expires_at is not None
    current_time[0] += 8 * 86400
    assert [item.delivery_id for item in chat_service.list_pending_for_owner(owner_id="alice")] == [definition_delivery.delivery_id]


# contract-test: supporting surface=rest_api assertions=workflows.chat.result-return,workflows.chat-delivery.claim-fenced
@pytest.mark.anyio
async def test_production_caller_delivery_queues_result_and_retries_with_stable_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    service = workflow_service(repository=InMemoryWorkflowRepository())
    definition = service.create_workflow("alice", "One-off", _manual_graph(), lifecycle="chat_embed", source_chat_id="chat-1")
    now = [int(time.time())]
    chat_service = WorkflowChatDeliveryService(cipher=SimpleNamespace(), clock=lambda: now[0])
    adapter = WorkflowActionAdapter(workflow_service=service)
    encrypted: list[dict] = []

    class _Closable:
        async def close(self) -> None:
            pass

    async def encrypt(**payload: dict) -> str:
        encrypted.append(payload)
        return f"encrypted:{len(encrypted)}"

    async def publish(**_kwargs: object) -> None:
        pass

    monkeypatch.setattr(adapter, "_get_cache_service", lambda: _Closable())
    monkeypatch.setattr(adapter, "_get_directus_service", lambda cache: SimpleNamespace(chat=_Chat(), close=_Closable().close))
    monkeypatch.setattr(adapter, "_get_chat_delivery_service", lambda: chat_service)
    monkeypatch.setattr(adapter, "_encrypt_chat_delivery_payload", encrypt)
    monkeypatch.setattr(adapter, "_publish_workflow_chat_delivery_available", publish)
    monkeypatch.setattr(workflow_action_adapter_module, "time", SimpleNamespace(time=lambda: now[0]))
    run = WorkflowRunDetail(
        id="run-1", workflow_id=definition.id, version_id=definition.current_version_id,
        trigger_type="manual", status="completed", finished_at=now[0],
        output_summary={"returned_outputs": {"status": "completed", "values": {
            "processed": {"ref": "$nodes.loop.output.completed_count", "type": "integer", "value": 3},
        }}},
    )
    first = await adapter.deliver_caller_result(run, "alice", {"source_chat_id": "chat-1"})
    now[0] += 61
    retried = await adapter.deliver_caller_result(run, "alice", {"source_chat_id": "chat-1"})
    assert first == retried
    assert len(chat_service.list_pending_for_owner(owner_id="alice")) == 2
    assert "processed: 3" in next(payload["message"] for payload in encrypted if payload["title"] == "Workflow result")
