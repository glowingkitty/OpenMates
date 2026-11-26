"""Content-free cancellation intent shared by the API and AI worker."""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Longer than the worker's maximum runtime, bounded so abandoned intents expire.
CANCELLATION_INTENT_TTL_SECONDS = 3600


def cancellation_scope_key(chat_id: str, task_id: str) -> str:
    return f"ai_task_cancel_scope:{chat_id}:{task_id}"


async def record_cancellation_scope(
    cache: Any, *, chat_id: str, task_id: str, user_id: str,
    team_id: str | None = None, session_nonce: str | None = None, user_message_id: str | None = None,
) -> None:
    """Bind the first-party task actor and, after a durable claim, its user message."""
    try:
        if await cache.set(
            cancellation_scope_key(chat_id, task_id),
            {"user_id": user_id, "chat_id": chat_id, "task_id": task_id,
             "team_id": team_id, "session_nonce": session_nonce, "user_message_id": user_message_id},
            ttl=CANCELLATION_INTENT_TTL_SECONDS,
        ):
            return
    except Exception:
        logger.warning("Live AI cancellation scope could not be recorded", exc_info=True)
        return
    logger.warning("Live AI cancellation scope could not be recorded")


async def fence_cancelled_turn_if_idle(
    cache: Any, *, chat_id: str, latest_key: str, expected_latest: str | None, task_id: str, ttl: int,
) -> None:
    """The stop of a finished delivery must never invalidate a newly admitted turn."""
    client = await cache.client
    if client is None:
        return
    await client.eval(
        "if redis.call('EXISTS', KEYS[1]) == 1 or (redis.call('GET', KEYS[2]) or '') ~= ARGV[1] "
        "then return 0 end; redis.call('SET', KEYS[2], ARGV[2], 'EX', ARGV[3]); return 1",
        2, cache._get_active_task_key(chat_id), latest_key,
        expected_latest or "", f"cancelled:{task_id}", ttl,
    )


def cancellation_intent_key(user_id: str, chat_id: str, task_id: str) -> str:
    """Scope intent to the authenticated owner, chat and exact delivery."""
    return f"ai_task_cancel_requested:{user_id}:{chat_id}:{task_id}"


async def record_cancellation_intent(cache: Any, user_id: str, chat_id: str, task_id: str) -> None:
    """Record the exact delivery before the worker can receive a stop signal."""
    if not await cache.set(
        cancellation_intent_key(user_id, chat_id, task_id), "1", ttl=CANCELLATION_INTENT_TTL_SECONDS,
    ):
        raise RuntimeError("Cancellation intent could not be recorded")
