"""Persist client-encrypted voice-call transcript messages.

This first-party WebSocket surface is deliberately separate from ordinary sends and
AI completions.  A live call issues each message identity before the client may
store it, and only ciphertext crosses this durable boundary.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from backend.core.api.app.services.directus.chat_methods import _validate_client_encrypted_message_content
from backend.shared.python_utils.chat_ciphertext_fingerprint import (
    authoritative_chat_fingerprint,
    validate_message_matches_authoritative_fingerprint,
)
from backend.shared.python_utils.voice_call_registry import require_active_call

logger = logging.getLogger(__name__)

_ALLOWED_FIELDS = frozenset({
    "request_id", "call_id", "chat_id", "message_id", "role",
    "encrypted_content", "created_at", "revision", "user_message_id", "_traceparent",
})
_MAX_CIPHERTEXT_LENGTH = 128_000
_MAX_REVISIONS = 64
_MESSAGE_ID = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
_TRACEPARENT = re.compile(r"^[0-9a-f]{2}-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")


class CallMessageError(ValueError):
    def __init__(self, code: str, current_revision: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.current_revision = current_revision


def _validated_message(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) - _ALLOWED_FIELDS:
        raise CallMessageError("invalid_call_message")
    traceparent = payload.get("_traceparent")
    if traceparent is not None and (not isinstance(traceparent, str) or not _TRACEPARENT.fullmatch(traceparent)):
        raise CallMessageError("invalid_call_message")
    message_id = payload.get("message_id")
    chat_id = payload.get("chat_id")
    call_id = payload.get("call_id")
    request_id = payload.get("request_id")
    role = payload.get("role")
    ciphertext = payload.get("encrypted_content")
    created_at = payload.get("created_at")
    revision = payload.get("revision")
    if not all(isinstance(value, str) and _MESSAGE_ID.fullmatch(value)
               for value in (message_id, chat_id, call_id, request_id)):
        raise CallMessageError("invalid_call_message")
    if role not in {"user", "assistant"}:
        raise CallMessageError("invalid_call_message_role")
    if not isinstance(ciphertext, str) or len(ciphertext) > _MAX_CIPHERTEXT_LENGTH:
        raise CallMessageError("invalid_call_ciphertext")
    try:
        _validate_client_encrypted_message_content(message_id, ciphertext)
    except ValueError as exc:
        raise CallMessageError("invalid_call_ciphertext") from exc
    if type(created_at) is not int or created_at <= 0 or created_at > int(time.time()) + 300:
        raise CallMessageError("invalid_call_message_timestamp")
    if type(revision) is not int or not 1 <= revision <= _MAX_REVISIONS:
        raise CallMessageError("invalid_call_message_revision")
    user_message_id = payload.get("user_message_id")
    if user_message_id is not None and (
        role != "assistant" or not isinstance(user_message_id, str)
        or not _MESSAGE_ID.fullmatch(user_message_id)
    ):
        raise CallMessageError("invalid_call_message")
    return {
        "request_id": request_id, "call_id": call_id, "chat_id": chat_id,
        "message_id": message_id, "role": role,
        "encrypted_content": ciphertext, "created_at": created_at,
        "revision": revision, "user_message_id": user_message_id,
    }


async def _load_message(directus_service: Any, message_id: str) -> dict[str, Any] | None:
    rows = await directus_service.get_items(
        "messages",
        params={"filter[client_message_id][_eq]": message_id,
                "fields": "id,client_message_id,chat_id,hashed_user_id,role,encrypted_content,queue_revision,queue_pending_revision,created_at,user_message_id",
                "limit": 1},
        no_cache=True, admin_required=True, raise_on_error=True,
    )
    if not isinstance(rows, list):
        raise RuntimeError("Call message authority unavailable")
    return rows[0] if rows else None


def _same_identity(row: dict[str, Any], message: dict[str, Any], user_id_hash: str) -> bool:
    return (
        row.get("client_message_id") == message["message_id"]
        and row.get("chat_id") == message["chat_id"]
        and row.get("hashed_user_id") == user_id_hash
        and row.get("role") == message["role"]
        and row.get("created_at") == message["created_at"]
        and (row.get("user_message_id") or None) == message["user_message_id"]
    )


async def _advance_chat_version(directus_service: Any, cache_service: Any, user_id: str,
                                chat_id: str, user_id_hash: str, created_at: int) -> int:
    """Advance the chat sync revision with a chat-row compare-and-swap."""
    for _ in range(8):
        chat = await directus_service.chat.get_chat_metadata(chat_id)
        if not chat or chat.get("hashed_user_id") != user_id_hash:
            raise CallMessageError("call_chat_not_owned")
        current = int(chat.get("messages_v") or 0)
        updated = await directus_service.update_item_if_version(
            "chats", chat_id,
            {"messages_v": current + 1, "updated_at": int(time.time()),
             "last_edited_overall_timestamp": max(int(chat.get("last_edited_overall_timestamp") or 0), created_at),
             "last_message_timestamp": max(int(chat.get("last_message_timestamp") or 0), created_at)},
            current, version_field="messages_v", owner_hash_field="hashed_user_id",
            owner_hash=user_id_hash, admin_required=True,
        )
        if updated:
            await cache_service.delete_chat_versions(user_id, chat_id)
            return current + 1
    raise RuntimeError("Call chat version update conflicted")


async def _invalidate_message_caches(cache_service: Any, user_id: str, chat_id: str) -> None:
    await cache_service.delete_chat_versions(user_id, chat_id)
    await cache_service.delete(f"chat:{chat_id}:messages")
    await cache_service.delete_sync_messages_history(user_id, chat_id)


async def _finish_new_message(directus_service: Any, cache_service: Any, user_id: str,
                              user_id_hash: str, message: dict[str, Any], row: dict[str, Any]) -> int:
    # Zero is a durable "created but not counted" marker. If a process dies after
    # writing the row, its replay still advances the chat sync revision. A crash
    # between that advance and this CAS may overadvance it once, which is safe:
    # messages_v is a revision, not a row count.
    messages_v = await _advance_chat_version(directus_service, cache_service, user_id,
                                message["chat_id"], user_id_hash, message["created_at"])
    updated = await directus_service.update_item_if_version(
        "messages", row["id"], {"queue_revision": 1}, 0,
        version_field="queue_revision",
        extra_filters={"chat_id": message["chat_id"], "role": message["role"]},
        owner_hash_field="hashed_user_id", owner_hash=user_id_hash, admin_required=True,
    )
    if not updated:
        latest = await _load_message(directus_service, message["message_id"])
        if not latest or int(latest.get("queue_revision") or 0) < 1:
            raise RuntimeError("Call message count marker update failed")
    await _invalidate_message_caches(cache_service, user_id, message["chat_id"])
    return messages_v


async def _finish_revision(directus_service: Any, cache_service: Any, user_id: str,
                           user_id_hash: str, message: dict[str, Any], row: dict[str, Any]) -> int | None:
    pending = int(row.get("queue_pending_revision") or 0)
    if not pending:
        return
    messages_v = await _advance_chat_version(directus_service, cache_service, user_id,
                                message["chat_id"], user_id_hash, message["created_at"])
    cleared = await directus_service.update_item_if_version(
        "messages", row["id"], {"queue_pending_revision": None}, pending,
        version_field="queue_pending_revision",
        extra_filters={"chat_id": message["chat_id"], "role": message["role"]},
        owner_hash_field="hashed_user_id", owner_hash=user_id_hash, admin_required=True,
    )
    if not cleared:
        latest = await _load_message(directus_service, message["message_id"])
        if not latest or latest.get("queue_pending_revision") is not None:
            raise RuntimeError("Call correction sync marker update failed")
    await _invalidate_message_caches(cache_service, user_id, message["chat_id"])
    return messages_v


async def _persist_encrypted_call_message(
    *, directus_service: Any, cache_service: Any, user_id: str,
    user_id_hash: str, session_hash: str, message: dict[str, Any], encryption_service: Any = None,
) -> tuple[str, int, int, dict[str, Any] | None]:
    """Return outcome, message revision, canonical chat version, and newly settled row."""
    if not session_hash:
        raise CallMessageError("call_session_unavailable")
    try:
        await require_active_call(
            cache_service, user_id=user_id, session_id=session_hash,
            chat_id=message["chat_id"], call_id=message["call_id"],
            message_id=message["message_id"], role=message["role"],
        )
    except ValueError as exc:
        if encryption_service is None:
            raise CallMessageError("call_message_not_authorized") from exc
        from backend.shared.python_utils.voice_action_receipts import require_committed_voice_action
        try:
            await require_committed_voice_action(cache_service=cache_service,
                directus_service=directus_service, encryption_service=encryption_service,
                user_id=user_id, user_hash=user_id_hash, session_id=session_hash, message=message)
        except ValueError as receipt_exc:
            raise CallMessageError("call_message_not_authorized") from receipt_exc

    chat = await directus_service.chat.get_chat_metadata(message["chat_id"])
    if (not chat or chat.get("hashed_user_id") != user_id_hash
            or chat.get("hashed_team_id") or chat.get("chat_visibility") in {"team", "direct"}):
        raise CallMessageError("call_chat_not_owned")
    fingerprint = authoritative_chat_fingerprint(chat)
    if not fingerprint:
        # Untitled legacy chats may have arbitrarily many pre-OM ciphertexts.
        # Preserve the established oldest modern key authority across pages.
        offset = 0
        while True:
            existing_rows = await directus_service.get_items(
                "messages",
                params={"filter[chat_id][_eq]": message["chat_id"],
                        "fields": "id,encrypted_content,encrypted_sender_name,encrypted_category,encrypted_model_name,encrypted_thinking_content,encrypted_thinking_signature",
                        "sort": "created_at,id", "limit": 100, "offset": offset},
                no_cache=True, admin_required=True, raise_on_error=True,
            )
            if not isinstance(existing_rows, list):
                raise RuntimeError("Call chat fingerprint authority unavailable")
            fingerprint = authoritative_chat_fingerprint(chat, existing_rows)
            if fingerprint or len(existing_rows) < 100:
                break
            offset += len(existing_rows)
    match = validate_message_matches_authoritative_fingerprint(message, fingerprint)
    if not match.valid:
        raise CallMessageError("chat_key_mismatch")

    committed_version: int | None = None

    async def receipt(outcome: str, revision: int) -> tuple[str, int, int, dict[str, Any] | None]:
        # Newly committed/repair writes already hold the actual chat CAS result.
        # Replays read current authority without incrementing the chat revision.
        messages_v = committed_version
        if messages_v is None:
            latest_chat = await directus_service.chat.get_chat_metadata(message["chat_id"])
            if not latest_chat:
                raise RuntimeError("Call chat version authority unavailable")
            if (latest_chat.get("hashed_user_id") != user_id_hash
                    or latest_chat.get("hashed_team_id")
                    or latest_chat.get("chat_visibility") in {"team", "direct"}):
                raise CallMessageError("call_chat_not_owned")
            messages_v = latest_chat.get("messages_v")
            if type(messages_v) is not int or messages_v < 0:
                raise RuntimeError("Call chat version authority unavailable")
        return outcome, revision, messages_v, dict(row) if committed_version is not None else None

    row = await _load_message(directus_service, message["message_id"])
    if not row:
        if message["revision"] != 1:
            raise CallMessageError("call_message_revision_gap")
        created = await directus_service.chat.create_message_in_directus({
            "message_id": message["message_id"], "chat_id": message["chat_id"],
            "hashed_user_id": user_id_hash, "role": message["role"],
            "encrypted_content": message["encrypted_content"],
            "created_at": message["created_at"], "queue_revision": 0,
            "user_message_id": message["user_message_id"],
        })
        if not created:
            raise RuntimeError("Call message storage failed")
        row = await _load_message(directus_service, message["message_id"])
        if not row:
            raise RuntimeError("Call message verification failed")
        if not _same_identity(row, message, user_id_hash):
            raise CallMessageError("call_message_identity_conflict")
        if row.get("encrypted_content") != message["encrypted_content"]:
            raise CallMessageError("call_message_revision_conflict")
        # The Directus writer returns only id/client_message_id on a duplicate.
        if "chat_id" in created:
            committed_version = await _finish_new_message(directus_service, cache_service, user_id,
                                      user_id_hash, message, row)
            return await receipt("created", 1)

    if not _same_identity(row, message, user_id_hash):
        raise CallMessageError("call_message_identity_conflict")
    current = int(row.get("queue_revision") or 0)
    if current == 0:
        committed_version = await _finish_new_message(directus_service, cache_service, user_id,
                                  user_id_hash, message, row)
        row = await _load_message(directus_service, message["message_id"])
        if not row:
            raise RuntimeError("Call message repair verification failed")
        current = int(row.get("queue_revision") or 0)
    if row.get("queue_pending_revision") is not None:
        committed_version = await _finish_revision(directus_service, cache_service, user_id,
                               user_id_hash, message, row)
        row = await _load_message(directus_service, message["message_id"])
        if not row:
            raise RuntimeError("Call correction repair verification failed")
        current = int(row.get("queue_revision") or 0)
    if message["revision"] <= current:
        if message["revision"] == current and row.get("encrypted_content") == message["encrypted_content"]:
            await _invalidate_message_caches(cache_service, user_id, message["chat_id"])
            return await receipt("replayed", current)
        if message["revision"] == current:
            raise CallMessageError("call_message_revision_conflict", current)
        await _invalidate_message_caches(cache_service, user_id, message["chat_id"])
        return await receipt("stale", current)
    if message["revision"] != current + 1:
        raise CallMessageError("call_message_revision_gap")
    updated = await directus_service.update_item_if_version(
        "messages", row["id"],
        {"encrypted_content": message["encrypted_content"], "queue_revision": message["revision"],
         "queue_pending_revision": message["revision"]},
        current, version_field="queue_revision",
        extra_filters={"chat_id": message["chat_id"], "role": message["role"]},
        owner_hash_field="hashed_user_id", owner_hash=user_id_hash, admin_required=True,
    )
    if not updated:
        winning = await _load_message(directus_service, message["message_id"])
        if winning and _same_identity(winning, message, user_id_hash):
            winning_revision = int(winning.get("queue_revision") or 0)
            if winning_revision == message["revision"]:
                if winning.get("encrypted_content") != message["encrypted_content"]:
                    raise CallMessageError("call_message_revision_conflict", winning_revision)
                if winning.get("queue_pending_revision") is not None:
                    committed_version = await _finish_revision(directus_service, cache_service, user_id,
                                           user_id_hash, message, winning)
                row = winning
                await _invalidate_message_caches(cache_service, user_id, message["chat_id"])
                return await receipt("replayed", winning_revision)
            if winning_revision > message["revision"]:
                await _invalidate_message_caches(cache_service, user_id, message["chat_id"])
                return await receipt("stale", winning_revision)
        raise RuntimeError("Call message revision storage failed")
    committed_version = await _finish_revision(directus_service, cache_service, user_id,
                           user_id_hash, message, updated)
    row = updated
    return await receipt("updated", message["revision"])


async def persist_encrypted_call_message(
    *, directus_service: Any, cache_service: Any, user_id: str,
    user_id_hash: str, session_hash: str, message: dict[str, Any], encryption_service: Any = None,
) -> tuple[str, int]:
    """Return the existing outcome/message-revision pair for persistence callers."""
    outcome, revision, _messages_v, _changed = await _persist_encrypted_call_message(
        directus_service=directus_service, cache_service=cache_service, user_id=user_id,
        user_id_hash=user_id_hash, session_hash=session_hash, message=message,
        encryption_service=encryption_service,
    )
    return outcome, revision


async def handle_call_message_completed(*, manager: Any, cache_service: Any,
                                        directus_service: Any, user_id: str,
                                        user_id_hash: str, session_hash: str,
                                        device_fingerprint_hash: str, payload: Any,
                                        encryption_service: Any = None) -> None:
    request_id = payload.get("request_id") if isinstance(payload, dict) else None
    try:
        message = _validated_message(payload)
        outcome, revision, messages_v, changed = await _persist_encrypted_call_message(
            directus_service=directus_service, cache_service=cache_service,
            user_id=user_id, user_id_hash=user_id_hash,
            session_hash=session_hash, message=message, encryption_service=encryption_service,
        )
        await manager.send_personal_message({"type": "call_message_confirmed", "payload": {
            "request_id": message["request_id"], "chat_id": message["chat_id"],
            "message_id": message["message_id"], "revision": revision, "outcome": outcome,
            "messages_v": messages_v,
        }}, user_id, device_fingerprint_hash)
        if changed is not None:
            # A repaired replay publishes the stored winning ciphertext, even if
            # this request carried an older partial transcript.
            await manager.broadcast_to_user({"type": "call_message_changed", "payload": {
                "chat_id": message["chat_id"], "message_id": message["message_id"],
                "role": changed["role"], "created_at": changed["created_at"],
                "encrypted_content": changed["encrypted_content"], "revision": revision,
                "user_message_id": changed.get("user_message_id"), "messages_v": messages_v,
            }}, user_id, exclude_device_hash=device_fingerprint_hash)
    except CallMessageError as exc:
        await manager.send_personal_message({"type": "call_message_rejected", "payload": {
            "request_id": request_id if isinstance(request_id, str) else None,
            "code": exc.code, "current_revision": exc.current_revision,
        }}, user_id, device_fingerprint_hash)
    except Exception:
        logger.exception("Encrypted call message persistence failed")
        await manager.send_personal_message({"type": "call_message_rejected", "payload": {
            "request_id": request_id if isinstance(request_id, str) else None,
            "code": "call_message_storage_failed",
        }}, user_id, device_fingerprint_hash)
