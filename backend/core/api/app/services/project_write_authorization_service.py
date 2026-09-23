"""Server-authoritative Project focus and write authorization.

Project focus instructions are client-decrypted and kept only in the short-lived
cache used for inference.  Directus stores only encrypted settings and the hash
of the opaque Project-owned focus id.  Write authorization is always recomputed
from the current chat, Project, Team role, focus binding, and write policy.
"""

from __future__ import annotations

import hashlib
import re
import time
import uuid
from typing import Any

from backend.core.api.app.services.directus.team_methods import TeamPermissionError


PROJECT_FOCUS_TTL_SECONDS = 7 * 24 * 60 * 60
PROJECT_WRITE_APPROVAL_TTL_SECONDS = 15 * 60
PROJECT_WRITE_RECEIPT_TTL_SECONDS = 24 * 60 * 60
PROJECT_READ_ROLES = {"owner", "admin", "member", "viewer"}
PROJECT_WRITE_ROLES = {"owner", "admin", "member"}
SUPPORTED_WRITE_MODES = {"apply_and_show", "always_ask"}
PROPOSAL_DIGEST_RE = re.compile(r"^[a-f0-9]{64}$")


class ProjectWriteAuthorizationError(PermissionError):
    """A stable, fail-closed Project authorization denial."""

    def __init__(self, code: str, *, status_code: int = 403) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def normalize_focus_id(focus_id: str) -> str:
    try:
        return str(uuid.UUID(focus_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ProjectWriteAuthorizationError("INVALID_PROJECT_FOCUS_ID", status_code=422) from exc


def focus_id_hash(focus_id: str) -> str:
    return hashlib.sha256(normalize_focus_id(focus_id).encode()).hexdigest()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _validate_write_binding(operation_id: str, proposal_digest: str) -> None:
    if not operation_id or len(operation_id) > 128:
        raise ProjectWriteAuthorizationError("INVALID_PROJECT_OPERATION_ID", status_code=422)
    if not PROPOSAL_DIGEST_RE.fullmatch(proposal_digest):
        raise ProjectWriteAuthorizationError("INVALID_PROJECT_PROPOSAL_DIGEST", status_code=422)


def _settings_revision(settings: dict[str, Any]) -> str:
    """Bind approvals to every server-visible/ciphertext settings change."""
    material = "\x00".join(
        str(settings.get(field) or "")
        for field in ("write_mode", "default_focus_id_hash", "encrypted_settings", "updated_at")
    )
    return _hash(material)


class ProjectWriteAuthorizationService:
    """Own the active Project-focus binding and immutable write approvals."""

    def __init__(self, directus_service: Any, cache_service: Any) -> None:
        self.directus_service = directus_service
        self.cache_service = cache_service

    @staticmethod
    def _focus_key(user_id: str, chat_id: str) -> str:
        return f"project_focus:v1:{_hash(user_id)}:{chat_id}"

    @staticmethod
    def _approval_key(user_id: str, chat_id: str, project_id: str, operation_id: str) -> str:
        return f"project_write_approval:v1:{_hash(user_id)}:{chat_id}:{_hash(project_id)}:{_hash(operation_id)}"

    @staticmethod
    def _receipt_key(user_id: str, chat_id: str, project_id: str, operation_id: str) -> str:
        return f"project_write_receipt:v1:{_hash(user_id)}:{chat_id}:{_hash(project_id)}:{_hash(operation_id)}"

    async def _require_team_role(self, team_id: str, user_id: str, roles: set[str]) -> dict[str, Any]:
        try:
            return await self.directus_service.team.require_team_role(team_id, user_id, roles)
        except TeamPermissionError as exc:
            raise ProjectWriteAuthorizationError("TEAM_PERMISSION_DENIED") from exc

    async def _require_chat_access(self, user_id: str, chat_id: str, team_id: str | None) -> dict[str, Any]:
        # This deliberately queries Directus. A historical client frame or stale
        # user chat-list cache must never establish focus authority.
        chat = await self.directus_service.chat.get_chat_metadata(chat_id, admin_required=True)
        if not chat:
            raise ProjectWriteAuthorizationError("CHAT_NOT_FOUND", status_code=404)
        if team_id:
            await self._require_team_role(team_id, user_id, PROJECT_READ_ROLES)
            if chat.get("hashed_team_id") != _hash(team_id):
                raise ProjectWriteAuthorizationError("CHAT_PROJECT_CONTEXT_MISMATCH", status_code=404)
        elif chat.get("hashed_team_id") is not None or chat.get("hashed_user_id") != _hash(user_id):
            raise ProjectWriteAuthorizationError("CHAT_NOT_FOUND", status_code=404)
        return chat

    async def _require_project_access(
        self,
        user_id: str,
        project_id: str,
        team_id: str | None,
        *,
        write: bool,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        membership = None
        if team_id:
            membership = await self._require_team_role(
                team_id,
                user_id,
                PROJECT_WRITE_ROLES if write else PROJECT_READ_ROLES,
            )
        project = await self.directus_service.project.get_project(project_id, user_id, team_id=team_id)
        if not project:
            raise ProjectWriteAuthorizationError("PROJECT_NOT_FOUND", status_code=404)
        return project, membership

    async def activate_focus(
        self,
        *,
        user_id: str,
        chat_id: str,
        project_id: str,
        focus_id: str,
        instruction: str,
        team_id: str | None = None,
    ) -> dict[str, Any]:
        await self._require_chat_access(user_id, chat_id, team_id)
        await self._require_project_access(user_id, project_id, team_id, write=False)
        settings = await self.directus_service.project.get_project_settings(project_id, user_id, team_id=team_id)
        expected_focus_hash = settings.get("default_focus_id_hash") if settings else None
        actual_focus_hash = focus_id_hash(focus_id)
        if not expected_focus_hash or expected_focus_hash != actual_focus_hash:
            raise ProjectWriteAuthorizationError("PROJECT_FOCUS_MISMATCH")
        binding = {
            "project_id_hash": _hash(project_id),
            "project_id": project_id,
            "focus_id_hash": actual_focus_hash,
            "focus_id": normalize_focus_id(focus_id),
            "team_id": team_id,
            "team_id_hash": _hash(team_id) if team_id else None,
            "instruction": instruction,
            "activated_at": int(time.time()),
        }
        if not await self.cache_service.set(
            self._focus_key(user_id, chat_id),
            binding,
            ttl=PROJECT_FOCUS_TTL_SECONDS,
        ):
            raise ProjectWriteAuthorizationError("PROJECT_FOCUS_CACHE_UNAVAILABLE", status_code=503)
        return binding

    async def get_active_focus(self, *, user_id: str, chat_id: str) -> dict[str, Any] | None:
        binding = await self.cache_service.get(self._focus_key(user_id, chat_id))
        # This cache entry is the authority, not a projection of durable state.
        # A miss means inactive: falling back to encrypted chat history would
        # let a historical client frame silently reactivate write authority.
        if not isinstance(binding, dict):
            return None
        team_id = binding.get("team_id") if isinstance(binding.get("team_id"), str) else None
        project_id = binding.get("project_id")
        if not isinstance(project_id, str):
            return None
        try:
            await self._require_chat_access(user_id, chat_id, team_id)
            await self._require_project_access(user_id, project_id, team_id, write=False)
            settings = await self.directus_service.project.get_project_settings(project_id, user_id, team_id=team_id)
        except ProjectWriteAuthorizationError:
            return None
        if not settings or settings.get("default_focus_id_hash") != binding.get("focus_id_hash"):
            return None
        return binding

    async def deactivate_focus(self, *, user_id: str, chat_id: str) -> bool:
        binding = await self.cache_service.get(self._focus_key(user_id, chat_id))
        if isinstance(binding, dict):
            team_id = binding.get("team_id") if isinstance(binding.get("team_id"), str) else None
            await self._require_chat_access(user_id, chat_id, team_id)
            if not await self.cache_service.delete(self._focus_key(user_id, chat_id)):
                raise ProjectWriteAuthorizationError("PROJECT_FOCUS_CACHE_UNAVAILABLE", status_code=503)
            return True
        return False

    async def approve_write(
        self,
        *,
        user_id: str,
        chat_id: str,
        project_id: str,
        operation_id: str,
        proposal_digest: str,
        team_id: str | None = None,
    ) -> dict[str, Any]:
        _validate_write_binding(operation_id, proposal_digest)
        decision = await self._current_write_decision(
            user_id=user_id,
            chat_id=chat_id,
            project_id=project_id,
            team_id=team_id,
        )
        if decision["write_mode"] != "always_ask":
            raise ProjectWriteAuthorizationError("PROJECT_WRITE_APPROVAL_NOT_REQUIRED", status_code=409)
        approval = {
            "operation_id": operation_id,
            "proposal_digest": proposal_digest,
            "project_id_hash": _hash(project_id),
            "chat_id": chat_id,
            "focus_id_hash": decision["focus_id_hash"],
            "settings_revision": decision["settings_revision"],
            "team_id_hash": _hash(team_id) if team_id else None,
            "approved_at": int(time.time()),
        }
        if not await self.cache_service.set(
            self._approval_key(user_id, chat_id, project_id, operation_id),
            approval,
            ttl=PROJECT_WRITE_APPROVAL_TTL_SECONDS,
        ):
            raise ProjectWriteAuthorizationError("PROJECT_WRITE_APPROVAL_CACHE_UNAVAILABLE", status_code=503)
        return approval

    async def _current_write_decision(
        self,
        *,
        user_id: str,
        chat_id: str,
        project_id: str,
        team_id: str | None,
    ) -> dict[str, Any]:
        await self._require_chat_access(user_id, chat_id, team_id)
        _project, membership = await self._require_project_access(user_id, project_id, team_id, write=True)
        binding = await self.cache_service.get(self._focus_key(user_id, chat_id))
        # Deliberately no DB fallback; see get_active_focus. Focus authority is
        # an ephemeral, explicitly activated server state.
        if not isinstance(binding, dict):
            raise ProjectWriteAuthorizationError("PROJECT_FOCUS_REQUIRED")
        if (
            binding.get("project_id_hash") != _hash(project_id)
            or binding.get("team_id_hash") != (_hash(team_id) if team_id else None)
        ):
            raise ProjectWriteAuthorizationError("PROJECT_FOCUS_MISMATCH")
        settings = await self.directus_service.project.get_project_settings(project_id, user_id, team_id=team_id)
        if not settings:
            raise ProjectWriteAuthorizationError("PROJECT_WRITE_MODE_REQUIRED", status_code=409)
        stored_mode = settings.get("write_mode")
        # An existing explicit legacy safe-write choice maps to the renamed
        # policy. Missing or unknown legacy values remain unresolved and deny.
        write_mode = "apply_and_show" if stored_mode == "auto_approve_safe_writes" else stored_mode
        if write_mode not in SUPPORTED_WRITE_MODES:
            raise ProjectWriteAuthorizationError("PROJECT_WRITE_MODE_REQUIRED", status_code=409)
        if (
            not settings.get("default_focus_id_hash")
            or settings.get("default_focus_id_hash") != binding.get("focus_id_hash")
        ):
            raise ProjectWriteAuthorizationError("PROJECT_FOCUS_MISMATCH")
        return {
            "authorized": True,
            "write_mode": write_mode,
            "focus_id_hash": binding["focus_id_hash"],
            "settings_revision": _settings_revision(settings),
            "team_role": membership.get("role") if membership else "owner",
        }

    async def require_write_authorization(
        self,
        *,
        requester_user_id: str,
        chat_id: str,
        project_id: str,
        operation_id: str,
        proposal_digest: str,
        team_id: str | None = None,
        consume_approval: bool = False,
    ) -> dict[str, Any]:
        """Authorize preflight/commit for the relay-resolved requester.

        ``proposal_digest`` is an opaque Project-key HMAC that binds the full
        canonical proposal, including its base. The executor must verify that
        HMAC and path policy after decrypting the envelope. This service binds
        the exact digest to user/chat/Project/focus/policy without receiving
        private paths or file hashes.
        """
        _validate_write_binding(operation_id, proposal_digest)
        decision = await self._current_write_decision(
            user_id=requester_user_id,
            chat_id=chat_id,
            project_id=project_id,
            team_id=team_id,
        )
        if decision["write_mode"] == "apply_and_show":
            return {**decision, "approval": "not_required"}

        receipt_key = self._receipt_key(requester_user_id, chat_id, project_id, operation_id)
        receipt = await self.cache_service.get(receipt_key)
        if isinstance(receipt, dict) and receipt.get("proposal_digest") == proposal_digest:
            return {**decision, "approval": "consumed", "idempotent_replay": True}

        approval_key = self._approval_key(requester_user_id, chat_id, project_id, operation_id)
        approval = await self.cache_service.get(approval_key)
        if not isinstance(approval, dict):
            raise ProjectWriteAuthorizationError("PROJECT_WRITE_APPROVAL_REQUIRED", status_code=409)
        if (
            approval.get("proposal_digest") != proposal_digest
            or approval.get("focus_id_hash") != decision["focus_id_hash"]
            or approval.get("project_id_hash") != _hash(project_id)
            or approval.get("team_id_hash") != (_hash(team_id) if team_id else None)
            or approval.get("settings_revision") != decision["settings_revision"]
        ):
            raise ProjectWriteAuthorizationError("PROJECT_WRITE_APPROVAL_MISMATCH", status_code=409)
        if not consume_approval:
            return {**decision, "approval": "approved"}

        consumed = await self.cache_service.get_and_delete(approval_key)
        if not isinstance(consumed, dict) or consumed.get("proposal_digest") != proposal_digest:
            receipt = await self.cache_service.get(receipt_key)
            if isinstance(receipt, dict) and receipt.get("proposal_digest") == proposal_digest:
                return {**decision, "approval": "consumed", "idempotent_replay": True}
            raise ProjectWriteAuthorizationError("PROJECT_WRITE_APPROVAL_REQUIRED", status_code=409)
        receipt = {
            "operation_id": operation_id,
            "proposal_digest": proposal_digest,
            "focus_id_hash": decision["focus_id_hash"],
            "consumed_at": int(time.time()),
        }
        if not await self.cache_service.set(receipt_key, receipt, ttl=PROJECT_WRITE_RECEIPT_TTL_SECONDS):
            raise ProjectWriteAuthorizationError("PROJECT_WRITE_APPROVAL_CACHE_UNAVAILABLE", status_code=503)
        return {**decision, "approval": "consumed", "idempotent_replay": False}
