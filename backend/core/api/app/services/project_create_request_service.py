"""Client-executed Project creation requests (contract openmates.project_create_request v1).

Projects are client-side encrypted, so the server can only *ask* a capable
first-party client to create one. This module owns the request payload, its
transient Redis record and validation of the client's completion report. The
human-readable contract lives in
``docs/plans/cloud-project-development/contracts/project-create-request.md``;
keep both in sync.

Nothing here decrypts Project data or stores a Project name durably. The
proposed name is plaintext the server already derived from the user's current
message and lives only in the short-lived request record and event.
"""

from __future__ import annotations

import hashlib
import re
import time
import uuid
from typing import Any

from backend.core.api.app.services.project_write_authorization_service import (
    ProjectWriteAuthorizationError,
    normalize_focus_id,
)

PROJECT_CREATE_CONTRACT = "openmates.project_create_request"
PROJECT_CREATE_CONTRACT_VERSION = 1
# Connection capability a client advertises when it can execute this contract.
PROJECT_CREATE_CAPABILITY = "project_create_requests"
PROJECT_CREATE_REQUEST_PREFIX = "project-create-request-"
PROJECT_CREATE_REQUEST_TTL = 10 * 60
PROJECT_CREATE_EVENT = "project_create_requested"
PROJECT_CREATE_RESULT_MESSAGE = "project_create_result"
PROJECT_CREATE_CONFIRMED_EVENT = "project_create_confirmed"
PROJECT_CREATE_ERROR_EVENT = "project_create_error"
PROJECT_CREATE_WRITE_MODE = "apply_and_show"
# Application kind -> dedicated Project subfolder for its files.
PROJECT_CREATE_KINDS: dict[str, str] = {"web_app": "web-app", "native_app": "native-app"}
PROJECT_CREATE_RESULT_STATUSES = frozenset({"created", "failed", "undone"})
# A reported Project must be new for this request, not an older one rebound.
PROJECT_CREATE_MAX_AGE_SKEW_SECONDS = 10 * 60
_REQUEST_ID_RE = re.compile(r"^project-create-request-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
_FAILURE_CODE_RE = re.compile(r"^[A-Z0-9_]{1,64}$")
MAX_PROJECT_NAME_CHARS = 120
MAX_PROJECT_DESCRIPTION_CHARS = 400


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_project_create_request_id() -> str:
    return f"{PROJECT_CREATE_REQUEST_PREFIX}{uuid.uuid4()}"


def build_project_create_action(
    *, request_id: str, name: str, chat_id: str | None, message_id: str | None,
    team_id: str | None, origin: str, kind: str | None = None, description: str = "",
    created_at: float | None = None,
) -> dict[str, Any]:
    """Return the ``pending_client_action`` for one client-executed creation.

    ``origin`` is ``preprocessor`` (assistant-inferred, continues the turn after
    the completion report) or ``skill`` (projects.create; no turn continuation).
    """
    if origin not in {"preprocessor", "skill"}:
        raise ValueError("Unsupported Project create origin")
    if kind is not None and kind not in PROJECT_CREATE_KINDS:
        raise ValueError("Unsupported application kind")
    project_name = " ".join(str(name or "").split())[:MAX_PROJECT_NAME_CHARS]
    if not project_name:
        raise ValueError("Project create requires a name")
    now = time.time() if created_at is None else created_at
    return {
        "contract": PROJECT_CREATE_CONTRACT,
        "version": PROJECT_CREATE_CONTRACT_VERSION,
        "request_id": request_id,
        "action": "create",
        "origin": origin,
        "chat_id": chat_id,
        "message_id": message_id,
        "team_id": team_id,
        "name": project_name,
        "description": " ".join(str(description or "").split())[:MAX_PROJECT_DESCRIPTION_CHARS],
        "kind": kind,
        "subfolder": PROJECT_CREATE_KINDS.get(kind) if kind else None,
        "write_mode": PROJECT_CREATE_WRITE_MODE,
        "focus": {"activate": "immediate" if origin == "preprocessor" else "none", "countdown_seconds": 0},
        "undo": {"available": True},
        "created_at": int(now),
        "expires_at": int(now + PROJECT_CREATE_REQUEST_TTL),
        "notification_queued": False,
    }


def outbound_create_event(payload: Any) -> dict[str, Any] | None:
    """Re-validate a pub/sub event before it is forwarded to a client socket."""
    if not isinstance(payload, dict):
        return None
    action = payload.get("pending_client_action")
    chat_id, request_id = payload.get("chat_id"), payload.get("request_id")
    if (not isinstance(action, dict) or not isinstance(chat_id, str) or not 0 < len(chat_id) <= 128
            or not isinstance(request_id, str) or not _REQUEST_ID_RE.fullmatch(request_id)
            or action.get("request_id") != request_id or action.get("chat_id") != chat_id
            or action.get("contract") != PROJECT_CREATE_CONTRACT):
        return None
    return {"chat_id": chat_id, "request_id": request_id, "pending_client_action": action}


def parse_project_create_result(payload: Any) -> dict[str, Any]:
    """Validate the client's completion report shape; authority is checked later."""
    if not isinstance(payload, dict):
        raise ProjectWriteAuthorizationError("INVALID_PROJECT_CREATE_RESULT", status_code=422)
    chat_id, request_id, status = payload.get("chat_id"), payload.get("request_id"), payload.get("status")
    if (not isinstance(chat_id, str) or not 0 < len(chat_id) <= 128
            or not isinstance(request_id, str) or not _REQUEST_ID_RE.fullmatch(request_id)
            or status not in PROJECT_CREATE_RESULT_STATUSES):
        raise ProjectWriteAuthorizationError("INVALID_PROJECT_CREATE_RESULT", status_code=422)
    result: dict[str, Any] = {"chat_id": chat_id, "request_id": request_id, "status": status}
    if status == "created":
        project_id, focus_id = payload.get("project_id"), payload.get("focus_id")
        try:
            result["project_id"] = str(uuid.UUID(str(project_id)))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ProjectWriteAuthorizationError("INVALID_PROJECT_CREATE_RESULT", status_code=422) from exc
        if not isinstance(focus_id, str):
            raise ProjectWriteAuthorizationError("INVALID_PROJECT_CREATE_RESULT", status_code=422)
        result["focus_id"] = normalize_focus_id(focus_id)
    else:
        code = payload.get("error_code")
        result["error_code"] = code if isinstance(code, str) and _FAILURE_CODE_RE.fullmatch(code) else None
    return result


def continuation_result(pending: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    """Tool-completion row for the original turn. Contains no Project name."""
    subfolder = pending.get("subfolder")
    if report["status"] == "created":
        location = f" under {subfolder}/" if subfolder else ""
        return {
            "project_id": report["project_id"], "project_created": True, "access_granted": True,
            "write_mode": PROJECT_CREATE_WRITE_MODE, "subfolder": subfolder,
            "message": ("A new Project was created for this request and its Work on focus is active. "
                        f"Write the application's files{location} with the Project file tools; "
                        "do not ask for permission or confirmation first."),
        }
    return {
        "project_created": False, "access_granted": False, "status": report["status"],
        "message": ("The user undid the new Project. Do not create a Project or use Project file tools "
                    "in this turn; answer in the chat instead." if report["status"] == "undone" else
                    "The Project could not be created. Do not use Project file tools in this turn; "
                    "answer in the chat instead and say briefly that no Project was created."),
    }


class ProjectCreateRequestService:
    """Transient per-chat creation request records; never decrypts Projects."""

    def __init__(self, cache_service: Any) -> None:
        self.cache = cache_service

    @staticmethod
    def key(user_id: str, chat_id: str) -> str:
        return f"project_create_request:v1:{_hash(user_id)}:{chat_id}"

    @staticmethod
    def claim_key(user_id: str, request_id: str) -> str:
        return f"project_create_request:claimed:{_hash(user_id)}:{request_id}"

    async def create_pending(self, *, user_id: str, action: dict[str, Any]) -> dict[str, Any]:
        """Store the request and the chat's current-request pointer."""
        chat_id, request_id = action["chat_id"], action["request_id"]
        pending = {
            "request_id": request_id, "user_id": user_id, "chat_id": chat_id,
            "message_id": action["message_id"], "team_id": action.get("team_id"),
            "kind": action.get("kind"), "subfolder": action.get("subfolder"),
            "created_at": action["created_at"], "expires_at": action["expires_at"],
        }
        key = self.key(user_id, chat_id)
        if not await self.cache.set(key + ":" + request_id, pending, ttl=PROJECT_CREATE_REQUEST_TTL):
            raise ProjectWriteAuthorizationError("PROJECT_CREATE_CACHE_UNAVAILABLE", status_code=503)
        if not await self.cache.set(key, pending, ttl=PROJECT_CREATE_REQUEST_TTL):
            await self.cache.delete(key + ":" + request_id)
            raise ProjectWriteAuthorizationError("PROJECT_CREATE_CACHE_UNAVAILABLE", status_code=503)
        return pending

    async def has_pending(self, *, user_id: str, chat_id: str) -> bool:
        current = await self.cache.get(self.key(user_id, chat_id))
        return isinstance(current, dict) and time.time() < current.get("expires_at", 0)

    async def require_pending(self, *, user_id: str, chat_id: str, request_id: str) -> dict[str, Any]:
        """The exact, unexpired, current-turn request of this owner and chat."""
        from backend.apps.ai.tasks.async_skill_continuation import async_skill_latest_user_turn_key

        key = self.key(user_id, chat_id)
        pending = await self.cache.get(key + ":" + request_id)
        current = await self.cache.get(key)
        if (not isinstance(pending, dict) or pending.get("request_id") != request_id
                or not isinstance(current, dict) or current.get("request_id") != request_id
                or pending.get("user_id") != user_id or pending.get("chat_id") != chat_id
                or time.time() >= pending.get("expires_at", 0)):
            raise ProjectWriteAuthorizationError("PROJECT_CREATE_REQUEST_EXPIRED", status_code=409)
        latest = await self.cache.get(async_skill_latest_user_turn_key(user_id, chat_id))
        if latest != pending.get("message_id"):
            raise ProjectWriteAuthorizationError("PROJECT_CREATE_REQUEST_STALE", status_code=409)
        return pending

    async def claim(self, *, user_id: str, request_id: str) -> None:
        """One completion report wins; a second tab or replay is rejected."""
        client = await self.cache.client
        if not client or not await client.set(self.claim_key(user_id, request_id), "1",
                                              ex=PROJECT_CREATE_REQUEST_TTL, nx=True):
            raise ProjectWriteAuthorizationError("PROJECT_CREATE_REQUEST_STALE", status_code=409)

    async def finish(self, *, user_id: str, chat_id: str, request_id: str) -> None:
        key = self.key(user_id, chat_id)
        await self.cache.delete(key + ":" + request_id)
        current = await self.cache.get(key)
        if isinstance(current, dict) and current.get("request_id") == request_id:
            await self.cache.delete(key)


def require_new_project(project: dict[str, Any], pending: dict[str, Any]) -> None:
    """Reject rebinding an older Project; undo would otherwise delete it."""
    created_at = project.get("created_at")
    if isinstance(created_at, (int, float)) and created_at > 100_000_000_000:
        created_at = created_at / 1000  # client millisecond timestamps
    if isinstance(created_at, (int, float)) and created_at < pending["created_at"] - PROJECT_CREATE_MAX_AGE_SKEW_SECONDS:
        raise ProjectWriteAuthorizationError("PROJECT_CREATE_NOT_NEW", status_code=409)
