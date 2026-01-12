"""
Handler for system message events (chat_system_message_added).

System messages are used for internal chat events like:
- App settings/memories response (included/rejected)
- Focus mode activation/deactivation
- Other chat events that need to be persisted and synced across devices

These messages:
- Are stored in Directus alongside regular messages
- Are synced to other devices via WebSocket broadcast
- Have role='system' to distinguish them from user/assistant messages
- Contain JSON content with a 'type' field identifying the event
"""

import logging
import hashlib
from typing import Dict, Any

from fastapi import WebSocket

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.routes.connection_manager import ConnectionManager
from backend.core.api.app.tasks.celery_config import app as celery_app_instance

logger = logging.getLogger(__name__)


async def handle_chat_system_message_added(
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    encryption_service: EncryptionService,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any]
):
    """
    Handles system messages sent from the client.
    
    System messages are used for internal events like:
    - App settings/memories response (included/rejected)
    - Focus mode changes
    
    These are persisted in Directus and synced across devices.
    
    Expected payload:
    {
        "chat_id": "...",
        "message": {
            "message_id": "...",
            "role": "system",
            "content": "{\"type\": \"app_settings_memories_response\", ...}",
            "created_at": 1234567890
        }
    }
    """
    try:
        chat_id = payload.get("chat_id")
        message_payload = payload.get("message")
        
        if not chat_id or not message_payload or not isinstance(message_payload, dict):
            logger.error(f"Invalid system message payload from {user_id}/{device_fingerprint_hash}: {payload}")
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Invalid system message payload structure"}},
                user_id,
                device_fingerprint_hash
            )
            return
        
        message_id = message_payload.get("message_id")
        role = message_payload.get("role")
        content = message_payload.get("content")
        created_at = message_payload.get("created_at")
        
        # Validate required fields
        if not message_id or not content:
            logger.error(f"Missing required fields in system message from {user_id}: message_id={message_id}, has_content={bool(content)}")
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Missing message_id or content"}},
                user_id,
                device_fingerprint_hash
            )
            return
        
        # Validate role is 'system'
        if role != "system":
            logger.error(f"Invalid role for system message from {user_id}: {role}")
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "System messages must have role='system'"}},
                user_id,
                device_fingerprint_hash
            )
            return
        
        logger.info(f"[SystemMessage] Processing system message {message_id} for chat {chat_id} from {user_id}")
        
        # Verify chat ownership
        # Note: get_chat_metadata only takes chat_id - it always fetches the same metadata fields
        chat_metadata = await directus_service.get_chat_metadata(chat_id)
        if not chat_metadata:
            logger.error(f"[SystemMessage] Chat {chat_id} not found in Directus")
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Chat not found", "chat_id": chat_id}},
                user_id,
                device_fingerprint_hash
            )
            return
        
        # Verify chat owner using hashed_user_id
        hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
        if chat_metadata.get("hashed_user_id") != hashed_user_id:
            logger.warning(f"[SystemMessage] User {user_id} attempted to add message to chat {chat_id} owned by another user")
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Not authorized to modify this chat", "chat_id": chat_id}},
                user_id,
                device_fingerprint_hash
            )
            return
        
        # Encrypt message content with vault key for storage
        encrypted_content = encryption_service.encrypt(content)
        hashed_chat_id = hashlib.sha256(chat_id.encode()).hexdigest()
        hashed_message_id = hashlib.sha256(message_id.encode()).hexdigest()
        
        # Increment messages_v in cache
        new_messages_v = await cache_service.increment_chat_component_version(user_id, chat_id, "messages_v")
        if new_messages_v is None:
            logger.warning(f"[SystemMessage] Failed to increment messages_v for chat {chat_id}")
            new_messages_v = 0
        
        # Persist to Directus via Celery task
        message_data_for_directus = {
            "message_id": message_id,
            "hashed_message_id": hashed_message_id,
            "hashed_chat_id": hashed_chat_id,
            "hashed_user_id": hashed_user_id,
            "role": "system",
            "encrypted_content": encrypted_content,
            "created_at": created_at
        }
        
        celery_app_instance.send_task(
            'app.tasks.persistence_tasks.persist_message',
            kwargs={
                "message_data": message_data_for_directus,
                "messages_v": new_messages_v
            },
            queue='persistence'
        )
        logger.info(f"[SystemMessage] Dispatched Celery task to persist system message {message_id}")
        
        # Send confirmation to sender
        await manager.send_personal_message(
            {
                "type": "system_message_confirmed",
                "payload": {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "messages_v": new_messages_v
                }
            },
            user_id,
            device_fingerprint_hash
        )
        
        # Broadcast to other devices for sync
        broadcast_payload = {
            "event": "new_system_message",
            "chat_id": chat_id,
            "data": {
                "message_id": message_id,
                "role": "system",
                "content": content,  # Send plaintext for other devices to display
                "created_at": created_at
            },
            "versions": {"messages_v": new_messages_v}
        }
        await manager.broadcast_to_user(
            message=broadcast_payload,
            user_id=user_id,
            exclude_device=device_fingerprint_hash  # Don't send back to sender
        )
        logger.info(f"[SystemMessage] Broadcasted system message {message_id} to other devices")
        
    except Exception as e:
        logger.error(f"[SystemMessage] Error handling system message: {e}", exc_info=True)
        await manager.send_personal_message(
            {"type": "error", "payload": {"message": "Failed to process system message"}},
            user_id,
            device_fingerprint_hash
        )
