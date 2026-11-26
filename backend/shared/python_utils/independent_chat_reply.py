"""One short, answer-only delivery alongside an authenticated foreground chat turn."""

import hashlib
import json
import logging
import re
from typing import Any
from uuid import UUID

from backend.shared.python_utils.ai_task_cancellation import cancellation_scope_key

logger = logging.getLogger(__name__)
PARALLEL_CHAT_TURNS_CAPABILITY = "parallel_chat_turns_v1"
_INDEPENDENT_REPLY_TTL = 900


def supports_parallel_chat_turns(websocket: Any) -> bool:
    """Read the authenticated socket's negotiated presentation capability."""
    return getattr(websocket, "scope", {}).get(PARALLEL_CHAT_TURNS_CAPABILITY) is True


def _slot(chat_id: str) -> str:
    return f"independent_chat_reply:{chat_id}"


def _binding(request: Any) -> dict[str, Any] | None:
    """Bind the existing immutable inference identity and the exact user text."""
    content = request.current_user_content
    if (not isinstance(content, str) or not content.strip() or len(content) > 1200
            or re.search(r"(?<!\w)@\w", content)
            or any(getattr(request, flag, None) for flag in (
                "team_id", "is_external", "is_anonymous", "is_incognito", "is_sub_chat",
                "parent_id", "orchestration_id", "user_task_id", "preprocessing_resume_ref",
                "is_sub_chat_continuation", "is_async_skill_continuation", "is_focus_mode_continuation",
                "is_app_settings_memories_continuation", "is_connected_account_permission_continuation",
                "active_input_reply",
                "active_input_steer_task_id", "active_input_steer_batch_id",
            ))):
        return None
    task_id, source_id = request.recovery_task_id, request.active_input_parallel_source
    try:
        if any(str(UUID(value)) != value for value in (task_id, source_id, request.recovery_turn_id,
                                                       request.recovery_preflight_id)):
            return None
    except (ValueError, AttributeError, TypeError):
        return None
    if (task_id == source_id or request.queue_revision != 1 or not request.message_id
            or not request.active_input_parallel_source_message
            or request.active_input_parallel_source_message == request.message_id
            or not request.user_id or not request.chat_id
            or request.user_id_hash != hashlib.sha256(request.user_id.encode()).hexdigest()):
        return None
    latest = next((item for item in reversed(request.message_history) if item.role == "user"), None)
    if latest is None or latest.message_id != request.message_id or latest.content != content:
        return None
    return {
        "user_id": request.user_id, "chat_id": request.chat_id, "task_id": task_id,
        "source_id": source_id, "source_message_id": request.active_input_parallel_source_message,
        "preflight_id": request.recovery_preflight_id,
        "turn_id": request.recovery_turn_id, "message_id": request.message_id,
        "content_digest": hashlib.sha256(content.encode()).hexdigest(),
    }


async def reserve_independent_reply(cache: Any, request: Any) -> int:
    """Atomically reserve one slot against the observed foreground.

    Return 1 for a new dispatch, 2 for an exact retry and 0 for the normal queue.
    Once admitted the original foreground may also finish independently.
    """
    binding = _binding(request)
    if not binding:
        return 0
    client = await cache.client
    if client is None:
        return 0
    return int(await client.eval(
        """
        local current = redis.call('GET', KEYS[2])
        if current == ARGV[2] then return 2 end
        if current or redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
        if redis.call('GET', KEYS[4]) ~= ARGV[5] then return 0 end
        local source = redis.call('GET', KEYS[5])
        if not source then return 0 end
        local scope = cjson.decode(source)
        if scope.user_id ~= ARGV[6] or scope.chat_id ~= ARGV[4] or scope.task_id ~= ARGV[1]
            or scope.user_message_id ~= ARGV[5] then return 0 end
        redis.call('SET', KEYS[2], ARGV[2], 'EX', ARGV[3])
        redis.call('SET', KEYS[3], ARGV[4], 'EX', ARGV[3])
        return 1
        """,
        5, cache._get_active_task_key(request.chat_id), _slot(request.chat_id),
        cache._get_task_chat_mapping_key(request.recovery_task_id),
        f"async_skill_latest_user_turn:{request.user_id}:{request.chat_id}",
        cancellation_scope_key(request.chat_id, binding["source_id"]),
        binding["source_id"], json.dumps(binding, sort_keys=True, separators=(",", ":")),
        _INDEPENDENT_REPLY_TTL, request.chat_id, binding["source_message_id"], request.user_id,
    ))


async def independent_reply_is_active(cache: Any, *, user_id: str, chat_id: str, task_id: str) -> bool:
    """Verify the second delivery for the same owner and chat."""
    slot = await cache.get(_slot(chat_id))
    return isinstance(slot, dict) and (slot.get("user_id"), slot.get("chat_id"), slot.get("task_id")) == (
        user_id, chat_id, task_id,
    )


async def current_independent_reply_task(cache: Any, *, user_id: str, chat_id: str) -> str | None:
    """Find the additional task only inside its authenticated chat slot."""
    slot = await cache.get(_slot(chat_id))
    if (isinstance(slot, dict) and (slot.get("user_id"), slot.get("chat_id")) == (user_id, chat_id)
            and isinstance(slot.get("task_id"), str)):
        return slot["task_id"]
    return None


async def verify_independent_reply(cache: Any, request: Any, task_id: str, claim: dict[str, Any]) -> bool:
    """Verify the server slot and the ordinary durable worker claim."""
    binding = _binding(request)
    return bool(
        binding and claim.get("claimed") is True and task_id == binding["task_id"]
        and (claim.get("inference_task_id"), claim.get("hashed_user_id"), claim.get("chat_id"),
             claim.get("preflight_id"), claim.get("turn_id"))
        == (task_id, request.user_id_hash, request.chat_id, binding["preflight_id"], binding["turn_id"])
        and await cache.get(_slot(request.chat_id)) == binding
    )


async def release_independent_reply(cache: Any, *, user_id: str, chat_id: str, task_id: str) -> bool:
    """Clear only this second slot, leaving foreground and queue authority intact."""
    try:
        client = await cache.client
        if client is None:
            return False
        return bool(await client.eval(
            """
            local current = redis.call('GET', KEYS[1])
            if not current then return 0 end
            local value = cjson.decode(current)
            if value.user_id ~= ARGV[1] or value.chat_id ~= ARGV[2] or value.task_id ~= ARGV[3] then
                return 0
            end
            return redis.call('DEL', KEYS[1])
            """,
            1, _slot(chat_id), user_id, chat_id, task_id,
        ))
    except Exception:
        logger.warning("Independent reply slot release failed", exc_info=True)
        return False


def completed_context_before_source(
    history: Any, *, source_message_id: str, message_id: str,
) -> list[Any]:
    """Only completed visible conversation before the captured foreground turn."""
    source_index = next((index for index, message in enumerate(history)
                         if message.role == "user" and message.message_id == source_message_id), None)
    if source_index is None:
        return []
    return [
        message for message in history[:source_index]
        if message.role in {"user", "assistant"} and message.message_id != message_id
        and message.sender_name not in {"async_tool_result", "tool"}
        and isinstance(message.content, str) and message.content.strip()
    ][-8:]


def is_independent_reply(request: Any) -> bool:
    """Use only the worker's verified marker, never the serialized request field."""
    return getattr(request, "_verified_independent_reply", False) is True
