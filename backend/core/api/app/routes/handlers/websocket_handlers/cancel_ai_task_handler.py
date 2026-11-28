"""Scoped cancellation for an authenticated first-party assistant turn."""

import logging
import re
from typing import Any

from backend.core.api.app.routes.connection_manager import volatile_ai_live_key
from backend.core.api.app.services.direct_chat_access import is_direct_chat, project_direct_chat_metadata
from backend.core.api.app.services.directus.team_methods import TEAM_ROLES, TeamPermissionError, hash_id
from backend.core.api.app.tasks.celery_config import app as celery_app
from backend.shared.python_utils.independent_chat_reply import independent_reply_is_active
from backend.shared.python_utils.ai_task_cancellation import (
    cancellation_scope_key,
    fence_cancelled_turn_if_idle,
    record_cancellation_intent,
)

logger = logging.getLogger(__name__)
_IDENTITY = re.compile(r"[a-zA-Z0-9_:-]{1,255}")


async def _authorized_chat_scope(
    *, cache: Any, directus: Any, manager: Any, user_id: str,
    device_fingerprint_hash: str, chat_id: str, task_id: str,
) -> bool:
    """Require current personal ownership or the task actor's current Team/live scope."""
    actor = await cache.get(cancellation_scope_key(chat_id, task_id))
    if not isinstance(actor, dict) or (
        actor.get("user_id"), actor.get("chat_id"), actor.get("task_id"),
    ) != (user_id, chat_id, task_id):
        actor = {}
    team_id = actor.get("team_id")
    session_nonce = actor.get("session_nonce")
    if session_nonce:
        if (manager.get_volatile_session_nonce(user_id, device_fingerprint_hash) != session_nonce
                or await cache.get(volatile_ai_live_key(session_nonce)) != hash_id(user_id)):
            return False
    else:
        chat = await directus.chat.get_chat_metadata(chat_id, admin_required=True)
        if not isinstance(chat, dict) or chat.get("id") != chat_id or "hashed_team_id" not in chat:
            return False
        if not chat["hashed_team_id"]:
            return chat.get("hashed_user_id") == hash_id(user_id) and not is_direct_chat(chat)
        if not isinstance(team_id, str) or hash_id(team_id) != chat["hashed_team_id"]:
            return False
        if is_direct_chat(chat):
            try:
                project_direct_chat_metadata(chat, user_id)
            except (ValueError, PermissionError):
                return False
    if team_id:
        try:
            await directus.team.require_team_role(team_id, user_id, TEAM_ROLES - {"viewer"})
        except TeamPermissionError:
            return False
    return True


async def cancel_owned_ai_task(
    *, cache_service: Any, directus_service: Any, manager: Any, user_id: str,
    device_fingerprint_hash: str, chat_id: str | None, task_id: str,
) -> str | None:
    """Apply the explicit Stop action to exactly one currently authorized execution."""
    if not isinstance(task_id, str) or not _IDENTITY.fullmatch(task_id):
        return None
    from backend.apps.ai.tasks.async_skill_continuation import (
        ASYNC_SKILL_CONTINUATION_TTL_SECONDS,
        async_skill_latest_user_turn_key,
        cancel_same_turn_source,
    )
    from backend.shared.python_utils.focus_continuation_history import (
        cancel_focus_execution,
        find_cancellable_focus_execution,
    )

    mapped_chat_id = await cache_service.get_chat_id_for_task(task_id)
    if chat_id is None:
        chat_id = mapped_chat_id
    if (not isinstance(chat_id, str) or not _IDENTITY.fullmatch(chat_id)
            or (mapped_chat_id is not None and mapped_chat_id != chat_id)
            or not await _authorized_chat_scope(
                cache=cache_service, directus=directus_service, manager=manager,
                user_id=user_id, device_fingerprint_hash=device_fingerprint_hash,
                chat_id=chat_id, task_id=task_id,
            )):
        return None

    foreground = (mapped_chat_id == chat_id and await cache_service.get_active_ai_task(chat_id) == task_id)
    independent = (not foreground and mapped_chat_id == chat_id and await independent_reply_is_active(
        cache_service, user_id=user_id, chat_id=chat_id, task_id=task_id,
    ))
    focus = not foreground and not independent and await find_cancellable_focus_execution(
        cache_service, user_id, chat_id, task_id,
    )
    if independent:
        await record_cancellation_intent(cache_service, user_id, chat_id, task_id)
        celery_app.control.revoke(task_id, terminate=True, signal="SIGUSR1")
        status = "revocation_sent"
    elif foreground or focus:
        # Record intent before SIGUSR1. The worker may observe this signal
        # before Celery records REVOKED and must seal an interrupted reply.
        latest_key = async_skill_latest_user_turn_key(user_id, chat_id)
        latest_turn = await cache_service.get(latest_key) if foreground else None
        await record_cancellation_intent(cache_service, user_id, chat_id, task_id)
        celery_app.control.revoke(task_id, terminate=True, signal="SIGUSR1")
        paused_cancelled = await cancel_same_turn_source(
            cache_service, user_id=user_id, chat_id=chat_id, source_task_id=task_id,
        )
        focus_cancelled = await cancel_focus_execution(cache_service, user_id, chat_id, task_id)
        if (foreground and not focus_cancelled
                and await cache_service.complete_active_ai_task_if_queue_empty(chat_id, task_id) == 1
                and not paused_cancelled):
            await fence_cancelled_turn_if_idle(
                cache_service, chat_id=chat_id, latest_key=latest_key,
                expected_latest=latest_turn, task_id=task_id,
                ttl=ASYNC_SKILL_CONTINUATION_TTL_SECONDS,
            )
        status = "revocation_sent"
    elif await cancel_same_turn_source(
        cache_service, user_id=user_id, chat_id=chat_id, source_task_id=task_id,
    ):
        status = "paused_turn_cancelled"
    else:
        return None
    return status


async def handle_cancel_ai_task(
    *, websocket: Any, manager: Any, user_id: str, device_fingerprint_hash: str,
    payload: dict[str, Any], cache_service: Any, directus_service: Any,
    user_otel_attrs: dict | None = None,
) -> None:
    """Signal only a presently bound delivery, or settle its exact parked turn."""
    task_id = payload.get("task_id")
    chat_id = payload.get("chat_id")
    span, token = None, None
    try:
        from backend.shared.python_utils.tracing.ws_span_helper import start_ws_handler_span
        span, token = start_ws_handler_span("cancel_ai_task", user_id, payload, user_otel_attrs)
    except Exception:
        pass

    async def send(kind: str, details: dict[str, Any]) -> None:
        await manager.send_personal_message(
            message={"type": kind, "payload": details},
            user_id=user_id, device_fingerprint_hash=device_fingerprint_hash,
        )

    try:
        if not isinstance(task_id, str) or not _IDENTITY.fullmatch(task_id):
            await send("error", {"code": "invalid_ai_task_cancel", "message": "A task ID is required."})
            return
        status = await cancel_owned_ai_task(
            cache_service=cache_service, directus_service=directus_service, manager=manager,
            user_id=user_id, device_fingerprint_hash=device_fingerprint_hash, chat_id=chat_id,
            task_id=task_id,
        )
        if status is None:
            await send("error", {"code": "ai_task_cancel_unavailable", "message": "This task is unavailable to stop."})
            return
        await send("ai_task_cancel_requested", {"task_id": task_id, "status": status})
    except Exception:
        logger.exception("Verified AI task cancellation did not settle")
        await send("error", {"code": "ai_task_cancel_failed", "message": "The task stop could not be confirmed."})
    finally:
        if span and token:
            from backend.shared.python_utils.tracing.ws_span_helper import end_ws_handler_span
            end_ws_handler_span(span, token)
