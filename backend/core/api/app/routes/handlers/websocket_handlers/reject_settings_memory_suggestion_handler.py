# backend/core/api/app/routes/handlers/websocket_handlers/reject_settings_memory_suggestion_handler.py
"""
Handler for rejecting settings/memory suggestions.

When a user rejects a suggested settings/memory entry (shown as suggestion cards
in the UI), we store the rejection hash for cross-device sync. This uses a
zero-knowledge approach where only SHA-256 hashes are stored, never the actual
suggestion content.

Hash format: SHA-256 of "app_id:item_type:title.toLowerCase()"
"""
import logging
from typing import Dict, Any

from fastapi import WebSocket

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.routes.connection_manager import ConnectionManager
from backend.core.api.app.tasks.celery_config import app as celery_app

logger = logging.getLogger(__name__)


async def handle_reject_settings_memory_suggestion(
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    user_id: str,
    user_id_hash: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any]
):
    """
    Handle rejection of a settings/memory suggestion.
    
    Stores the rejection hash in the chat's rejected_suggestion_hashes array
    and broadcasts to other devices for cross-device sync.

    Expected payload structure:
    {
        "chat_id": "...",
        "rejection_hash": "..."  // SHA-256 hash of "app_id:item_type:title.toLowerCase()"
    }
    """
    try:
        chat_id = payload.get("chat_id")
        rejection_hash = payload.get("rejection_hash")

        if not chat_id:
            logger.error(f"Missing chat_id in rejection payload from {user_id}")
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Missing chat_id in rejection payload"}},
                user_id,
                device_fingerprint_hash
            )
            return

        if not rejection_hash:
            logger.error(f"Missing rejection_hash in rejection payload from {user_id}")
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Missing rejection_hash in rejection payload"}},
                user_id,
                device_fingerprint_hash
            )
            return

        # Validate hash format (should be 64 hex chars for SHA-256)
        if len(rejection_hash) != 64 or not all(c in '0123456789abcdef' for c in rejection_hash.lower()):
            logger.warning(f"Invalid rejection_hash format from {user_id}: {rejection_hash[:20]}...")
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Invalid rejection_hash format"}},
                user_id,
                device_fingerprint_hash
            )
            return

        # Verify chat ownership
        is_owner = await directus_service.chat.check_chat_ownership(chat_id, user_id)
        if not is_owner:
            logger.warning(f"User {user_id} attempted to reject suggestion for chat {chat_id} they don't own")
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "You do not have permission to modify this chat.", "chat_id": chat_id}},
                user_id,
                device_fingerprint_hash
            )
            return

        logger.info(f"Processing settings/memory suggestion rejection for chat {chat_id} from {user_id}")

        # Queue task to append rejection hash to chat's rejected_suggestion_hashes array
        # We use a dedicated task to handle atomic array append
        celery_app.send_task(
            "app.tasks.persistence_tasks.append_rejected_suggestion_hash",
            args=[chat_id, rejection_hash, user_id_hash, user_id],
            queue="persistence"
        )
        logger.info(f"Queued rejection hash append task for chat {chat_id}")

        # Broadcast to other devices owned by this user (for real-time cross-device sync)
        # This allows other devices to immediately hide the rejected suggestion
        await manager.broadcast_to_user_except_device(
            user_id=user_id,
            exclude_device=device_fingerprint_hash,
            message={
                "type": "settings_memory_suggestion_rejected",
                "payload": {
                    "chat_id": chat_id,
                    "rejection_hash": rejection_hash
                }
            }
        )

        # Send confirmation to the originating device
        await manager.send_personal_message(
            {
                "type": "settings_memory_suggestion_rejected_confirmed",
                "payload": {
                    "chat_id": chat_id,
                    "rejection_hash": rejection_hash,
                    "status": "queued_for_storage"
                }
            },
            user_id,
            device_fingerprint_hash
        )

        logger.info(f"Confirmed rejection hash storage for chat {chat_id}")

    except Exception as e:
        logger.error(f"Error handling suggestion rejection from {user_id}: {e}", exc_info=True)
        raise RuntimeError(f"Failed to process suggestion rejection: {e}")
