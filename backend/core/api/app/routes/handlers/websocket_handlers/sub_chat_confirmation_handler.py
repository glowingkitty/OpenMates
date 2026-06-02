# backend/core/api/app/routes/handlers/websocket_handlers/sub_chat_confirmation_handler.py
#
# Handles explicit user approval/rejection for large sub-chat batches.
# The model can propose more than the auto-run threshold, but no child chats or
# Celery tasks are created until this handler consumes the pending Redis context.
# Capacity is rechecked at approval time so concurrent devices cannot exceed the
# per-parent hard cap.

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from backend.apps.ai.sub_chat_orchestration import (
    MAX_AUTO_SUB_CHATS_PER_TURN,
    MAX_DIRECT_SUB_CHATS_PER_PARENT,
    consume_pending_sub_chat_confirmation,
    count_direct_sub_chats,
    create_and_dispatch_sub_chats,
    create_sub_chat_records,
    dispatch_sub_chat_task,
    validate_sub_chat_capacity,
)
from backend.core.api.app.routes.connection_manager import ConnectionManager

if TYPE_CHECKING:
    from backend.core.api.app.services.cache import CacheService
    from backend.core.api.app.services.directus import DirectusService

logger = logging.getLogger(__name__)


async def _publish_to_parent_stream(cache_service: "CacheService", chat_id: str, payload: dict[str, Any]) -> None:
    await cache_service.publish_event(f"chat_stream::{chat_id}", payload)


async def handle_sub_chat_confirmation(
    *,
    manager: ConnectionManager,
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
        _otel_span, _otel_token = start_ws_handler_span("sub_chat_confirmation", user_id, payload, user_otel_attrs)
    except Exception:
        pass

    try:
        chat_id = payload.get("chat_id")
        task_id = payload.get("task_id")
        action = payload.get("action")
        approve_count = payload.get("approve_count")

        if not chat_id or not task_id or action not in {"approve", "cancel"}:
            logger.warning("Invalid sub_chat_confirmation payload from user %s: %s", user_id, payload)
            return

        is_owner = await directus_service.chat.check_chat_ownership(chat_id, user_id)
        if not is_owner:
            logger.warning("User %s attempted sub-chat confirmation for chat %s they do not own", user_id, chat_id)
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "You do not have permission to modify this chat."}},
                user_id,
                device_fingerprint_hash,
            )
            return

        pending_context = await consume_pending_sub_chat_confirmation(
            cache_service=cache_service,
            chat_id=chat_id,
            task_id=task_id,
        )
        if not pending_context:
            await manager.send_personal_message(
                {"type": "sub_chat_confirmation_resolved", "payload": {"chat_id": chat_id, "task_id": task_id, "status": "expired"}},
                user_id,
                device_fingerprint_hash,
            )
            return

        if action == "cancel":
            await manager.send_personal_message(
                {"type": "sub_chat_confirmation_resolved", "payload": {"chat_id": chat_id, "task_id": task_id, "status": "cancelled"}},
                user_id,
                device_fingerprint_hash,
            )
            return

        all_sub_chats = pending_context.get("sub_chats") or []
        if not isinstance(all_sub_chats, list) or not all_sub_chats:
            return

        if not isinstance(approve_count, int) or approve_count <= 0:
            approve_count = len(all_sub_chats)

        approved_sub_chats = all_sub_chats[:approve_count]
        execution_mode = pending_context.get("execution_mode", "parallel")
        existing_sub_chat_count = await count_direct_sub_chats(directus_service, chat_id)
        capacity_result = (
            {"allowed": True, "remaining": None, "message": ""}
            if execution_mode == "sequential"
            else validate_sub_chat_capacity(existing_sub_chat_count, len(approved_sub_chats))
        )
        if not capacity_result["allowed"]:
            await manager.send_personal_message(
                {
                    "type": "sub_chat_confirmation_resolved",
                    "payload": {
                        "chat_id": chat_id,
                        "task_id": task_id,
                        "status": "limit_exceeded",
                        "message": capacity_result["message"],
                        "max_direct_sub_chats": MAX_DIRECT_SUB_CHATS_PER_PARENT,
                    },
                },
                user_id,
                device_fingerprint_hash,
            )
            return

        from backend.apps.ai.skills.ask_skill import AskSkillRequest
        from backend.apps.ai.tasks.stream_consumer import _store_sub_chat_pending_context

        request_data = AskSkillRequest(**pending_context["parent_request_data"])
        log_prefix = f"[SUB_CHAT_CONFIRM:{chat_id}:{task_id}]"
        active_task_id = None
        if execution_mode == "sequential":
            await create_sub_chat_records(
                directus_service=directus_service,
                request_data=request_data,
                spawned_sub_chats=approved_sub_chats,
                log_prefix=log_prefix,
            )
            if approved_sub_chats:
                active_task_id = await dispatch_sub_chat_task(
                    request_data=request_data,
                    skill_config_dict=pending_context.get("skill_config_dict") or {},
                    sub_chat=approved_sub_chats[0],
                    log_prefix=log_prefix,
                )
                if active_task_id:
                    await cache_service.set_active_ai_task(approved_sub_chats[0]["id"], active_task_id)
        else:
            await create_and_dispatch_sub_chats(
                directus_service=directus_service,
                request_data=request_data,
                skill_config_dict=pending_context.get("skill_config_dict") or {},
                spawned_sub_chats=approved_sub_chats,
                log_prefix=log_prefix,
            )

        spawn_payload = {
            "type": "spawn_sub_chats",
            "task_id": task_id,
            "chat_id": chat_id,
            "user_id_uuid": user_id,
            "user_id_hash": request_data.user_id_hash,
            "message_id": task_id,
            "sub_chats": approved_sub_chats,
            "report_trigger": pending_context.get("report_trigger", "all"),
            "execution_mode": execution_mode,
        }
        await _publish_to_parent_stream(cache_service, chat_id, spawn_payload)

        if any(sc.get("wait_for_completion", True) for sc in approved_sub_chats):
            if execution_mode == "sequential":
                await cache_service.set(
                    f"sub_chat_pending:{chat_id}",
                    {
                        "parent_task_id": task_id,
                        "parent_request_data": request_data.model_dump(mode="json"),
                        "skill_config_dict": pending_context.get("skill_config_dict") or {},
                        "expected_sub_chat_ids": [str(sc.get("id")) for sc in approved_sub_chats if sc.get("id")],
                        "sub_chats": approved_sub_chats,
                        "completed": {},
                        "report_trigger": pending_context.get("report_trigger", "all"),
                        "execution_mode": "sequential",
                        "context_policy": pending_context.get("context_policy", "previous_summary"),
                        "next_index": 1 if approved_sub_chats else 0,
                        "active_sub_chat_id": approved_sub_chats[0].get("id") if approved_sub_chats else None,
                        "active_task_id": active_task_id,
                        "created_at": pending_context.get("created_at"),
                    },
                    ttl=60 * 60 * 24,
                )
                await _publish_to_parent_stream(cache_service, chat_id, {
                    "type": "sub_chat_progress",
                    "task_id": task_id,
                    "chat_id": chat_id,
                    "user_id_uuid": user_id,
                    "user_id_hash": request_data.user_id_hash,
                    "message_id": task_id,
                    "execution_mode": "sequential",
                    "status": "running",
                    "total": len(approved_sub_chats),
                    "completed": 0,
                    "active_sub_chat_id": approved_sub_chats[0].get("id") if approved_sub_chats else None,
                })
            else:
                await _store_sub_chat_pending_context(
                    cache_service=cache_service,
                    parent_request_data=request_data,
                    parent_task_id=task_id,
                    sub_chats=approved_sub_chats,
                    report_trigger=pending_context.get("report_trigger", "all"),
                    skill_config_dict=pending_context.get("skill_config_dict") or {},
                    log_prefix=log_prefix,
                )
            await _publish_to_parent_stream(cache_service, chat_id, {
                "type": "awaiting_sub_chats_completion",
                "task_id": task_id,
                "chat_id": chat_id,
                "user_id_uuid": user_id,
                "user_id_hash": request_data.user_id_hash,
                "message_id": task_id,
            })

        await manager.send_personal_message(
            {
                "type": "sub_chat_confirmation_resolved",
                "payload": {
                    "chat_id": chat_id,
                    "task_id": task_id,
                    "status": "approved",
                    "approved_count": len(approved_sub_chats),
                    "max_auto_sub_chats": MAX_AUTO_SUB_CHATS_PER_TURN,
                    "max_direct_sub_chats": MAX_DIRECT_SUB_CHATS_PER_PARENT,
                },
            },
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
