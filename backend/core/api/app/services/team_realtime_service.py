"""Team-scoped realtime event fanout.

This module keeps multi-user delivery separate from user-device synchronization.
Callers provide an authorized active-member set and safe encrypted or operational
payloads; plaintext message content is rejected before broadcast.
"""

import json
from typing import Any, Iterable

from backend.core.api.app.services.directus.team_methods import hash_id


TEAM_EVENT_ALLOWED_FIELDS = {
    "team_chat_message_created": frozenset(
        {
            "team_id",
            "chat_id",
            "message_id",
            "role",
            "encrypted_content",
            "encrypted_sender_name",
            "created_at",
            "encrypted_chat_key",
        }
    ),
    "team_ai_processing": frozenset({"team_id", "chat_id", "message_id", "ai_task_id", "status"}),
    "team_ai_response_completed": frozenset(
        {
            "team_id",
            "chat_id",
            "message_id",
            "role",
            "encrypted_content",
            "encrypted_sender_name",
            "encrypted_category",
            "encrypted_model_name",
            "encrypted_thinking_content",
            "encrypted_thinking_signature",
            "has_thinking",
            "thinking_token_count",
            "created_at",
            "status",
            "user_message_id",
        }
    ),
}


def connected_team_member_user_ids(manager: Any, active_member_hashes: set[str]) -> tuple[str, ...]:
    """Resolve active socket users against privacy-preserving membership hashes."""
    active_connections = getattr(manager, "active_connections", {})
    if not isinstance(active_connections, dict):
        return ()
    return tuple(user_id for user_id in active_connections if hash_id(user_id) in active_member_hashes)


async def broadcast_team_event(
    *,
    manager: Any,
    active_member_user_ids: Iterable[str],
    event_name: str,
    payload: dict[str, Any],
    cache_service: Any | None = None,
    active_member_hashes: Iterable[str] | None = None,
) -> None:
    """Broadcast one safe Team event once to every authorized active member."""
    allowed_fields = TEAM_EVENT_ALLOWED_FIELDS.get(event_name)
    if allowed_fields is None:
        raise ValueError(f"Unsupported Team realtime event: {event_name}")
    unexpected_fields = set(payload).difference(allowed_fields)
    if unexpected_fields:
        raise ValueError(f"Team realtime payload contains unapproved fields: {sorted(unexpected_fields)}")

    if cache_service is not None and active_member_hashes is not None:
        client = await cache_service.client
        if not client:
            raise RuntimeError("Team realtime publish requires cache")
        for member_hash in dict.fromkeys(active_member_hashes):
            if isinstance(member_hash, str) and member_hash:
                await client.publish(
                    f"websocket:user:{member_hash}",
                    json.dumps({"event": event_name, "type": event_name, "event_for_client": event_name, "payload": payload}),
                )
        return

    for user_id in dict.fromkeys(active_member_user_ids):
        if isinstance(user_id, str) and user_id:
            if cache_service is None:
                await manager.broadcast_to_user_specific_event(user_id, event_name, payload)
                continue
            client = await cache_service.client
            if not client:
                raise RuntimeError("Team realtime publish requires cache")
            await client.publish(
                f"websocket:user:{hash_id(user_id)}",
                json.dumps(
                    {
                        "event": event_name,
                        "type": event_name,
                        "event_for_client": event_name,
                        "user_id_uuid": user_id,
                        "payload": payload,
                    }
                ),
            )
