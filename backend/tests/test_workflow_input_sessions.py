"""Workflow input session contract tests.

These tests cover the Workflows-screen natural-language input architecture:
durable sessions, append-only events, stop/follow-up/undo, backend sanitization,
strict graph validation, and project workflow target ownership checks. The
planner is deterministic in tests; production can replace it with an LLM-backed
planner without changing the service/API contract.

Spec: docs/specs/workflows-v1/spec.yml
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import threading
import time
from typing import Any

import pytest
from pydantic import ValidationError

from backend.tests.runtime_import_stubs import install_code_route_import_stubs

install_code_route_import_stubs()

from backend.core.api.app.routes.workflows import WorkflowInputStartRequest  # noqa: E402
from backend.core.api.app.services.workflow_input_service import (  # noqa: E402
    WORKFLOW_INPUT_PLANNER_UNAVAILABLE,
    WORKFLOW_INPUT_SESSION_STATE_INVALID,
    WORKFLOW_INPUT_TRANSCRIPTION_UNAVAILABLE,
    DirectusWorkflowInputRepository,
    DragonflyWorkflowInputCheckpointStore,
    WorkflowInputEvent,
    WorkflowInputMutation,
    WorkflowInputService,
)
from backend.core.api.app.services.workflow_service import _hash_owner_id  # noqa: E402
from backend.core.api.app.services.directus.team_methods import TeamPermissionError  # noqa: E402
from backend.core.api.app.services.workflow_models import WorkflowGraph  # noqa: E402
from backend.tests.test_workflows_models import FakeDirectusClient, rain_graph  # noqa: E402
from backend.tests.workflow_test_utils import workflow_service  # noqa: E402


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

    def save_session(self, session: dict[str, Any], vault_key_id: str | None) -> None:
        del vault_key_id
        self.sessions[session["id"]] = dict(session)

    def get_session(self, session_id: str, user_id: str, vault_key_id: str | None) -> dict[str, Any] | None:
        del vault_key_id
        session = self.sessions.get(session_id)
        if not session or session["user_id"] != user_id:
            return None
        return session

    def save_event(self, event: WorkflowInputEvent, user_id: str, vault_key_id: str | None) -> None:
        del user_id, vault_key_id
        self.events.append(event)

    def list_events(
        self,
        session_id: str,
        user_id: str,
        after_event_id: int,
        vault_key_id: str | None,
    ) -> list[WorkflowInputEvent]:
        session = self.get_session(session_id, user_id, vault_key_id)
        if not session:
            return []
        return [event for event in self.events if event.session_id == session_id and event.event_id > after_event_id]

    def save_mutation(
        self,
        mutation: WorkflowInputMutation,
        session_id: str,
        user_id: str,
        vault_key_id: str | None,
    ) -> None:
        del session_id, user_id, vault_key_id
        self.mutations = [item for item in self.mutations if item.id != mutation.id]
        self.mutations.append(mutation)

    def list_mutations(self, session_id: str, user_id: str, vault_key_id: str | None) -> list[WorkflowInputMutation]:
        session = self.get_session(session_id, user_id, vault_key_id)
        if not session:
            return []
        return list(self.mutations)


# contract-test: direct surface=rest_api assertions=teams.context.full-switch-local
def test_natural_instruction_creates_only_in_selected_team_and_pins_session_context() -> None:
    service = workflow_service()
    input_service = WorkflowInputService(
        workflow_service=service,
        planner=QueuePlanner([{"action": "batch", "operations": [
            {"action": "create_workflow", "title": "Team instruction", "graph": rain_graph()},
        ]}]),
        repository=FakeWorkflowInputRepository(),
    )
    result = input_service.start(user_id="alice", text="Create a rain workflow", team_id="team-a")
    assert result.status == "executed"
    assert service.list_workflows("alice") == []
    assert service.list_workflows("alice", team_id="team-b") == []
    assert [item.title for item in service.list_workflows("bob", team_id="team-a")] == ["Team instruction"]
    assert input_service.status(result.session_id, "alice", team_id="team-a").status == "executed"
    with pytest.raises(PermissionError):
        input_service.status(result.session_id, "alice")
    with pytest.raises(PermissionError):
        input_service.status(result.session_id, "alice", team_id="team-b")


# contract-test: supporting surface=rest_api assertions=workflows-ui.authoring.composer-and-preview
def test_workflow_input_request_requires_one_strict_input_source() -> None:
    assert WorkflowInputStartRequest(text="Create a workflow").input_type == "text"
    assert WorkflowInputStartRequest(text="Create a workflow", idempotency_key="11111111-1111-4111-8111-111111111111").idempotency_key
    assert WorkflowInputStartRequest(input_type="audio", audio_ref={"id": "audio-1"}).audio_ref == {"id": "audio-1"}

    with pytest.raises(ValidationError):
        WorkflowInputStartRequest(text="Create a workflow", audio_ref={"id": "audio-1"})
    with pytest.raises(ValidationError):
        WorkflowInputStartRequest(input_type="audio", audio_ref={"id": 1})
    with pytest.raises(ValidationError):
        WorkflowInputStartRequest(text="Create a workflow", unexpected=True)
    with pytest.raises(ValidationError):
        WorkflowInputStartRequest(text="Create a workflow", idempotency_key="not-a-uuid")


# contract-test: supporting surface=rest_api assertions=workflows.authoring.provisional-validation,workflows.authoring.atomic-update
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
        "validation_passed",
        "assumption",
        "draft_node_added",
        "draft_node_added",
        "draft_node_added",
        "draft_node_added",
        "draft_node_added",
        "committed",
    ]
    status = input_service.status(result.session_id)
    assert status.event_cursor == 10
    assert status.undo_available is True


# contract-test: supporting surface=rest_api assertions=workflows.authoring.atomic-update
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


# contract-test: supporting surface=rest_api assertions=workflows.content.encrypted-retained
def test_directus_workflow_input_persists_sensitive_state_only_in_vault_blobs() -> None:
    service = workflow_service()
    repository = DirectusWorkflowInputRepository(payload_cipher=service.payload_cipher, token="test-token")
    fake_client = FakeDirectusClient()
    repository._client = fake_client
    input_service = WorkflowInputService(
        workflow_service=service,
        planner=QueuePlanner([{"action": "create_workflow", "title": "Private rain plan", "graph": rain_graph()}]),
        repository=repository,
    )

    result = input_service.start(user_id="alice", text="Create a private rain alert")
    raw_session = fake_client.collections["workflow_input_sessions"][result.session_id]
    raw_event_rows = fake_client.collections["workflow_input_events"]
    raw_mutation_rows = fake_client.collections["workflow_input_mutations"]
    raw_blob_rows = fake_client.collections["workflow_encrypted_blobs"]

    assert "record_json" not in raw_session
    assert raw_session["encrypted_state_ref"].startswith("vault://workflows/workflow_input_session/")
    assert all("payload_json" not in row for row in raw_event_rows.values())
    assert all("before_json" not in row and "after_json" not in row for row in raw_mutation_rows.values())
    assert "Create a private rain alert" not in str(raw_session)
    assert "Private rain plan" not in str(raw_mutation_rows)
    assert "Private rain plan" not in str(raw_blob_rows)

    input_service._sessions.clear()
    restored = input_service.status(result.session_id, user_id="alice")
    assert restored.workflow is not None
    assert restored.workflow.title == "Private rain plan"


# contract-test: supporting surface=rest_api assertions=workflows.access.boundaries,workflows.content.encrypted-retained,workflows.authoring.provisional-validation
def test_directus_stop_poll_reads_only_owner_encrypted_state_after_cache_signal_loss(monkeypatch) -> None:
    service = workflow_service()
    repository = DirectusWorkflowInputRepository(payload_cipher=service.payload_cipher, token="test-token")
    repository._client = FakeDirectusClient()

    class LostStopCache:
        def load(self, user_id: str, session_id: str, vault_key_id: str | None) -> None:
            return None

        def stop_requested(self, user_id: str, session_id: str) -> bool:
            return False

        def request_stop(self, user_id: str, session_id: str) -> None:
            pass

    cache = LostStopCache()
    producer = WorkflowInputService(workflow_service=service, repository=repository, checkpoint_store=cache)
    stopper = WorkflowInputService(workflow_service=service, repository=repository, checkpoint_store=cache)
    session = producer._create_session("alice", None, None, None)
    session_id = session["id"]
    assert repository.get_stop_requested(session_id, "alice", None) is False
    assert repository.get_stop_requested(session_id, "bob", None) is None
    assert stopper.stop(user_id="alice", session_id=session_id).stop_requested is True

    def no_event_or_mutation_reads(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Stop polling must not hydrate events or mutations")

    monkeypatch.setattr(repository, "list_events", no_event_or_mutation_reads)
    monkeypatch.setattr(repository, "list_mutations", no_event_or_mutation_reads)
    assert repository.get_stop_requested(session_id, "alice", None) is True
    session["_last_durable_stop_check"] = 0.0
    assert producer._should_stop(session, None) is True
    assert session["stop_requested"] is True
    assert session["_poll_counts"]["stop_durable_reads"] == 1


# contract-test: supporting surface=rest_api assertions=workflows.access.boundaries,workflows.content.encrypted-retained
def test_directus_stop_poll_rejects_missing_or_malformed_encrypted_state(monkeypatch) -> None:
    service = workflow_service()
    repository = DirectusWorkflowInputRepository(payload_cipher=service.payload_cipher, token="test-token")
    client = FakeDirectusClient()
    repository._client = client
    input_service = WorkflowInputService(workflow_service=service, repository=repository)
    session = input_service._create_session("alice", None, None, None)
    session_id = session["id"]
    row = client.collections["workflow_input_sessions"][session_id]
    row["encrypted_state_ref"] = None
    with pytest.raises(RuntimeError, match="missing its encrypted state"):
        repository.get_stop_requested(session_id, "alice", None)
    session["_last_durable_stop_check"] = 0.0
    assert input_service._should_stop(session, None) is False

    row["encrypted_state_ref"] = "vault://workflows/workflow_input_session/test"
    monkeypatch.setattr(repository, "_load_private_blob", lambda *args: ["malformed"])
    with pytest.raises(RuntimeError, match="state is invalid"):
        repository.get_stop_requested(session_id, "alice", None)
    session["_last_durable_stop_check"] = 0.0
    assert input_service._should_stop(session, None) is False

    monkeypatch.setattr(repository, "_load_private_blob", lambda *args: {"stop_requested": "yes"})
    with pytest.raises(RuntimeError, match="Stop state is invalid"):
        repository.get_stop_requested(session_id, "alice", None)
    session["_last_durable_stop_check"] = 0.0
    assert input_service._should_stop(session, None) is False


# contract-test: supporting surface=rest_api assertions=workflows.authoring.compact-plan
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


# contract-test: supporting surface=rest_api assertions=workflows.authoring.provisional-validation,workflows.activation.reachable-side-effect
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


# contract-test: supporting surface=rest_api assertions=workflows.authoring.provisional-validation,workflows.authoring.atomic-update
def test_stop_followup_and_undo_are_session_scoped() -> None:
    service = workflow_service()
    planner = QueuePlanner([{"action": "draft", "draft_graph": rain_graph()}])
    input_service = WorkflowInputService(workflow_service=service, planner=planner)

    draft = input_service.start(user_id="alice", text="Create a rain workflow")
    assert draft.status == "draft"
    stopped = input_service.stop(user_id="alice", session_id=draft.session_id)
    assert stopped.status == "stopped"
    assert service.list_workflows("alice") == []

    rejected = input_service.follow_up(user_id="alice", session_id=draft.session_id, text="Actually run it at 8")
    assert rejected.status == "stopped"
    assert rejected.error_code == WORKFLOW_INPUT_SESSION_STATE_INVALID
    assert service.list_workflows("alice") == []

    undone = input_service.undo(user_id="alice", session_id=draft.session_id)
    assert undone.status == "stopped"
    assert undone.error_code == "WORKFLOW_INPUT_UNDO_UNAVAILABLE"


# contract-test: supporting surface=rest_api assertions=workflows.authoring.atomic-update
def test_undo_reverts_an_executed_workflow_creation() -> None:
    service = workflow_service()
    input_service = WorkflowInputService(
        workflow_service=service,
        planner=QueuePlanner([{"action": "create_workflow", "title": "Rain at 8", "graph": rain_graph()}]),
    )

    committed = input_service.start(user_id="alice", text="Create a rain workflow")
    assert committed.status == "executed"
    assert committed.undo_available is True

    undone = input_service.undo(user_id="alice", session_id=committed.session_id)
    assert undone.status == "undone"
    assert undone.undo_available is False
    assert service.list_workflows("alice") == []


# contract-test: supporting surface=rest_api assertions=workflows.access.boundaries
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


# contract-test: supporting surface=rest_api assertions=workflows-ui.authoring.composer-and-preview
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


# contract-test: supporting surface=rest_api assertions=workflows-ui.authoring.composer-and-preview
def test_unconfigured_planner_and_transcriber_are_visible_typed_failures() -> None:
    service = workflow_service()
    input_service = WorkflowInputService(workflow_service=service)

    planner_result = input_service.start(user_id="alice", text="Create a rain alert")
    assert planner_result.status == "failed"
    assert planner_result.error_code == WORKFLOW_INPUT_PLANNER_UNAVAILABLE
    assert input_service.events(planner_result.session_id)[-1].type == "capability_unavailable"

    transcription_result = input_service.start(user_id="alice", input_type="audio", audio_ref={"id": "audio-1"})
    assert transcription_result.status == "failed"
    assert transcription_result.error_code == WORKFLOW_INPUT_TRANSCRIPTION_UNAVAILABLE


# contract-test: supporting surface=rest_api assertions=workflows.access.boundaries
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


# contract-test: supporting surface=rest_api assertions=workflows.authoring.atomic-update,workflows.authoring.provisional-validation
def test_batch_validates_every_graph_before_any_workflow_is_saved() -> None:
    service = workflow_service()
    invalid = rain_graph()
    invalid["nodes"].append({"id": "code", "type": "custom_code", "config": {"runtime": "python"}})
    input_service = WorkflowInputService(
        workflow_service=service,
        planner=QueuePlanner([{"action": "batch", "operations": [
            {"action": "create_workflow", "title": "Valid first", "graph": rain_graph()},
            {"action": "create_workflow", "title": "Invalid second", "graph": invalid},
        ]}]),
    )

    result = input_service.start(user_id="alice", text="Make two workflows")

    assert result.status == "failed"
    assert service.list_workflows("alice") == []


# contract-test: supporting surface=rest_api assertions=workflows.authoring.provisional-validation,workflows.authoring.atomic-update
def test_queued_batch_has_plural_previews_and_no_early_mutation() -> None:
    service = workflow_service()
    repository = DirectusWorkflowInputRepository(payload_cipher=service.payload_cipher, token="test-token")
    repository._client = FakeDirectusClient()
    input_service = WorkflowInputService(
        workflow_service=service,
        repository=repository,
        planner=QueuePlanner([{"action": "batch", "operations": [
            {"action": "create_workflow", "title": "Rain morning", "graph": rain_graph()},
            {"action": "create_workflow", "title": "Rain evening", "graph": rain_graph()},
        ]}]),
    )

    result = input_service.start(user_id="alice", text="Make two rain workflows", optimistic_save=True)

    assert result.status == "queued"
    assert [item.title for item in result.preview_workflows] == ["Rain morning", "Rain evening"]
    assert result.preview_workflow == result.preview_workflows[0]
    assert [item["operation"] for item in result.changes] == ["create", "create"]
    assert service.list_workflows("alice") == []
    assert repository.get_session(result.session_id, "alice", None)["pending_operation_id"] == result.session_id
    input_service._sessions.clear()
    restored = input_service.status(result.session_id, user_id="alice")
    assert len(restored.preview_workflows) == 2


# contract-test: direct surface=rest_api assertions=teams.context.full-switch-local
def test_queued_team_input_rechecks_membership_before_commit() -> None:
    service = workflow_service()
    repository = DirectusWorkflowInputRepository(payload_cipher=service.payload_cipher, token="test-token")
    repository._client = FakeDirectusClient()
    input_service = WorkflowInputService(
        workflow_service=service, repository=repository,
        planner=QueuePlanner([{"action": "create_workflow", "title": "Shared rain", "graph": rain_graph()}]),
    )
    queued = input_service.start(user_id="alice", text="Create a rain workflow", team_id="team-a", optimistic_save=True)
    assert queued.status == "queued"
    assert service.list_workflows("alice", team_id="team-a") == []

    def revoked(team_id: str, user_id: str) -> None:
        assert (team_id, user_id) == ("team-a", "alice")
        raise TeamPermissionError("Team permission denied")

    service.repository.require_team_write_role = revoked
    result = input_service.commit_queued(queued.session_id)
    assert result is not None and result.status == "failed"
    assert service.list_workflows("alice", team_id="team-a") == []


# contract-test: direct surface=rest_api assertions=teams.context.full-switch-local
def test_team_ai_plan_rechecks_membership_before_workflow_creation() -> None:
    service = workflow_service()
    input_service = WorkflowInputService(
        workflow_service=service,
        planner=QueuePlanner([{"action": "create_workflow", "title": "Shared rain", "graph": rain_graph()}]),
    )
    def revoked(team_id: str, user_id: str) -> None:
        assert (team_id, user_id) == ("team-a", "alice")
        raise TeamPermissionError("Team permission denied")

    service.repository.require_team_write_role = revoked
    result = input_service.start(user_id="alice", text="Create a rain workflow", team_id="team-a")
    assert result.status == "failed"
    assert service.list_workflows("alice", team_id="team-a") == []


# contract-test: supporting surface=rest_api assertions=workflows.authoring.atomic-update
def test_batch_calls_atomic_commit_once_and_returns_plural_changes() -> None:
    service = workflow_service()
    calls: list[dict[str, Any]] = []

    def commit(user_id: str, operations: list[dict[str, Any]], operation_id: str,
               vault_key_id: str | None = None, *, before_snapshots: list[Any], session_id: str) -> list[Any]:
        calls.append({"operations": operations, "operation_id": operation_id,
                      "before_snapshots": before_snapshots, "session_id": session_id})
        return [service.create_workflow(user_id, item["title"], item["graph"],
                                        source="workflow_input", created_by_assistant=True,
                                        vault_key_id=vault_key_id) for item in operations]

    service.apply_authoring_batch = commit  # type: ignore[method-assign]
    input_service = WorkflowInputService(
        workflow_service=service,
        planner=QueuePlanner([{"action": "batch", "operations": [
            {"action": "create_workflow", "title": "Rain morning", "graph": rain_graph()},
            {"action": "create_workflow", "title": "Rain evening", "graph": rain_graph()},
        ]}]),
    )

    result = input_service.start(user_id="alice", text="Make two rain workflows")

    assert result.status == "executed"
    assert len(calls) == 1
    assert calls[0]["operation_id"] == result.session_id == calls[0]["session_id"]
    assert len(result.workflows) == 2
    assert result.workflow == result.workflows[0]
    assert [item["operation"] for item in result.changes] == ["create", "create"]
    assert result.undo_available is True
    undone_operations: list[str] = []

    def undo(user_id: str, operation_id: str, vault_key_id: str | None = None, *, session_id: str) -> list[Any]:
        del user_id, vault_key_id
        assert session_id == result.session_id
        undone_operations.append(operation_id)
        return []

    service.undo_authoring_batch = undo  # type: ignore[method-assign]
    undone = input_service.undo(user_id="alice", session_id=result.session_id)
    assert undone.status == "undone"
    assert undone_operations == [result.session_id]
    assert undone.undo_available is False


# contract-test: supporting surface=rest_api assertions=workflows.authoring.provisional-validation
def test_component_preview_is_provisional_and_cannot_save_invalid_plan() -> None:
    class PreviewPlanner:
        def plan(self, *, text: str, context: dict[str, Any]) -> dict[str, Any]:
            del text
            context["_on_checkpoint"]({"workflow_index": 0, "operation": "create",
                                       "accepted_node_count": len(rain_graph()["nodes"]),
                                       "graph": rain_graph(), "metadata": {"title": "Draft"}})
            return {"action": "create_workflow", "title": "Invalid", "graph": {"version": 2, "nodes": []}}

    service = workflow_service()
    seen: list[dict[str, Any]] = []
    result = WorkflowInputService(workflow_service=service, planner=PreviewPlanner()).start(
        user_id="alice", text="Make a workflow", on_event=seen.append,
    )

    assert seen[0]["type"] == "started"
    assert seen[1] == {"type": "progress", "phase": "planning"}
    assert any(event.get("type") == "preview" and event.get("provisional") is True
               and event.get("validated") is True for event in seen)
    assert result.status == "failed"
    assert service.list_workflows("alice") == []


# contract-test: supporting surface=rest_api assertions=workflows.authoring.provisional-validation,workflows.authoring.atomic-update
def test_cross_worker_stop_retains_accepted_prefix_as_disabled_draft() -> None:
    prefix = {"version": 2, "trigger_node_id": "trigger", "nodes": [{
        "id": "trigger", "type": "schedule_trigger",
        "config": {"schedule": {"type": "daily", "time": "07:00", "timezone": "UTC"}},
    }], "edges": []}
    accepted = threading.Event()

    class CheckpointStore:
        def __init__(self) -> None:
            self.checkpoints: dict[str, dict[str, Any]] = {}
            self.stopped: set[str] = set()

        def save(self, user_id: str, session_id: str, checkpoints: dict[str, Any], vault_key_id: str | None) -> None:
            del user_id, vault_key_id
            self.checkpoints[session_id] = deepcopy(checkpoints)

        def load(self, user_id: str, session_id: str, vault_key_id: str | None) -> dict[str, Any] | None:
            del user_id, vault_key_id
            return deepcopy(self.checkpoints.get(session_id))

        def request_stop(self, user_id: str, session_id: str) -> None:
            del user_id
            self.stopped.add(session_id)

        def stop_requested(self, user_id: str, session_id: str) -> bool:
            del user_id
            return session_id in self.stopped

        def clear(self, user_id: str, session_id: str) -> None:
            del user_id
            self.checkpoints.pop(session_id, None)
            self.stopped.discard(session_id)

    class WaitingPlanner:
        atomic_authoring = True

        def plan(self, *, text: str, context: dict[str, Any]) -> dict[str, Any]:
            del text
            context["_on_checkpoint"]({"workflow_index": 0, "operation": "create", "accepted_node_count": 1,
                                       "graph": prefix, "metadata": {"title": "Stopped prefix"}})
            accepted.set()
            deadline = time.monotonic() + 3
            while not context["_should_stop"]() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert context["_should_stop"]()
            return {"action": "partial", "reason": "stopped", "notice": "Stopped after one valid step.",
                    "operations": [{"action": "create_workflow", "title": "Stopped prefix", "graph": prefix}]}

    service = workflow_service()
    repository = FakeWorkflowInputRepository()
    cache = CheckpointStore()
    producer = WorkflowInputService(workflow_service=service, repository=repository,
                                    checkpoint_store=cache, planner=WaitingPlanner())
    stopper = WorkflowInputService(workflow_service=service, repository=repository, checkpoint_store=cache)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(producer.start, user_id="alice", text="Create a workflow")
        assert accepted.wait(2)
        session_id = next(iter(cache.checkpoints))
        ack = stopper.stop(user_id="alice", session_id=session_id)
        assert ack.status == "running" and ack.stop_requested is True
        cache.stopped.clear()  # The durable signal still reaches a producer if cache loses its marker.
        producer._sessions[session_id]["_last_durable_stop_check"] = 0.0
        assert producer._should_stop(producer._sessions[session_id], None) is True
        result = pending.result(timeout=5)
    assert result.status == "draft" and result.partial_reason == "stopped"
    assert result.partial_warning == "Stopped after one valid step."
    assert result.workflow and result.workflow.enabled is False
    assert result.workflow.graph == WorkflowGraph.model_validate(prefix)
    assert service.list_workflows("alice")[0].id == result.workflow.id
    assert result.authoring_metrics["service_poll_counts"]["stop_checks"] >= 1
    assert "stop_cache_read_seconds" in result.authoring_metrics["service_stages_seconds"]
    assert "stop_durable_read_seconds" in result.authoring_metrics["service_stages_seconds"]


# contract-test: supporting surface=rest_api assertions=workflows.authoring.provisional-validation,workflows.access.boundaries
def test_new_session_skips_redundant_stop_read_and_still_observes_durable_stop(monkeypatch) -> None:
    now = [100.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    repository = FakeWorkflowInputRepository()

    class HealthyCache:
        def stop_requested(self, user_id: str, session_id: str) -> bool:
            return False

        def clear(self, user_id: str, session_id: str) -> None:
            pass

    class Planner:
        def plan(self, *, text: str, context: dict[str, Any]) -> dict[str, Any]:
            assert context["_should_stop"]() is False
            session = next(iter(service._sessions.values()))
            assert not session["_poll_counts"].get("stop_durable_reads")
            repository.sessions[session["id"]]["stop_requested"] = True
            now[0] += 1.01
            assert context["_should_stop"]() is True
            return {"action": "needs_clarification", "message": "Stopped"}

    service = WorkflowInputService(workflow_service=workflow_service(), planner=Planner(),
                                   repository=repository, checkpoint_store=HealthyCache())
    result = service.start(user_id="alice", text="Create a workflow")
    assert result.stop_requested is True
    assert result.authoring_metrics["service_poll_counts"]["stop_durable_reads"] == 1


# contract-test: supporting surface=rest_api assertions=workflows.authoring.provisional-validation,workflows.access.boundaries
def test_stop_poll_throttles_cache_but_keeps_fast_signal_and_durable_fallback() -> None:
    class CountingCache:
        def __init__(self) -> None:
            self.reads = 0
            self.stopped = False
            self.fail = False

        def stop_requested(self, user_id: str, session_id: str) -> bool:
            del user_id, session_id
            self.reads += 1
            if self.fail:
                raise RuntimeError("cache unavailable")
            return self.stopped

    repository = FakeWorkflowInputRepository()
    cache = CountingCache()
    service = WorkflowInputService(workflow_service=workflow_service(), repository=repository,
                                   checkpoint_store=cache)
    session = service._create_session("alice", None, None, None)
    session["_last_stop_cache_check"] = time.monotonic()
    for _ in range(100):
        assert service._should_stop(session, None) is False
    assert cache.reads == 0
    assert session["_poll_counts"]["stop_cache_read_skips"] == 100

    cache.stopped = True
    time.sleep(0.11)
    assert service._should_stop(session, None) is True
    assert cache.reads == 1
    assert session["_poll_counts"]["stop_cache_reads"] == 1

    # A failed cache signal still reaches the producer through the durable row.
    second = service._create_session("alice", None, None, None)
    second["_last_stop_cache_check"] = time.monotonic()
    repository.sessions[second["id"]]["stop_requested"] = True
    assert service._should_stop(second, None) is True
    assert second["_poll_counts"]["stop_durable_reads"] == 1

    # A cache read failure bypasses the one-second durable-read interval.
    third = service._create_session("alice", None, None, None)
    third["_last_stop_cache_check"] = 0.0
    third["_last_durable_stop_check"] = time.monotonic()
    repository.sessions[third["id"]]["stop_requested"] = True
    cache.fail = True
    assert service._should_stop(third, None) is True
    assert third["_poll_counts"]["stop_durable_reads"] == 1

    class FailedWriteCache(CountingCache):
        def load(self, user_id: str, session_id: str, vault_key_id: str | None) -> None:
            del user_id, session_id, vault_key_id
            return None

        def request_stop(self, user_id: str, session_id: str) -> None:
            del user_id, session_id
            raise RuntimeError("cache write unavailable")

    failed_cache = FailedWriteCache()
    producer = WorkflowInputService(workflow_service=workflow_service(), repository=repository,
                                    checkpoint_store=failed_cache)
    fourth = producer._create_session("alice", None, None, None)
    stopper = WorkflowInputService(workflow_service=producer.workflow_service, repository=repository,
                                   checkpoint_store=failed_cache)
    assert stopper.stop(user_id="alice", session_id=fourth["id"]).stop_requested is True
    assert producer._should_stop(fourth, None) is True


# contract-test: supporting surface=rest_api assertions=workflows.authoring.provisional-validation
def test_stop_between_compiler_acceptance_and_checkpoint_keeps_that_node() -> None:
    graph = rain_graph()
    seen: list[dict[str, Any]] = []
    holder: dict[str, WorkflowInputService] = {}

    class RacingPlanner:
        atomic_authoring = True

        def plan(self, *, text: str, context: dict[str, Any]) -> dict[str, Any]:
            del text
            session_id = seen[0]["session_id"]
            # The compiler accepted the graph just before this Stop request;
            # its checkpoint callback has not run yet.
            ack = holder["service"].stop(user_id="alice", session_id=session_id)
            assert ack.status == "running" and ack.stop_requested is True
            context["_on_checkpoint"]({"workflow_index": 0, "operation": "create",
                                       "accepted_node_count": len(graph["nodes"]), "graph": graph,
                                       "metadata": {"title": "Accepted before Stop"}})
            assert context["_should_stop"]() is True
            return {"action": "partial", "reason": "stopped", "notice": "Stopped after the accepted node.",
                    "operations": [{"action": "create_workflow", "title": "Accepted before Stop", "graph": graph}]}

    workflow = workflow_service()
    holder["service"] = WorkflowInputService(workflow_service=workflow, planner=RacingPlanner())
    result = holder["service"].start(user_id="alice", text="Make a rain workflow", on_event=seen.append)

    assert result.status == "draft" and result.partial_reason == "stopped"
    assert result.workflow and result.workflow.enabled is False
    assert result.workflow.graph == WorkflowGraph.model_validate(graph)
    assert len(result.partial_previews) == 1
    assert any(event.get("type") == "preview" and event.get("validated") is True for event in seen)


# contract-test: supporting surface=rest_api assertions=workflows.authoring.atomic-update
def test_partial_update_disables_same_workflow_and_undo_restores_active_snapshot() -> None:
    service = workflow_service()
    original = service.create_workflow("alice", "Active original", rain_graph(), enabled=True)
    modified = deepcopy(rain_graph())
    modified["nodes"][1]["config"]["input"]["location"] = "Lisbon"
    class PartialPlanner(QueuePlanner):
        def plan(self, *, text: str, context: dict[str, Any]) -> dict[str, Any]:
            context["_on_checkpoint"]({"workflow_index": 0, "operation": "update", "accepted_node_count": 1,
                                       "graph": modified, "metadata": {"workflow_id": original.id,
                                                                            "expected_record_version": original.version}})
            return super().plan(text=text, context=context)

    input_service = WorkflowInputService(workflow_service=service, planner=PartialPlanner([{
        "action": "partial", "reason": "provider_error", "notice": "One later step could not be completed.",
        "operations": [{"action": "update_workflow", "workflow_id": original.id,
                        "expected_record_version": original.version, "graph": modified}],
    }]))

    result = input_service.start(user_id="alice", text="Change the city", selected_workflow_id=original.id)
    assert result.status == "draft" and result.partial_reason == "provider_error"
    assert result.workflow and result.workflow.id == original.id and result.workflow.enabled is False
    assert result.workflow.graph.nodes[1].config["input"]["location"] == "Lisbon"
    assert len(service.list_workflows("alice")) == 1
    undone = input_service.undo(user_id="alice", session_id=result.session_id)
    assert undone.status == "undone"
    restored = service.get_workflow(original.id, "alice")
    assert restored.enabled is True and restored.title == original.title
    assert restored.graph == original.graph


# contract-test: supporting surface=rest_api assertions=workflows.authoring.provisional-validation,workflows.access.boundaries
def test_header_checkpoint_is_saveable_and_stop_is_owner_scoped() -> None:
    prefix = {"version": 2, "trigger_node_id": "trigger", "nodes": [{
        "id": "trigger", "type": "schedule_trigger",
        "config": {"schedule": {"type": "daily", "time": "07:00", "timezone": "UTC"}},
    }], "edges": []}

    class HeaderPlanner:
        atomic_authoring = True

        def plan(self, *, text: str, context: dict[str, Any]) -> dict[str, Any]:
            del text
            context["_on_checkpoint"]({"workflow_index": 0, "operation": "create", "accepted_node_count": 0,
                                       "graph": prefix, "metadata": {"title": "Header only"}})
            return {"action": "partial", "reason": "stopped", "notice": "Stopped after the trigger.",
                    "operations": [{"action": "create_workflow", "title": "Header only", "graph": prefix}]}

    input_service = WorkflowInputService(workflow_service=workflow_service(), planner=HeaderPlanner())
    result = input_service.start(user_id="alice", text="Create a reminder")
    assert result.status == "draft" and result.workflow and result.workflow.enabled is False
    assert result.partial_previews[0]["accepted_node_count"] == 0
    with pytest.raises(PermissionError):
        input_service.stop(user_id="bob", session_id=result.session_id)
    with pytest.raises(PermissionError):
        input_service.status(result.session_id, user_id="bob")


# contract-test: supporting surface=rest_api assertions=workflows.authoring.provisional-validation
def test_partial_plan_cannot_save_graph_beyond_validated_checkpoint() -> None:
    prefix = {"version": 2, "trigger_node_id": "trigger", "nodes": [{
        "id": "trigger", "type": "schedule_trigger",
        "config": {"schedule": {"type": "daily", "time": "07:00", "timezone": "UTC"}},
    }], "edges": []}

    class UnsafePlanner:
        atomic_authoring = True

        def plan(self, *, text: str, context: dict[str, Any]) -> dict[str, Any]:
            del text
            context["_on_checkpoint"]({"workflow_index": 0, "operation": "create", "accepted_node_count": 0,
                                       "graph": prefix, "metadata": {"title": "Safe prefix"}})
            extra = deepcopy(prefix)
            extra["nodes"].append({"id": "unvalidated", "type": "end", "config": {}})
            extra["edges"].append({"from": "trigger", "to": "unvalidated"})
            return {"action": "partial", "reason": "provider_error", "notice": "Stopped.",
                    "operations": [{"action": "create_workflow", "title": "Unsafe suffix", "graph": extra}]}

    service = workflow_service()
    result = WorkflowInputService(workflow_service=service, planner=UnsafePlanner()).start(
        user_id="alice", text="Create a reminder")
    assert result.status == "failed" and service.list_workflows("alice") == []


# contract-test: supporting surface=rest_api assertions=workflows.content.encrypted-retained,workflows.access.boundaries
def test_checkpoint_cache_encrypts_payload_and_separates_owners() -> None:
    import json

    class Cipher:
        private: dict[str, Any] | None = None

        def encrypt_json(self, payload: dict[str, Any], vault_key_id: str | None) -> dict[str, str]:
            assert vault_key_id == "vault-alice"
            self.private = deepcopy(payload)
            return {"ciphertext": "opaque-encrypted-value"}

        def decrypt_json(self, blob: dict[str, Any], vault_key_id: str | None) -> dict[str, Any]:
            assert blob == {"ciphertext": "opaque-encrypted-value"} and vault_key_id == "vault-alice"
            assert self.private is not None
            return deepcopy(self.private)

    class Cache:
        def __init__(self) -> None:
            self.values: dict[str, str] = {}
            self.ttls: dict[str, int] = {}

        def setex(self, key: str, ttl: int, value: str) -> None:
            self.values[key], self.ttls[key] = value, ttl

        def get(self, key: str) -> str | None:
            return self.values.get(key)

        def exists(self, key: str) -> bool:
            return key in self.values

        def delete(self, *keys: str) -> None:
            for key in keys:
                self.values.pop(key, None)

    cipher = Cipher()
    cache = Cache()
    store = DragonflyWorkflowInputCheckpointStore(cipher)
    store._client = cache
    payload = {"0": {"graph": {"nodes": [{"title": "private instruction"}]}}}
    store.save("alice", "session-1", payload, "vault-alice")
    assert len(cache.values) == 1
    assert "private instruction" not in next(iter(cache.values.values()))
    assert json.loads(next(iter(cache.values.values()))) == {"ciphertext": "opaque-encrypted-value"}
    assert next(iter(cache.ttls.values())) >= 7 * 24 * 60 * 60
    assert store.load("alice", "session-1", "vault-alice") == payload
    assert store.load("bob", "session-1", "vault-alice") is None
    store.request_stop("alice", "session-1")
    assert store.stop_requested("alice", "session-1") is True
    assert store.stop_requested("bob", "session-1") is False


# contract-test: supporting surface=rest_api assertions=workflows.authoring.provisional-validation,workflows.authoring.atomic-update
def test_stale_stopped_session_recovers_validated_prefix_after_worker_loss() -> None:
    prefix = {"version": 2, "trigger_node_id": "trigger", "nodes": [{
        "id": "trigger", "type": "schedule_trigger",
        "config": {"schedule": {"type": "daily", "time": "07:00", "timezone": "UTC"}},
    }], "edges": []}

    class Cache:
        def __init__(self) -> None:
            self.checkpoints: dict[str, dict[str, Any]] = {}
            self.stopped: set[str] = set()
            self.claimed: set[str] = set()

        def save(self, user_id: str, session_id: str, checkpoints: dict[str, Any], vault_key_id: str | None) -> None:
            del user_id, vault_key_id
            self.checkpoints[session_id] = deepcopy(checkpoints)

        def load(self, user_id: str, session_id: str, vault_key_id: str | None) -> dict[str, Any] | None:
            del user_id, vault_key_id
            return deepcopy(self.checkpoints.get(session_id))

        def request_stop(self, user_id: str, session_id: str) -> None:
            del user_id
            self.stopped.add(session_id)

        def stop_requested(self, user_id: str, session_id: str) -> bool:
            del user_id
            return session_id in self.stopped

        def claim_recovery(self, user_id: str, session_id: str) -> bool:
            del user_id
            if session_id in self.claimed:
                return False
            self.claimed.add(session_id)
            return True

        def clear(self, user_id: str, session_id: str) -> None:
            del user_id
            self.checkpoints.pop(session_id, None)
            self.stopped.discard(session_id)
            self.claimed.discard(session_id)

    service = workflow_service()
    repository = FakeWorkflowInputRepository()
    cache = Cache()
    producer = WorkflowInputService(workflow_service=service, repository=repository, checkpoint_store=cache)
    pending = producer._create_session("alice", None, None, None)
    producer._accept_checkpoint(pending, {"workflow_index": 0, "operation": "create",
                                          "accepted_node_count": 0, "graph": prefix,
                                          "metadata": {"title": "Recovered prefix"}}, None)
    consumer = WorkflowInputService(workflow_service=service, repository=repository, checkpoint_store=cache)
    ack = consumer.stop(user_id="alice", session_id=pending["id"])
    assert ack.status == "running" and ack.stop_requested
    repository.sessions[pending["id"]]["cancellation_requested_at"] = int(time.time()) - 61

    recovered = consumer.status(pending["id"], user_id="alice")

    assert recovered.status == "draft" and recovered.workflow and recovered.workflow.enabled is False
    assert recovered.workflow.title == "Recovered prefix"
    assert len(service.list_workflows("alice")) == 1
    assert consumer.status(pending["id"], user_id="alice").status == "draft"


# contract-test: supporting surface=rest_api assertions=workflows.authoring.provisional-validation
def test_planner_failure_after_checkpoint_saves_validated_prefix() -> None:
    prefix = {"version": 2, "trigger_node_id": "trigger", "nodes": [{
        "id": "trigger", "type": "schedule_trigger",
        "config": {"schedule": {"type": "daily", "time": "07:00", "timezone": "UTC"}},
    }], "edges": []}

    class BrokenPlanner:
        atomic_authoring = True

        def plan(self, *, text: str, context: dict[str, Any]) -> dict[str, Any]:
            del text
            context["_on_checkpoint"]({"workflow_index": 0, "operation": "create", "accepted_node_count": 0,
                                       "graph": prefix, "metadata": {"title": "Safe prefix"}})
            raise RuntimeError("provider connection lost")

    service = workflow_service()
    result = WorkflowInputService(workflow_service=service, planner=BrokenPlanner()).start(
        user_id="alice", text="Create a reminder")
    assert result.status == "draft" and result.partial_reason == "provider_error"
    assert result.workflow and result.workflow.enabled is False
    assert len(service.list_workflows("alice")) == 1


# contract-test: supporting surface=rest_api assertions=workflows.authoring.provisional-validation
def test_partial_without_validated_checkpoint_fails_without_saving() -> None:
    service = workflow_service()
    input_service = WorkflowInputService(workflow_service=service, planner=QueuePlanner([{
        "action": "partial", "reason": "provider_error", "notice": "No valid steps completed.",
        "operations": [],
    }]))

    result = input_service.start(user_id="alice", text="Create a workflow")

    assert result.status == "failed" and result.error_code == "WORKFLOW_INPUT_NO_VALID_PARTIAL"
    assert service.list_workflows("alice") == []


# contract-test: supporting surface=rest_api assertions=workflows.authoring.atomic-update
def test_input_idempotency_reuses_same_instruction_and_rejects_conflict() -> None:
    service = workflow_service()
    input_service = WorkflowInputService(
        workflow_service=service,
        repository=FakeWorkflowInputRepository(),
        planner=QueuePlanner([{"action": "create_workflow", "title": "Rain once", "graph": rain_graph()}]),
    )

    first = input_service.start(user_id="alice", text="Rain workflow", idempotency_key="chat:1:message:1")
    repeat = input_service.start(user_id="alice", text="Rain workflow", idempotency_key="chat:1:message:1")

    assert repeat.session_id == first.session_id
    assert len(service.list_workflows("alice")) == 1
    with pytest.raises(ValueError, match="different instruction"):
        input_service.start(user_id="alice", text="Change the instruction", idempotency_key="chat:1:message:1")


# contract-test: supporting surface=rest_api assertions=workflows.activation.reachable-side-effect,workflows.authoring.atomic-update
def test_generic_blank_draft_undo_preserves_later_edit() -> None:
    class AtomicPlanner(QueuePlanner):
        atomic_authoring = True

    service = workflow_service()
    input_service = WorkflowInputService(
        workflow_service=service,
        planner=AtomicPlanner([{"action": "create_empty_workflow", "title": "My reminder"}]),
    )

    result = input_service.start(user_id="alice", text="My reminder")
    assert result.status == "draft" and result.workflow is not None
    assert result.workflow.enabled is False
    assert result.workflow.graph.nodes == []
    service.update_workflow(result.workflow.id, "alice", title="Edited later")

    undone = input_service.undo(user_id="alice", session_id=result.session_id)

    assert undone.error_code == "WORKFLOW_INPUT_UNDO_CONFLICT"
    assert service.get_workflow(result.workflow.id, "alice").title == "Edited later"


# contract-test: supporting surface=rest_api assertions=workflows.authoring.atomic-update
def test_generic_single_create_uses_atomic_ledger_and_undo() -> None:
    class AtomicPlanner(QueuePlanner):
        atomic_authoring = True

    service = workflow_service()
    input_service = WorkflowInputService(
        workflow_service=service,
        planner=AtomicPlanner([{"action": "create_workflow", "title": "Rain report", "graph": rain_graph()}]),
    )

    result = input_service.start(user_id="alice", text="Create a rain report")
    assert result.status == "executed"
    assert len(result.workflows) == 1
    assert input_service.status(result.session_id).mutations[0].operation_id == result.session_id

    undone = input_service.undo(user_id="alice", session_id=result.session_id)
    assert undone.status == "undone"
    assert service.list_workflows("alice") == []


# contract-test: supporting surface=rest_api assertions=workflows.activation.reachable-side-effect,workflows.authoring.atomic-update
def test_generic_blank_draft_followup_uses_new_atomic_operation() -> None:
    class AtomicPlanner(QueuePlanner):
        atomic_authoring = True

    service = workflow_service()
    input_service = WorkflowInputService(
        workflow_service=service,
        planner=AtomicPlanner([
            {"action": "create_empty_workflow", "title": "My reminder"},
            {"action": "update_workflow", "graph": rain_graph()},
        ]),
    )

    draft = input_service.start(user_id="alice", text="My reminder")
    updated = input_service.follow_up(user_id="alice", session_id=draft.session_id, text="Add rain steps")

    assert updated.status == "executed"
    assert updated.workflow is not None and updated.workflow.id == draft.workflow.id
    operation_ids = {item.operation_id for item in input_service.status(draft.session_id).mutations}
    assert operation_ids == {draft.session_id, f"{draft.session_id}:followup:1"}

    undone = input_service.undo(user_id="alice", session_id=draft.session_id)
    assert undone.status == "undone"
    assert service.get_workflow(draft.workflow.id, "alice").graph.nodes == []


# contract-test: supporting surface=rest_api assertions=workflows.authoring.atomic-update,workflows.content.encrypted-retained
def test_directus_mutation_reload_groups_transaction_rows_and_hides_inverse() -> None:
    service = workflow_service()
    repository = DirectusWorkflowInputRepository(payload_cipher=service.payload_cipher, token="test-token")
    fake_client = FakeDirectusClient()
    repository._client = fake_client
    rows = fake_client.collections.setdefault("workflow_input_mutations", {})
    for index, operation_id in enumerate(("op-original", "undo:op-original")):
        rows[f"mutation-{index}"] = {
            "id": f"mutation-{index}", "session_id": "session-1", "hashed_user_id": _hash_owner_id("alice"),
            "type": "create_workflow" if index == 0 else "delete_workflow",
            "target_type": "workflow", "target_id": "workflow-1", "operation_id": operation_id,
            "encrypted_before_ref": None, "encrypted_after_ref": None,
            "undone_at": 123 if index == 0 else None, "created_at": 100 + index,
        }

    mutations = repository.list_mutations("session-1", "alice", None)

    assert len(mutations) == 1
    assert mutations[0].operation_id == "op-original"
    assert mutations[0].undone_at == 123


# contract-test: supporting surface=rest_api assertions=workflows.authoring.provisional-validation,workflows-ui.authoring.composer-and-preview
def test_stream_route_emits_provisional_preview_and_final_session() -> None:
    import json
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.core.api.app.routes.workflows import (
        ensure_workflows_enabled, get_current_user_or_api_key, get_workflow_input_service, limiter, router,
    )

    class StreamingPlanner:
        def plan(self, *, text: str, context: dict[str, Any]) -> dict[str, Any]:
            del text
            context["_on_checkpoint"]({"workflow_index": 0, "operation": "create",
                                       "accepted_node_count": len(rain_graph()["nodes"]),
                                       "graph": rain_graph(), "metadata": {"title": "Rain draft"}})
            return {"action": "needs_clarification", "message": "Choose a time"}

    service = workflow_service()
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(router)
    app.dependency_overrides[ensure_workflows_enabled] = lambda: None
    app.dependency_overrides[get_current_user_or_api_key] = lambda: SimpleNamespace(id="alice", vault_key_id=None)
    app.dependency_overrides[get_workflow_input_service] = lambda: WorkflowInputService(
        workflow_service=service, planner=StreamingPlanner(),
    )

    with TestClient(app) as client:
        response = client.post("/v1/workflows/input/stream", json={"text": "Make a rain workflow"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = [json.loads(line.removeprefix("data: ")) for line in response.text.splitlines() if line.startswith("data: ")]
    assert events[0]["type"] == "started" and events[0]["status"] == "running"
    assert events[1] == {"type": "progress", "phase": "planning"}
    assert events[2]["type"] == "preview" and events[2]["provisional"] is True and events[2]["validated"] is True
    assert events[-1]["type"] == "session" and events[-1]["session"]["status"] == "needs_clarification"
    assert service.list_workflows("alice") == []


# contract-test: supporting surface=rest_api assertions=workflows-ui.authoring.composer-and-preview
def test_session_routes_serialize_nested_graph_edges_with_public_aliases() -> None:
    import json
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.core.api.app.routes.workflows import (
        ensure_workflows_enabled, get_current_user_or_api_key, get_workflow_identity_service,
        get_workflow_input_service, get_workflow_service, get_workspace_history_service,
        limiter, router,
    )
    from backend.core.api.app.services.workflow_input_service import WorkflowInputSessionResult

    workflow = workflow_service().create_workflow("alice", "Rain workflow", rain_graph())
    result = WorkflowInputSessionResult(
        session_id="session-1", status="executed", event_cursor=1,
        workflow=workflow, workflows=[workflow],
        preview_workflow=workflow, preview_workflows=[workflow],
    )

    class SessionService:
        def start(self, *args: Any, **kwargs: Any) -> WorkflowInputSessionResult:
            del args
            on_event = kwargs.get("on_event")
            if on_event is not None:
                on_event({"type": "preview", "graph": workflow.graph.model_dump(mode="json", by_alias=True)})
            return result

        def status(self, *args: Any, **kwargs: Any) -> WorkflowInputSessionResult:
            return result

        def follow_up(self, *args: Any, **kwargs: Any) -> WorkflowInputSessionResult:
            return result

        def stop(self, *args: Any, **kwargs: Any) -> WorkflowInputSessionResult:
            return result

        def undo(self, *args: Any, **kwargs: Any) -> WorkflowInputSessionResult:
            return result

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(router)
    app.dependency_overrides[ensure_workflows_enabled] = lambda: None
    app.dependency_overrides[get_current_user_or_api_key] = lambda: SimpleNamespace(id="alice", vault_key_id=None)
    app.dependency_overrides[get_workflow_input_service] = lambda: SessionService()
    app.dependency_overrides[get_workflow_service] = lambda: SimpleNamespace()
    app.dependency_overrides[get_workflow_identity_service] = lambda: SimpleNamespace()
    app.dependency_overrides[get_workspace_history_service] = lambda: SimpleNamespace()

    def assert_public_edges(payload: dict[str, Any]) -> None:
        for key in ("workflow", "preview_workflow"):
            edges = payload[key]["graph"]["edges"]
            assert edges and all("from" in edge and "to" in edge for edge in edges)
            assert all("from_node" not in edge and "to_node" not in edge for edge in edges)
        for key in ("workflows", "preview_workflows"):
            edges = payload[key][0]["graph"]["edges"]
            assert edges and all("from" in edge and "to" in edge for edge in edges)
            assert all("from_node" not in edge and "to_node" not in edge for edge in edges)

    with TestClient(app) as client:
        responses = [
            client.post("/v1/workflows/input", json={"text": "Rain workflow"}),
            client.get("/v1/workflows/input/session-1"),
            client.post("/v1/workflows/input/session-1/follow-up", json={"text": "Change time"}),
            client.post("/v1/workflows/input/session-1/stop"),
            client.post("/v1/workflows/input/session-1/undo"),
        ]
        for response in responses:
            assert response.status_code == 200
            assert_public_edges(response.json()["session"])

        ask = client.post("/v1/workflows/ask", json={"instruction": "Rain workflow"})
        assert ask.status_code == 200
        ask_body = ask.json()
        assert_public_edges(ask_body["session"])
        assert "from" in ask_body["workflow"]["graph"]["edges"][0]
        assert "to" in ask_body["workflows"][0]["graph"]["edges"][0]

        stream = client.post("/v1/workflows/input/stream", json={"text": "Rain workflow"})
        assert stream.status_code == 200
        events = [json.loads(line.removeprefix("data: ")) for line in stream.text.splitlines() if line.startswith("data: ")]
        preview = next(event for event in events if event["type"] == "preview")
        assert "from" in preview["graph"]["edges"][0] and "to" in preview["graph"]["edges"][0]
        assert "from_node" not in preview["graph"]["edges"][0]
        assert_public_edges(events[-1]["session"])
