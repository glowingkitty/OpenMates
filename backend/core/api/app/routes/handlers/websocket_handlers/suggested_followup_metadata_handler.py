"""First-party WebSocket storage for a client-encrypted composer suggestion."""

import hashlib
import json
import logging
from typing import Any

from backend.core.api.app.services.directus.team_methods import TeamPermissionError, hash_id
from backend.shared.python_utils.client_ciphertext import is_client_encrypted_base64

logger = logging.getLogger(__name__)


def _message_row(value: Any) -> dict[str, Any] | None:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return None
    return value if isinstance(value, dict) else None


def _message_id(row: dict[str, Any]) -> str | None:
    return row.get("client_message_id") or row.get("message_id") or row.get("id")


async def _latest_message(cache_service, directus_service, user_id: str, chat_id: str) -> dict[str, Any] | None:
    """Use the AI cache for an unpersisted completion; verify against DB if present."""
    cached = await cache_service.get_ai_messages_history(user_id, chat_id, -1, -1)
    cache_row = _message_row(cached[-1]) if cached else None
    rows = await directus_service.get_items(
        "messages",
        params={
            "filter": {"chat_id": {"_eq": chat_id}},
            "fields": "id,client_message_id,role,created_at",
            "sort": ["-created_at", "-id"],
            "limit": 1,
        },
        admin_required=True,
    )
    if rows is None:
        raise RuntimeError("Could not verify the latest chat message")
    db_row = _message_row(rows[0]) if rows else None
    if cache_row and db_row:
        try:
            cache_time = int(cache_row.get("created_at") or 0)
            db_time = int(db_row.get("created_at") or 0)
        except (TypeError, ValueError):
            raise RuntimeError("Could not verify latest chat message time")
        # A newer durable turn must win over a stale or evicted cache row.
        if db_time >= cache_time and _message_id(db_row) != _message_id(cache_row):
            return db_row
    return cache_row or db_row


async def handle_suggested_followup_metadata(
    *,
    manager,
    cache_service,
    directus_service,
    user_id: str,
    device_fingerprint_hash: str,
    payload: dict[str, Any],
) -> None:
    """Store ciphertext only after fresh access and completed-source checks."""
    if not isinstance(payload, dict):
        payload = {}
    chat_id = payload.get("chat_id")
    team_id = payload.get("team_id")
    source_message_id = payload.get("source_message_id")
    source_task_id = payload.get("source_task_id")
    source_user_message_id = payload.get("source_user_message_id")
    ciphertext = payload.get("encrypted_suggested_followup_message")
    submitted_chat_key = payload.get("encrypted_chat_key")

    async def reject(code: str) -> None:
        error_payload = {"code": code, "chat_id": chat_id}
        result_type = "error"
        if code == "stale_suggested_followup_source":
            # Optional metadata uses a compare-and-set source fence. A losing
            # write is an explicit not-stored outcome, not a chat/server fault.
            result_type = "encrypted_suggested_followup_message_not_stored"
            error_payload.update({
                "source_message_id": source_message_id,
                "source_task_id": source_task_id,
                "source_user_message_id": source_user_message_id,
            })
        await manager.send_personal_message(
            {"type": result_type, "payload": error_payload},
            user_id,
            device_fingerprint_hash,
        )

    if (
        not isinstance(chat_id, str) or not chat_id
        or not isinstance(source_message_id, str) or not source_message_id or len(source_message_id) > 128
        or not isinstance(source_task_id, str) or not source_task_id or len(source_task_id) > 128
        or not isinstance(source_user_message_id, str) or not source_user_message_id or len(source_user_message_id) > 128
        or not isinstance(ciphertext, str) or len(ciphertext) > 8192
        or not is_client_encrypted_base64(ciphertext)
        or "suggested_followup_message" in payload
    ):
        await reject("invalid_suggested_followup_metadata")
        return

    # First-party authenticated WebSocket only. The authoritative chat row is
    # required; no new chat or ownership inferred from an untrusted cache key.
    chat = await directus_service.chat.get_chat_metadata(chat_id, admin_required=True)
    if not chat:
        await reject("chat_not_found")
        return
    hashed_team_id = chat.get("hashed_team_id")
    if hashed_team_id:
        if not isinstance(team_id, str) or hash_id(team_id) != hashed_team_id:
            await reject("team_chat_scope_mismatch")
            return
        try:
            await directus_service.team.require_team_role(team_id, user_id, {"owner", "admin", "member"})
        except TeamPermissionError:
            await reject("team_chat_permission_denied")
            return
    elif team_id or chat.get("hashed_user_id") != hashlib.sha256(user_id.encode()).hexdigest():
        await reject("chat_permission_denied")
        return

    # A stale client key could produce valid-looking ciphertext that other
    # devices cannot decrypt. Compare the opaque wrapped key, never unwrap it.
    if not isinstance(submitted_chat_key, str) or submitted_chat_key != chat.get("encrypted_chat_key"):
        await reject("chat_key_mismatch")
        return

    active_task = await cache_service.get_active_ai_task(chat_id)
    if active_task and active_task != source_task_id:
        await reject("stale_suggested_followup_source")
        return
    latest = await _latest_message(cache_service, directus_service, user_id, chat_id)
    if not latest or latest.get("role") != "assistant" or _message_id(latest) != source_message_id:
        await reject("stale_suggested_followup_source")
        return

    # Do not place plaintext suggestion text in Directus, cache, or logs.
    persisted = await directus_service.chat.update_chat_fields_in_directus(
        chat_id, {"encrypted_suggested_followup_message": ciphertext}
    )
    if not persisted:
        raise RuntimeError("Could not store encrypted suggested follow-up metadata")
    await cache_service.update_chat_list_item_field(
        user_id, chat_id, "encrypted_suggested_followup_message", ciphertext
    )
    event_payload = {
        "chat_id": chat_id,
        "source_message_id": source_message_id,
        "source_task_id": source_task_id,
        "source_user_message_id": source_user_message_id,
        "encrypted_suggested_followup_message": ciphertext,
    }
    await manager.send_personal_message(
        {"type": "encrypted_suggested_followup_message_stored", "payload": event_payload},
        user_id,
        device_fingerprint_hash,
    )
    await manager.broadcast_to_user(
        message={"type": "encrypted_chat_metadata", "payload": event_payload},
        user_id=user_id,
        exclude_device_hash=device_fingerprint_hash,
    )
