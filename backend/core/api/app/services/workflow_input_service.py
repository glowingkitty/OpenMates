"""Durable, Vault-protected workflow-input session orchestration.

Workflow input is deliberately independent from the chat pre/main/post pipeline.
The durable Directus records contain only reconnect metadata; user text,
transcripts, drafts, planner output, and undo snapshots live in owner-scoped
Automation Vault blobs.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from copy import deepcopy
from typing import Annotated, Any, Callable, Literal, Protocol, TypeAlias

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

from backend.core.api.app.services.workflow_input_security import redacted_event_summary, sanitize_workflow_input_text
from backend.core.api.app.services.workflow_models import WorkflowDetail, WorkflowGraph, validate_workflow_composition_refs, validate_workflow_readiness
from backend.core.api.app.services.workflow_service import (
    DirectusWorkflowRepository,
    WorkflowNotFoundError,
    WorkflowPayloadCipher,
    WorkflowService,
    _hash_owner_id,
)


logger = logging.getLogger(__name__)

WORKFLOW_INPUT_SESSION_TTL_SECONDS = 7 * 24 * 60 * 60
WORKFLOW_INPUT_SESSION_BLOB_KIND = "workflow_input_session"
WORKFLOW_INPUT_EVENT_BLOB_KIND = "workflow_input_event"
WORKFLOW_INPUT_MUTATION_BLOB_KIND = "workflow_input_mutation"
WORKFLOW_INPUT_PLANNER_UNAVAILABLE = "WORKFLOW_INPUT_PLANNER_UNAVAILABLE"
WORKFLOW_INPUT_TRANSCRIPTION_UNAVAILABLE = "WORKFLOW_INPUT_TRANSCRIPTION_UNAVAILABLE"
WORKFLOW_INPUT_ACTION_UNAVAILABLE = "WORKFLOW_INPUT_ACTION_UNAVAILABLE"
WORKFLOW_INPUT_SESSION_STATE_INVALID = "WORKFLOW_INPUT_SESSION_STATE_INVALID"
WORKFLOW_INPUT_UNDO_UNAVAILABLE = "WORKFLOW_INPUT_UNDO_UNAVAILABLE"
WORKFLOW_INPUT_UNDO_CONFLICT = "WORKFLOW_INPUT_UNDO_CONFLICT"

EventPayloadValue: TypeAlias = str | int | bool | None


class WorkflowInputUnavailableError(RuntimeError):
    """A required workflow-input capability is intentionally not configured."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class WorkflowInputPlanner(Protocol):
    def plan(self, *, text: str, context: dict[str, Any]) -> dict[str, Any]:
        """Return a structured command that conforms to ``WorkflowInputPlan``."""


class WorkflowProjectLinker(Protocol):
    def link_workflow(self, *, user_id: str, project_id: str, workflow_id: str, display_name: str) -> dict[str, Any]:
        """Link an owned workflow into an owned project."""

    def unlink_project_item(self, project_item_id: str) -> bool:
        """Undo a prior project-item link."""


class WorkflowInputRepository(Protocol):
    def save_session(self, session: dict[str, Any], vault_key_id: str | None) -> None:
        """Persist a session's encrypted private state and public reconnect metadata."""

    def get_session(self, session_id: str, user_id: str, vault_key_id: str | None) -> dict[str, Any] | None:
        """Return a user-owned session and decrypt its private state."""

    def save_event(self, event: WorkflowInputEvent, user_id: str, vault_key_id: str | None) -> None:
        """Persist an append-only encrypted event body."""

    def save_events(self, events: list[WorkflowInputEvent], user_id: str, vault_key_id: str | None) -> None:
        """Persist one request's ordered events with encrypted payloads."""

    def save_mutation(
        self,
        mutation: WorkflowInputMutation,
        session_id: str,
        user_id: str,
        vault_key_id: str | None,
    ) -> None:
        """Persist encrypted undo snapshots."""

    def list_events(
        self,
        session_id: str,
        user_id: str,
        after_event_id: int,
        vault_key_id: str | None,
    ) -> list[WorkflowInputEvent]:
        """Return user-owned events after a reconnect cursor."""

    def list_mutations(self, session_id: str, user_id: str, vault_key_id: str | None) -> list[WorkflowInputMutation]:
        """Return the encrypted undo ledger for a user-owned session."""


class DirectusWorkflowInputRepository(DirectusWorkflowRepository):
    """Directus metadata rows plus the existing workflow Automation Vault blobs."""

    SESSIONS = "workflow_input_sessions"
    EVENTS = "workflow_input_events"
    MUTATIONS = "workflow_input_mutations"

    def __init__(self, *, payload_cipher: WorkflowPayloadCipher, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.payload_cipher = payload_cipher

    def save_session(self, session: dict[str, Any], vault_key_id: str | None) -> None:
        state_ref = self._blob_ref(WORKFLOW_INPUT_SESSION_BLOB_KIND, session["id"])
        state_blob = self._save_private_blob(
            user_id=session["user_id"],
            kind=WORKFLOW_INPUT_SESSION_BLOB_KIND,
            ref=state_ref,
            payload=_session_private_state(session),
            expires_at=session["expires_at"],
            vault_key_id=vault_key_id,
        )
        payload = {
            "id": session["id"],
            "session_id": session["id"],
            "hashed_user_id": _hash_owner_id(session["user_id"]),
            "status": session["status"],
            "event_cursor": len(session.get("events") or []),
            "encrypted_state_ref": state_blob["ref"],
            "encrypted_state_checksum": state_blob["checksum"],
            "created_at": session["created_at"],
            "updated_at": session["updated_at"],
            "expires_at": session["expires_at"],
        }
        existing = self._find_one(self.SESSIONS, {"id": {"_eq": session["id"]}}, fields="id")
        if existing:
            self._patch_item(self.SESSIONS, existing["id"], payload)
        else:
            self._create_item(self.SESSIONS, payload)

    def get_session(self, session_id: str, user_id: str, vault_key_id: str | None) -> dict[str, Any] | None:
        item = self._find_one(
            self.SESSIONS,
            {"_and": [{"id": {"_eq": session_id}}, {"hashed_user_id": {"_eq": _hash_owner_id(user_id)}}]},
        )
        if not item:
            return None
        state_ref = item.get("encrypted_state_ref")
        if not isinstance(state_ref, str) or not state_ref:
            raise RuntimeError("Workflow input session is missing its encrypted state")
        state = self._load_private_blob(user_id, state_ref, vault_key_id)
        if not isinstance(state, dict):
            raise RuntimeError("Workflow input session state is invalid")
        session = {
            "id": str(item["session_id"]),
            "user_id": user_id,
            "status": str(item["status"]),
            "events": self.list_events(session_id, user_id, 0, vault_key_id),
            "mutations": self.list_mutations(session_id, user_id, vault_key_id),
            "created_at": int(item["created_at"]),
            "updated_at": int(item["updated_at"]),
            "expires_at": int(item["expires_at"]),
            **state,
        }
        return session

    def queued_session_ids(self, limit: int = 100) -> list[str]:
        rows = self._get_items(
            self.SESSIONS, {"status": {"_eq": "queued"}},
            fields="session_id", sort="created_at", limit=limit,
        )
        return [str(row["session_id"]) for row in rows if row.get("session_id")]

    def queued_session_owner(self, session_id: str) -> tuple[str, str | None] | None:
        """Recover a queued owner's identity only inside the trusted commit worker."""
        row = self._find_one(self.SESSIONS, {"_and": [
            {"session_id": {"_eq": session_id}}, {"status": {"_eq": "queued"}},
        ]})
        if not row:
            return None
        ref = row.get("encrypted_state_ref")
        if not isinstance(ref, str) or not ref:
            raise RuntimeError("Queued workflow input is missing encrypted state")
        blob = self.get_encrypted_blob(ref)
        if not blob:
            raise RuntimeError("Queued workflow input encrypted state is unavailable")
        key_ref = blob.get("vault_key_ref")
        state = self.payload_cipher.decrypt_json(blob, key_ref)
        user_id = state.get("queued_user_id") if isinstance(state, dict) else None
        if not isinstance(user_id, str) or _hash_owner_id(user_id) != row.get("hashed_user_id"):
            raise RuntimeError("Queued workflow input owner verification failed")
        return user_id, str(key_ref) if key_ref else None

    def save_event(self, event: WorkflowInputEvent, user_id: str, vault_key_id: str | None) -> None:
        payload_blob = self._save_private_blob(
            user_id=user_id,
            kind=WORKFLOW_INPUT_EVENT_BLOB_KIND,
            ref=self._blob_ref(WORKFLOW_INPUT_EVENT_BLOB_KIND, event.id),
            payload=event.payload,
            expires_at=None,
            vault_key_id=vault_key_id,
        )
        payload = {
            "id": event.id,
            "session_id": event.session_id,
            "hashed_user_id": _hash_owner_id(user_id),
            "event_id": event.event_id,
            "type": event.type,
            "status": event.status,
            "redacted_summary": event.redacted_summary,
            "encrypted_payload_ref": payload_blob["ref"],
            "encrypted_payload_checksum": payload_blob["checksum"],
            "created_at": event.created_at,
        }
        try:
            self._create_item(self.EVENTS, payload)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 409:
                raise

    def save_events(self, events: list[WorkflowInputEvent], user_id: str, vault_key_id: str | None) -> None:
        if not events:
            return
        # The synchronous input route exposes its progress after the request
        # completes. One encrypted batch preserves every event while avoiding a
        # Vault call and a Directus blob round trip for each graph node.
        payload_blob = self._save_private_blob(
            user_id=user_id,
            kind=WORKFLOW_INPUT_EVENT_BLOB_KIND,
            ref=self._blob_ref(WORKFLOW_INPUT_EVENT_BLOB_KIND, f"batch/{uuid.uuid4()}"),
            payload={"_event_payloads": {str(event.event_id): event.payload for event in events}},
            expires_at=None,
            vault_key_id=vault_key_id,
            create_only=True,
        )
        rows = [
            {
                "id": event.id,
                "session_id": event.session_id,
                "hashed_user_id": _hash_owner_id(user_id),
                "event_id": event.event_id,
                "type": event.type,
                "status": event.status,
                "redacted_summary": event.redacted_summary,
                "encrypted_payload_ref": payload_blob["ref"],
                "encrypted_payload_checksum": payload_blob["checksum"],
                "created_at": event.created_at,
            }
            for event in events
        ]
        self._request("POST", f"/items/{self.EVENTS}", json=rows)

    def save_mutation(
        self,
        mutation: WorkflowInputMutation,
        session_id: str,
        user_id: str,
        vault_key_id: str | None,
    ) -> None:
        before_blob = self._save_optional_blob(
            user_id=user_id,
            kind=WORKFLOW_INPUT_MUTATION_BLOB_KIND,
            ref=self._blob_ref(WORKFLOW_INPUT_MUTATION_BLOB_KIND, f"{mutation.id}/before"),
            payload=mutation.before,
            vault_key_id=vault_key_id,
        )
        after_blob = self._save_optional_blob(
            user_id=user_id,
            kind=WORKFLOW_INPUT_MUTATION_BLOB_KIND,
            ref=self._blob_ref(WORKFLOW_INPUT_MUTATION_BLOB_KIND, f"{mutation.id}/after"),
            payload=mutation.after,
            vault_key_id=vault_key_id,
        )
        payload = {
            "id": mutation.id,
            "session_id": session_id,
            "hashed_user_id": _hash_owner_id(user_id),
            "type": mutation.type,
            "target_type": mutation.target_type,
            "target_id": mutation.target_id,
            "encrypted_before_ref": before_blob["ref"] if before_blob else None,
            "encrypted_before_checksum": before_blob["checksum"] if before_blob else None,
            "encrypted_after_ref": after_blob["ref"] if after_blob else None,
            "encrypted_after_checksum": after_blob["checksum"] if after_blob else None,
            "undone_at": mutation.undone_at,
            "created_at": mutation.created_at,
        }
        existing = self._find_one(self.MUTATIONS, {"id": {"_eq": mutation.id}}, fields="id")
        if existing:
            self._patch_item(self.MUTATIONS, existing["id"], payload)
        else:
            self._create_item(self.MUTATIONS, payload)

    def list_events(
        self,
        session_id: str,
        user_id: str,
        after_event_id: int,
        vault_key_id: str | None,
    ) -> list[WorkflowInputEvent]:
        filters = {
            "_and": [
                {"session_id": {"_eq": session_id}},
                {"hashed_user_id": {"_eq": _hash_owner_id(user_id)}},
                {"event_id": {"_gt": after_event_id}},
            ]
        }
        items = self._get_items(self.EVENTS, filters, sort="event_id", limit=-1)
        events: list[WorkflowInputEvent] = []
        payload_cache: dict[str, dict[str, Any]] = {}
        for item in items:
            payload_ref = item.get("encrypted_payload_ref")
            if not isinstance(payload_ref, str) or not payload_ref:
                raise RuntimeError("Workflow input event is missing its encrypted payload")
            if payload_ref not in payload_cache:
                payload_cache[payload_ref] = self._load_private_blob(user_id, payload_ref, vault_key_id)
            payload = payload_cache[payload_ref]
            if "_event_payloads" in payload:
                payload = payload["_event_payloads"].get(str(item["event_id"]))
            if not isinstance(payload, dict):
                raise RuntimeError("Workflow input event payload is invalid")
            events.append(
                WorkflowInputEvent(
                    id=str(item["id"]),
                    session_id=str(item["session_id"]),
                    event_id=int(item["event_id"]),
                    type=str(item["type"]),
                    status=str(item.get("status") or "ok"),
                    redacted_summary=str(item.get("redacted_summary") or ""),
                    payload=payload,
                    created_at=int(item["created_at"]),
                )
            )
        return events

    def list_mutations(self, session_id: str, user_id: str, vault_key_id: str | None) -> list[WorkflowInputMutation]:
        items = self._get_items(
            self.MUTATIONS,
            {"_and": [{"session_id": {"_eq": session_id}}, {"hashed_user_id": {"_eq": _hash_owner_id(user_id)}}]},
            sort="created_at",
            limit=-1,
        )
        mutations: list[WorkflowInputMutation] = []
        for item in items:
            before = self._load_optional_blob(user_id, item.get("encrypted_before_ref"), vault_key_id)
            after = self._load_optional_blob(user_id, item.get("encrypted_after_ref"), vault_key_id)
            mutations.append(
                WorkflowInputMutation(
                    id=str(item["id"]),
                    type=str(item["type"]),
                    target_type=str(item["target_type"]),
                    target_id=str(item["target_id"]),
                    before=before,
                    after=after,
                    undone_at=int(item["undone_at"]) if item.get("undone_at") is not None else None,
                    created_at=int(item["created_at"]),
                )
            )
        return mutations

    def _save_optional_blob(
        self,
        *,
        user_id: str,
        kind: str,
        ref: str,
        payload: dict[str, Any] | None,
        vault_key_id: str | None,
    ) -> dict[str, Any] | None:
        if payload is None:
            return None
        return self._save_private_blob(
            user_id=user_id,
            kind=kind,
            ref=ref,
            payload=payload,
            expires_at=None,
            vault_key_id=vault_key_id,
        )

    def _load_optional_blob(self, user_id: str, ref: Any, vault_key_id: str | None) -> dict[str, Any] | None:
        if ref is None:
            return None
        if not isinstance(ref, str) or not ref:
            raise RuntimeError("Workflow input mutation has an invalid encrypted snapshot reference")
        payload = self._load_private_blob(user_id, ref, vault_key_id)
        if not isinstance(payload, dict):
            raise RuntimeError("Workflow input mutation snapshot is invalid")
        return payload

    def _save_private_blob(
        self,
        *,
        user_id: str,
        kind: str,
        ref: str,
        payload: dict[str, Any],
        expires_at: int | None,
        vault_key_id: str | None,
        create_only: bool = False,
    ) -> dict[str, Any]:
        encrypted = self.payload_cipher.encrypt_json(payload, vault_key_id)
        blob = {
                "ref": ref,
                "owner_hash": _hash_owner_id(user_id),
                "kind": kind,
                "ciphertext": encrypted["ciphertext"],
                "checksum": encrypted["checksum"],
                "vault_key_ref": encrypted.get("vault_key_ref"),
                "key_version": encrypted.get("key_version"),
                "expires_at": expires_at,
                "created_at": int(time.time()),
            }
        return self.create_encrypted_blob(blob) if create_only else self.save_encrypted_blob(blob)

    def _load_private_blob(self, user_id: str, ref: str, vault_key_id: str | None) -> Any:
        blob = self.get_encrypted_blob(ref)
        if not blob or blob.get("owner_hash") != _hash_owner_id(user_id):
            raise WorkflowNotFoundError(ref)
        if blob.get("expires_at") is not None and int(blob["expires_at"]) <= int(time.time()):
            raise WorkflowNotFoundError(ref)
        return self.payload_cipher.decrypt_json(blob, vault_key_id)

    @staticmethod
    def _blob_ref(kind: str, identifier: str) -> str:
        return f"vault://workflows/{kind}/{identifier}"


class WorkflowInputEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    session_id: str
    event_id: int
    type: str
    status: str = "ok"
    redacted_summary: str = ""
    payload: dict[str, EventPayloadValue] = Field(default_factory=dict)
    created_at: int


class WorkflowInputMutation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: Literal["create_workflow", "update_workflow", "link_workflow_to_project"]
    target_type: Literal["workflow", "project_item"]
    target_id: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    undone_at: int | None = None
    created_at: int


class WorkflowInputSessionResult(BaseModel):
    session_id: str
    status: str
    event_cursor: int
    message: str | None = None
    error: str | None = None
    error_code: str | None = None
    workflow: WorkflowDetail | None = None
    preview_workflow: WorkflowDetail | None = None
    project_item: dict[str, Any] | None = None
    undo_available: bool = False
    assumptions: list[str] = Field(default_factory=list)
    authoring_metrics: dict[str, Any] | None = None


class WorkflowInputSessionDetail(WorkflowInputSessionResult):
    events: list[WorkflowInputEvent] = Field(default_factory=list)
    draft_graph: dict[str, Any] | None = None
    mutations: list[WorkflowInputMutation] = Field(default_factory=list)


class _PlanModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _ClarificationPlan(_PlanModel):
    action: Literal["needs_clarification"]
    message: str = Field(min_length=1, max_length=2_000)


class _DraftPlan(_PlanModel):
    action: Literal["draft"]
    draft_graph: WorkflowGraph


class _CreateEmptyWorkflowPlan(_PlanModel):
    action: Literal["create_empty_workflow"]
    title: str = Field(min_length=1, max_length=200)


class _CreateWorkflowPlan(_PlanModel):
    action: Literal["create_workflow"]
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2_000)
    category: str | None = None
    icon: str | None = None
    graph: WorkflowGraph
    enabled: bool = False
    assumptions: list[str] = Field(default_factory=list, max_length=20)


class _UpdateWorkflowPlan(_PlanModel):
    action: Literal["update_workflow"]
    workflow_id: str | None = Field(default=None, min_length=1, max_length=200)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    graph: WorkflowGraph | None = None

    @model_validator(mode="after")
    def require_change(self) -> _UpdateWorkflowPlan:
        if self.title is None and self.graph is None:
            raise ValueError("update_workflow requires title or graph")
        return self


class _LinkWorkflowToProjectPlan(_PlanModel):
    action: Literal["link_workflow_to_project"]
    workflow_id: str = Field(min_length=1, max_length=200)
    project_id: str | None = Field(default=None, min_length=1, max_length=200)
    display_name: str | None = Field(default=None, min_length=1, max_length=200)


WorkflowInputPlan: TypeAlias = Annotated[
    _ClarificationPlan | _DraftPlan | _CreateEmptyWorkflowPlan | _CreateWorkflowPlan | _UpdateWorkflowPlan | _LinkWorkflowToProjectPlan,
    Field(discriminator="action"),
]
WORKFLOW_INPUT_PLAN_ADAPTER = TypeAdapter(WorkflowInputPlan)


class WorkflowInputService:
    """Workflow input session state machine with durable encrypted persistence."""

    _FOLLOW_UP_STATUSES = frozenset({"needs_clarification", "draft"})
    _STOPPABLE_STATUSES = frozenset({"running", "needs_clarification", "draft"})

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
        self.planner = planner
        self.project_linker = project_linker
        self.transcriber = transcriber
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
        timezone: str | None = None,
        vault_key_id: str | None = None,
        optimistic_save: bool = False,
    ) -> WorkflowInputSessionResult:
        started = time.perf_counter()
        resolved_vault_key_id = self._resolve_vault_key_id(user_id, vault_key_id)
        key_resolved_at = time.perf_counter()
        session = self._create_session(
            user_id, selected_workflow_id, selected_project_id, resolved_vault_key_id,
            persist_initial=not (optimistic_save and input_type == "text"),
        )
        session["timezone"] = timezone
        session["_timings"] = {
            "key_resolution_seconds": key_resolved_at - started,
            "initial_session_seconds": time.perf_counter() - key_resolved_at,
        }
        session["_batch_events"] = True
        session["_batch_owner_thread"] = threading.get_ident()
        try:
            result = self._process_input(session, text=text, input_type=input_type, audio_ref=audio_ref,
                                         vault_key_id=resolved_vault_key_id, optimistic_save=optimistic_save)
        finally:
            self._flush_persistence(session, resolved_vault_key_id)
            session.pop("_batch_events", None)
            session.pop("_batch_owner_thread", None)
        result.authoring_metrics = {
            **(result.authoring_metrics or {}),
            "service_seconds": round(time.perf_counter() - started, 3),
            "service_stages_seconds": {key: round(value, 3) for key, value in session["_timings"].items()},
        }
        return result

    def follow_up(
        self,
        *,
        user_id: str,
        session_id: str,
        text: str,
        vault_key_id: str | None = None,
    ) -> WorkflowInputSessionResult:
        resolved_vault_key_id = self._resolve_vault_key_id(user_id, vault_key_id)
        session = self._require_session(session_id, user_id, resolved_vault_key_id)
        if session["status"] not in self._FOLLOW_UP_STATUSES:
            self._append_event(session, "follow_up_rejected", {"status": session["status"]}, status="error", vault_key_id=resolved_vault_key_id)
            return self._result(
                session,
                error="This workflow input session no longer accepts follow-up instructions.",
                error_code=WORKFLOW_INPUT_SESSION_STATE_INVALID,
            )
        session["status"] = "running"
        session["_batch_events"] = True
        session["_batch_owner_thread"] = threading.get_ident()
        try:
            self._append_event(session, "followup_received", {"text_length": len(text)}, vault_key_id=resolved_vault_key_id)
            return self._process_input(session, text=text, input_type="text", audio_ref=None,
                                       vault_key_id=resolved_vault_key_id, optimistic_save=False)
        finally:
            self._flush_persistence(session, resolved_vault_key_id)
            session.pop("_batch_events", None)
            session.pop("_batch_owner_thread", None)

    def commit_queued(self, session_id: str) -> WorkflowInputSessionResult | None:
        """Replay an encrypted queued plan; safe to retry after worker loss."""
        if not isinstance(self.repository, DirectusWorkflowInputRepository):
            raise WorkflowInputUnavailableError(WORKFLOW_INPUT_ACTION_UNAVAILABLE, "Queued workflow persistence is unavailable.")
        owner = self.repository.queued_session_owner(session_id)
        if owner is None:
            return None
        user_id, vault_key_id = owner
        # Directus is the replay authority. The API process may still hold a
        # newer in-memory copy from a failed final flush.
        session = self.repository.get_session(session_id, user_id, vault_key_id)
        if session is None:
            raise WorkflowNotFoundError(session_id)
        self._sessions[session_id] = session
        if session["status"] != "queued":
            return self._result(session)
        plan = WORKFLOW_INPUT_PLAN_ADAPTER.validate_python(session.get("pending_plan"))
        session["commit_attempts"] = int(session.get("commit_attempts") or 0) + 1
        session["_batch_events"] = True
        session["_batch_owner_thread"] = threading.get_ident()
        try:
            self._append_event(session, "commit_started", {}, vault_key_id=vault_key_id)
            result = self._apply_plan(session, plan, vault_key_id)
            session.pop("pending_plan", None)
            session.pop("pending_before", None)
            session.pop("queued_user_id", None)
            return result
        except (ValueError, ValidationError, WorkflowNotFoundError) as exc:
            logger.exception("Queued workflow commit failed for session %s", session_id)
            return self._fail_session(session, "commit_failed", "WORKFLOW_INPUT_COMMIT_FAILED",
                                      "The workflow could not be saved. Please try again.", vault_key_id, exc)
        except Exception as exc:
            logger.exception("Queued workflow commit will retry for session %s", session_id)
            session["status"] = "queued"
            session["workflow"] = None
            if session["commit_attempts"] >= 20:
                return self._fail_session(session, "commit_failed", "WORKFLOW_INPUT_COMMIT_FAILED",
                                          "The workflow could not be saved. Please try again.", vault_key_id, exc)
            self._append_event(session, "commit_retry", {}, status="error", vault_key_id=vault_key_id)
            return self._result(session)
        finally:
            self._flush_persistence(session, vault_key_id)
            session.pop("_batch_events", None)
            session.pop("_batch_owner_thread", None)

    def stop(
        self,
        *,
        user_id: str,
        session_id: str,
        vault_key_id: str | None = None,
    ) -> WorkflowInputSessionResult:
        resolved_vault_key_id = self._resolve_vault_key_id(user_id, vault_key_id)
        session = self._require_session(session_id, user_id, resolved_vault_key_id)
        if session["status"] not in self._STOPPABLE_STATUSES:
            self._append_event(session, "stop_rejected", {"status": session["status"]}, status="error", vault_key_id=resolved_vault_key_id)
            return self._result(
                session,
                error="This workflow input session cannot be stopped in its current state.",
                error_code=WORKFLOW_INPUT_SESSION_STATE_INVALID,
            )
        session["status"] = "stopped"
        session["cancellation_requested_at"] = int(time.time())
        self._append_event(session, "stopped", {}, vault_key_id=resolved_vault_key_id)
        return self._result(session)

    def undo(
        self,
        *,
        user_id: str,
        session_id: str,
        vault_key_id: str | None = None,
    ) -> WorkflowInputSessionResult:
        resolved_vault_key_id = self._resolve_vault_key_id(user_id, vault_key_id)
        session = self._require_session(session_id, user_id, resolved_vault_key_id)
        mutation = self._last_undoable_mutation(session)
        if mutation is None:
            self._append_event(session, "undo_unavailable", {}, status="error", vault_key_id=resolved_vault_key_id)
            return self._result(
                session,
                error="No workflow input mutation is available to undo.",
                error_code=WORKFLOW_INPUT_UNDO_UNAVAILABLE,
            )
        if mutation.target_type == "workflow":
            try:
                current = self.workflow_service.get_workflow(mutation.target_id, user_id, resolved_vault_key_id)
            except WorkflowNotFoundError:
                current = None
            expected_version = (mutation.after or {}).get("current_version_id")
            expected = mutation.after or {}
            if (current is None or current.current_version_id != expected_version
                    or any(getattr(current, field) != expected.get(field) for field in ("title", "description", "category", "icon", "enabled"))
                    or current.model_dump(mode="json").get("graph") != expected.get("graph")):
                self._append_event(session, "undo_conflict", {"target_id": mutation.target_id}, status="error", vault_key_id=resolved_vault_key_id)
                return self._result(
                    session,
                    error="This workflow changed after the AI edit. Open version history to restore it without losing later changes.",
                    error_code=WORKFLOW_INPUT_UNDO_CONFLICT,
                )
        if mutation.type == "create_workflow":
            self.workflow_service.delete_workflow(mutation.target_id, user_id)
        elif mutation.type == "update_workflow" and mutation.before:
            self.workflow_service.update_workflow(
                mutation.target_id,
                user_id,
                title=mutation.before.get("title"),
                graph=mutation.before.get("graph"),
                description=mutation.before.get("description"),
                category=mutation.before.get("category"),
                icon=mutation.before.get("icon"),
                vault_key_id=resolved_vault_key_id,
            )
        elif mutation.type == "link_workflow_to_project" and self.project_linker is not None:
            project_item_id = (mutation.after or {}).get("project_item_id")
            if not project_item_id or not self.project_linker.unlink_project_item(str(project_item_id)):
                self._append_event(session, "undo_failed", {"mutation_type": mutation.type}, status="error", vault_key_id=resolved_vault_key_id)
                return self._result(session, error="The project workflow link could not be undone.")
        else:
            self._append_event(session, "undo_failed", {"mutation_type": mutation.type}, status="error", vault_key_id=resolved_vault_key_id)
            return self._result(session, error=f"Undo is not supported for {mutation.type}.", error_code=WORKFLOW_INPUT_UNDO_UNAVAILABLE)

        mutation.undone_at = int(time.time())
        self._save_mutation(session, mutation, resolved_vault_key_id)
        session["status"] = "undone"
        self._append_event(
            session,
            "undone",
            {"mutation_type": mutation.type, "target_id": mutation.target_id},
            vault_key_id=resolved_vault_key_id,
        )
        return self._result(session)

    def status(
        self,
        session_id: str,
        user_id: str | None = None,
        vault_key_id: str | None = None,
    ) -> WorkflowInputSessionDetail:
        session = self._get_session(session_id, user_id, vault_key_id)
        if user_id is not None and session["user_id"] != user_id:
            raise PermissionError("Workflow input session not found")
        result = self._result(session)
        return WorkflowInputSessionDetail(
            **result.model_dump(),
            events=list(session["events"]),
            draft_graph=deepcopy(session.get("draft_graph")),
            mutations=list(session["mutations"]),
        )

    def events(
        self,
        session_id: str,
        after_event_id: int = 0,
        user_id: str | None = None,
        vault_key_id: str | None = None,
    ) -> list[WorkflowInputEvent]:
        if after_event_id < 0:
            raise ValueError("after_event_id must be greater than or equal to zero")
        if user_id is not None and self.repository is not None:
            events = self.repository.list_events(session_id, user_id, after_event_id, vault_key_id)
            if events:
                return events
        session = self._get_session(session_id, user_id, vault_key_id)
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
        vault_key_id: str | None,
        optimistic_save: bool = False,
    ) -> WorkflowInputSessionResult:
        try:
            if input_type == "audio":
                if self.transcriber is None:
                    raise WorkflowInputUnavailableError(
                        WORKFLOW_INPUT_TRANSCRIPTION_UNAVAILABLE,
                        "Audio transcription is not available for workflow input.",
                    )
                self._append_event(session, "transcribing_started", {}, vault_key_id=vault_key_id)
                self._flush_persistence(session, vault_key_id)
                text = self.transcriber(audio_ref or {})
                self._append_event(session, "transcript_ready", {"text_length": len(text)}, vault_key_id=vault_key_id)
            if input_type != "text" and input_type != "audio":
                raise ValueError("workflow input type is invalid")
            if text is None:
                raise ValueError("workflow input text is required")

            sanitized_text, stats = sanitize_workflow_input_text(text)
            if not sanitized_text.strip():
                raise ValueError("workflow input text must not be empty")
            if int(stats.get("removed_count", 0) or 0) > 0:
                self._append_event(
                    session,
                    "input_sanitized",
                    {"removed_count": int(stats.get("removed_count") or 0)},
                    vault_key_id=vault_key_id,
                )
            self._append_event(session, "input_received", {"text_length": len(sanitized_text)}, vault_key_id=vault_key_id)
            self._append_event(session, "planning_started", {}, vault_key_id=vault_key_id)
            # The optimistic text endpoint has not returned a session ID yet
            # and cannot be stopped by the caller while planning. Persist its
            # events with the validated queued plan in one encrypted batch.
            if not (optimistic_save and input_type == "text"):
                self._flush_persistence(session, vault_key_id)
            if self.planner is None:
                raise WorkflowInputUnavailableError(
                    WORKFLOW_INPUT_PLANNER_UNAVAILABLE,
                    "Structured workflow planning is not available.",
                )
            context_started = time.perf_counter()
            context = self._planner_context(session, vault_key_id)
            self._record_timing(session, "context_seconds", context_started)
            plan = self.planner.plan(text=sanitized_text, context=context)
            if isinstance(plan, dict) and isinstance(plan.get("_authoring_metrics"), dict):
                session["authoring_metrics"] = plan.pop("_authoring_metrics")
            if session["status"] == "stopped":
                return self._result(session)
            validated_plan = WORKFLOW_INPUT_PLAN_ADAPTER.validate_python(plan)
            self._append_event(session, "validation_passed", {}, vault_key_id=vault_key_id)
            if optimistic_save and isinstance(validated_plan, (_CreateWorkflowPlan, _UpdateWorkflowPlan)):
                return self._queue_plan(session, validated_plan, vault_key_id)
            return self._apply_plan(session, validated_plan, vault_key_id)
        except WorkflowInputUnavailableError as exc:
            return self._fail_session(session, "capability_unavailable", exc.code, str(exc), vault_key_id)
        except (ValidationError, ValueError) as exc:
            return self._fail_session(session, "validation_failed", "WORKFLOW_INPUT_VALIDATION_FAILED", str(exc), vault_key_id)
        except WorkflowNotFoundError as exc:
            return self._fail_session(session, "target_not_found", "WORKFLOW_INPUT_TARGET_NOT_FOUND", "Workflow target was not found.", vault_key_id, exc)
        except Exception as exc:  # Boundary: logs internal detail and returns a safe durable error state.
            logger.exception("Workflow input processing failed for session %s", session["id"])
            return self._fail_session(session, "failed", "WORKFLOW_INPUT_PROCESSING_FAILED", "Workflow input processing failed.", vault_key_id, exc)

    def _queue_plan(
        self,
        session: dict[str, Any],
        plan: _CreateWorkflowPlan | _UpdateWorkflowPlan,
        vault_key_id: str | None,
    ) -> WorkflowInputSessionResult:
        if not isinstance(self.repository, DirectusWorkflowInputRepository):
            return self._apply_plan(session, plan, vault_key_id)
        if isinstance(plan, _CreateWorkflowPlan):
            validate_workflow_readiness(plan.graph, require_schedule=True)
            validate_workflow_composition_refs(plan.graph)
            session["assumptions"] = list(plan.assumptions)
        else:
            workflow_id = plan.workflow_id or session.get("selected_workflow_id")
            if not workflow_id:
                raise ValueError("update_workflow requires workflow_id or a selected workflow")
            cached = session.get("_selected_workflow_detail")
            before = cached if isinstance(cached, WorkflowDetail) and cached.id == workflow_id else self.workflow_service.get_workflow(
                workflow_id, session["user_id"], vault_key_id,
            )
            graph = plan.graph or before.graph
            validate_workflow_readiness(graph, require_schedule=before.enabled)
            validate_workflow_composition_refs(graph, before.graph)
            session["pending_before"] = before.model_dump(mode="json")
        session["pending_plan"] = plan.model_dump(mode="json", by_alias=True)
        session["queued_user_id"] = session["user_id"]
        session["status"] = "queued"
        session["message"] = "Workflow prepared. Saving now."
        self._append_event(session, "queued", {}, vault_key_id=vault_key_id)
        return self._result(session)

    def _apply_plan(
        self,
        session: dict[str, Any],
        plan: WorkflowInputPlan,
        vault_key_id: str | None,
    ) -> WorkflowInputSessionResult:
        if session["status"] == "stopped":
            return self._result(session)
        if isinstance(plan, _ClarificationPlan):
            session["status"] = "needs_clarification"
            session["message"] = plan.message
            self._append_event(session, "clarification_requested", {"message_length": len(plan.message)}, vault_key_id=vault_key_id)
            return self._result(session, message=plan.message)
        if isinstance(plan, _DraftPlan):
            session["status"] = "draft"
            session["draft_graph"] = plan.draft_graph.model_dump(mode="json", by_alias=True)
            self._append_event(
                session,
                "draft_saved",
                {"node_count": len(plan.draft_graph.nodes)},
                vault_key_id=vault_key_id,
            )
            return self._result(session)
        if isinstance(plan, _CreateEmptyWorkflowPlan):
            graph = WorkflowGraph.model_validate({"version": 2, "trigger_node_id": None, "nodes": [], "edges": []})
            workflow_started = time.perf_counter()
            workflow = self.workflow_service.create_workflow(
                session["user_id"], plan.title, graph, enabled=False,
                source="workflow_input", created_by_assistant=True, vault_key_id=vault_key_id,
            )
            self._record_timing(session, "workflow_persistence_seconds", workflow_started)
            session["status"] = "draft"
            session["workflow"] = workflow
            self._append_mutation(
                session,
                WorkflowInputMutation(
                    id=str(uuid.uuid4()), type="create_workflow", target_type="workflow",
                    target_id=workflow.id, after=workflow.model_dump(mode="json"),
                    created_at=int(time.time()),
                ),
                vault_key_id,
            )
            self._append_event(session, "draft_saved", {"workflow_id": workflow.id}, vault_key_id=vault_key_id)
            return self._result(session, workflow=workflow)
        if isinstance(plan, _CreateWorkflowPlan):
            return self._create_workflow(session, plan, vault_key_id)
        if isinstance(plan, _UpdateWorkflowPlan):
            return self._update_workflow(session, plan, vault_key_id)
        if isinstance(plan, _LinkWorkflowToProjectPlan):
            return self._link_workflow_to_project(session, plan, vault_key_id)
        raise ValueError("Workflow input action is unavailable")

    def _create_workflow(
        self,
        session: dict[str, Any],
        plan: _CreateWorkflowPlan,
        vault_key_id: str | None,
    ) -> WorkflowInputSessionResult:
        session["assumptions"] = list(plan.assumptions)
        for assumption in plan.assumptions:
            self._append_event(session, "assumption", {"text_length": len(assumption)}, vault_key_id=vault_key_id)
        graph = plan.graph.model_dump(mode="json", by_alias=True)
        validate_workflow_readiness(plan.graph, require_schedule=True)
        validate_workflow_composition_refs(plan.graph)
        self._stream_draft_nodes(session, graph, vault_key_id)
        if session["status"] == "stopped":
            return self._result(session)
        workflow_started = time.perf_counter()
        workflow = self.workflow_service.create_workflow(
            session["user_id"],
            plan.title,
            plan.graph,
            enabled=False,
            source="workflow_input",
            created_by_assistant=True,
            vault_key_id=vault_key_id,
            description=plan.description,
            category=plan.category,
            icon=plan.icon,
            workflow_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"workflow-input:{session['id']}:create")) if session.get("pending_plan") else None,
            initial_version_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"workflow-input:{session['id']}:version")) if session.get("pending_plan") else None,
        )
        self._record_timing(session, "workflow_persistence_seconds", workflow_started)
        session["status"] = "executed"
        session["message"] = None
        session["workflow"] = workflow
        self._append_mutation(
            session,
            WorkflowInputMutation(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"workflow-input:{session['id']}:mutation")) if session.get("pending_plan") else str(uuid.uuid4()),
                type="create_workflow",
                target_type="workflow",
                target_id=workflow.id,
                after=workflow.model_dump(mode="json"),
                created_at=int(time.time()),
            ),
            vault_key_id,
        )
        self._append_event(session, "committed", {"mutation_type": "create_workflow", "workflow_id": workflow.id}, vault_key_id=vault_key_id)
        return self._result(session, workflow=workflow)

    def _update_workflow(
        self,
        session: dict[str, Any],
        plan: _UpdateWorkflowPlan,
        vault_key_id: str | None,
    ) -> WorkflowInputSessionResult:
        workflow_id = plan.workflow_id or session.get("selected_workflow_id")
        if not workflow_id:
            raise ValueError("update_workflow requires workflow_id or a selected workflow")
        workflow_read_started = time.perf_counter()
        cached = session.get("_selected_workflow_detail")
        pending_before = session.get("pending_before")
        before = (WorkflowDetail.model_validate(pending_before) if isinstance(pending_before, dict)
                  else cached if isinstance(cached, WorkflowDetail) and cached.id == workflow_id
                  else self.workflow_service.get_workflow(workflow_id, session["user_id"], vault_key_id))
        self._record_timing(session, "workflow_read_seconds", workflow_read_started)
        graph = plan.graph or before.graph
        validate_workflow_readiness(graph, require_schedule=before.enabled)
        validate_workflow_composition_refs(graph, before.graph)
        self._stream_draft_nodes(session, graph.model_dump(mode="json", by_alias=True), vault_key_id)
        if session["status"] == "stopped":
            return self._result(session)
        workflow_started = time.perf_counter()
        workflow = self.workflow_service.update_workflow(
            workflow_id,
            session["user_id"],
            title=plan.title,
            graph=graph,
            vault_key_id=vault_key_id,
            expected_record_version=before.version,
            known_prior=before,
            new_version_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"workflow-input:{session['id']}:version")) if session.get("pending_plan") else None,
        )
        self._record_timing(session, "workflow_persistence_seconds", workflow_started)
        session["status"] = "executed"
        session["message"] = None
        session["workflow"] = workflow
        self._append_mutation(
            session,
            WorkflowInputMutation(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"workflow-input:{session['id']}:mutation")) if session.get("pending_plan") else str(uuid.uuid4()),
                type="update_workflow",
                target_type="workflow",
                target_id=workflow.id,
                before=before.model_dump(mode="json"),
                after=workflow.model_dump(mode="json"),
                created_at=int(time.time()),
            ),
            vault_key_id,
        )
        self._append_event(session, "committed", {"mutation_type": "update_workflow", "workflow_id": workflow.id}, vault_key_id=vault_key_id)
        return self._result(session, workflow=workflow)

    def _link_workflow_to_project(
        self,
        session: dict[str, Any],
        plan: _LinkWorkflowToProjectPlan,
        vault_key_id: str | None,
    ) -> WorkflowInputSessionResult:
        if self.project_linker is None:
            raise WorkflowInputUnavailableError(
                WORKFLOW_INPUT_ACTION_UNAVAILABLE,
                "Project workflow linking is not available.",
            )
        project_id = plan.project_id or session.get("selected_project_id")
        if not project_id:
            raise ValueError("link_workflow_to_project requires project_id or a selected project")
        workflow = self.workflow_service.get_workflow(plan.workflow_id, session["user_id"], vault_key_id)
        project_item = self.project_linker.link_workflow(
            user_id=session["user_id"],
            project_id=project_id,
            workflow_id=workflow.id,
            display_name=plan.display_name or workflow.title,
        )
        project_item_id = project_item.get("project_item_id")
        if not isinstance(project_item_id, str) or not project_item_id:
            raise ValueError("Project linker returned an invalid project item")
        session["status"] = "executed"
        session["project_item"] = project_item
        self._append_mutation(
            session,
            WorkflowInputMutation(
                id=str(uuid.uuid4()),
                type="link_workflow_to_project",
                target_type="project_item",
                target_id=project_item_id,
                after=project_item,
                created_at=int(time.time()),
            ),
            vault_key_id,
        )
        self._append_event(
            session,
            "committed",
            {"mutation_type": "link_workflow_to_project", "workflow_id": workflow.id},
            vault_key_id=vault_key_id,
        )
        return self._result(session, project_item=project_item)

    def _stream_draft_nodes(self, session: dict[str, Any], graph: dict[str, Any], vault_key_id: str | None) -> None:
        session["draft_graph"] = deepcopy(graph)
        for node in graph.get("nodes") or []:
            node_type = node.get("type") if isinstance(node, dict) else "unknown"
            self._append_event(session, "draft_node_added", {"node_type": str(node_type)}, vault_key_id=vault_key_id)

    def _planner_context(self, session: dict[str, Any], vault_key_id: str | None) -> dict[str, Any]:
        workflows = (
            [item.model_dump(mode="json") for item in self.workflow_service.list_workflows(session["user_id"], vault_key_id)]
            if getattr(self.planner, "requires_workflow_overview", True)
            else []
        )
        selected_workflow_id = session.get("selected_workflow_id")
        selected_workflow = None
        session.pop("_selected_workflow_detail", None)
        if selected_workflow_id:
            try:
                detail = self.workflow_service.get_workflow(selected_workflow_id, session["user_id"], vault_key_id)
                session["_selected_workflow_detail"] = detail
                selected_workflow = detail.model_dump(mode="json")
            except WorkflowNotFoundError:
                selected_workflow = None
        return {
            "workflows": workflows,
            "selected_workflow": selected_workflow,
            "projects": [],
            "selected_project_id": session.get("selected_project_id"),
            "timezone": session.get("timezone"),
        }

    def _create_session(
        self,
        user_id: str,
        selected_workflow_id: str | None,
        selected_project_id: str | None,
        vault_key_id: str | None,
        *,
        persist_initial: bool = True,
    ) -> dict[str, Any]:
        now = int(time.time())
        session = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "status": "running",
            "selected_workflow_id": selected_workflow_id,
            "selected_project_id": selected_project_id,
            "timezone": None,
            "authoring_metrics": None,
            "events": [],
            "mutations": [],
            "draft_graph": None,
            "workflow": None,
            "project_item": None,
            "message": None,
            "assumptions": [],
            "commit_attempts": 0,
            "cancellation_requested_at": None,
            "created_at": now,
            "updated_at": now,
            "expires_at": now + WORKFLOW_INPUT_SESSION_TTL_SECONDS,
        }
        self._sessions[session["id"]] = session
        if persist_initial:
            self._persist_session(session, vault_key_id)
        return session

    def _require_session(self, session_id: str, user_id: str, vault_key_id: str | None) -> dict[str, Any]:
        session = self._get_session(session_id, user_id, vault_key_id)
        if session["user_id"] != user_id:
            raise PermissionError("Workflow input session not found")
        return session

    def _get_session(self, session_id: str, user_id: str | None, vault_key_id: str | None) -> dict[str, Any]:
        session = self._sessions.get(session_id)
        if (session is None or session.get("status") == "queued") and user_id is not None and self.repository is not None:
            refreshed = self.repository.get_session(session_id, user_id, vault_key_id)
            if refreshed is not None:
                session = refreshed
                self._sessions[session_id] = refreshed
        if session is None:
            raise KeyError(session_id)
        return session

    def _append_event(
        self,
        session: dict[str, Any],
        event_type: str,
        payload: dict[str, EventPayloadValue],
        *,
        status: str = "ok",
        vault_key_id: str | None,
    ) -> None:
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
        if self._is_batch_owner(session):
            session.setdefault("_pending_events", []).append(event)
            return
        if self.repository is not None:
            self.repository.save_event(event, session["user_id"], vault_key_id)
        self._persist_session(session, vault_key_id)

    def _append_mutation(self, session: dict[str, Any], mutation: WorkflowInputMutation, vault_key_id: str | None) -> None:
        session["mutations"] = [item for item in session["mutations"] if item.id != mutation.id]
        session["mutations"].append(mutation)
        self._save_mutation(session, mutation, vault_key_id)

    def _save_mutation(self, session: dict[str, Any], mutation: WorkflowInputMutation, vault_key_id: str | None) -> None:
        if self.repository is not None:
            started = time.perf_counter()
            self.repository.save_mutation(mutation, session["id"], session["user_id"], vault_key_id)
            self._record_timing(session, "mutation_persistence_seconds", started)
        if not self._is_batch_owner(session):
            self._persist_session(session, vault_key_id)

    def _last_undoable_mutation(self, session: dict[str, Any]) -> WorkflowInputMutation | None:
        for mutation in reversed(session["mutations"]):
            if mutation.undone_at is None:
                return mutation
        return None

    def _fail_session(
        self,
        session: dict[str, Any],
        event_type: str,
        error_code: str,
        message: str,
        vault_key_id: str | None,
        exc: Exception | None = None,
    ) -> WorkflowInputSessionResult:
        if exc is not None:
            logger.info("Workflow input session %s failed with %s", session["id"], type(exc).__name__)
        session["status"] = "failed"
        self._append_event(session, event_type, {"error_code": error_code}, status="error", vault_key_id=vault_key_id)
        return self._result(session, error=message, error_code=error_code)

    def _result(
        self,
        session: dict[str, Any],
        *,
        message: str | None = None,
        error: str | None = None,
        error_code: str | None = None,
        workflow: WorkflowDetail | None = None,
        project_item: dict[str, Any] | None = None,
    ) -> WorkflowInputSessionResult:
        return WorkflowInputSessionResult(
            session_id=session["id"],
            status=session["status"],
            event_cursor=len(session["events"]),
            message=message or session.get("message"),
            error=error,
            error_code=error_code,
            workflow=workflow or session.get("workflow"),
            preview_workflow=self._queued_preview(session),
            project_item=project_item or session.get("project_item"),
            undo_available=session["status"] in {"executed", "draft"} and self._last_undoable_mutation(session) is not None,
            assumptions=list(session.get("assumptions") or []),
            authoring_metrics=session.get("authoring_metrics"),
        )

    def _queued_preview(self, session: dict[str, Any]) -> WorkflowDetail | None:
        """Return a validated renderable graph while its durable save is pending."""
        if session.get("status") != "queued" or not isinstance(session.get("pending_plan"), dict):
            return None
        plan = WORKFLOW_INPUT_PLAN_ADAPTER.validate_python(session["pending_plan"])
        version_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"workflow-input:{session['id']}:version"))
        if isinstance(plan, _CreateWorkflowPlan):
            now = int(time.time())
            return WorkflowDetail.model_validate({
                "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"workflow-input:{session['id']}:create")),
                "title": plan.title, "description": plan.description,
                "category": plan.category or "general_knowledge", "icon": plan.icon or "help-circle",
                "status": "disabled", "enabled": False, "source": "workflow_input",
                "created_by_assistant": True, "current_version_id": version_id,
                "created_at": now, "updated_at": now,
                "trigger_summary": self.workflow_service._trigger_summary(plan.graph),
                "graph": plan.graph,
            })
        if isinstance(plan, _UpdateWorkflowPlan) and isinstance(session.get("pending_before"), dict):
            before = WorkflowDetail.model_validate(session["pending_before"])
            return before.model_copy(update={
                "title": plan.title or before.title,
                "graph": plan.graph or before.graph,
                "version": before.version + 1,
                "current_version_id": version_id,
                "updated_at": int(time.time()),
                "trigger_summary": self.workflow_service._trigger_summary(plan.graph or before.graph),
            })
        return None

    def _persist_session(self, session: dict[str, Any], vault_key_id: str | None) -> None:
        if self.repository is not None:
            self.repository.save_session(session, vault_key_id)

    def _flush_persistence(self, session: dict[str, Any], vault_key_id: str | None) -> None:
        if not self._is_batch_owner(session) or self.repository is None:
            return
        pending = session.get("_pending_events") or []
        if not pending:
            return
        started = time.perf_counter()
        save_events = getattr(self.repository, "save_events", None)
        if callable(save_events):
            save_events(pending, session["user_id"], vault_key_id)
        else:
            for event in pending:
                self.repository.save_event(event, session["user_id"], vault_key_id)
        session["_pending_events"] = []
        self._record_timing(session, "event_persistence_seconds", started)
        started = time.perf_counter()
        self._persist_session(session, vault_key_id)
        self._record_timing(session, "session_persistence_seconds", started)

    @staticmethod
    def _record_timing(session: dict[str, Any], name: str, started: float) -> None:
        timings = session.get("_timings")
        if isinstance(timings, dict):
            timings[name] = timings.get(name, 0.0) + time.perf_counter() - started

    @staticmethod
    def _is_batch_owner(session: dict[str, Any]) -> bool:
        return bool(session.get("_batch_events")) and session.get("_batch_owner_thread") == threading.get_ident()

    def _resolve_vault_key_id(self, user_id: str, vault_key_id: str | None) -> str | None:
        return self.workflow_service.resolve_user_vault_key_id(user_id, vault_key_id)


def _session_private_state(session: dict[str, Any]) -> dict[str, Any]:
    workflow = session.get("workflow")
    return {
        "selected_workflow_id": session.get("selected_workflow_id"),
        "selected_project_id": session.get("selected_project_id"),
        "timezone": session.get("timezone"),
        "authoring_metrics": deepcopy(session.get("authoring_metrics")),
        "draft_graph": deepcopy(session.get("draft_graph")),
        "workflow": workflow.model_dump(mode="json") if isinstance(workflow, WorkflowDetail) else deepcopy(workflow),
        "project_item": deepcopy(session.get("project_item")),
        "message": session.get("message"),
        "assumptions": list(session.get("assumptions") or []),
        "pending_plan": deepcopy(session.get("pending_plan")),
        "pending_before": deepcopy(session.get("pending_before")),
        "queued_user_id": session.get("queued_user_id"),
        "commit_attempts": int(session.get("commit_attempts") or 0),
        "cancellation_requested_at": session.get("cancellation_requested_at"),
    }
