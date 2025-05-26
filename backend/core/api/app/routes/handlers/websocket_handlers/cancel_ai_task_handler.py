# backend/core/api/app/routes/handlers/websocket_handlers/cancel_ai_task_handler.py
# Handles WebSocket requests to cancel an ongoing AI Celery task.

import logging
from typing import Dict, Any
from fastapi import WebSocket

from backend.core.api.app.routes.connection_manager import ConnectionManager
from backend.core.api.app.tasks.celery_config import app as celery_app # Celery app instance

logger = logging.getLogger(__name__)

async def handle_cancel_ai_task(
    websocket: WebSocket,
    manager: ConnectionManager,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any]
):
    """
    Handles a request to cancel an AI task.
    Payload is expected to contain:
    {
        "task_id": "celery_task_id_to_cancel"
    }
    """
    task_id_to_cancel = payload.get("task_id")
    log_prefix = f"[CancelAI Task][User: {user_id[:6]}][Device: {device_fingerprint_hash[:6]}]"

    if not task_id_to_cancel:
        logger.warning(f"{log_prefix} 'task_id' not provided in cancel_ai_task payload: {payload}")
        await manager.send_personal_message(
            message={"type": "error", "payload": {"message": "Task ID is required for cancellation.", "details": "missing_task_id"}},
            user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash
        )
        return

    logger.info(f"{log_prefix} Received request to cancel AI task_id: {task_id_to_cancel}")

    try:
        # Revoke the task. terminate=True sends SIGTERM.
        # The task needs to be designed to handle this signal or check for is_revoked().
        # Our AI task checks is_revoked().
        celery_app.control.revoke(task_id_to_cancel, terminate=True, signal='SIGUSR1') # Using SIGUSR1 as tasks.py checks is_revoked
        logger.info(f"{log_prefix} Revocation signal sent for task_id: {task_id_to_cancel}")

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