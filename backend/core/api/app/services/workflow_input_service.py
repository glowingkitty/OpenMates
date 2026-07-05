"""Durable workflow-input session orchestration.

This service backs the Workflows screen command input and CLI/SDK workflow-input
contract. It intentionally does not use the chat pre/main/post processing
pipeline. A planner produces strict structured commands; this service owns
sanitization, owner checks, graph validation, event persistence, stop/follow-up,
commit, and undo behavior.

Spec: docs/specs/workflows-v1/spec.yml
"""

from __future__ import annotations

import time
import uuid
from copy import deepcopy
from typing import Any, Callable, Protocol

import httpx
from pydantic import BaseModel, Field, ValidationError

from backend.core.api.app.services.workflow_input_security import (
    redacted_event_summary,
    sanitize_workflow_input_text,
)
from backend.core.api.app.services.workflow_models import WorkflowDetail, WorkflowGraph
from backend.core.api.app.services.workflow_service import DirectusWorkflowRepository, WorkflowNotFoundError, WorkflowService, _hash_owner_id


WORKFLOW_INPUT_SESSION_TTL_SECONDS = 7 * 24 * 60 * 60


class WorkflowInputPlanner(Protocol):
    def plan(self, *, text: str, context: dict[str, Any]) -> dict[str, Any]:
        """Return a strict structured workflow-input command."""


class WorkflowProjectLinker(Protocol):
    def link_workflow(self, *, user_id: str, project_id: str, workflow_id: str, display_name: str) -> dict[str, Any]:
        """Link an owned workflow into an owned project."""

    def unlink_project_item(self, project_item_id: str) -> bool:
        """Undo a prior project-item link."""


class WorkflowInputRepository(Protocol):
    def save_session(self, session: dict[str, Any]) -> None:
        """Persist the latest session snapshot."""

    def get_session(self, session_id: str, user_id: str) -> dict[str, Any] | None:
        """Return a user-owned session snapshot."""

    def save_event(self, event: WorkflowInputEvent, user_id: str) -> None:
        """Persist an append-only event."""

    def save_mutation(self, mutation: WorkflowInputMutation, session_id: str, user_id: str) -> None:
        """Persist or update a workflow-input mutation ledger entry."""

    def list_events(self, session_id: str, user_id: str, after_event_id: int = 0) -> list[WorkflowInputEvent]:
        """Return user-owned events after a cursor."""


class DirectusWorkflowInputRepository(DirectusWorkflowRepository):
    """Durable workflow-input repository backed by Directus custom collections."""

    SESSIONS = "workflow_input_sessions"
    EVENTS = "workflow_input_events"
    MUTATIONS = "workflow_input_mutations"

    def save_session(self, session: dict[str, Any]) -> None:
        record = _serialize_session(session)
        payload = {
            "id": session["id"],
            "session_id": session["id"],
            "hashed_user_id": _hash_owner_id(session["user_id"]),
            "status": session["status"],
            "selected_workflow_id": session.get("selected_workflow_id"),
            "selected_project_id": session.get("selected_project_id"),
            "event_cursor": len(session.get("events") or []),
            "record_json": record,
            "created_at": session["created_at"],
            "updated_at": session["updated_at"],
            "expires_at": session["expires_at"],
        }
        existing = self._find_one(self.SESSIONS, {"id": {"_eq": session["id"]}}, fields="id")
        if existing:
            self._patch_item(self.SESSIONS, existing["id"], payload)
        else:
            self._create_item(self.SESSIONS, payload)

    def get_session(self, session_id: str, user_id: str) -> dict[str, Any] | None:
        item = self._find_one(
            self.SESSIONS,
            {"_and": [{"id": {"_eq": session_id}}, {"hashed_user_id": {"_eq": _hash_owner_id(user_id)}}]},
        )
        if not item or not isinstance(item.get("record_json"), dict):
            return None
        return _deserialize_session(item["record_json"])

    def save_event(self, event: WorkflowInputEvent, user_id: str) -> None:
        payload = {
            "id": event.id,
            "session_id": event.session_id,
            "hashed_user_id": _hash_owner_id(user_id),
            "event_id": event.event_id,
            "type": event.type,
            "status": event.status,
            "redacted_summary": event.redacted_summary,
            "payload_json": event.payload,
            "created_at": event.created_at,
        }
        try:
            self._create_item(self.EVENTS, payload)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 409:
                raise

    def save_mutation(self, mutation: WorkflowInputMutation, session_id: str, user_id: str) -> None:
        payload = {
            "id": mutation.id,
            "session_id": session_id,
            "hashed_user_id": _hash_owner_id(user_id),
            "type": mutation.type,
            "target_type": mutation.target_type,
            "target_id": mutation.target_id,
            "before_json": mutation.before,
            "after_json": mutation.after,
            "undone_at": mutation.undone_at,
            "created_at": int(time.time()),
        }
        existing = self._find_one(self.MUTATIONS, {"id": {"_eq": mutation.id}}, fields="id")
        if existing:
            self._patch_item(self.MUTATIONS, existing["id"], payload)
        else:
            self._create_item(self.MUTATIONS, payload)

    def list_events(self, session_id: str, user_id: str, after_event_id: int = 0) -> list[WorkflowInputEvent]:
        filters = {
            "_and": [
                {"session_id": {"_eq": session_id}},
                {"hashed_user_id": {"_eq": _hash_owner_id(user_id)}},
                {"event_id": {"_gt": after_event_id}},
            ]
        }
        items = self._get_items(self.EVENTS, filters, sort="event_id", limit=-1)
        return [
            WorkflowInputEvent(
                id=str(item["id"]),
                session_id=str(item["session_id"]),
                event_id=int(item["event_id"]),
                type=str(item["type"]),
                status=str(item.get("status") or "ok"),
                redacted_summary=str(item.get("redacted_summary") or ""),
                payload=item.get("payload_json") if isinstance(item.get("payload_json"), dict) else {},
                created_at=int(item["created_at"]),
            )
            for item in items
        ]


class DeterministicWorkflowInputPlanner:
    """Conservative fallback planner used until an LLM planner is wired in."""

    def plan(self, *, text: str, context: dict[str, Any]) -> dict[str, Any]:
        del context
        normalized = text.strip().lower()
        if not normalized:
            return {"action": "needs_clarification", "message": "What workflow should I help with?"}
        if "rain" in normalized:
            return {
                "action": "create_workflow",
                "title": "Rain alert",
                "graph": _rain_alert_graph(),
                "enabled": True,
                "assumptions": ["Using push notification as the default alert channel."],
            }
        return {
            "action": "needs_clarification",
            "message": "I need a clearer workflow instruction before making changes.",
        }


class WorkflowInputEvent(BaseModel):
    id: str
    session_id: str
    event_id: int
    type: str
    status: str = "ok"
    redacted_summary: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: int


class WorkflowInputMutation(BaseModel):
    id: str
    type: str
    target_type: str
    target_id: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    undone_at: int | None = None


class WorkflowInputSessionResult(BaseModel):
    session_id: str
    status: str
    event_cursor: int
    message: str | None = None
    error: str | None = None
    workflow: WorkflowDetail | None = None
    project_item: dict[str, Any] | None = None
    undo_available: bool = False


class WorkflowInputSessionDetail(WorkflowInputSessionResult):
    events: list[WorkflowInputEvent] = Field(default_factory=list)
    draft_graph: dict[str, Any] | None = None
    mutations: list[WorkflowInputMutation] = Field(default_factory=list)


class WorkflowInputService:
    """Session-scoped workflow input service with in-memory storage for V1."""

    def __init__(
        self,
        *,
        workflow_service: WorkflowService,
        planner: WorkflowInputPlanner | None = None,
        project_linker: WorkflowProjectLinker | None = None,
        transcriber: Callable[[dict[str, Any]], str] | None = None,
        repository: WorkflowInputRepository | None = None,
    ) -> None:
        self.workflow_service = workflow_service
        self.planner = planner or DeterministicWorkflowInputPlanner()
        self.project_linker = project_linker
        self.transcriber = transcriber or _default_transcriber
        self.repository = repository
        self._sessions: dict[str, dict[str, Any]] = {}

    def start(
        self,
        *,
        user_id: str,
        text: str | None = None,
        input_type: str = "text",
        audio_ref: dict[str, Any] | None = None,
        selected_workflow_id: str | None = None,
        selected_project_id: str | None = None,
    ) -> WorkflowInputSessionResult:
        session = self._create_session(user_id, selected_workflow_id, selected_project_id)
        return self._process_input(session, text=text, input_type=input_type, audio_ref=audio_ref)

    def follow_up(self, *, user_id: str, session_id: str, text: str) -> WorkflowInputSessionResult:
        session = self._require_session(session_id, user_id)
        session["status"] = "running"
        self._append_event(session, "followup_received", {"text_length": len(text)})
        return self._process_input(session, text=text, input_type="text", audio_ref=None)

    def stop(self, *, user_id: str, session_id: str) -> WorkflowInputSessionResult:
        session = self._require_session(session_id, user_id)
        session["status"] = "stopped"
        session["cancellation_requested_at"] = int(time.time())
        self._append_event(session, "stopped", {})
        return self._result(session)

    def undo(self, *, user_id: str, session_id: str) -> WorkflowInputSessionResult:
        session = self._require_session(session_id, user_id)
        mutation = self._last_undoable_mutation(session)
        if mutation is None:
            session["status"] = "failed"
            self._append_event(session, "undo_unavailable", {}, status="error")
            return self._result(session, error="No workflow input mutation is available to undo")

        if mutation.type == "create_workflow":
            self.workflow_service.delete_workflow(mutation.target_id, user_id)
        elif mutation.type == "update_workflow" and mutation.before:
            self.workflow_service.update_workflow(
                mutation.target_id,
                user_id,
                title=mutation.before.get("title"),
                graph=mutation.before.get("graph"),
            )
        elif mutation.type == "link_workflow_to_project" and self.project_linker is not None:
            project_item_id = (mutation.after or {}).get("project_item_id")
            if project_item_id:
                self.project_linker.unlink_project_item(str(project_item_id))
        else:
            session["status"] = "failed"
            self._append_event(session, "undo_failed", {"mutation_type": mutation.type}, status="error")
            return self._result(session, error=f"Undo is not supported for {mutation.type}")

        mutation.undone_at = int(time.time())
        if self.repository is not None:
            self.repository.save_mutation(mutation, session["id"], user_id)
        session["status"] = "undone"
        self._append_event(session, "undone", {"mutation_type": mutation.type, "target_id": mutation.target_id})
        return self._result(session)

    def status(self, session_id: str, user_id: str | None = None) -> WorkflowInputSessionDetail:
        session = self._get_session(session_id, user_id)
        if user_id is not None and session["user_id"] != user_id:
            raise PermissionError("Workflow input session not found")
        result = self._result(session)
        return WorkflowInputSessionDetail(
            **result.model_dump(),
            events=list(session["events"]),
            draft_graph=deepcopy(session.get("draft_graph")),
            mutations=list(session["mutations"]),
        )

    def events(self, session_id: str, after_event_id: int = 0, user_id: str | None = None) -> list[WorkflowInputEvent]:
        if user_id is not None and self.repository is not None:
            events = self.repository.list_events(session_id, user_id, after_event_id)
            if events:
                return events
        session = self._get_session(session_id, user_id)
        if user_id is not None and session["user_id"] != user_id:
            raise PermissionError("Workflow input session not found")
        return [event for event in session["events"] if event.event_id > after_event_id]

    def _process_input(
        self,
        session: dict[str, Any],
        *,
        text: str | None,
        input_type: str,
        audio_ref: dict[str, Any] | None,
    ) -> WorkflowInputSessionResult:
        try:
            if input_type == "audio":
                self._append_event(session, "transcribing_started", {})
                text = self.transcriber(audio_ref or {})
                self._append_event(session, "transcript_ready", {"text_length": len(text)})
            if text is None:
                raise ValueError("workflow input text is required")

            sanitized_text, stats = sanitize_workflow_input_text(text)
            if int(stats.get("removed_count", 0) or 0) > 0:
                self._append_event(session, "input_sanitized", {"removed_count": stats.get("removed_count")})
            self._append_event(session, "input_received", {"text_length": len(sanitized_text)})
            self._append_event(session, "planning_started", {})

            plan = self.planner.plan(text=sanitized_text, context=self._planner_context(session))
            return self._apply_plan(session, plan)
        except Exception as exc:  # Boundary converts all failures into visible session state.
            session["status"] = "failed"
            if session["events"] and session["events"][-1].type in {"validation_failed", "target_not_found"}:
                return self._result(session, error=str(exc))
            self._append_event(session, "failed", {"error_type": type(exc).__name__}, status="error")
            return self._result(session, error=str(exc))

    def _apply_plan(self, session: dict[str, Any], plan: dict[str, Any]) -> WorkflowInputSessionResult:
        action = str(plan.get("action") or "").strip()
        if action == "needs_clarification":
            session["status"] = "needs_clarification"
            message = str(plan.get("message") or "I need more detail before changing workflows.")
            session["message"] = message
            self._append_event(session, "clarification_requested", {"message_length": len(message)})
            return self._result(session, message=message)
        if action == "draft":
            session["status"] = "draft"
            session["draft_graph"] = deepcopy(plan.get("draft_graph"))
            self._append_event(session, "draft_saved", {"node_count": len((session["draft_graph"] or {}).get("nodes") or [])})
            return self._result(session)
        if action == "create_workflow":
            return self._create_workflow(session, plan)
        if action == "update_workflow":
            return self._update_workflow(session, plan)
        if action == "delete_workflow":
            return self._delete_workflow(session, plan)
        if action == "link_workflow_to_project":
            return self._link_workflow_to_project(session, plan)
        session["status"] = "failed"
        self._append_event(session, "unsupported", {"action": action}, status="error")
        return self._result(session, error=f"Unsupported workflow input action: {action}")

    def _create_workflow(self, session: dict[str, Any], plan: dict[str, Any]) -> WorkflowInputSessionResult:
        graph = plan.get("graph")
        for assumption in plan.get("assumptions") or []:
            self._append_event(session, "assumption", {"text_length": len(str(assumption))})
        self._stream_draft_nodes(session, graph)
        workflow_graph = self._validate_graph(session, graph)
        workflow = self.workflow_service.create_workflow(
            session["user_id"],
            str(plan.get("title") or "Untitled workflow"),
            workflow_graph,
            enabled=bool(plan.get("enabled", False)),
            source="workflow_input",
            created_by_assistant=True,
        )
        session["status"] = "executed"
        session["workflow"] = workflow
        self._append_mutation(session, WorkflowInputMutation(id=str(uuid.uuid4()), type="create_workflow", target_type="workflow", target_id=workflow.id, after=workflow.model_dump(mode="json")))
        self._append_event(session, "committed", {"mutation_type": "create_workflow", "workflow_id": workflow.id})
        return self._result(session, workflow=workflow)

    def _update_workflow(self, session: dict[str, Any], plan: dict[str, Any]) -> WorkflowInputSessionResult:
        workflow_id = str(plan.get("workflow_id") or session.get("selected_workflow_id") or "")
        before = self.workflow_service.get_workflow(workflow_id, session["user_id"])
        graph = plan.get("graph") or before.graph.model_dump(mode="json", by_alias=True)
        self._stream_draft_nodes(session, graph)
        workflow_graph = self._validate_graph(session, graph)
        workflow = self.workflow_service.update_workflow(
            workflow_id,
            session["user_id"],
            title=plan.get("title"),
            graph=workflow_graph,
        )
        session["status"] = "executed"
        session["workflow"] = workflow
        self._append_mutation(session, WorkflowInputMutation(id=str(uuid.uuid4()), type="update_workflow", target_type="workflow", target_id=workflow.id, before=before.model_dump(mode="json"), after=workflow.model_dump(mode="json")))
        self._append_event(session, "committed", {"mutation_type": "update_workflow", "workflow_id": workflow.id})
        return self._result(session, workflow=workflow)

    def _delete_workflow(self, session: dict[str, Any], plan: dict[str, Any]) -> WorkflowInputSessionResult:
        workflow_id = str(plan.get("workflow_id") or session.get("selected_workflow_id") or "")
        before = self.workflow_service.get_workflow(workflow_id, session["user_id"])
        self.workflow_service.delete_workflow(workflow_id, session["user_id"])
        session["status"] = "executed"
        self._append_mutation(session, WorkflowInputMutation(id=str(uuid.uuid4()), type="delete_workflow", target_type="workflow", target_id=workflow_id, before=before.model_dump(mode="json")))
        self._append_event(session, "committed", {"mutation_type": "delete_workflow", "workflow_id": workflow_id})
        return self._result(session)

    def _link_workflow_to_project(self, session: dict[str, Any], plan: dict[str, Any]) -> WorkflowInputSessionResult:
        if self.project_linker is None:
            raise ValueError("Project linking is not configured")
        workflow_id = str(plan.get("workflow_id") or "")
        project_id = str(plan.get("project_id") or session.get("selected_project_id") or "")
        try:
            workflow = self.workflow_service.get_workflow(workflow_id, session["user_id"])
        except WorkflowNotFoundError as exc:
            session["status"] = "failed"
            self._append_event(session, "target_not_found", {"target_type": "workflow"}, status="error")
            raise ValueError("Workflow not found") from exc
        project_item = self.project_linker.link_workflow(
            user_id=session["user_id"],
            project_id=project_id,
            workflow_id=workflow.id,
            display_name=str(plan.get("display_name") or workflow.title),
        )
        session["status"] = "executed"
        session["project_item"] = project_item
        self._append_mutation(session, WorkflowInputMutation(id=str(uuid.uuid4()), type="link_workflow_to_project", target_type="project_item", target_id=str(project_item.get("project_item_id")), after=project_item))
        self._append_event(session, "committed", {"mutation_type": "link_workflow_to_project", "workflow_id": workflow.id})
        return self._result(session, project_item=project_item)

    def _validate_graph(self, session: dict[str, Any], graph: Any) -> WorkflowGraph:
        try:
            workflow_graph = graph if isinstance(graph, WorkflowGraph) else WorkflowGraph.model_validate(graph)
        except (ValidationError, ValueError) as exc:
            session["status"] = "failed"
            self._append_event(session, "validation_failed", {"error_type": type(exc).__name__}, status="error")
            raise
        self._append_event(session, "validation_passed", {})
        return workflow_graph

    def _stream_draft_nodes(self, session: dict[str, Any], graph: Any) -> None:
        if not isinstance(graph, dict):
            return
        session["draft_graph"] = deepcopy(graph)
        for node in graph.get("nodes") or []:
            self._append_event(session, "draft_node_added", {"node_type": node.get("type") if isinstance(node, dict) else "unknown"})

    def _planner_context(self, session: dict[str, Any]) -> dict[str, Any]:
        workflows = [item.model_dump(mode="json") for item in self.workflow_service.list_workflows(session["user_id"])]
        selected_workflow_id = session.get("selected_workflow_id")
        selected_workflow = None
        if selected_workflow_id:
            try:
                selected_workflow = self.workflow_service.get_workflow(selected_workflow_id, session["user_id"]).model_dump(mode="json")
            except WorkflowNotFoundError:
                selected_workflow = None
        return {
            "workflows": workflows,
            "selected_workflow": selected_workflow,
            "projects": [],
            "selected_project_id": session.get("selected_project_id"),
        }

    def _create_session(self, user_id: str, selected_workflow_id: str | None, selected_project_id: str | None) -> dict[str, Any]:
        now = int(time.time())
        session = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "status": "running",
            "selected_workflow_id": selected_workflow_id,
            "selected_project_id": selected_project_id,
            "events": [],
            "mutations": [],
            "draft_graph": None,
            "workflow": None,
            "project_item": None,
            "created_at": now,
            "updated_at": now,
            "expires_at": now + WORKFLOW_INPUT_SESSION_TTL_SECONDS,
        }
        self._sessions[session["id"]] = session
        self._persist_session(session)
        return session

    def _require_session(self, session_id: str, user_id: str) -> dict[str, Any]:
        session = self._get_session(session_id, user_id)
        if session["user_id"] != user_id:
            raise PermissionError("Workflow input session not found")
        return session

    def _get_session(self, session_id: str, user_id: str | None = None) -> dict[str, Any]:
        session = self._sessions.get(session_id)
        if session is None and user_id is not None and self.repository is not None:
            session = self.repository.get_session(session_id, user_id)
            if session is not None:
                self._sessions[session_id] = session
        if session is None:
            raise KeyError(session_id)
        return session

    def _append_event(self, session: dict[str, Any], event_type: str, payload: dict[str, Any], status: str = "ok") -> None:
        event = WorkflowInputEvent(
            id=str(uuid.uuid4()),
            session_id=session["id"],
            event_id=len(session["events"]) + 1,
            type=event_type,
            status=status,
            redacted_summary=redacted_event_summary(payload),
            payload=deepcopy(payload),
            created_at=int(time.time()),
        )
        session["events"].append(event)
        session["updated_at"] = event.created_at
        if self.repository is not None:
            self.repository.save_event(event, session["user_id"])
        self._persist_session(session)

    def _append_mutation(self, session: dict[str, Any], mutation: WorkflowInputMutation) -> None:
        session["mutations"].append(mutation)
        if self.repository is not None:
            self.repository.save_mutation(mutation, session["id"], session["user_id"])
        self._persist_session(session)

    def _last_undoable_mutation(self, session: dict[str, Any]) -> WorkflowInputMutation | None:
        for mutation in reversed(session["mutations"]):
            if mutation.undone_at is None:
                return mutation
        return None

    def _result(
        self,
        session: dict[str, Any],
        *,
        message: str | None = None,
        error: str | None = None,
        workflow: WorkflowDetail | None = None,
        project_item: dict[str, Any] | None = None,
    ) -> WorkflowInputSessionResult:
        return WorkflowInputSessionResult(
            session_id=session["id"],
            status=session["status"],
            event_cursor=len(session["events"]),
            message=message or session.get("message"),
            error=error,
            workflow=workflow or session.get("workflow"),
            project_item=project_item or session.get("project_item"),
            undo_available=self._last_undoable_mutation(session) is not None,
        )

    def _persist_session(self, session: dict[str, Any]) -> None:
        if self.repository is not None:
            self.repository.save_session(session)


def _serialize_session(session: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(session)
    payload["events"] = [event.model_dump(mode="json") if isinstance(event, WorkflowInputEvent) else event for event in payload.get("events") or []]
    payload["mutations"] = [mutation.model_dump(mode="json") if isinstance(mutation, WorkflowInputMutation) else mutation for mutation in payload.get("mutations") or []]
    if isinstance(payload.get("workflow"), WorkflowDetail):
        payload["workflow"] = payload["workflow"].model_dump(mode="json")
    return payload


def _deserialize_session(record: dict[str, Any]) -> dict[str, Any]:
    session = deepcopy(record)
    session["events"] = [WorkflowInputEvent.model_validate(event) for event in session.get("events") or []]
    session["mutations"] = [WorkflowInputMutation.model_validate(mutation) for mutation in session.get("mutations") or []]
    if isinstance(session.get("workflow"), dict):
        session["workflow"] = WorkflowDetail.model_validate(session["workflow"])
    return session


def _default_transcriber(audio_ref: dict[str, Any]) -> str:
    raise ValueError(f"Workflow input audio transcription is not configured for {audio_ref.get('id', 'audio')}")


def _rain_alert_graph() -> dict[str, Any]:
    return {
        "version": 1,
        "trigger_node_id": "trigger",
        "nodes": [
            {"id": "trigger", "type": "schedule_trigger", "config": {"schedule": {"type": "daily", "time": "07:00", "timezone": "Europe/Berlin"}}},
            {"id": "weather", "type": "app_skill_action", "config": {"app_id": "weather", "skill_id": "forecast", "input": {"location": "Berlin", "days": 1}}},
            {"id": "decision", "type": "decision", "config": {"predicate": {"left": "$nodes.weather.output.rain_probability", "op": "gte", "right": 60}}},
            {"id": "notify", "type": "send_notification", "config": {"title": "Rain today", "body": "Take an umbrella."}},
        ],
        "edges": [
            {"from": "trigger", "to": "weather"},
            {"from": "weather", "to": "decision"},
            {"from": "decision", "to": "notify", "branch": "yes"},
        ],
    }
