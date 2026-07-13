# backend/tests/test_workflow_ai_and_chat_actions.py
#
# Contracts for Workflow-native chat delivery and user-input waits. These keep
# the backend run semantics independent from the later web run-page UI.
#
# Spec: docs/specs/workflows-cli-runtime/spec.yml

import pytest

from backend.core.api.app.services.workflow_action_adapter import WorkflowActionAdapter
from backend.core.api.app.services.workflow_chat_delivery_service import WorkflowChatDeliveryService
from backend.core.api.app.services.workflow_models import WorkflowRunStatus
from backend.core.api.app.services.workflow_runner import WorkflowRunner
from backend.tests.workflow_test_utils import workflow_service


class FakeDeliveryCipher:
    def encrypt_delivery(self, *, owner_id: str, delivery_id: str, payload: dict[str, str]) -> str:
        del payload
        return f"ciphertext:{owner_id}:{delivery_id}"


def _base_graph(node: dict) -> dict:
    return {
        "version": 1,
        "trigger_node_id": "trigger",
        "nodes": [
            {"id": "trigger", "type": "schedule_trigger", "config": {"schedule": {"type": "daily", "time": "07:00", "timezone": "Europe/Berlin"}}},
            node,
        ],
        "edges": [{"from": "trigger", "to": node["id"]}],
    }


@pytest.mark.asyncio
async def test_send_chat_message_creates_pending_delivery_without_regular_chat_key() -> None:
    delivery_service = WorkflowChatDeliveryService(cipher=FakeDeliveryCipher())
    service = workflow_service()
    workflow = service.create_workflow(
        "alice",
        "Chat delivery",
        _base_graph({"id": "chat", "type": "start_new_chat", "config": {"title": "Workflow output", "message": "Rain is likely."}}),
        enabled=True,
    )

    run = await WorkflowRunner(
        service,
        action_adapter=WorkflowActionAdapter(chat_delivery_service=delivery_service),
    ).run_workflow(workflow, "alice", trigger_type="schedule")

    assert run.status == WorkflowRunStatus.COMPLETED
    output = run.node_runs[-1].output_summary
    assert output["status"] == "delivery_pending"
    delivery = delivery_service.get_delivery(delivery_id=output["delivery_id"], owner_id="alice")
    assert delivery.encrypted_payload.startswith("ciphertext:alice:")
    assert delivery.client_persistence is None


@pytest.mark.asyncio
async def test_send_chat_message_preserves_configured_existing_chat_id() -> None:
    delivery_service = WorkflowChatDeliveryService(cipher=FakeDeliveryCipher())
    service = workflow_service()
    workflow = service.create_workflow(
        "alice",
        "Existing chat delivery",
        _base_graph({"id": "chat", "type": "start_new_chat", "config": {"chat_id": "chat-existing", "title": "Existing", "message": "Rain is likely."}}),
        enabled=True,
    )

    run = await WorkflowRunner(
        service,
        action_adapter=WorkflowActionAdapter(chat_delivery_service=delivery_service),
    ).run_workflow(workflow, "alice", trigger_type="schedule")

    assert run.status == WorkflowRunStatus.COMPLETED
    output = run.node_runs[-1].output_summary
    assert output["chat_id"] == "chat-existing"
    delivery = delivery_service.get_delivery(delivery_id=output["delivery_id"], owner_id="alice")
    assert delivery.chat_id == "chat-existing"


@pytest.mark.asyncio
async def test_ask_for_user_input_pauses_run_as_waiting_with_prompt_metadata() -> None:
    service = workflow_service()
    workflow = service.create_workflow(
        "alice",
        "Input wait",
        _base_graph(
            {
                "id": "ask",
                "type": "ask_user",
                "config": {
                    "prompt": "Which city should I use?",
                    "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
                },
            }
        ),
        enabled=True,
    )

    run = await WorkflowRunner(service).run_workflow(workflow, "alice", trigger_type="schedule")

    assert run.status == WorkflowRunStatus.WAITING
    wait_output = run.node_runs[-1].output_summary
    assert wait_output["wait_for_user_input"] is True
    assert wait_output["prompt"] == "Which city should I use?"
    assert service.get_run(workflow.id, run.id, "alice").status == WorkflowRunStatus.WAITING
