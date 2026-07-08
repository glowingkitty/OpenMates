"""Workflow input session contract tests.

These tests cover the Workflows-screen natural-language input architecture:
durable sessions, append-only events, stop/follow-up/undo, backend sanitization,
strict graph validation, and project workflow target ownership checks. The
planner is deterministic in tests; production can replace it with an LLM-backed
planner without changing the service/API contract.

Spec: docs/specs/workflows-v1/spec.yml
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.core.api.app.services.workflow_input_service import WorkflowInputEvent, WorkflowInputMutation, WorkflowInputService
from backend.tests.test_workflows_models import rain_graph
from backend.tests.workflow_test_utils import workflow_service


class QueuePlanner:
    def __init__(self, plans: list[dict[str, Any]]) -> None:
        self.plans = list(plans)
        self.seen_texts: list[str] = []

    def plan(self, *, text: str, context: dict[str, Any]) -> dict[str, Any]:
        self.seen_texts.append(text)
        assert "workflows" in context
        assert "projects" in context
        if not self.plans:
            raise AssertionError("Planner called without a queued plan")
        return self.plans.pop(0)


class FakeProjectLinker:
    def __init__(self) -> None:
        self.links: list[dict[str, Any]] = []

    def link_workflow(self, *, user_id: str, project_id: str, workflow_id: str, display_name: str) -> dict[str, Any]:
        item = {
            "project_item_id": f"item-{len(self.links) + 1}",
            "user_id": user_id,
            "project_id": project_id,
            "workflow_id": workflow_id,
            "display_name": display_name,
        }
        self.links.append(item)
        return item

    def unlink_project_item(self, project_item_id: str) -> bool:
        before = len(self.links)
        self.links = [item for item in self.links if item["project_item_id"] != project_item_id]
        return len(self.links) != before


class FakeWorkflowInputRepository:
    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, Any]] = {}
        self.events: list[WorkflowInputEvent] = []
        self.mutations: list[WorkflowInputMutation] = []

    def save_session(self, session: dict[str, Any]) -> None:
        self.sessions[session["id"]] = dict(session)

    def get_session(self, session_id: str, user_id: str) -> dict[str, Any] | None:
        session = self.sessions.get(session_id)
        if not session or session["user_id"] != user_id:
            return None
        return session

    def save_event(self, event: WorkflowInputEvent, user_id: str) -> None:
        del user_id
        self.events.append(event)

    def list_events(self, session_id: str, user_id: str, after_event_id: int = 0) -> list[WorkflowInputEvent]:
        session = self.get_session(session_id, user_id)
        if not session:
            return []
        return [event for event in self.events if event.session_id == session_id and event.event_id > after_event_id]

    def save_mutation(self, mutation: WorkflowInputMutation, session_id: str, user_id: str) -> None:
        del session_id, user_id
        self.mutations = [item for item in self.mutations if item.id != mutation.id]
        self.mutations.append(mutation)


def test_text_workflow_input_creates_durable_session_and_streams_events() -> None:
    service = workflow_service()
    planner = QueuePlanner([
        {
            "action": "create_workflow",
            "title": "Rain alert",
            "graph": rain_graph(),
            "enabled": True,
            "assumptions": ["Using push notification as the default alert channel."],
        }
    ])
    input_service = WorkflowInputService(workflow_service=service, planner=planner)

    result = input_service.start(user_id="alice", text="Tell me when it will rain")

    assert result.status == "executed"
    assert result.session_id
    assert result.workflow is not None
    assert result.workflow.title == "Rain alert"
    assert [workflow.title for workflow in service.list_workflows("alice")] == ["Rain alert"]
    assert [event.type for event in input_service.events(result.session_id)] == [
        "input_received",
        "planning_started",
        "assumption",
        "draft_node_added",
        "draft_node_added",
        "draft_node_added",
        "draft_node_added",
        "draft_node_added",
        "validation_passed",
        "committed",
    ]
    status = input_service.status(result.session_id)
    assert status.event_cursor == 10
    assert status.undo_available is True


def test_workflow_input_persists_session_events_and_mutations() -> None:
    service = workflow_service()
    repository = FakeWorkflowInputRepository()
    input_service = WorkflowInputService(
        workflow_service=service,
        planner=QueuePlanner([{"action": "create_workflow", "title": "Rain alert", "graph": rain_graph()}]),
        repository=repository,
    )

    result = input_service.start(user_id="alice", text="Tell me when it will rain")
    input_service._sessions.clear()

    assert repository.sessions[result.session_id]["status"] == "executed"
    assert [event.type for event in repository.events][-1] == "committed"
    assert repository.mutations[0].type == "create_workflow"
    assert input_service.status(result.session_id, user_id="alice").status == "executed"
    assert [event.event_id for event in input_service.events(result.session_id, after_event_id=8, user_id="alice")] == [9]


def test_workflow_input_sanitizes_ascii_smuggling_before_planner_use() -> None:
    service = workflow_service()
    planner = QueuePlanner([
        {
            "action": "needs_clarification",
            "message": "Which city should this workflow use?",
        }
    ])
    input_service = WorkflowInputService(workflow_service=service, planner=planner)
    hidden_tag_a = chr(0xE0061)

    result = input_service.start(user_id="alice", text=f"Create rain alert{hidden_tag_a}")

    assert result.status == "needs_clarification"
    assert planner.seen_texts == ["Create rain alert"]
    assert any(event.type == "input_sanitized" for event in input_service.events(result.session_id))


def test_invalid_generated_nodes_are_rejected_before_commit() -> None:
    invalid_graph = rain_graph()
    invalid_graph["nodes"].append({"id": "code", "type": "custom_code", "config": {"runtime": "python"}})
    service = workflow_service()
    input_service = WorkflowInputService(
        workflow_service=service,
        planner=QueuePlanner([{"action": "create_workflow", "title": "Unsafe", "graph": invalid_graph}]),
    )

    result = input_service.start(user_id="alice", text="Create a workflow with code")

    assert result.status == "failed"
    assert "future UI only" in (result.error or "")
    assert service.list_workflows("alice") == []
    assert [event.type for event in input_service.events(result.session_id)][-1] == "validation_failed"


def test_stop_followup_and_undo_are_session_scoped() -> None:
    service = workflow_service()
    planner = QueuePlanner([
        {"action": "draft", "draft_graph": rain_graph()},
        {"action": "create_workflow", "title": "Rain at 8", "graph": rain_graph(), "enabled": False},
    ])
    input_service = WorkflowInputService(workflow_service=service, planner=planner)

    draft = input_service.start(user_id="alice", text="Create a rain workflow")
    assert draft.status == "draft"
    stopped = input_service.stop(user_id="alice", session_id=draft.session_id)
    assert stopped.status == "stopped"
    assert service.list_workflows("alice") == []

    committed = input_service.follow_up(user_id="alice", session_id=draft.session_id, text="Actually run it at 8")
    assert committed.status == "executed"
    assert [workflow.title for workflow in service.list_workflows("alice")] == ["Rain at 8"]

    undone = input_service.undo(user_id="alice", session_id=draft.session_id)
    assert undone.status == "undone"
    assert service.list_workflows("alice") == []
    assert [event.type for event in input_service.events(draft.session_id)][-1] == "undone"


def test_project_workflow_linking_validates_workflow_ownership() -> None:
    service = workflow_service()
    alice_workflow = service.create_workflow("alice", "Alice rain", rain_graph())
    bob_workflow = service.create_workflow("bob", "Bob rain", rain_graph())
    linker = FakeProjectLinker()
    input_service = WorkflowInputService(
        workflow_service=service,
        planner=QueuePlanner([
            {
                "action": "link_workflow_to_project",
                "workflow_id": alice_workflow.id,
                "project_id": "project-1",
                "display_name": "Alice rain",
            },
            {
                "action": "link_workflow_to_project",
                "workflow_id": bob_workflow.id,
                "project_id": "project-1",
                "display_name": "Bob rain",
            },
        ]),
        project_linker=linker,
    )

    linked = input_service.start(user_id="alice", text="Add Alice rain to project")
    assert linked.status == "executed"
    assert linker.links[0]["workflow_id"] == alice_workflow.id

    rejected = input_service.start(user_id="alice", text="Add Bob rain to project")
    assert rejected.status == "failed"
    assert "not found" in (rejected.error or "").lower()
    assert len(linker.links) == 1


def test_audio_input_transcribes_before_planning() -> None:
    service = workflow_service()
    planner = QueuePlanner([
        {"action": "needs_clarification", "message": "What time should it run?"},
    ])
    input_service = WorkflowInputService(
        workflow_service=service,
        planner=planner,
        transcriber=lambda audio_ref: f"corrected transcript for {audio_ref['id']}",
    )

    result = input_service.start(user_id="alice", input_type="audio", audio_ref={"id": "audio-1"})

    assert result.status == "needs_clarification"
    assert planner.seen_texts == ["corrected transcript for audio-1"]
    assert [event.type for event in input_service.events(result.session_id)][:3] == [
        "transcribing_started",
        "transcript_ready",
        "input_received",
    ]


def test_wrong_user_cannot_stop_or_undo_a_session() -> None:
    input_service = WorkflowInputService(
        workflow_service=workflow_service(),
        planner=QueuePlanner([{"action": "draft", "draft_graph": rain_graph()}]),
    )
    draft = input_service.start(user_id="alice", text="Create a rain workflow")

    with pytest.raises(PermissionError):
        input_service.stop(user_id="bob", session_id=draft.session_id)

    with pytest.raises(PermissionError):
        input_service.undo(user_id="bob", session_id=draft.session_id)
