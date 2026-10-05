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


def _focus_instruction_revision(settings: dict[str, Any]) -> str:
    return _hash("\x00".join(str(settings.get(field) or "") for field in ("default_focus_id_hash", "encrypted_settings")))


class ProjectWriteAuthorizationService:
    """Own the active Project-focus binding and immutable write approvals."""

    def __init__(self, directus_service: Any, cache_service: Any) -> None:
        self.directus_service = directus_service
        self.cache_service = cache_service

    @staticmethod
    def _focus_key(user_id: str, chat_id: str) -> str:
        return f"project_focus:v1:{_hash(user_id)}:{chat_id}"

    @staticmethod
    def _specialist_key(user_id: str, chat_id: str) -> str:
        return f"project_specialist_focus:v1:{_hash(user_id)}:{chat_id}"

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
        activation_request_id: str | None = None,
    ) -> dict[str, Any]:
        await self._require_chat_access(user_id, chat_id, team_id)
        project, _ = await self._require_project_access(user_id, project_id, team_id, write=False)
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
            "instruction_revision": _focus_instruction_revision(settings),
            "activation_id": str(uuid.uuid4()),
            "activated_at": int(time.time()),
        }
        if activation_request_id:
            from backend.core.api.app.services.project_focus_request_service import ProjectFocusRequestService
            service = ProjectFocusRequestService(self.cache_service, self.directus_service)
            pending = await self.cache_service.get(service.key(user_id, chat_id) + ":" + activation_request_id)
            if (not isinstance(pending, dict) or pending.get("request_id") != activation_request_id
                    or pending.get("project_id") != project_id or pending.get("user_id") != user_id
                    or pending.get("chat_id") != chat_id or pending.get("team_id") != team_id
                    or project.get("archived") or settings.get("auto_selection") is False):
                raise ProjectWriteAuthorizationError("PROJECT_FOCUS_REQUEST_EXPIRED", status_code=409)
            binding.update(activation_request_id=activation_request_id, activation_message_id=pending.get("message_id"))
            if not await service.write_activation(pending, binding):
                raise ProjectWriteAuthorizationError("PROJECT_FOCUS_REQUEST_STALE", status_code=409)
        elif not await self.cache_service.set(
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
        if binding.get("instruction_revision") != _focus_instruction_revision(settings):
            return None
        specialist = await self.cache_service.get(self._specialist_key(user_id, chat_id))
        specialist_id = specialist.get("focus_id") if (
            isinstance(specialist, dict) and specialist.get("base_activation_id") == binding.get("activation_id")
            and binding.get("activation_id")
        ) else None
        from backend.core.api.app.services.project_focus_request_service import ProjectFocusRequestService
        if not await ProjectFocusRequestService(self.cache_service, self.directus_service).activation_is_current(
            user_id=user_id, chat_id=chat_id, binding=binding,
        ):
            return None
        return {**binding, "specialist_focus_id": specialist_id}

    async def deactivate_focus(self, *, user_id: str, chat_id: str) -> bool:
        from backend.core.api.app.services.project_focus_request_service import ProjectFocusRequestService

        # Off also rejects any current automatic proposal; its timer cannot restore
        # Project authority on a later callback.
        pending_key = ProjectFocusRequestService.key(user_id, chat_id)
        pending = await self.cache_service.get(pending_key)
        if isinstance(pending, dict):
            await self._require_chat_access(user_id, chat_id, pending.get("team_id"))
            request_id = pending.get("request_id")
            if isinstance(request_id, str):
                if not await self.cache_service.delete(pending_key + ":" + request_id):
                    # The consumed request may already be gone; the current
                    # pointer below must still be removed before off succeeds.
                    if await self.cache_service.get(pending_key + ":" + request_id) is not None:
                        raise ProjectWriteAuthorizationError("PROJECT_FOCUS_CACHE_UNAVAILABLE", status_code=503)
            if not await self.cache_service.delete(pending_key):
                if await self.cache_service.get(pending_key) is not None:
                    raise ProjectWriteAuthorizationError("PROJECT_FOCUS_CACHE_UNAVAILABLE", status_code=503)
        consume_specialist = getattr(self.cache_service, "get_and_delete_pending_focus_activation", None)
        cancelled_specialist = None
        if consume_specialist:
            cancelled_specialist = await consume_specialist(chat_id, user_id=user_id)
        specialist_key = self._specialist_key(user_id, chat_id)
        if await self.cache_service.get(specialist_key) is not None:
            if not await self.cache_service.delete(specialist_key):
                raise ProjectWriteAuthorizationError("PROJECT_FOCUS_CACHE_UNAVAILABLE", status_code=503)
        binding = await self.cache_service.get(self._focus_key(user_id, chat_id))
        if isinstance(binding, dict):
            team_id = binding.get("team_id") if isinstance(binding.get("team_id"), str) else None
            await self._require_chat_access(user_id, chat_id, team_id)
            if not await self.cache_service.delete(self._focus_key(user_id, chat_id)):
                raise ProjectWriteAuthorizationError("PROJECT_FOCUS_CACHE_UNAVAILABLE", status_code=503)
        if isinstance(pending, dict) and pending.get("continuation_id"):
            from backend.apps.ai.tasks.async_skill_continuation import dispatch_async_skill_continuation
            await dispatch_async_skill_continuation(cache_service=self.cache_service,
                async_task_id=pending["continuation_id"], completed_results=[{
                    "project_id": pending["project_id"], "access_granted": False,
                    "message": "User switched Project focus off. Continue without this Project's private context.",
                }])
        if isinstance(cancelled_specialist, dict):
            from backend.apps.ai.tasks.async_skill_continuation import async_skill_latest_user_turn_key
            latest = await self.cache_service.get(async_skill_latest_user_turn_key(user_id, chat_id))
            if latest == cancelled_specialist.get("message_id"):
                from backend.core.api.app.routes.handlers.websocket_handlers.focus_mode_rejected_handler import _trigger_continuation_without_focus
                from backend.core.api.app.utils.encryption import EncryptionService
                await _trigger_continuation_without_focus(self.cache_service, self.directus_service,
                    EncryptionService(), cancelled_specialist, "[ProjectFocusOff]")
        return isinstance(binding, dict)

    async def validate_specialist_context(
        self, *, user_id: str, chat_id: str, focus_id: str,
        instruction: str, item_revision: str,
        require_accepted: bool = True,
    ) -> dict[str, Any]:
        """Revalidate client-decrypted private Focus against live Project authority.

        This does not activate a Focus. The shared accepted Focus transition must
        choose its identity first; historical requests cannot establish a Project
        binding. Full content is transient and never server-decrypted from storage.
        """
        from backend.core.api.app.services.project_recommendation_service import project_item_revision

        parts = focus_id.split(":")
        if len(parts) != 3 or parts[0] != "project-focus":
            raise ProjectWriteAuthorizationError("INVALID_PROJECT_FOCUS_ID", status_code=422)
        project_id, item_id = normalize_focus_id(parts[1]), normalize_focus_id(parts[2])
        if not isinstance(instruction, str) or not instruction.strip() or len(instruction) > 128_000:
            raise ProjectWriteAuthorizationError("INVALID_PROJECT_FOCUS_INSTRUCTION", status_code=422)
        binding = await self.get_active_focus(user_id=user_id, chat_id=chat_id)
        if not binding or binding.get("project_id") != project_id:
            raise ProjectWriteAuthorizationError("PROJECT_FOCUS_REQUIRED")
        if require_accepted:
            specialist = await self.cache_service.get(self._specialist_key(user_id, chat_id))
            if (not isinstance(specialist, dict) or specialist.get("focus_id") != focus_id
                    or specialist.get("base_activation_id") != binding.get("activation_id")
                    or not binding.get("activation_id")):
                raise ProjectWriteAuthorizationError("PROJECT_SPECIALIST_FOCUS_NOT_ACCEPTED")
        item = await self.directus_service.project.get_item(project_id, item_id, user_id, team_id=binding.get("team_id"))
        if not item or item.get("item_type") not in {"embed", "file", "upload"} or item.get("deleted_target_state"):
            raise ProjectWriteAuthorizationError("PROJECT_FOCUS_NOT_FOUND", status_code=404)
        revision = project_item_revision(item)
        if not isinstance(item_revision, str) or item_revision != revision:
            raise ProjectWriteAuthorizationError("PROJECT_FOCUS_REVISION_STALE", status_code=409)
        # Private specialists are complete Focus documents, not arbitrary notes
        # relabelled by client metadata. Parse only transient supplied content.
        import re
        import yaml
        from backend.shared.python_utils.focus_mode_skill_loader import UniqueFocusYamlLoader
        from backend.core.api.app.services.project_authoring_service import ProjectFocusDocument
        match = re.fullmatch(r"---\r?\n(.*?)\r?\n---(?:\r?\n|$)(.*)", instruction.lstrip("\ufeff"), re.S)
        try:
            if not match:
                raise ValueError("Focus frontmatter required")
            metadata = yaml.load(match[1], Loader=UniqueFocusYamlLoader)
            if not isinstance(metadata, dict):
                raise ValueError("Focus metadata required")
            if "preprocessor_hint" in metadata:
                if "when_to_use" in metadata:
                    raise ValueError("Ambiguous Focus selection metadata")
                metadata["when_to_use"] = metadata.pop("preprocessor_hint")
            ProjectFocusDocument.model_validate({**metadata, "instructions": match[2].strip()})
        except (ValueError, yaml.YAMLError, RecursionError):
            raise ProjectWriteAuthorizationError("INVALID_PROJECT_FOCUS_INSTRUCTION", status_code=422) from None
        return {"focus_id": focus_id, "project_id": project_id, "item_id": item_id,
                "item_revision": revision, "instruction": instruction}

    async def accept_specialist_focus(self, *, user_id: str, chat_id: str, focus_id: str, request_id: str | None = None) -> None:
        """Record only a shared authoritative accepted transition, retaining its base."""
        binding = await self.get_active_focus(user_id=user_id, chat_id=chat_id)
        if binding:
            value = {"focus_id": focus_id, "project_id": binding["project_id"],
                     "base_activation_id": binding.get("activation_id"), "request_id": request_id}
            if not await self.cache_service.set(self._specialist_key(user_id, chat_id), value, ttl=PROJECT_FOCUS_TTL_SECONDS):
                raise ProjectWriteAuthorizationError("PROJECT_FOCUS_CACHE_UNAVAILABLE", status_code=503)
        else:
            if focus_id.startswith("project-focus:"):
                raise ProjectWriteAuthorizationError("PROJECT_FOCUS_REQUIRED")
            await self.cache_service.delete(self._specialist_key(user_id, chat_id))

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
        from backend.core.api.app.services.project_focus_request_service import ProjectFocusRequestService
        if not await ProjectFocusRequestService(self.cache_service, self.directus_service).activation_is_current(
            user_id=user_id, chat_id=chat_id, binding=binding,
        ):
            raise ProjectWriteAuthorizationError("PROJECT_FOCUS_REQUIRED")
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
