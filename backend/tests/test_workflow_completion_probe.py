"""Probe assertions for isolated scheduled-completion notification evidence."""

from __future__ import annotations

import pytest

from backend.core.api.app.services.workflow_models import (
    WorkflowNodeRun, WorkflowNodeRunStatus, WorkflowNodeType,
    WorkflowRunContentStorage, WorkflowRunDetail, WorkflowRunStatus,
)
from backend.scripts import probe_workflow_completion_notification as probe


def _row(message_id: str) -> dict[str, str]:
    return {"workflow_id": "workflow-1", "run_id": "run-1", "chat_id": "chat-" + message_id,
            "message_id": message_id, "delivery_id": "delivery-" + message_id}


# contract-test: supporting surface=rest_api assertions=notifications.workflow-run.chat-target,notifications.delivery.idempotent
def test_mail_selection_ignores_previous_messages_but_rejects_current_duplicates() -> None:
    current = [_row("current-one"), _row("current-two")]
    earlier = _row("earlier")
    messages = [{"HTML": f'<a href="{probe.message_url(row)}">Open chat</a>'} for row in [earlier, *current]]
    assert set(probe._current_message_emails(messages, current)) == {"current-one", "current-two"}
    with pytest.raises(AssertionError, match="current-one.*found 2"):
        probe._current_message_emails([*messages, messages[1]], current)
    with pytest.raises(AssertionError, match="current-two.*found 0"):
        probe._current_message_emails(messages[:2], current)
    wrong = {"HTML": f'<a href="{probe.message_url(current[0])}&chat-id=wrong">Open chat</a>'}
    with pytest.raises(AssertionError, match="wrong target"):
        probe._current_message_emails([messages[2], wrong], current)


def _pruned_run() -> WorkflowRunDetail:
    delivery = {
        "type": "send_chat_message", "status": "delivery_pending",
        "delivery_id": "delivery-1", "chat_id": "chat-1", "message_id": "message-1",
        "client_persisted": False, "delivered_result_count": 0, "pending_result_count": 1,
    }
    second = {**delivery, "delivery_id": "delivery-2", "chat_id": "chat-2", "message_id": "message-2"}
    return WorkflowRunDetail(
        id="run-1", workflow_id="workflow-1", version_id="version-1",
        trigger_type="schedule", status=WorkflowRunStatus.COMPLETED,
        content_available=False, content_storage=WorkflowRunContentStorage.DELETED,
        node_runs=[WorkflowNodeRun(
            id="node-run-1", run_id="run-1", workflow_id="workflow-1", node_id="send",
            node_type=WorkflowNodeType.SEND_CHAT_MESSAGE, status=WorkflowNodeRunStatus.COMPLETED,
            output_summary=delivery,
        ), WorkflowNodeRun(
            id="node-run-2", run_id="run-1", workflow_id="workflow-1", node_id="send-second",
            node_type=WorkflowNodeType.SEND_CHAT_MESSAGE, status=WorkflowNodeRunStatus.COMPLETED,
            output_summary=second,
        )],
        output_summary={"deliveries": {"send": delivery, "send-second": second}},
    )


def _expected_targets() -> list[dict[str, str]]:
    return [{"workflow_id": "workflow-1", "run_id": "run-1", "delivery_id": f"delivery-{number}",
             "chat_id": f"chat-{number}", "message_id": f"message-{number}"} for number in (1, 2)]


# contract-test: supporting surface=rest_api assertions=notifications.workflow-run.chat-target,notifications.content.privacy-boundary
def test_pruned_run_allows_routing_metadata_but_rejects_private_content() -> None:
    run = _pruned_run()
    probe._assert_pruned_run_metadata(run, ("Private workflow title", "Private result"), _expected_targets())

    leaked_action = run.model_copy(deep=True)
    leaked_action.node_runs[0].output_summary["message"] = "Private result"
    with pytest.raises(AssertionError):
        probe._assert_pruned_run_metadata(leaked_action, ("Private workflow title", "Private result"), _expected_targets())

    leaked_title = run.model_copy(deep=True)
    leaked_title.node_runs[0].skipped_reason = "Private workflow title"
    with pytest.raises(AssertionError):
        probe._assert_pruned_run_metadata(leaked_title, ("Private workflow title", "Private result"), _expected_targets())

    retained_cipher_ref = run.model_copy(update={"encrypted_content_ref": "vault://secret"})
    with pytest.raises(AssertionError):
        probe._assert_pruned_run_metadata(retained_cipher_ref, ("Private workflow title", "Private result"), _expected_targets())


# contract-test: supporting surface=rest_api assertions=notifications.workflow-run.chat-target,notifications.content.privacy-boundary
@pytest.mark.parametrize("defect", ["empty", "missing", "extra", "wrong_tuple", "missing_send_node", "wrong_send_tuple"])
def test_pruning_proof_requires_both_exact_targets_and_completed_send_nodes(defect: str) -> None:
    run = _pruned_run()
    deliveries = run.output_summary["deliveries"]
    if defect == "empty":
        deliveries.clear()
        run.node_runs.clear()
    elif defect == "missing":
        deliveries.pop("send-second")
        run.node_runs.pop()
    elif defect == "extra":
        deliveries["unexpected"] = dict(deliveries["send"])
    elif defect == "wrong_tuple":
        deliveries["send-second"]["message_id"] = "foreign-message"
        run.node_runs[1].output_summary["message_id"] = "foreign-message"
    elif defect == "missing_send_node":
        run.node_runs.pop()
    elif defect == "wrong_send_tuple":
        run.node_runs[1].output_summary = {**run.node_runs[1].output_summary, "chat_id": "foreign-chat"}
    with pytest.raises(AssertionError):
        probe._assert_pruned_run_metadata(run, (), _expected_targets())
