"""Settle exact queued revisions whose parked artifact producer cannot resume."""
from __future__ import annotations

import hashlib
from typing import Any


async def retire_parked_steers(cache: Any, *, user_id: str, chat_id: str, batch_id: str) -> None:
    from backend.core.api.app.services.directus import DirectusService
    from backend.shared.python_utils.queued_turn_marker import queued_turn_pending_key

    prefix = f"same_turn_skill:{batch_id}:"
    metadata = await cache.get(f"{prefix}batch")
    if (not isinstance(metadata, dict) or not metadata.get("code_work")
            or metadata.get("user_id") != user_id or metadata.get("chat_id") != chat_id):
        return
    client = await cache.client
    if client is None:
        raise RuntimeError("Parked steer retirement is unavailable")
    await client.set(f"{prefix}stopping", "1", ex=90 * 60)
    async with cache.queued_message_edit_lock(chat_id):
        rows = await cache.get_parked_steer_members(chat_id, user_id, batch_id)
        if not rows:
            return
        directus = DirectusService(cache_service=cache)
        try:
            for row in rows:
                member = row["member"]
                message_id = member["message_id"]
                revision = member["queue_revision"]
                mode = member["queue_mode"]
                result = await directus.chat.mark_queued_message_paused(
                    chat_id, user_id, message_id, revision, "dispatch_failed", queue_mode=mode,
                )
                if result.get("status") not in {"paused", "already_paused"}:
                    raise RuntimeError("Parked steer revision could not be durably paused")
                await cache.publish_event(f"user_updates::{hashlib.sha256(user_id.encode()).hexdigest()}", {
                    "event_for_client": "queued_handoff_paused",
                    "user_id_uuid": user_id,
                    "payload": {
                        "chat_id": chat_id, "message_id": message_id,
                        "reason_code": "dispatch_failed", "retryable": False,
                    },
                })
                await cache.delete(queued_turn_pending_key(user_id, chat_id, message_id))
                await cache.remove_parked_steer_member(chat_id, row["raw"])
        finally:
            await directus.close()
