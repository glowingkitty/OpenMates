import logging
import json
from typing import Dict, Any

from fastapi import WebSocket

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService # Corrected import path if needed
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.routes.connection_manager import ConnectionManager
from backend.core.api.app.tasks.celery_config import app as celery_app_instance

logger = logging.getLogger(__name__)

async def handle_update_title(
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    encryption_service: EncryptionService,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any]
):
    chat_id = payload.get("chat_id")
    encrypted_title_from_client = payload.get("encrypted_title")  # Frontend sends encrypted title

    if not chat_id or encrypted_title_from_client is None:
        logger.warning(f"Received update_title with missing chat_id or encrypted_title from {user_id}/{device_fingerprint_hash}")
        await manager.send_personal_message(
            message={"type": "error", "payload": {"message": "Missing chat_id or encrypted_title for update_title", "chat_id": chat_id}},
            user_id=user_id, device_fingerprint_hash=device_fingerprint_hash
        )
        return

    logger.info(f"Processing update_title for chat {chat_id} (encrypted content) from {user_id}/{device_fingerprint_hash}")

    # Basic validation - check encrypted content length (rough estimate for cleartext limits)
    if len(encrypted_title_from_client) > 1000:  # Encrypted content will be longer than cleartext
        logger.warning(f"Encrypted title for chat {chat_id} is too long ({len(encrypted_title_from_client)} chars). User: {user_id}")
        await manager.send_personal_message(
            message={"type": "error", "payload": {"message": "New title is too long.", "chat_id": chat_id}},
            user_id=user_id, device_fingerprint_hash=device_fingerprint_hash
        )
        return
    
    try:
        # Store the encrypted title from client directly (already encrypted with master key)
        encrypted_new_title = encrypted_title_from_client

        # Increment title_v in cache
        new_cache_title_v = await cache_service.increment_chat_component_version(user_id, chat_id, "title_v")
        
    except Exception as e:
        logger.error(f"Error processing title update for chat {chat_id}: {str(e)}. User: {user_id}")
        await manager.send_personal_message(
            message={"type": "error", "payload": {"message": "Failed to process title update.", "chat_id": chat_id}},
            user_id=user_id, device_fingerprint_hash=device_fingerprint_hash
        )
        return
    
    if new_cache_title_v is None:
        logger.error(f"Failed to increment title_v in cache for chat {chat_id}. User: {user_id}")
        current_versions = await cache_service.get_chat_versions(user_id, chat_id)
        new_cache_title_v = current_versions.title_v if current_versions else 0
        await manager.send_personal_message(
            message={"type": "error", "payload": {"message": "Failed to update title version in cache.", "chat_id": chat_id}},
            user_id=user_id, device_fingerprint_hash=device_fingerprint_hash
        )
        return


    # Update encrypted title in user:{user_id}:chat:{chat_id}:list_item_data
    update_field_success = await cache_service.update_chat_list_item_field(user_id, chat_id, "title", encrypted_new_title)
    if not update_field_success:
        logger.error(f"Failed to update title in list_item_data for chat {chat_id}. User: {user_id}")
        # The version was incremented, but data update failed. This is a partial failure.
        # Client will eventually sync, but this is not ideal.
        # For now, continue with broadcast and DB persistence.

    # Dispatch Celery task to persist to Directus
    celery_app_instance.send_task(
        'app.tasks.persistence_tasks.persist_chat_title', 
        kwargs={
            "chat_id": chat_id,
            "encrypted_title": encrypted_new_title,
            "title_v": new_cache_title_v
        },
        queue='persistence'
    )
    logger.info(f"Dispatched Celery task to persist title for chat {chat_id}, version {new_cache_title_v}")

    # Broadcast to all connected devices for this user
    broadcast_payload = {
        "event": "chat_title_updated", 
        "chat_id": chat_id,
        "data": {"encrypted_title": encrypted_new_title},  # Send encrypted title for other devices to decrypt
        "versions": {"title_v": new_cache_title_v}
    }
    await manager.broadcast_to_user(
        message_content=broadcast_payload, 
        user_id=user_id,
        exclude_device_hash=None 
    )
    logger.info(f"Broadcasted chat_title_updated for chat {chat_id} to user {user_id}")