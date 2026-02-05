# backend/core/api/app/routes/handlers/websocket_handlers/cancel_ai_task_handler.py
# Handles WebSocket requests to cancel an ongoing AI Celery task.

import logging
from typing import Dict, Any, Optional
from fastapi import WebSocket

from backend.core.api.app.routes.connection_manager import ConnectionManager
from backend.core.api.app.tasks.celery_config import app as celery_app # Celery app instance
from backend.core.api.app.services.cache import CacheService

logger = logging.getLogger(__name__)


async def handle_cancel_ai_task(
    websocket: WebSocket,
    manager: ConnectionManager,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any],
    cache_service: Optional[CacheService] = None
):
    """
    Handles a request to cancel an AI task.
    
    This handler:
    1. Sends a revocation signal to Celery to stop the task
    2. Clears the active_ai_task marker in cache so the typing indicator stops immediately
    
    Payload is expected to contain:
    {
        "task_id": "celery_task_id_to_cancel",
        "chat_id": "chat_id_where_task_is_running"  # Required to clear active task marker
    }
    """
    task_id_to_cancel = payload.get("task_id")
    chat_id = payload.get("chat_id")
    log_prefix = f"[CancelAI Task][User: {user_id[:6]}][Device: {device_fingerprint_hash[:6]}]"

    if not task_id_to_cancel:
        logger.warning(f"{log_prefix} 'task_id' not provided in cancel_ai_task payload: {payload}")
        await manager.send_personal_message(
            message={"type": "error", "payload": {"message": "Task ID is required for cancellation.", "details": "missing_task_id"}},
            user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash
        )
        return

    logger.info(f"{log_prefix} Received request to cancel AI task_id: {task_id_to_cancel}, chat_id: {chat_id}")

    try:
        # Revoke the task. terminate=True sends SIGTERM.
        # The task needs to be designed to handle this signal or check for is_revoked().
        # Our AI task checks is_revoked().
        celery_app.control.revoke(task_id_to_cancel, terminate=True, signal='SIGUSR1') # Using SIGUSR1 as tasks.py checks is_revoked
        logger.info(f"{log_prefix} Revocation signal sent for task_id: {task_id_to_cancel}")

        # CRITICAL: Clear the active_ai_task marker immediately so the typing indicator stops
        # The task's exception handler will also try to clear this, but we do it here proactively
        # to ensure the UI updates immediately without waiting for the task to process the signal
        if chat_id:
            try:
                if not cache_service:
                    cache_service = CacheService()
                cleared = await cache_service.clear_active_ai_task(chat_id)
                if cleared:
                    logger.info(f"{log_prefix} Cleared active_ai_task marker for chat {chat_id}")
                else:
                    logger.debug(f"{log_prefix} active_ai_task marker not found for chat {chat_id} (may already be cleared)")
            except Exception as cache_err:
                logger.warning(f"{log_prefix} Failed to clear active_ai_task marker: {cache_err}")
        else:
            logger.warning(f"{log_prefix} chat_id not provided - cannot clear active_ai_task marker. Typing indicator may persist until task processes revocation.")

        await manager.send_personal_message(
            message={"type": "ai_task_cancel_requested", "payload": {"task_id": task_id_to_cancel, "status": "revocation_sent"}},
            user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash
        )
    except Exception as e:
        logger.error(f"{log_prefix} Error revoking task_id {task_id_to_cancel}: {e}", exc_info=True)
        await manager.send_personal_message(
            message={"type": "error", "payload": {"message": f"Failed to send cancellation for task {task_id_to_cancel}.", "details": str(e)}},
            user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash
        )