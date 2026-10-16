"""Monotonic canonical revisions for client-encrypted system messages."""
from typing import Any


async def advance_system_message_version(directus: Any, *, chat_id: str,
                                         owner_hash: str, timestamp: int,
                                         minimum_version: int | None = None) -> int:
    """Allocate a revision, or safely settle a previously allocated revision.

    A call transcript can invalidate Redis's version hash. The durable chat row
    remains the authority, including when delayed persistence races a later turn.
    """
    for _ in range(8):
        chat = await directus.chat.get_chat_metadata(chat_id)
        if not chat or chat.get("hashed_user_id") != owner_hash:
            raise RuntimeError("System message chat authority unavailable")
        current = chat.get("messages_v")
        if type(current) is not int or current < 0:
            raise RuntimeError("System message version authority unavailable")
        target = current + 1 if minimum_version is None else max(current, minimum_version)
        updated = await directus.update_item_if_version(
            "chats", chat_id,
            {"messages_v": target,
             "last_edited_overall_timestamp": max(int(chat.get("last_edited_overall_timestamp") or 0), timestamp),
             "last_message_timestamp": max(int(chat.get("last_message_timestamp") or 0), timestamp)},
            current, version_field="messages_v", owner_hash_field="hashed_user_id",
            owner_hash=owner_hash, admin_required=True,
        )
        if updated:
            return target
    raise RuntimeError("System message version update conflicted")
