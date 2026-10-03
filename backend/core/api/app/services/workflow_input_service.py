"""Durable, Vault-protected workflow-input session orchestration.

Workflow input is deliberately independent from the chat pre/main/post pipeline.
The durable Directus records contain only reconnect metadata; user text,
transcripts, drafts, planner output, and undo snapshots live in owner-scoped
Automation Vault blobs.
"""

from __future__ import annotations

import logging
import hashlib
import json
import os
import threading
import time
import uuid
from copy import deepcopy
from typing import Annotated, Any, Callable, Literal, Protocol, TypeAlias

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

from backend.core.api.app.services.workflow_input_security import redacted_event_summary, sanitize_workflow_input_text
from backend.core.api.app.services.workflow_authoring_billing import WorkflowAuthoringBillingError
from backend.core.api.app.services.workflow_models import WorkflowDetail, WorkflowGraph, WorkflowLifecycle, validate_workflow_composition_refs, validate_workflow_readiness
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
WORKFLOW_INPUT_NO_VALID_PARTIAL = "WORKFLOW_INPUT_NO_VALID_PARTIAL"
WORKFLOW_INPUT_STOP_RECOVERY_DELAY_SECONDS = 60
WORKFLOW_INPUT_STOP_CACHE_POLL_SECONDS = 0.1

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


class DragonflyWorkflowInputCheckpointStore:
    """Short-lived encrypted node checkpoints and owner-scoped stop signals.

    Directus remains the durable final authority. A checkpoint can be recovered
    by another API worker while the authoring request is still in flight.
    """

    def __init__(self, payload_cipher: WorkflowPayloadCipher) -> None:
        import redis

        address = os.getenv("DRAGONFLY_URL", "cache:6379")
        password = os.getenv("DRAGONFLY_PASSWORD", "openmates_cache")
        if "://" in address:
            self._client = redis.Redis.from_url(address, password=password, socket_connect_timeout=1, socket_timeout=1)
        else:
            host, _, port = address.partition(":")
            self._client = redis.Redis(host=host, port=int(port or "6379"), password=password,
                                       socket_connect_timeout=1, socket_timeout=1)
        self._cipher = payload_cipher

    @staticmethod
    def _key(kind: str, user_id: str, session_id: str) -> str:
        return f"workflow-input:{kind}:{_hash_owner_id(user_id)}:{session_id}"

    def save(self, user_id: str, session_id: str, checkpoints: dict[str, Any], vault_key_id: str | None) -> None:
        blob = self._cipher.encrypt_json({"checkpoints": checkpoints}, vault_key_id)
        self._client.setex(self._key("checkpoint", user_id, session_id),
                           WORKFLOW_INPUT_SESSION_TTL_SECONDS, json.dumps(blob))

    def load(self, user_id: str, session_id: str, vault_key_id: str | None) -> dict[str, Any] | None:
        value = self._client.get(self._key("checkpoint", user_id, session_id))
        if not value:
            return None
        blob = json.loads(value)
        state = self._cipher.decrypt_json(blob, vault_key_id)
        return state.get("checkpoints") if isinstance(state, dict) and isinstance(state.get("checkpoints"), dict) else None

    def request_stop(self, user_id: str, session_id: str) -> None:
        self._client.setex(self._key("cancel", user_id, session_id), 600, "1")

    def stop_requested(self, user_id: str, session_id: str) -> bool:
        return bool(self._client.exists(self._key("cancel", user_id, session_id)))

    def claim_recovery(self, user_id: str, session_id: str) -> bool:
        return bool(self._client.set(self._key("recovery", user_id, session_id), "1", nx=True, ex=120))

    def clear(self, user_id: str, session_id: str) -> None:
        self._client.delete(self._key("checkpoint", user_id, session_id),
                            self._key("cancel", user_id, session_id),
                            self._key("recovery", user_id, session_id))


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

    def get_stop_requested(self, session_id: str, user_id: str, vault_key_id: str | None) -> bool | None:
        """Read an owner's durable Stop flag without hydrating events or mutations."""
        item = self._find_one(
            self.SESSIONS,
            {"_and": [{"id": {"_eq": session_id}}, {"hashed_user_id": {"_eq": _hash_owner_id(user_id)}}]},
            fields="encrypted_state_ref",
        )
        if not item:
            return None
        state_ref = item.get("encrypted_state_ref")
        if not isinstance(state_ref, str) or not state_ref:
            raise RuntimeError("Workflow input session is missing its encrypted state")
        state = self._load_private_blob(user_id, state_ref, vault_key_id)
        if not isinstance(state, dict):
            raise RuntimeError("Workflow input session state is invalid")
        requested = state.get("stop_requested", False)
        if not isinstance(requested, bool):
            raise RuntimeError("Workflow input session Stop state is invalid")
        return requested

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
            if str(item.get("operation_id") or "").startswith("undo:"):
                continue  # Inverse transaction rows are not a new user undo action.
            before = self._load_optional_blob(user_id, item.get("encrypted_before_ref"), vault_key_id)
            after = self._load_optional_blob(user_id, item.get("encrypted_after_ref"), vault_key_id)
            mutations.append(
                WorkflowInputMutation(
                    id=str(item["id"]),
                    type=str(item["type"]),
                    target_type=str(item["target_type"]),
                    target_id=str(item["target_id"]),
                    operation_id=str(item["operation_id"]) if item.get("operation_id") else None,
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
    type: Literal["create_workflow", "update_workflow", "delete_workflow", "restore_deleted_workflow", "link_workflow_to_project"]
    target_type: Literal["workflow", "project_item"]
    target_id: str
    operation_id: str | None = None
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
    workflows: list[WorkflowDetail] = Field(default_factory=list)
    preview_workflows: list[WorkflowDetail] = Field(default_factory=list)
    changes: list[dict[str, Any]] = Field(default_factory=list)
    project_item: dict[str, Any] | None = None
    undo_available: bool = False
    assumptions: list[str] = Field(default_factory=list)
    authoring_metrics: dict[str, Any] | None = None
    stop_requested: bool = False
    partial_reason: Literal["stopped", "provider_error"] | None = None
    partial_warning: str | None = None
    partial_previews: list[dict[str, Any]] = Field(default_factory=list)


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
    expected_record_version: int | None = Field(default=None, ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2_000)
    category: str | None = None
    icon: str | None = None
    graph: WorkflowGraph | None = None
    assumptions: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def require_change(self) -> _UpdateWorkflowPlan:
        if all(value is None for value in (self.title, self.description, self.category, self.icon, self.graph)):
            raise ValueError("update_workflow requires a change")
        return self


class _BatchPlan(_PlanModel):
    action: Literal["batch"]
    operations: list[_CreateWorkflowPlan | _UpdateWorkflowPlan] = Field(min_length=1, max_length=12)


class _PartialPlan(_PlanModel):
    action: Literal["partial"]
    reason: Literal["stopped", "provider_error"]
    notice: str = Field(min_length=1, max_length=2_000)
    operations: list[_CreateWorkflowPlan | _UpdateWorkflowPlan] = Field(default_factory=list, max_length=12)


class _LinkWorkflowToProjectPlan(_PlanModel):
    action: Literal["link_workflow_to_project"]
    workflow_id: str = Field(min_length=1, max_length=200)
    project_id: str | None = Field(default=None, min_length=1, max_length=200)
    display_name: str | None = Field(default=None, min_length=1, max_length=200)


WorkflowInputPlan: TypeAlias = Annotated[
    _ClarificationPlan | _DraftPlan | _CreateEmptyWorkflowPlan | _CreateWorkflowPlan | _UpdateWorkflowPlan | _LinkWorkflowToProjectPlan | _BatchPlan | _PartialPlan,
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
        checkpoint_store: DragonflyWorkflowInputCheckpointStore | None = None,
    ) -> None:
        self.workflow_service = workflow_service
        self.planner = planner
        self.project_linker = project_linker
        self.transcriber = transcriber
        self.repository = repository
        self.checkpoint_store = checkpoint_store
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
        on_event: Callable[[dict[str, Any]], None] | None = None,
        idempotency_key: str | None = None,
        source_chat_id: str | None = None,
        execution_mode: Literal["saved", "run_once"] = "saved",
        return_outputs: dict[str, dict[str, str]] | None = None,
    ) -> WorkflowInputSessionResult:
        if execution_mode == "run_once" and not source_chat_id:
            raise ValueError("One-time chat workflows require a source chat")
        started = time.perf_counter()
        resolved_vault_key_id = self._resolve_vault_key_id(user_id, vault_key_id)
        key_resolved_at = time.perf_counter()
        stable_session_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"workflow-input:{user_id}:{idempotency_key}")) if idempotency_key else None
        request_digest = (hashlib.sha256(sanitize_workflow_input_text(text)[0].encode("utf-8")).hexdigest()
                          if stable_session_id and isinstance(text, str) else None)
        if stable_session_id and self.repository is not None:
            existing = self.repository.get_session(stable_session_id, user_id, resolved_vault_key_id)
            if existing is not None:
                if existing.get("request_digest") != request_digest:
                    raise ValueError("Workflow input idempotency key was reused for a different instruction")
                existing = self._sessions.get(stable_session_id) or existing
                self._sessions[stable_session_id] = existing
                if callable(on_event):
                    on_event({"type": "started", "session_id": stable_session_id, "status": existing["status"]})
                return self._result(existing)
        session = self._create_session(
            user_id, selected_workflow_id, selected_project_id, resolved_vault_key_id,
            persist_initial=not (optimistic_save and input_type == "text") and on_event is None,
            session_id=stable_session_id,
            request_digest=request_digest,
        )
        session["timezone"] = timezone
        session["source_chat_id"] = source_chat_id
        session["execution_mode"] = execution_mode
        session["return_outputs"] = return_outputs or {}
        session["_on_stream_event"] = on_event
        if on_event is not None:
            self._persist_session(session, resolved_vault_key_id)
            self._emit_stream(session, {"type": "started", "session_id": session["id"], "status": "running"})
        session["_timings"] = {
            "key_resolution_seconds": key_resolved_at - started,
            "initial_session_seconds": time.perf_counter() - key_resolved_at,
        }
        # This is a newly initialized session, so its durable Stop state is
        # already known. Cache signals remain immediate; the regular one-second
        # database fallback still catches a failed or lost cache Stop write.
        session["_last_durable_stop_check"] = time.monotonic()
        session["_batch_events"] = True
        session["_batch_owner_thread"] = threading.get_ident()
        try:
            result = self._process_input(session, text=text, input_type=input_type, audio_ref=audio_ref,
                                         vault_key_id=resolved_vault_key_id, optimistic_save=optimistic_save)
        finally:
            self._flush_persistence(session, resolved_vault_key_id)
            if session.get("status") not in {"running", "queued"} and self.checkpoint_store is not None:
                try:
                    self.checkpoint_store.clear(user_id, session["id"])
                except Exception:
                    logger.warning("Workflow input checkpoint cleanup failed")
            session.pop("_batch_events", None)
            session.pop("_batch_owner_thread", None)
            session.pop("_on_stream_event", None)
        result.authoring_metrics = {
            **(result.authoring_metrics or {}),
            "service_seconds": round(time.perf_counter() - started, 3),
            "service_stages_seconds": {key: round(value, 3) for key, value in session["_timings"].items()},
            "service_poll_counts": dict(session.get("_poll_counts") or {}),
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
            session.pop("pending_operation_id", None)
            session.pop("queued_user_id", None)
            return result
        except (ValueError, ValidationError, WorkflowNotFoundError) as exc:
            logger.warning("Queued workflow commit failed for session %s with %s", session_id, type(exc).__name__)
            return self._fail_session(session, "commit_failed", "WORKFLOW_INPUT_COMMIT_FAILED",
                                      "The workflow could not be saved. Please try again.", vault_key_id, exc)
        except Exception as exc:
            logger.warning("Queued workflow commit will retry for session %s after %s", session_id, type(exc).__name__)
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
        if session["status"] == "running":
            session["stop_requested"] = True
            if self.checkpoint_store is not None:
                try:
                    self.checkpoint_store.request_stop(user_id, session_id)
                except Exception:
                    logger.warning("Workflow input stop cache signal failed")
            session["cancellation_requested_at"] = int(time.time())
            self._append_event(session, "stop_requested", {}, vault_key_id=resolved_vault_key_id)
            return self._result(session)
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
        if mutation.operation_id:
            undo_batch = getattr(self.workflow_service, "undo_authoring_batch", None)
            if not callable(undo_batch):
                return self._result(session, error="Batch undo is unavailable.", error_code=WORKFLOW_INPUT_UNDO_UNAVAILABLE)
            try:
                undo_batch(user_id, mutation.operation_id, resolved_vault_key_id, session_id=session_id)
            except (ValueError, WorkflowNotFoundError):
                self._append_event(session, "undo_conflict", {}, status="error", vault_key_id=resolved_vault_key_id)
                return self._result(session, error="A workflow changed after the AI edit. Open version history to restore it safely.", error_code=WORKFLOW_INPUT_UNDO_CONFLICT)
            undone_at = int(time.time())
            for item in session["mutations"]:
                if item.operation_id == mutation.operation_id:
                    item.undone_at = undone_at
            session["status"] = "undone"
            self._append_event(session, "undone", {"mutation_type": "authoring_batch"}, vault_key_id=resolved_vault_key_id)
            return self._result(session)
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
                allow_data_dependencies=True,
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
        if user_id is not None and session.get("status") == "running" and session.get("stop_requested"):
            self._recover_stopped_session(session, vault_key_id)
        result = self._result(session)
        return WorkflowInputSessionDetail(
            **result.model_dump(),
            events=list(session["events"]),
            draft_graph=deepcopy(session.get("draft_graph")),
            mutations=list(session["mutations"]),
        )

    def _recover_stopped_session(self, session: dict[str, Any], vault_key_id: str | None) -> None:
        """Finish a stopped prefix when its producer has not returned within one network timeout."""
        requested_at = session.get("cancellation_requested_at")
        if not isinstance(requested_at, int) or time.time() - requested_at < WORKFLOW_INPUT_STOP_RECOVERY_DELAY_SECONDS:
            return
        claim = getattr(self.checkpoint_store, "claim_recovery", None)
        if callable(claim):
            try:
                if not claim(session["user_id"], session["id"]):
                    return
            except Exception:
                logger.warning("Workflow input stop recovery lock failed")
                return
        try:
            self._apply_partial(session, self._partial_from_checkpoints(session), vault_key_id)
        except (ValidationError, ValueError, WorkflowNotFoundError) as exc:
            self._fail_session(session, "stop_recovery_failed", "WORKFLOW_INPUT_STOP_RECOVERY_FAILED",
                               "The stopped workflow could not be saved safely.", vault_key_id, exc)
        except Exception as exc:
            logger.warning("Stopped workflow input recovery will retry for session %s after %s",
                           session["id"], type(exc).__name__)
            return
        if session.get("status") != "running" and self.checkpoint_store is not None:
            try:
                self.checkpoint_store.clear(session["user_id"], session["id"])
            except Exception:
                logger.warning("Workflow input stop recovery cleanup failed")

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
            self._emit_stream(session, {"type": "progress", "phase": "planning"})
            self._record_timing(session, "context_seconds", context_started)
            try:
                planning_text = sanitized_text
                if session.get("execution_mode") == "run_once":
                    planning_text = (
                        "Execution mode: run exactly once now in this chat. Create one workflow "
                        "with a manual trigger and no schedule. Preserve the requested actions "
                        "and result routing.\n\n" + sanitized_text
                    )
                plan = self.planner.plan(text=planning_text, context=context)
            except Exception as exc:
                if isinstance(exc, WorkflowAuthoringBillingError):
                    raise
                if not session.get("accepted_checkpoints"):
                    raise
                logger.warning("Workflow planner exited after validated checkpoints for session %s with %s",
                               session["id"], type(exc).__name__)
                plan = self._partial_from_checkpoints(
                    session, reason="stopped" if self._should_stop(session, vault_key_id) else "provider_error")
            if isinstance(plan, dict) and isinstance(plan.get("_authoring_metrics"), dict):
                session["authoring_metrics"] = plan.pop("_authoring_metrics")
            if isinstance(plan, dict) and isinstance(plan.get("_authoring_before"), dict):
                session["authoring_before"] = plan.pop("_authoring_before")
            if session["status"] == "stopped":
                return self._result(session)
            validated_plan = WORKFLOW_INPUT_PLAN_ADAPTER.validate_python(plan)
            if self._should_stop(session, vault_key_id) and not isinstance(validated_plan, _PartialPlan):
                validated_plan = self._partial_from_checkpoints(session)
            if (getattr(self.planner, "atomic_authoring", False)
                    and isinstance(validated_plan, (_CreateWorkflowPlan, _UpdateWorkflowPlan))):
                validated_plan = _BatchPlan(action="batch", operations=[validated_plan])
            self._emit_stream(session, {"type": "progress", "phase": "validating"})
            self._append_event(session, "validation_passed", {}, vault_key_id=vault_key_id)
            if isinstance(validated_plan, _PartialPlan):
                self._emit_stream(session, {"type": "progress", "phase": "saving"})
                return self._apply_partial(session, validated_plan, vault_key_id)
            if optimistic_save and isinstance(validated_plan, (_CreateWorkflowPlan, _UpdateWorkflowPlan, _BatchPlan)):
                return self._queue_plan(session, validated_plan, vault_key_id)
            self._emit_stream(session, {"type": "progress", "phase": "saving"})
            return self._apply_plan(session, validated_plan, vault_key_id)
        except WorkflowAuthoringBillingError as exc:
            message = ("Insufficient credits for workflow authoring."
                       if exc.code == "INSUFFICIENT_CREDITS"
                       else "Workflow authoring billing could not be completed.")
            return self._fail_session(session, "billing_failed", exc.code, message, vault_key_id, exc)
        except WorkflowInputUnavailableError as exc:
            return self._fail_session(session, "capability_unavailable", exc.code, str(exc), vault_key_id)
        except (ValidationError, ValueError) as exc:
            return self._fail_session(session, "validation_failed", "WORKFLOW_INPUT_VALIDATION_FAILED", str(exc), vault_key_id)
        except WorkflowNotFoundError as exc:
            return self._fail_session(session, "target_not_found", "WORKFLOW_INPUT_TARGET_NOT_FOUND", "Workflow target was not found.", vault_key_id, exc)
        except Exception as exc:  # Boundary: logs the error type without user text or provider bodies.
            logger.error("Workflow input processing failed for session %s with %s", session["id"], type(exc).__name__)
            return self._fail_session(session, "failed", "WORKFLOW_INPUT_PROCESSING_FAILED", "Workflow input processing failed.", vault_key_id, exc)

    def _queue_plan(
        self,
        session: dict[str, Any],
        plan: _CreateWorkflowPlan | _UpdateWorkflowPlan | _BatchPlan,
        vault_key_id: str | None,
    ) -> WorkflowInputSessionResult:
        if not isinstance(self.repository, DirectusWorkflowInputRepository):
            return self._apply_plan(session, plan, vault_key_id)
        if isinstance(plan, _BatchPlan):
            self._prepare_batch(session, plan, vault_key_id)
        elif isinstance(plan, _CreateWorkflowPlan):
            validate_workflow_readiness(plan.graph, require_schedule=True)
            validate_workflow_composition_refs(plan.graph, allow_data_dependencies=True)
            session["assumptions"] = list(plan.assumptions)
        else:
            workflow_id = plan.workflow_id or session.get("selected_workflow_id")
            if not workflow_id:
                raise ValueError("update_workflow requires workflow_id or a selected workflow")
            cached = session.get("_selected_workflow_detail")
            authored = (session.get("authoring_before") or {}).get(workflow_id)
            before = (WorkflowDetail.model_validate(authored) if isinstance(authored, dict)
                      else cached if isinstance(cached, WorkflowDetail) and cached.id == workflow_id
                      else self.workflow_service.get_workflow(workflow_id, session["user_id"], vault_key_id))
            if plan.expected_record_version is not None and before.version != plan.expected_record_version:
                raise ValueError("Workflow changed while the AI edit was being prepared. Reload it and retry.")
            graph = plan.graph or before.graph
            validate_workflow_readiness(graph, require_schedule=before.enabled)
            validate_workflow_composition_refs(graph, before.graph, allow_data_dependencies=True)
            session["assumptions"] = list(plan.assumptions)
            session["pending_before"] = before.model_dump(mode="json")
        session["pending_plan"] = plan.model_dump(mode="json", by_alias=True)
        session["pending_operation_id"] = self._authoring_operation_id(session)
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
        if session.get("execution_mode") == "run_once" and not isinstance(plan, (_CreateWorkflowPlan, _ClarificationPlan, _DraftPlan)):
            raise ValueError("One-time chat execution requires a single new workflow")
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
            if getattr(self.planner, "atomic_authoring", False):
                return self._create_empty_workflow_atomic(session, plan, vault_key_id)
            graph = WorkflowGraph.model_validate({"version": 2, "trigger_node_id": None, "nodes": [], "edges": []})
            workflow_started = time.perf_counter()
            workflow = self.workflow_service.create_workflow(
                session["user_id"], plan.title, graph, enabled=False,
                source="workflow_input", source_chat_id=session.get("source_chat_id"),
                created_by_assistant=True, vault_key_id=vault_key_id,
            )
            self._record_timing(session, "workflow_persistence_seconds", workflow_started)
            session["status"] = "draft"
            session["workflow"] = workflow
            session["selected_workflow_id"] = workflow.id
            session["workflows"] = [workflow]
            session["changes"] = [self._workflow_change(None, workflow)]
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
        if isinstance(plan, _BatchPlan):
            return self._apply_batch(session, plan, vault_key_id)
        if isinstance(plan, _PartialPlan):
            return self._apply_partial(session, plan, vault_key_id)
        if isinstance(plan, _LinkWorkflowToProjectPlan):
            return self._link_workflow_to_project(session, plan, vault_key_id)
        raise ValueError("Workflow input action is unavailable")

    def _create_empty_workflow_atomic(
        self, session: dict[str, Any], plan: _CreateEmptyWorkflowPlan, vault_key_id: str | None,
    ) -> WorkflowInputSessionResult:
        """Save a blank disabled draft with a version guarded atomic undo ledger."""
        operation_id = self._authoring_operation_id(session)
        workflow_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"workflow-input:{operation_id}:create:0"))
        graph = {"version": 2, "trigger_node_id": None, "nodes": [], "edges": []}
        details = self.workflow_service.apply_authoring_batch(
            session["user_id"], [{
                "type": "create", "workflow_id": workflow_id,
                "initial_version_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"workflow-input:{operation_id}:version:0")),
                "title": plan.title, "graph": graph, "enabled": False,
                "source": "workflow_input", "created_by_assistant": True,
                "source_chat_id": session.get("source_chat_id"), "allow_data_dependencies": True,
            }], operation_id, vault_key_id, before_snapshots=[None], session_id=operation_id,
        )
        if len(details) != 1 or not isinstance(details[0], WorkflowDetail):
            raise RuntimeError("Atomic blank workflow save returned no draft")
        workflow = details[0]
        session["status"] = "draft"
        session["workflow"] = workflow
        session["selected_workflow_id"] = workflow.id
        session["workflows"] = [workflow]
        session["changes"] = [self._workflow_change(None, workflow)]
        session["mutations"].append(WorkflowInputMutation(
            id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"workflow-authoring:{operation_id}:0")),
            type="create_workflow", target_type="workflow", target_id=workflow.id,
            operation_id=operation_id, after=workflow.model_dump(mode="json"), created_at=int(time.time()),
        ))
        self._append_event(session, "draft_saved", {"workflow_id": workflow.id}, vault_key_id=vault_key_id)
        return self._result(session)

    @staticmethod
    def _authoring_operation_id(session: dict[str, Any]) -> str:
        prior = {item.operation_id for item in session["mutations"] if item.operation_id
                 and not item.operation_id.startswith("undo:")}
        return session["id"] if not prior else f"{session['id']}:followup:{len(prior)}"

    def _prepare_batch(
        self,
        session: dict[str, Any],
        plan: _BatchPlan,
        vault_key_id: str | None,
        *,
        partial: bool = False,
    ) -> list[dict[str, Any] | None]:
        """Validate the complete group and capture versions before any mutation."""
        snapshots: list[dict[str, Any] | None] = []
        seen_targets: set[str] = set()
        assumptions: list[str] = []
        for operation in plan.operations:
            if isinstance(operation, _CreateWorkflowPlan):
                if not partial:
                    validate_workflow_readiness(operation.graph, require_schedule=True)
                validate_workflow_composition_refs(operation.graph, allow_data_dependencies=True)
                assumptions.extend(operation.assumptions)
                snapshots.append(None)
                continue
            workflow_id = operation.workflow_id or session.get("selected_workflow_id")
            if not workflow_id:
                raise ValueError("update_workflow requires workflow_id or a selected workflow")
            if workflow_id in seen_targets:
                raise ValueError("A workflow can only be edited once in one batch")
            seen_targets.add(workflow_id)
            authored = (session.get("authoring_before") or {}).get(workflow_id)
            before = (WorkflowDetail.model_validate(authored) if isinstance(authored, dict)
                      else self.workflow_service.get_workflow(workflow_id, session["user_id"], vault_key_id))
            if operation.expected_record_version is not None and before.version != operation.expected_record_version:
                raise ValueError("Workflow changed while the AI edit was being prepared. Reload it and retry.")
            graph = operation.graph or before.graph
            if not partial:
                validate_workflow_readiness(graph, require_schedule=before.enabled)
            validate_workflow_composition_refs(graph, before.graph, allow_data_dependencies=True)
            assumptions.extend(operation.assumptions)
            snapshots.append(before.model_dump(mode="json"))
        session["assumptions"] = assumptions
        session["pending_before"] = snapshots
        return snapshots

    def _apply_batch(
        self,
        session: dict[str, Any],
        plan: _BatchPlan,
        vault_key_id: str | None,
        *,
        partial: bool = False,
    ) -> WorkflowInputSessionResult:
        before_snapshots = session.get("pending_before")
        if not isinstance(before_snapshots, list):
            before_snapshots = self._prepare_batch(session, plan, vault_key_id, partial=partial)
        operation_id = session.get("pending_operation_id") or self._authoring_operation_id(session)
        operations: list[dict[str, Any]] = []
        for index, operation in enumerate(plan.operations):
            version_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"workflow-input:{operation_id}:version:{index}"))
            if isinstance(operation, _CreateWorkflowPlan):
                operations.append({
                    "type": "create", "workflow_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"workflow-input:{operation_id}:create:{index}")),
                    "initial_version_id": version_id, "title": operation.title,
                    "description": operation.description, "category": operation.category, "icon": operation.icon,
                    "graph": operation.graph.model_dump(mode="json", by_alias=True),
                    "enabled": False, "source": "workflow_input", "created_by_assistant": True,
                    "source_chat_id": session.get("source_chat_id"),
                    "allow_data_dependencies": True,
                })
            else:
                before_payload = before_snapshots[index]
                if not isinstance(before_payload, dict):
                    raise ValueError("An update is missing its prior workflow snapshot")
                before = WorkflowDetail.model_validate(before_payload)
                operations.append({
                    "type": "update", "workflow_id": before.id,
                    "expected_record_version": before.version, "new_version_id": version_id,
                    "title": operation.title, "description": operation.description,
                    "category": operation.category, "icon": operation.icon,
                    "graph": (operation.graph or before.graph).model_dump(mode="json", by_alias=True),
                    **({"enabled": False} if partial else {}),
                    "allow_data_dependencies": True,
                })
        commit = getattr(self.workflow_service, "apply_authoring_batch", None)
        if not callable(commit):
            raise WorkflowInputUnavailableError(WORKFLOW_INPUT_ACTION_UNAVAILABLE, "Atomic workflow authoring is unavailable.")
        started = time.perf_counter()
        details = commit(session["user_id"], operations, operation_id, vault_key_id,
                         before_snapshots=before_snapshots, session_id=session["id"])
        self._record_timing(session, "workflow_persistence_seconds", started)
        workflows = [detail for detail in details if isinstance(detail, WorkflowDetail)]
        if len(workflows) != len(operations):
            raise RuntimeError("Atomic workflow commit returned incomplete results")
        session["workflows"] = workflows
        session["workflow"] = workflows[0]
        session["changes"] = [self._workflow_change(before_snapshots[index], workflow)
                              for index, workflow in enumerate(workflows)]
        session["status"] = "draft" if partial else "executed"
        if not partial:
            session["message"] = None
        # The atomic transaction already published its encrypted per-target undo
        # rows. Mirror those rows for this immediate response without writing a
        # second marker that could split the group's undo after a reload.
        existing_mutation_ids = {item.id for item in session["mutations"]}
        session["mutations"].extend(item for item in (WorkflowInputMutation(
            id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"workflow-authoring:{operation_id}:{index}")),
            type="create_workflow" if operation["type"] == "create" else "update_workflow",
            target_type="workflow", target_id=workflow.id, operation_id=operation_id,
            before=before_snapshots[index], after=workflow.model_dump(mode="json"),
            created_at=int(time.time()),
        ) for index, (operation, workflow) in enumerate(zip(operations, workflows)))
            if item.id not in existing_mutation_ids)
        self._append_event(session, "partial_saved" if partial else "committed",
                           {"mutation_type": "authoring_batch", "workflow_count": len(workflows)}, vault_key_id=vault_key_id)
        return self._result(session)

    def _apply_partial(
        self, session: dict[str, Any], plan: _PartialPlan, vault_key_id: str | None,
    ) -> WorkflowInputSessionResult:
        if not plan.operations or any(not operation.graph or not operation.graph.nodes for operation in plan.operations):
            return self._fail_session(session, "no_valid_partial", WORKFLOW_INPUT_NO_VALID_PARTIAL,
                                      "No valid workflow steps were completed before authoring stopped.", vault_key_id)
        checkpoints = sorted((session.get("accepted_checkpoints") or {}).values(),
                             key=lambda item: item["workflow_index"])
        if len(checkpoints) != len(plan.operations):
            raise ValueError("Partial workflow plan does not match validated checkpoints")
        for operation, checkpoint in zip(plan.operations, checkpoints):
            expected_action = "update_workflow" if checkpoint["operation"] == "update" else "create_workflow"
            if (operation.action != expected_action
                    or operation.graph.model_dump(mode="json", by_alias=True) != checkpoint["graph"]
                    or (expected_action == "update_workflow"
                        and operation.workflow_id != checkpoint["metadata"].get("workflow_id"))):
                raise ValueError("Partial workflow plan contains an unvalidated change")
        session["partial_reason"] = plan.reason
        session["partial_warning"] = plan.notice
        session["message"] = plan.notice
        return self._apply_batch(session, _BatchPlan(action="batch", operations=plan.operations),
                                 vault_key_id, partial=True)

    @staticmethod
    def _workflow_change(before: dict[str, Any] | None, after: WorkflowDetail) -> dict[str, Any]:
        before_nodes = {node["id"]: node for node in ((before or {}).get("graph") or {}).get("nodes", [])}
        after_nodes = {node.id: node.model_dump(mode="json") for node in after.graph.nodes}
        return {
            "workflow_id": after.id,
            "operation": "update" if before else "create",
            "added_node_ids": sorted(after_nodes.keys() - before_nodes.keys()),
            "removed_node_ids": sorted(before_nodes.keys() - after_nodes.keys()),
            "changed_node_ids": sorted(key for key in before_nodes.keys() & after_nodes.keys()
                                       if before_nodes[key] != after_nodes[key]),
        }

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
        run_once = session.get("execution_mode") == "run_once"
        validate_workflow_readiness(
            plan.graph, require_schedule=not run_once,
            allow_return_outputs=run_once and bool(session.get("return_outputs")),
        )
        validate_workflow_composition_refs(plan.graph, allow_data_dependencies=True)
        self._stream_draft_nodes(session, graph, vault_key_id)
        if session["status"] == "stopped":
            return self._result(session)
        workflow_started = time.perf_counter()
        workflow = self.workflow_service.create_workflow(
            session["user_id"],
            plan.title,
            plan.graph,
            enabled=False,
            lifecycle=WorkflowLifecycle.CHAT_EMBED if run_once else WorkflowLifecycle.PERSISTED,
            source="workflow_input",
            source_chat_id=session.get("source_chat_id"),
            created_by_assistant=True,
            vault_key_id=vault_key_id,
            description=plan.description,
            category=plan.category,
            icon=plan.icon,
            allow_data_dependencies=True,
            workflow_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"workflow-input:{session['id']}:create")) if session.get("pending_plan") else None,
            initial_version_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"workflow-input:{session['id']}:version")) if session.get("pending_plan") else None,
        )
        self._record_timing(session, "workflow_persistence_seconds", workflow_started)
        session["status"] = "executed"
        session["message"] = None
        session["workflow"] = workflow
        session["workflows"] = [workflow]
        session["changes"] = [self._workflow_change(None, workflow)]
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
        authored = (session.get("authoring_before") or {}).get(workflow_id)
        before = (WorkflowDetail.model_validate(pending_before) if isinstance(pending_before, dict)
                  else WorkflowDetail.model_validate(authored) if isinstance(authored, dict)
                  else cached if isinstance(cached, WorkflowDetail) and cached.id == workflow_id
                  else self.workflow_service.get_workflow(workflow_id, session["user_id"], vault_key_id))
        if plan.expected_record_version is not None and before.version != plan.expected_record_version:
            raise ValueError("Workflow changed while the AI edit was being prepared. Reload it and retry.")
        self._record_timing(session, "workflow_read_seconds", workflow_read_started)
        graph = plan.graph or before.graph
        validate_workflow_readiness(graph, require_schedule=before.enabled)
        validate_workflow_composition_refs(graph, before.graph, allow_data_dependencies=True)
        session["assumptions"] = list(plan.assumptions)
        self._stream_draft_nodes(session, graph.model_dump(mode="json", by_alias=True), vault_key_id)
        if session["status"] == "stopped":
            return self._result(session)
        workflow_started = time.perf_counter()
        workflow = self.workflow_service.update_workflow(
            workflow_id,
            session["user_id"],
            title=plan.title,
            graph=graph,
            description=plan.description,
            category=plan.category,
            icon=plan.icon,
            allow_data_dependencies=True,
            vault_key_id=vault_key_id,
            expected_record_version=before.version,
            known_prior=before,
            new_version_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"workflow-input:{session['id']}:version")) if session.get("pending_plan") else None,
        )
        self._record_timing(session, "workflow_persistence_seconds", workflow_started)
        session["status"] = "executed"
        session["message"] = None
        session["workflow"] = workflow
        session["workflows"] = [workflow]
        session["changes"] = [self._workflow_change(before.model_dump(mode="json"), workflow)]
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
        context: dict[str, Any] = {
            "workflows": workflows,
            "selected_workflow": selected_workflow,
            "projects": [],
            "selected_project_id": session.get("selected_project_id"),
            "timezone": session.get("timezone"),
            "execution_mode": session.get("execution_mode", "saved"),
        }
        if getattr(self.planner, "atomic_authoring", False):
            # Private server-side billing identity. The planner passes only
            # explicit request/registry fields to Jev and Gemini.
            context["_billing_user_id"] = session["user_id"]
            context["_billing_session_id"] = session["id"]
        if getattr(self.planner, "requires_workflow_lookup", False):
            # Keep owner credentials and library contents out of model input.
            # The NL planner invokes these only after it has classified an edit.
            context["_load_workflows"] = lambda: self.workflow_service.list_workflows(session["user_id"], vault_key_id)
            def load_workflow(workflow_id: str) -> WorkflowDetail:
                detail = self.workflow_service.get_workflow(workflow_id, session["user_id"], vault_key_id)
                session["_selected_workflow_detail"] = detail
                return detail
            context["_load_workflow"] = load_workflow
        context["_should_stop"] = lambda: self._should_stop(session, vault_key_id)
        context["_on_checkpoint"] = lambda checkpoint: self._accept_checkpoint(session, checkpoint, vault_key_id)
        if callable(session.get("_on_stream_event")):
            context["_on_component"] = lambda event: self._emit_stream(session, event) if event.get("type") != "preview" else None
        return context

    def _should_stop(self, session: dict[str, Any], vault_key_id: str | None) -> bool:
        counts = session.setdefault("_poll_counts", {})
        counts["stop_checks"] = counts.get("stop_checks", 0) + 1
        if session.get("stop_requested") or session.get("status") == "stopped":
            return True
        now = time.monotonic()
        cache_failed = False
        if self.checkpoint_store is not None:
            if now - session.get("_last_stop_cache_check", 0.0) >= WORKFLOW_INPUT_STOP_CACHE_POLL_SECONDS:
                session["_last_stop_cache_check"] = now
                counts["stop_cache_reads"] = counts.get("stop_cache_reads", 0) + 1
                started = time.perf_counter()
                try:
                    if self.checkpoint_store.stop_requested(session["user_id"], session["id"]):
                        session["stop_requested"] = True
                        return True
                except Exception:
                    cache_failed = True
                    logger.warning("Workflow input stop cache read failed")
                finally:
                    self._record_timing(session, "stop_cache_read_seconds", started)
            else:
                counts["stop_cache_read_skips"] = counts.get("stop_cache_read_skips", 0) + 1
        if self.repository is not None and (cache_failed or now - session.get("_last_durable_stop_check", 0.0) >= 1.0):
            session["_last_durable_stop_check"] = now
            counts["stop_durable_reads"] = counts.get("stop_durable_reads", 0) + 1
            started = time.perf_counter()
            try:
                read_stop = getattr(self.repository, "get_stop_requested", None)
                if callable(read_stop):
                    requested = read_stop(session["id"], session["user_id"], vault_key_id)
                else:
                    current = self.repository.get_session(session["id"], session["user_id"], vault_key_id)
                    requested = bool(current and current.get("stop_requested"))
                if requested:
                    session["stop_requested"] = True
                    return True
            except Exception:
                logger.warning("Workflow input durable stop read failed")
            finally:
                self._record_timing(session, "stop_durable_read_seconds", started)
        return False

    def _accept_checkpoint(
        self, session: dict[str, Any], checkpoint: dict[str, Any], vault_key_id: str | None,
    ) -> None:
        # The compiler has already accepted this node before invoking the
        # callback. A Stop arriving at this boundary must keep that validated
        # graph; the planner checks Stop before accepting the next component.
        if not isinstance(checkpoint, dict):
            raise ValueError("Workflow checkpoint must be an object")
        index = checkpoint.get("workflow_index")
        count = checkpoint.get("accepted_node_count")
        if (not isinstance(index, int) or isinstance(index, bool) or index < 0 or index >= 12
                or not isinstance(count, int) or isinstance(count, bool) or count < 0):
            raise ValueError("Workflow checkpoint index or node count is invalid")
        graph = WorkflowGraph.model_validate(checkpoint.get("graph"))
        if not graph.nodes:
            raise ValueError("Workflow checkpoint has no accepted node")
        validate_workflow_composition_refs(graph, allow_data_dependencies=True)
        metadata = checkpoint.get("metadata")
        if not isinstance(metadata, dict):
            raise ValueError("Workflow checkpoint metadata is missing")
        operation = checkpoint.get("operation")
        if operation not in {"create", "update"}:
            raise ValueError("Workflow checkpoint operation is invalid")
        if operation == "update" and not isinstance(metadata.get("workflow_id"), str):
            raise ValueError("Workflow update checkpoint has no target")
        if operation == "update" and (not isinstance(metadata.get("expected_record_version"), int)
                                      or isinstance(metadata["expected_record_version"], bool)
                                      or metadata["expected_record_version"] < 1):
            raise ValueError("Workflow update checkpoint has no target version")
        saved = session.setdefault("accepted_checkpoints", {})
        prior = saved.get(str(index))
        if isinstance(prior, dict) and int(prior.get("accepted_node_count") or 0) >= count:
            return
        accepted = {
            "workflow_index": index,
            "operation": operation,
            "graph": graph.model_dump(mode="json", by_alias=True),
            "metadata": {key: deepcopy(metadata.get(key)) for key in
                         ("title", "description", "category", "icon", "workflow_id", "expected_record_version", "assumptions")
                         if key in metadata},
            "accepted_node_count": count,
        }
        saved[str(index)] = accepted
        if self.checkpoint_store is not None:
            try:
                self.checkpoint_store.save(session["user_id"], session["id"], saved, vault_key_id)
            except Exception:
                logger.warning("Workflow input encrypted checkpoint cache write failed")
                self._persist_session(session, vault_key_id)
        else:
            self._persist_session(session, vault_key_id)
        accepted_node_id = checkpoint.get("accepted_node_id")
        accepted_node = next((node for node in accepted["graph"]["nodes"] if node["id"] == accepted_node_id), None)
        self._emit_stream(session, {"type": "preview", **deepcopy(accepted),
                                    "node": accepted_node or accepted["graph"]["nodes"][-1],
                                    "provisional": True, "validated": True})

    @staticmethod
    def _partial_from_checkpoints(
        session: dict[str, Any], *, reason: Literal["stopped", "provider_error"] = "stopped",
    ) -> _PartialPlan:
        operations: list[dict[str, Any]] = []
        for checkpoint in sorted((session.get("accepted_checkpoints") or {}).values(),
                                 key=lambda item: item["workflow_index"]):
            metadata = {key: value for key, value in checkpoint["metadata"].items() if value is not None}
            operation = {"action": "update_workflow" if checkpoint["operation"] == "update" else "create_workflow",
                         "graph": checkpoint["graph"], **metadata}
            if operation["action"] == "create_workflow":
                operation.setdefault("title", f"Workflow draft {checkpoint['workflow_index'] + 1}")
                operation["enabled"] = False
            operations.append(operation)
        notice = ("Stopped. Valid steps were saved as a disabled draft." if reason == "stopped"
                  else "A later step could not be completed. Valid steps were saved as a disabled draft.")
        return _PartialPlan.model_validate({"action": "partial", "reason": reason,
                                            "notice": notice,
                                            "operations": operations})

    @staticmethod
    def _emit_stream(session: dict[str, Any], event: dict[str, Any]) -> None:
        callback = session.get("_on_stream_event")
        if callable(callback):
            callback(event)

    def _create_session(
        self,
        user_id: str,
        selected_workflow_id: str | None,
        selected_project_id: str | None,
        vault_key_id: str | None,
        *,
        persist_initial: bool = True,
        session_id: str | None = None,
        request_digest: str | None = None,
    ) -> dict[str, Any]:
        now = int(time.time())
        session = {
            "id": session_id or str(uuid.uuid4()),
            "request_digest": request_digest,
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
            "stop_requested": False,
            "partial_reason": None,
            "partial_warning": None,
            "accepted_checkpoints": {},
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
        if (session is None or session.get("status") in {"running", "queued"}) and user_id is not None and self.repository is not None:
            refreshed = self.repository.get_session(session_id, user_id, vault_key_id)
            if refreshed is not None:
                session = refreshed
                self._sessions[session_id] = refreshed
        if session is None:
            raise KeyError(session_id)
        if user_id is not None and session.get("status") == "running" and self.checkpoint_store is not None:
            try:
                cached = self.checkpoint_store.load(user_id, session_id, vault_key_id)
                if cached:
                    session["accepted_checkpoints"] = cached
                if self.checkpoint_store.stop_requested(user_id, session_id):
                    session["stop_requested"] = True
            except Exception:
                logger.warning("Workflow input encrypted checkpoint cache read failed")
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
            if mutation.undone_at is None and not str(mutation.operation_id or "").startswith("undo:"):
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
        previews = self._queued_previews(session)
        changes = list(session.get("changes") or [])
        if previews and not changes:
            prior = session.get("pending_before")
            snapshots = prior if isinstance(prior, list) else [prior]
            changes = [self._workflow_change(snapshots[index] if index < len(snapshots) else None, item)
                       for index, item in enumerate(previews)]
        return WorkflowInputSessionResult(
            session_id=session["id"],
            status=session["status"],
            event_cursor=len(session["events"]),
            message=message or session.get("message"),
            error=error,
            error_code=error_code,
            workflow=workflow or session.get("workflow"),
            preview_workflow=previews[0] if previews else None,
            workflows=list(session.get("workflows") or ([workflow or session.get("workflow")] if workflow or session.get("workflow") else [])),
            preview_workflows=previews,
            changes=changes,
            project_item=project_item or session.get("project_item"),
            undo_available=session["status"] in {"executed", "draft"} and self._last_undoable_mutation(session) is not None,
            assumptions=list(session.get("assumptions") or []),
            authoring_metrics=session.get("authoring_metrics"),
            stop_requested=bool(session.get("stop_requested")),
            partial_reason=session.get("partial_reason"),
            partial_warning=session.get("partial_warning"),
            partial_previews=[deepcopy(item) for item in sorted((session.get("accepted_checkpoints") or {}).values(),
                                                                key=lambda item: item["workflow_index"])],
        )

    def _queued_preview(self, session: dict[str, Any]) -> WorkflowDetail | None:
        """Return a validated renderable graph while its durable save is pending."""
        previews = self._queued_previews(session)
        return previews[0] if previews else None

    def _queued_previews(self, session: dict[str, Any]) -> list[WorkflowDetail]:
        if session.get("status") != "queued" or not isinstance(session.get("pending_plan"), dict):
            return []
        plan = WORKFLOW_INPUT_PLAN_ADAPTER.validate_python(session["pending_plan"])
        if isinstance(plan, _BatchPlan):
            before = session.get("pending_before") or []
            return [self._preview_operation(session, operation, before[index], index, batch=True)
                    for index, operation in enumerate(plan.operations)]
        if isinstance(plan, (_CreateWorkflowPlan, _UpdateWorkflowPlan)):
            return [self._preview_operation(session, plan, session.get("pending_before"), 0, batch=False)]
        return []

    def _preview_operation(
        self, session: dict[str, Any], plan: _CreateWorkflowPlan | _UpdateWorkflowPlan,
        before_payload: dict[str, Any] | None, index: int, *, batch: bool,
    ) -> WorkflowDetail:
        suffix = f":{index}" if batch else ""
        operation_id = session.get("pending_operation_id") or session["id"]
        version_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"workflow-input:{operation_id}:version{suffix}"))
        if isinstance(plan, _CreateWorkflowPlan):
            now = int(time.time())
            return WorkflowDetail.model_validate({
                "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"workflow-input:{operation_id}:create{suffix}")),
                "title": plan.title, "description": plan.description,
                "category": plan.category or "general_knowledge", "icon": plan.icon or "help-circle",
                "status": "disabled", "enabled": False, "source": "workflow_input",
                "created_by_assistant": True, "current_version_id": version_id,
                "created_at": now, "updated_at": now,
                "trigger_summary": self.workflow_service._trigger_summary(plan.graph),
                "graph": plan.graph,
            })
        if isinstance(plan, _UpdateWorkflowPlan) and isinstance(before_payload, dict):
            before = WorkflowDetail.model_validate(before_payload)
            return before.model_copy(update={
                "title": plan.title or before.title,
                "description": plan.description if plan.description is not None else before.description,
                "category": plan.category if plan.category is not None else before.category,
                "icon": plan.icon if plan.icon is not None else before.icon,
                "graph": plan.graph or before.graph,
                "version": before.version + 1,
                "current_version_id": version_id,
                "updated_at": int(time.time()),
                "trigger_summary": self.workflow_service._trigger_summary(plan.graph or before.graph),
            })
        raise ValueError("Queued workflow preview is missing its prior snapshot")

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
        "request_digest": session.get("request_digest"),
        "selected_project_id": session.get("selected_project_id"),
        "timezone": session.get("timezone"),
        "source_chat_id": session.get("source_chat_id"),
        "execution_mode": session.get("execution_mode", "saved"),
        "return_outputs": deepcopy(session.get("return_outputs") or {}),
        "authoring_metrics": deepcopy(session.get("authoring_metrics")),
        "draft_graph": deepcopy(session.get("draft_graph")),
        "workflow": workflow.model_dump(mode="json") if isinstance(workflow, WorkflowDetail) else deepcopy(workflow),
        "workflows": [item.model_dump(mode="json") if isinstance(item, WorkflowDetail) else deepcopy(item) for item in session.get("workflows") or []],
        "changes": deepcopy(session.get("changes") or []),
        "authoring_before": deepcopy(session.get("authoring_before")),
        "project_item": deepcopy(session.get("project_item")),
        "message": session.get("message"),
        "assumptions": list(session.get("assumptions") or []),
        "pending_plan": deepcopy(session.get("pending_plan")),
        "pending_operation_id": session.get("pending_operation_id"),
        "pending_before": deepcopy(session.get("pending_before")),
        "queued_user_id": session.get("queued_user_id"),
        "commit_attempts": int(session.get("commit_attempts") or 0),
        "cancellation_requested_at": session.get("cancellation_requested_at"),
        "stop_requested": bool(session.get("stop_requested")),
        "partial_reason": session.get("partial_reason"),
        "partial_warning": session.get("partial_warning"),
        "accepted_checkpoints": deepcopy(session.get("accepted_checkpoints") or {}),
    }
