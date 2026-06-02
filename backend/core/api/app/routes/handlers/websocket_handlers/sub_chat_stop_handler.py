# backend/core/api/app/routes/handlers/websocket_handlers/sub_chat_stop_handler.py
#
# Handles user requests to stop a sequential sub-chat queue.
# Running children receive a Celery revoke signal so they can finalize a partial
# answer; queued children are marked as canceled in the parent orchestration
# context while their chat metadata remains visible to the user.

from __future__ import annotations

import logging
import time
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from backend.core.api.app.routes.connection_manager import ConnectionManager
    from backend.core.api.app.services.cache import CacheService
    from backend.core.api.app.services.directus import DirectusService

logger = logging.getLogger(__name__)


async def _publish_to_parent_stream(cache_service: "CacheService", chat_id: str, payload: dict[str, Any]) -> None:
    await cache_service.publish(f"chat_stream::{chat_id}", payload)


def _revoke_child_task(task_id: str) -> None:
    from backend.core.api.app.tasks.celery_config import app as celery_app

    celery_app.control.revoke(task_id, terminate=False)


async def handle_sub_chat_stop(
    *,
    manager: "ConnectionManager",
    user_id: str,
    device_fingerprint_hash: str,
    payload: dict[str, Any],
    cache_service: "CacheService",
    directus_service: "DirectusService",
    user_otel_attrs: dict | None = None,
) -> None:
    _otel_span, _otel_token = None, None
    try:
        from backend.shared.python_utils.tracing.ws_span_helper import start_ws_handler_span
        _otel_span, _otel_token = start_ws_handler_span("sub_chat_stop", user_id, payload, user_otel_attrs)
    except Exception:
        pass

    try:
        chat_id = payload.get("chat_id")
        task_id = payload.get("task_id")
        if not chat_id:
            logger.warning("Invalid sub_chat_stop payload from user %s: %s", user_id, payload)
            return

        is_owner = await directus_service.chat.check_chat_ownership(chat_id, user_id)
        if not is_owner:
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "You do not have permission to stop these sub-chats."}},
                user_id,
                device_fingerprint_hash,
            )
            return

        pending_key = f"sub_chat_pending:{chat_id}"
        pending_context = await cache_service.get(pending_key)
        if not isinstance(pending_context, dict) or pending_context.get("execution_mode") != "sequential":
            await manager.send_personal_message(
                {"type": "sub_chat_stop_resolved", "payload": {"chat_id": chat_id, "task_id": task_id, "status": "not_found"}},
                user_id,
                device_fingerprint_hash,
            )
            return

        completed = pending_context.get("completed") if isinstance(pending_context.get("completed"), dict) else {}
        expected_ids = [str(chat_id_value) for chat_id_value in pending_context.get("expected_sub_chat_ids", [])]
        active_sub_chat_id = pending_context.get("active_sub_chat_id")
        active_task_id = pending_context.get("active_task_id")
        pending_context["stop_requested"] = True
        pending_context["stopped_at"] = int(time.time())

        for expected_id in expected_ids:
            if expected_id == active_sub_chat_id or expected_id in completed:
                continue
            completed[expected_id] = {
                "summary": "Canceled before this sequential sub-chat started.",
                "task_id": None,
                "completed_at": int(time.time()),
                "cancelled": True,
            }
        pending_context["completed"] = completed
        await cache_service.set(pending_key, pending_context, ttl=60 * 60 * 24)

        if active_task_id and active_sub_chat_id:
            _revoke_child_task(str(active_task_id))
            await cache_service.clear_active_ai_task(str(active_sub_chat_id))
            status = "stopping"
        else:
            from backend.apps.ai.tasks.stream_consumer import _dispatch_sub_chat_parent_continuation

            pending_context["continuation_dispatched"] = True
            await cache_service.set(pending_key, pending_context, ttl=60 * 60 * 24)
            await _dispatch_sub_chat_parent_continuation(
                pending_context=pending_context,
                parent_chat_id=chat_id,
                log_prefix=f"[SUB_CHAT_STOP:{chat_id}:{task_id}]",
            )
            await cache_service.delete(pending_key)
            status = "stopped"

        await _publish_to_parent_stream(cache_service, chat_id, {
            "type": "sub_chat_progress",
            "task_id": pending_context.get("parent_task_id") or task_id,
            "chat_id": chat_id,
            "user_id_uuid": user_id,
            "user_id_hash": pending_context.get("parent_request_data", {}).get("user_id_hash"),
            "message_id": pending_context.get("parent_task_id") or task_id,
            "execution_mode": "sequential",
            "status": status,
            "total": len(expected_ids),
            "completed": len(completed),
            "active_sub_chat_id": active_sub_chat_id,
        })
        await manager.send_personal_message(
            {"type": "sub_chat_stop_resolved", "payload": {"chat_id": chat_id, "task_id": task_id, "status": status}},
            user_id,
            device_fingerprint_hash,
        )
    finally:
        if _otel_span is not None:
            try:
                from backend.shared.python_utils.tracing.ws_span_helper import end_ws_handler_span
                end_ws_handler_span(_otel_span, _otel_token)
            except Exception:
                pass
