# backend/tests/test_workflow_assistant_countdown.py
#
# Focused contracts for owner-scoped assistant workflow drafts and run countdowns.
# Draft mutations remain encrypted until the user saves them, while assistant
# runs advance through the existing accepted-run handoff after cancellation time.
#

import asyncio

import pytest

from backend.core.api.app.services.workflow_assistant_service import (
    WorkflowAssistantDeleteConfirmationRequiredError,
    WorkflowAssistantProposalNotPendingError,
    WorkflowAssistantService,
)
from backend.core.api.app.services.workflow_service import WorkflowNotFoundError
from backend.tests.test_workflow_assistant_and_events import manual_input_graph, one_time_weather_graph
from backend.tests.workflow_test_utils import workflow_service


def test_assistant_create_draft_is_previewable_saveable_and_undoable() -> None:
    service = workflow_service()
    assistant = WorkflowAssistantService(service)

    proposal = assistant.schedule_once("alice", "Tomorrow weather", one_time_weather_graph())

    preview = assistant.get_draft_preview("alice", proposal["proposal_id"])
    assert preview["preview"]["title"] == "Tomorrow weather"
    assert preview["preview"]["graph"] == one_time_weather_graph()
    assert service.list_temporary_workflows("alice") == []

    saved = asyncio.run(assistant.save("alice", proposal["proposal_id"]))
    assert saved["status"] == "approved"
    assert service.list_temporary_workflows("alice")[0].title == "Tomorrow weather"

    discarded = assistant.schedule_once("alice", "Discarded weather", one_time_weather_graph())
    assert assistant.cancel_pending("alice", discarded["proposal_id"]) is True
    assert service.list_temporary_workflows("alice")[0].title == "Tomorrow weather"


def test_assistant_update_draft_does_not_persist_until_saved() -> None:
    service = workflow_service()
    workflow = service.create_workflow("alice", "Original weather", one_time_weather_graph())
    assistant = WorkflowAssistantService(service)

    proposal = assistant.propose_update("alice", workflow.id, {"title": "Updated weather"})

    preview = assistant.get_draft_preview("alice", proposal["proposal_id"])
    assert preview["preview"]["title"] == "Updated weather"
    assert service.get_workflow(workflow.id, "alice").title == "Original weather"

    asyncio.run(assistant.save("alice", proposal["proposal_id"]))
    assert service.get_workflow(workflow.id, "alice").title == "Updated weather"


def test_assistant_delete_requires_explicit_confirmation() -> None:
    service = workflow_service()
    workflow = service.create_workflow("alice", "Delete weather", one_time_weather_graph())
    assistant = WorkflowAssistantService(service)
    proposal = assistant.propose_delete("alice", workflow.id)

    with pytest.raises(WorkflowAssistantDeleteConfirmationRequiredError):
        asyncio.run(assistant.save("alice", proposal["proposal_id"]))
    assert service.get_workflow(workflow.id, "alice").id == workflow.id

    asyncio.run(assistant.confirm_delete("alice", proposal["proposal_id"]))
    with pytest.raises(WorkflowNotFoundError):
        service.get_workflow(workflow.id, "alice")


def test_assistant_run_uses_durable_countdown_before_accepted_run_handoff() -> None:
    service = workflow_service()
    workflow = service.create_workflow("alice", "Manual city workflow", manual_input_graph())
    scheduled: list[tuple[str, str]] = []
    dispatched: list[tuple] = []
    assistant = WorkflowAssistantService(
        service,
        enqueue_run_after_countdown=lambda user_id, proposal_id: scheduled.append((user_id, proposal_id)),
    )
    proposal = assistant.create_pending_run("alice", workflow.id, {"city": "Berlin"})

    assert scheduled == [("alice", proposal["proposal_id"])]
    assert proposal["countdown_ends_at"] == proposal["created_at"] + 6
    assert proposal["requires_approval"] is False

    class FakeRuntime:
        async def execute(self, operation: str, data: dict) -> dict:
            assert operation == "accept_manual_run"
            assert data["idempotency_key"] == proposal["proposal_id"]
            return {"run_id": "run-1", "version_id": workflow.current_version_id, "status": "queued"}

    with pytest.raises(ValueError, match="start automatically"):
        asyncio.run(assistant.save("alice", proposal["proposal_id"]))

    with pytest.raises(WorkflowAssistantProposalNotPendingError, match="countdown has not finished"):
        asyncio.run(
            assistant.execute_after_countdown(
                "alice",
                proposal["proposal_id"],
                runtime_service=FakeRuntime(),
                enqueue_accepted_run=lambda *_: None,
                now=proposal["created_at"],
            )
        )

    completed = asyncio.run(
        assistant.execute_after_countdown(
            "alice",
            proposal["proposal_id"],
            runtime_service=FakeRuntime(),
            enqueue_accepted_run=lambda *args: dispatched.append(args),
            now=proposal["countdown_ends_at"],
        )
    )
    assert completed["status"] == "approved"
    assert dispatched == [(workflow.id, "alice", "run-1", workflow.current_version_id, "manual", {"city": "Berlin"})]
