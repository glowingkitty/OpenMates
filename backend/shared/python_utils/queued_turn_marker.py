"""Cache marker for a user follow-up that waits in a chat's queue.

A follow-up admitted while an assistant run is active stays out of the chat's
"latest user turn" fence until it is dispatched (feature.chat-queued-followups,
admission.synced). The marker lets the focus and async-skill continuation code
recognise such a row as queued rather than as a newer turn that supersedes the
running one. It lives here, outside the Celery task modules, so the WebSocket
handler can use it without importing worker code.
"""

from typing import Any


def queued_turn_pending_key(user_id: str, chat_id: str, message_id: str) -> str:
    """Return the cache key marking `message_id` as queued and not yet dispatched."""
    return f"async_skill_queued_turn_pending:{user_id}:{chat_id}:{message_id}"


QUEUED_TURN_PENDING = "queued_pending"
"""Value stored under `queued_turn_pending_key`; any other value means not queued."""


async def is_queued_turn_pending(cache_service: Any, user_id: str, chat_id: str, message_id: str) -> bool:
    """Return whether `message_id` still waits in the chat's queue."""
    return await cache_service.get(queued_turn_pending_key(user_id, chat_id, message_id)) == QUEUED_TURN_PENDING
