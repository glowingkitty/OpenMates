"""Keep server-authored chat routing fields out of public skill input."""

from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import re
from typing import Any

from backend.shared.python_utils.explicit_chat_stop import STOP_REPLIES, explicit_stop_label

_ACTIVE_INPUT_FIELDS = (
    "active_input_reply", "active_input_steer_task_id", "active_input_steer_batch_id",
    "active_input_parallel_source", "active_input_parallel_source_message",
)
_active_input_scope: ContextVar[tuple[str, str, str] | None] = ContextVar(
    "active_input_scope", default=None,
)


@contextmanager
def authorize_active_input_dispatch(user_id: str, chat_id: str, message_id: str):
    """Enter only from the authenticated WebSocket after canonical chat admission."""
    token = _active_input_scope.set((user_id, chat_id, message_id))
    try:
        yield
    finally:
        _active_input_scope.reset(token)


def remove_untrusted_active_input(request: Any) -> Any:
    """Drop server-only routing state unless it originated in the scoped WS dispatch."""
    if (_active_input_scope.get() != (request.user_id, request.chat_id, request.message_id)
            and any(getattr(request, field, None) is not None for field in _ACTIVE_INPUT_FIELDS)):
        return request.model_copy(update=dict.fromkeys(_ACTIVE_INPUT_FIELDS))
    return request


ACTIVE_INPUT_CLARIFICATION = "Which work do you mean, and what would you like me to change or check?"
ACTIVE_INPUT_UNAVAILABLE = "I can no longer verify that work’s current progress. Check the latest result in this chat."
ACTIVE_INPUT_FINISHED = "The execution steps have reached an outcome. The assistant is still waiting to continue with the result."
ACTIVE_INPUT_STEER_UNAVAILABLE = (
    "That work is still running. I haven’t applied this change. "
    "You can send it as an edit once the result is ready."
)
_PROGRESS_TAIL = " execution steps have reached an outcome. The remaining work is still pending."
_PROGRESS = re.compile(r"(0|[1-9][0-9]{0,2}) of ([1-9][0-9]{0,2})" + re.escape(_PROGRESS_TAIL))
_STATUS_REQUESTS = frozenset({
    "status", "any updates", "what's the status", "what is the status", "what's the progress",
    "what is the progress", "how's it going", "how is it going", "is it done", "is it done yet",
    "is it still running", "are we done yet", "how far along is it",
})
_STATUS_QUESTION = re.compile(
    r"(?:(?:how's|how is) the (?:build|run|test|task|job|work) (?:going|progressing)"
    r"|is the (?:build|run|test|task|job|work) (?:done|done yet|finished|still running))"
)
_CLARIFICATION_REQUESTS = frozenset({
    "which one", "which work", "what about that", "what about it", "can you clarify",
})
_REPLY_AUTHORITY_TTL = 30 * 60


def active_input_progress_text(completed_count: int, task_count: int) -> str:
    return f"{completed_count} of {task_count}{_PROGRESS_TAIL}"


def closed_active_input_reply(reply: Any) -> str | None:
    """Return the known template kind; variable fields are bounded counts."""
    if not isinstance(reply, str):
        return None
    if reply in STOP_REPLIES:
        return "stop"
    if reply == ACTIVE_INPUT_CLARIFICATION:
        return "clarify"
    if reply == ACTIVE_INPUT_STEER_UNAVAILABLE:
        return "steer_unavailable"
    if reply in {ACTIVE_INPUT_UNAVAILABLE, ACTIVE_INPUT_FINISHED}:
        return "status"
    progress = _PROGRESS.fullmatch(reply)
    if progress and int(progress[1]) < int(progress[2]):
        return "status"
    return None


def _fixed_reply_authority_key(request: Any) -> str | None:
    """Match exactly one harmless fixed reply for the same admitted user revision."""
    reply = request.active_input_reply
    kind = closed_active_input_reply(reply)
    content = request.current_user_content
    if (kind not in {"status", "clarify", "stop"} or not isinstance(content, str) or len(content) > 100
            or any(getattr(request, flag, None) for flag in (
                "team_id", "is_external", "is_anonymous", "is_incognito", "is_sub_chat",
                "parent_id", "orchestration_id", "user_task_id", "preprocessing_resume_ref",
                "is_sub_chat_continuation", "is_async_skill_continuation", "is_focus_mode_continuation",
                "is_app_settings_memories_continuation", "is_connected_account_permission_continuation",
            ))):
        return None
    latest = next((message for message in reversed(request.message_history) if message.role == "user"), None)
    if latest is None or latest.message_id != request.message_id or latest.content != content:
        return None
    if kind == "stop":
        if explicit_stop_label(content) is None:
            return None
    else:
        if len(content) > 96:
            return None
        neutral_input = " ".join(content.casefold().replace("’", "'").strip().rstrip(".!?").split())
        is_status_question = neutral_input in _STATUS_REQUESTS or _STATUS_QUESTION.fullmatch(neutral_input)
        if not is_status_question and (kind != "clarify" or neutral_input not in _CLARIFICATION_REQUESTS):
            return None
    identity = (
        request.user_id, request.chat_id, request.message_id,
        request.recovery_task_id, request.recovery_preflight_id, request.recovery_turn_id,
    )
    if not all(isinstance(value, str) and value for value in identity):
        return None
    binding = json.dumps((*identity, request.queue_revision, content, reply), separators=(",", ":"))
    return "active_input_reply:v1:" + hashlib.sha256(binding.encode()).hexdigest()


async def admit_fixed_active_input_reply(cache: Any, request: Any) -> None:
    """Record first-party authority only after the original held outbox is verified."""
    key = _fixed_reply_authority_key(request)
    if key:
        await cache.set(key, "fixed", ttl=_REPLY_AUTHORITY_TTL)


async def verified_fixed_active_input_reply(cache: Any, request: Any, task_id: str) -> bool:
    """Call only after the worker wins the normal durable claim."""
    if request.recovery_task_id != task_id:
        return False
    key = _fixed_reply_authority_key(request)
    return bool(key and await cache.get(key) == "fixed"
                and await cache.get_active_ai_task(request.chat_id) == task_id)
