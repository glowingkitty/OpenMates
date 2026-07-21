"""
IdeaBucket scheduled-send orchestration.

This service consumes only the latest Redis processing-window payload, writes
durable chat history from client-encrypted ciphertext, and leaves the
server-processable payload in cache/AI boundaries only. Directus callers receive
only normal client-encrypted chat messages and sparse provenance metadata.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import inspect
import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from backend.core.api.app.schemas.chat import MessageInCache


logger = logging.getLogger(__name__)

IDEABUCKET_MESSAGE_NAMESPACE = uuid.UUID("9f60b32c-99d7-4932-a705-d50f18c9fbb3")
MIN_CLIENT_ENCRYPTED_PAYLOAD_BYTES = 29


class IdeaBucketScheduledSendService:
    """Processes due IdeaBucket windows without durable server-readable payload storage."""

    def __init__(
        self,
        *,
        cache_service: Any,
        persist_user_message: Callable[[dict[str, Any]], Any] | None = None,
        persist_system_event: Callable[[dict[str, Any]], Any] | None = None,
        dispatch_ai: Callable[[dict[str, Any]], Any] | None = None,
        mark_chat_provenance: Callable[[dict[str, Any]], Any] | None = None,
        delete_processed_draft: Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        self.cache_service = cache_service
        self.persist_user_message = persist_user_message
        self.persist_system_event = persist_system_event
        self.dispatch_ai = dispatch_ai
        self.mark_chat_provenance = mark_chat_provenance
        self.delete_processed_draft = delete_processed_draft

    async def process_due_window(
        self,
        *,
        user_id: str,
        processing_window_id: str,
        now: int | None = None,
    ) -> dict[str, Any]:
        """Locks and sends one due IdeaBucket processing window if eligible."""
        current_time = now if now is not None else int(datetime.now(timezone.utc).timestamp())
        lock_token = str(uuid.uuid4())
        window = await self.cache_service.lock_due_ideabucket_processing_window_in_cache(
            user_id,
            processing_window_id,
            now=current_time,
            lock_token=lock_token,
        )
        if not window:
            return {"status": "not_due", "processing_window_id": processing_window_id}
        if window.get("status") == "sent":
            return {
                "status": "already_sent",
                "processing_window_id": processing_window_id,
                "chat_id": window.get("chat_id"),
                "user_message_id": window.get("user_message_id"),
                "system_event_id": window.get("system_event_id"),
            }

        try:
            self._validate_locked_window(window)
            chat_id = str(window["chat_id"])
            version = int(window["version"])
            payload_hash = str(window["payload_hash"])
            user_message_id = self._stable_message_id(user_id, processing_window_id, version, payload_hash, "user")
            system_event_id = self._stable_message_id(user_id, processing_window_id, version, payload_hash, "system")
            hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
            created_at = current_time

            cache_versions = await self.cache_service.save_chat_message_and_update_versions(
                user_id=user_id,
                chat_id=chat_id,
                message_data=MessageInCache(
                    id=user_message_id,
                    chat_id=chat_id,
                    role="user",
                    sender_name="user",
                    encrypted_content=str(window["server_vault_encrypted_processing_payload"]),
                    created_at=created_at,
                    status="sending",
                ),
            )
            if not cache_versions:
                return await self._mark_failed(user_id, processing_window_id, lock_token, current_time, "ai_cache_failed")

            user_persist_payload = {
                "message_id": user_message_id,
                "chat_id": chat_id,
                "hashed_user_id": hashed_user_id,
                "role": "user",
                "encrypted_content": window["client_encrypted_future_user_message"],
                "created_at": created_at,
                "new_chat_messages_version": cache_versions.get("messages_v"),
                "new_last_edited_overall_timestamp": cache_versions.get("last_edited_overall_timestamp"),
                "user_id": user_id,
            }
            system_persist_payload = {
                "message_id": system_event_id,
                "chat_id": chat_id,
                "hashed_user_id": hashed_user_id,
                "role": "system",
                "encrypted_content": window["client_encrypted_ideabucket_system_event"],
                "created_at": created_at,
                "user_message_id": user_message_id,
                "user_id": user_id,
            }
            provenance_payload = {
                "chat_id": chat_id,
                "ideabucket": True,
                "ideabucket_processing_window_id": processing_window_id,
                "ideabucket_triggered_at": created_at,
            }

            await self._maybe_call(self.persist_user_message, user_persist_payload)
            await self._maybe_call(self.persist_system_event, system_persist_payload)
            await self._maybe_call(self.mark_chat_provenance, provenance_payload)

            ai_task_id = await self._maybe_call(
                self.dispatch_ai,
                {
                    "chat_id": chat_id,
                    "message_id": user_message_id,
                    "user_id": user_id,
                    "processing_window_id": processing_window_id,
                    "server_vault_encrypted_processing_payload": window["server_vault_encrypted_processing_payload"],
                    "payload_hash": payload_hash,
                },
            )
            if ai_task_id:
                await self.cache_service.set_active_ai_task(chat_id, str(ai_task_id))

            marked_sent = await self.cache_service.mark_ideabucket_processing_window_sent_in_cache(
                user_id,
                processing_window_id,
                lock_token=lock_token,
                user_message_id=user_message_id,
                system_event_id=system_event_id,
                sent_at=created_at,
            )
            if not marked_sent:
                return await self._mark_failed(user_id, processing_window_id, lock_token, current_time, "sent_tombstone_failed")

            await self._cleanup_processed_draft(user_id, chat_id)
            return {
                "status": "sent",
                "processing_window_id": processing_window_id,
                "chat_id": chat_id,
                "user_message_id": user_message_id,
                "system_event_id": system_event_id,
                "ai_task_id": str(ai_task_id) if ai_task_id else None,
            }
        except Exception as exc:
            logger.error(
                "IdeaBucket scheduled send failed for user=%s window=%s: %s",
                user_id,
                processing_window_id,
                exc,
                exc_info=True,
            )
            return await self._mark_failed(user_id, processing_window_id, lock_token, current_time, "processing_failed")

    async def _cleanup_processed_draft(self, user_id: str, chat_id: str) -> None:
        try:
            await self.cache_service.delete_user_draft_from_cache(user_id=user_id, chat_id=chat_id)
            await self.cache_service.delete_user_draft_version_from_chat_versions(user_id=user_id, chat_id=chat_id)
            await self._maybe_call(self.delete_processed_draft, {"user_id": user_id, "chat_id": chat_id})
        except Exception as exc:
            logger.warning("Failed to clean up processed IdeaBucket draft for chat %s: %s", chat_id, exc)

    async def _mark_failed(
        self,
        user_id: str,
        processing_window_id: str,
        lock_token: str,
        failed_at: int,
        error_code: str,
    ) -> dict[str, Any]:
        await self.cache_service.mark_ideabucket_processing_window_failed_in_cache(
            user_id,
            processing_window_id,
            lock_token=lock_token,
            failed_at=failed_at,
            error_code=error_code,
        )
        return {"status": "failed", "processing_window_id": processing_window_id, "error_code": error_code}

    def _stable_message_id(
        self,
        user_id: str,
        processing_window_id: str,
        version: int,
        payload_hash: str,
        role: str,
    ) -> str:
        identity = f"{user_id}:{processing_window_id}:{version}:{payload_hash}:{role}"
        return str(uuid.uuid5(IDEABUCKET_MESSAGE_NAMESPACE, identity))

    def _validate_locked_window(self, window: dict[str, Any]) -> None:
        required_fields = (
            "chat_id",
            "version",
            "scheduled_send_at",
            "server_vault_encrypted_processing_payload",
            "client_encrypted_future_user_message",
            "client_encrypted_ideabucket_system_event",
            "payload_hash",
        )
        missing = [field for field in required_fields if not window.get(field)]
        if missing:
            raise ValueError("IdeaBucket processing window missing required fields: " + ", ".join(missing))

        self._validate_client_encrypted_payload(
            "client_encrypted_future_user_message",
            str(window["client_encrypted_future_user_message"]),
        )
        self._validate_client_encrypted_payload(
            "client_encrypted_ideabucket_system_event",
            str(window["client_encrypted_ideabucket_system_event"]),
        )

    def _validate_client_encrypted_payload(self, field_name: str, encrypted_content: str) -> None:
        try:
            decoded = base64.b64decode(encrypted_content, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(f"{field_name} must contain client-encrypted base64 content") from exc
        if len(decoded) < MIN_CLIENT_ENCRYPTED_PAYLOAD_BYTES:
            raise ValueError(f"{field_name} client-encrypted content is too short")

    async def _maybe_call(self, callback: Callable[[dict[str, Any]], Any] | None, payload: dict[str, Any]) -> Any:
        if callback is None:
            return None
        result = callback(payload)
        if inspect.isawaitable(result):
            return await result
        return result
