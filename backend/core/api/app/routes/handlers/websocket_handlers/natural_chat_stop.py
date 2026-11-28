"""Apply a confirmed, saved personal terminal stop to one named execution."""

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from backend.shared.python_utils.ai_task_cancellation import cancellation_scope_key
from backend.shared.python_utils.explicit_chat_stop import (
    STOP_CLARIFY, STOP_REPLIES, STOP_REQUESTED, STOP_RUN_ENDED, STOP_RUN_REQUESTED,
    STOP_UNCONFIRMED, explicit_stop_label,
)
from backend.shared.python_utils.independent_chat_reply import current_independent_reply_task

logger = logging.getLogger(__name__)
_RECEIPT_TTL = 90 * 60
_MAX_WORK = 4


@dataclass(frozen=True)
class StopDecision:
    reply: str | None = None
    prior_request_pending: bool = False


@dataclass(frozen=True)
class _Work:
    user_message_id: str
    task_id: str
    code_runs: tuple[str, ...] = ()


async def _current_work(cache: Any, *, user_id: str, chat_id: str) -> list[_Work]:
    from backend.apps.ai.tasks.same_turn_skill_barrier import find_paused_code_work

    paused = await find_paused_code_work(cache, user_id=user_id, chat_id=chat_id)
    works = [
        _Work(row["turn_id"], row["source_delivery_task_id"], tuple(row["task_ids"]))
        for row in paused
    ]
    sources = {work.task_id for work in works}
    for task_id in (
        await cache.get_active_ai_task(chat_id),
        await current_independent_reply_task(cache, user_id=user_id, chat_id=chat_id),
    ):
        if not task_id or task_id in sources:
            continue
        scope = await cache.get(cancellation_scope_key(chat_id, task_id))
        if (isinstance(scope, dict)
                and (scope.get("user_id"), scope.get("chat_id"), scope.get("task_id")) == (user_id, chat_id, task_id)
                and not scope.get("team_id") and not scope.get("session_nonce")
                and isinstance(scope.get("user_message_id"), str)):
            works.append(_Work(scope["user_message_id"], task_id))
            sources.add(task_id)
        else:
            # A task with no exact user message bound to it could be the
            # intended target. Resolve after the worker publishes that binding.
            return []
    return works


def _matches(label: tuple[str, ...], content: str) -> bool:
    text = re.sub(r"```[\s\S]*?(?:```|$)|^>[^\n]*|https?://\S+", " ", content[:800], flags=re.MULTILINE)
    sentences = re.split(r"[.!?;\n]", text.casefold(), maxsplit=8)
    actions = [
        re.findall(r"[a-z0-9][a-z0-9-]*", sentence)
        for sentence in sentences
        if re.match(r"^\s*(?:please )?(?:run|start|launch|execute|build|test)\b", sentence)
    ]
    ambiguous = r"\b(?:not|never|except|skip|exclude|excluding|instead|without|avoid|omit)\b"
    if len(actions) != 1 or re.search(ambiguous, text.casefold()):
        return False
    words = actions[0]
    if {"and", "or", "then"} & set(words):
        return False
    width = len(label)
    return any(tuple(words[index:index + width]) == label for index in range(1, len(words) - width + 1))


async def resolve_natural_chat_stop(
    *, request: Any, cache: Any, directus: Any, manager: Any, device_hash: str,
    newly_enqueued: bool,
) -> StopDecision:
    """Resolve the labels only from committed user input scoped to current live work."""
    label = explicit_stop_label(request.current_user_content)
    if label is None:
        return StopDecision()
    latest = next((row for row in reversed(request.message_history) if row.role == "user"), None)
    if (not request.recovery_task_id or request.queue_revision != 1 or latest is None
            or (latest.message_id, latest.content) != (request.message_id, request.current_user_content)):
        return StopDecision(STOP_UNCONFIRMED)

    user_id, chat_id = request.user_id, request.chat_id
    binding = json.dumps((user_id, chat_id, request.recovery_task_id, request.message_id), separators=(",", ":"))
    key = "chat_stop_reply:v1:" + hashlib.sha256(binding.encode()).hexdigest()
    receipt = await cache.get(key)
    if isinstance(receipt, str) and receipt in STOP_REPLIES:
        return StopDecision(receipt)
    if not newly_enqueued:
        # A duplicate may run before the first handler stores its receipt, or
        # after a restart. It has no authority to resolve a replacement target.
        return StopDecision(prior_request_pending=True)

    result = STOP_CLARIFY
    if label:
        try:
            work = await _current_work(cache, user_id=user_id, chat_id=chat_id)
            old_requests = {
                row.message_id: row.content for row in request.message_history
                if row.role == "user" and row.message_id != request.message_id and isinstance(row.content, str)
            }
            # A missing label from any live target cannot prove uniqueness.
            if (0 < len(work) <= _MAX_WORK and all(item.user_message_id in old_requests for item in work)):
                matches = [item for item in work if _matches(label, old_requests[item.user_message_id])]
                if len(matches) == 1:
                    target = matches[0]
                    if len(target.code_runs) == 1:
                        from backend.core.api.app.routes.code_execution import request_owned_code_run_cancellation

                        status = await request_owned_code_run_cancellation(
                            execution_id=target.code_runs[0], user_id=user_id, cache_service=cache,
                        )
                        result = (STOP_RUN_REQUESTED if status == "cancelling" else
                                  STOP_RUN_ENDED if status else STOP_UNCONFIRMED)
                    elif not target.code_runs:
                        from .cancel_ai_task_handler import cancel_owned_ai_task

                        status = await cancel_owned_ai_task(
                            cache_service=cache, directus_service=directus, manager=manager, user_id=user_id,
                            device_fingerprint_hash=device_hash, chat_id=chat_id, task_id=target.task_id,
                        )
                        result = STOP_REQUESTED if status else STOP_UNCONFIRMED
        except Exception as exc:
            logger.warning("Scoped chat stop could not be confirmed (%s)", type(exc).__name__)
            result = STOP_UNCONFIRMED
    await cache.set(key, result, ttl=_RECEIPT_TTL)
    return StopDecision(result)
