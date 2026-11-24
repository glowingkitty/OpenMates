"""Content-free cancellation intent shared by the API and AI worker."""

from typing import Any

# Longer than the worker's maximum runtime, bounded so abandoned intents expire.
CANCELLATION_INTENT_TTL_SECONDS = 3600


def cancellation_intent_key(user_id: str, chat_id: str, task_id: str) -> str:
    """Scope intent to the authenticated owner, chat and exact delivery."""
    return f"ai_task_cancel_requested:{user_id}:{chat_id}:{task_id}"


async def record_cancellation_intent(cache: Any, user_id: str, chat_id: str, task_id: str) -> None:
    """Record the exact delivery before the worker can receive a stop signal."""
    if not await cache.set(
        cancellation_intent_key(user_id, chat_id, task_id), "1", ttl=CANCELLATION_INTENT_TTL_SECONDS,
    ):
        raise RuntimeError("Cancellation intent could not be recorded")
