"""First-party authenticated read receipts; opaque IDs, owner/Team scoped."""
import hashlib
from typing import Any

from backend.core.api.app.services.notification_presence import mark_message_viewed


async def handle_notification_read_receipt(*, directus_service: Any, cache_service: Any, user_id: str, payload: dict) -> bool:
    chat_id, message_id = payload.get("chat_id"), payload.get("message_id")
    if not isinstance(chat_id, str) or not isinstance(message_id, str) or not 0 < len(message_id) <= 255:
        return False
    chat = await directus_service.chat.get_chat_metadata(chat_id, admin_required=True)
    if not isinstance(chat, dict) or chat.get("deleted"):
        return False
    user_hash = hashlib.sha256(user_id.encode()).hexdigest()
    if chat.get("hashed_team_id"):
        teams = await directus_service.get_items(
            "teams", params={"filter": {"hashed_team_id": {"_eq": chat["hashed_team_id"]}}, "fields": "team_id", "limit": 1},
            admin_required=True,
        )
        if not teams or not teams[0].get("team_id"):
            return False
        member = await directus_service.team.get_membership(teams[0]["team_id"], user_id)
        if not isinstance(member, dict) or member.get("status") != "active":
            return False
    elif chat.get("hashed_user_id") != user_hash:
        return False
    # The receiving account can acknowledge an as-yet-unpersisted completion.
    # Read state affects only its own notifications, never delivery persistence.
    return await mark_message_viewed(cache_service, user_id, chat_id, message_id)
