"""Content-free cancellation intent shared by the API and AI worker."""

# Longer than the worker's maximum runtime, bounded so abandoned intents expire.
CANCELLATION_INTENT_TTL_SECONDS = 3600


def cancellation_intent_key(user_id: str, chat_id: str, task_id: str) -> str:
    """Scope intent to the authenticated owner, chat and exact delivery."""
    return f"ai_task_cancel_requested:{user_id}:{chat_id}:{task_id}"
