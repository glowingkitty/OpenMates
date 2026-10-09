"""Probe assertions for isolated scheduled-completion notification evidence."""

from __future__ import annotations

import pytest

from backend.core.api.app.services.workflow_models import (
    WorkflowNodeRun, WorkflowNodeRunStatus, WorkflowNodeType,
    WorkflowRunContentStorage, WorkflowRunDetail, WorkflowRunStatus,
)
from backend.scripts import probe_workflow_completion_notification as probe


def _row(run_id: str) -> dict[str, str]:
    return {"workflow_id": "workflow-1", "run_id": run_id}


# contract-test: supporting surface=rest_api assertions=notifications.workflow-run.completed-delivery,notifications.delivery.idempotent
def test_mail_selection_ignores_previous_runs_but_rejects_current_duplicates() -> None:
    current = (_row("current-chat"), _row("current-run"))
    earlier = _row("earlier-run")
    prefix_collision = _row("current-chat-extra")
    messages = [
        {"HTML": f'<a href="{probe.completion_url(row)}">Open run</a>'}
        for row in (earlier, prefix_collision, *current)
    ]
    selected = probe._current_run_messages(messages, current)
    assert set(selected) == {"current-chat", "current-run"}
    with pytest.raises(AssertionError, match="current-chat.*found 2"):
        probe._current_run_messages([*messages, messages[2]], current)
    with pytest.raises(AssertionError, match="current-run.*found 0"):
        probe._current_run_messages(messages[:3], current)

    wrong_target = {"HTML": f'<a href="{probe.completion_url(current[0])}&chat-id=wrong">Open run</a>'}
    with pytest.raises(AssertionError, match="current-chat has the wrong target"):
        probe._current_run_messages([messages[3], wrong_target], current)
    with pytest.raises(AssertionError, match="current-chat.*found 2"):
        probe._current_run_messages([*messages, wrong_target], current)


def _pruned_run() -> WorkflowRunDetail:
    delivery = {
        "type": "send_chat_message", "status": "delivery_pending",
        "delivery_id": "delivery-1", "chat_id": "chat-1", "message_id": "message-1",
        "client_persisted": False, "delivered_result_count": 0, "pending_result_count": 1,
    }
    return WorkflowRunDetail(
        id="run-1", workflow_id="workflow-1", version_id="version-1",
        trigger_type="schedule", status=WorkflowRunStatus.COMPLETED,
        content_available=False, content_storage=WorkflowRunContentStorage.DELETED,
        node_runs=[WorkflowNodeRun(
            id="node-run-1", run_id="run-1", workflow_id="workflow-1", node_id="send",
            node_type=WorkflowNodeType.SEND_CHAT_MESSAGE, status=WorkflowNodeRunStatus.COMPLETED,
            output_summary=delivery,
        )],
        output_summary={"deliveries": {"send": delivery}},
    )


# contract-test: supporting surface=rest_api assertions=notifications.workflow-run.chat-target,notifications.content.privacy-boundary
def test_pruned_run_allows_routing_metadata_but_rejects_private_content() -> None:
    run = _pruned_run()
    probe._assert_pruned_run_metadata(run, ("Private workflow title", "Private result"))

    leaked_action = run.model_copy(deep=True)
    leaked_action.node_runs[0].output_summary["message"] = "Private result"
    with pytest.raises(AssertionError):
        probe._assert_pruned_run_metadata(leaked_action, ("Private workflow title", "Private result"))

    leaked_title = run.model_copy(deep=True)
    leaked_title.node_runs[0].skipped_reason = "Private workflow title"
    with pytest.raises(AssertionError):
        probe._assert_pruned_run_metadata(leaked_title, ("Private workflow title", "Private result"))

    retained_cipher_ref = run.model_copy(update={"encrypted_content_ref": "vault://secret"})
    with pytest.raises(AssertionError):
        probe._assert_pruned_run_metadata(retained_cipher_ref, ("Private workflow title", "Private result"))
