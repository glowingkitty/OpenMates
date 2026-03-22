# backend/core/api/app/routes/handlers/websocket_handlers/focus_mode_deactivate_handler.py
# Handles WebSocket requests to deactivate a focus mode for a chat.
# This is triggered when the user rejects a focus mode during the countdown
# or clicks "Deactivate" in the focus mode context menu.

import logging
from typing import Dict, Any, Optional
from fastapi import WebSocket

from backend.core.api.app.routes.connection_manager import ConnectionManager
from backend.core.api.app.services.cache import CacheService

logger = logging.getLogger(__name__)


async def handle_focus_mode_deactivate(
    websocket: WebSocket,
    manager: ConnectionManager,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any],
    cache_service: Optional[CacheService] = None
):
    """
    Deactivate the active focus mode for a chat.

    Clears the encrypted_active_focus_id from the cache and dispatches
    a Celery task to persist the change to Directus.

    Payload:
    {
        "chat_id": "uuid-of-the-chat",
        "focus_id": "web-research"   # informational, for logging
    }
    """
    chat_id = payload.get("chat_id")
    focus_id = payload.get("focus_id", "unknown")
    log_prefix = f"[FocusModeDeactivate][User: {user_id[:6]}][Device: {device_fingerprint_hash[:6]}]"

    if not chat_id:
        logger.warning(f"{log_prefix} 'chat_id' not provided in focus_mode_deactivate payload")
        await manager.send_personal_message(
            message={
                "type": "error",
                "payload": {
                    "message": "chat_id is required to deactivate focus mode.",
                    "details": "missing_chat_id"
                }
            },
            user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash
        )
        return

    logger.info(f"{log_prefix} Deactivating focus mode '{focus_id}' for chat {chat_id}")

    try:
        if not cache_service:
            cache_service = CacheService()

        # Clear the encrypted_active_focus_id from the cache
        success = await cache_service.update_chat_active_focus_id(
            user_id=user_id,
            chat_id=chat_id,
            encrypted_focus_id=None  # Clear the field
        )

        if success:
            logger.info(f"{log_prefix} Cleared focus mode from cache for chat {chat_id}")
        else:
            logger.warning(f"{log_prefix} Failed to clear focus mode from cache for chat {chat_id}")

        # Dispatch Celery task to persist the change to Directus
        try:
            from backend.core.api.app.tasks.celery_config import app as celery_app_instance
            celery_app_instance.send_task(
                'app.tasks.persistence_tasks.persist_chat_active_focus_id',
                kwargs={
                    "chat_id": chat_id,
                    "encrypted_active_focus_id": None  # Clear the field
                },
                queue='persistence'
            )
            logger.info(f"{log_prefix} Dispatched Celery task to clear focus_id in Directus for chat {chat_id}")
        except Exception as celery_error:
            logger.error(f"{log_prefix} Error dispatching Celery task: {celery_error}", exc_info=True)

        # Acknowledge the deactivation to the client
        await manager.send_personal_message(
            message={
                "type": "focus_mode_deactivated",
                "payload": {
                    "chat_id": chat_id,
                    "focus_id": focus_id,
                    "status": "deactivated"
                }
            },
            user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash
        )

    except Exception as e:
        logger.error(f"{log_prefix} Error deactivating focus mode: {e}", exc_info=True)
        await manager.send_personal_message(
            message={
                "type": "error",
                "payload": {
                    "message": "Failed to deactivate focus mode.",
                    "details": str(e)
                }
            },
            user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash
        )
