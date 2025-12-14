# backend/core/api/app/routes/handlers/websocket_handlers/encrypted_chat_metadata_handler.py
import logging
import hashlib
from typing import Dict, Any
from datetime import datetime, timezone

from fastapi import WebSocket

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.routes.connection_manager import ConnectionManager
from backend.core.api.app.tasks.celery_config import app as celery_app

logger = logging.getLogger(__name__)


async def handle_encrypted_chat_metadata(
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    encryption_service: EncryptionService,
    user_id: str,
    user_id_hash: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any]
):
    """
    Handles encrypted chat metadata and user message storage.
    This is the SEPARATE handler for encrypted data storage after preprocessing completes.
    
    Expected payload structure:
    {
        "chat_id": "...",
        "message_id": "...",  // User message to store
        "encrypted_content": "...",  // Encrypted user message content
        "encrypted_sender_name": "...",
        "encrypted_category": "...",
        // Chat metadata fields from preprocessing:
        "encrypted_title": "...",
        "encrypted_chat_tags": "...",
        "encrypted_chat_key": "...",
        "created_at": 1234567890,
        "versions": {
            "messages_v": 123,
            "last_edited_overall_timestamp": 1234567890
        }
    }
    """
    try:
        chat_id = payload.get("chat_id")
        message_id = payload.get("message_id")
        encrypted_content = payload.get("encrypted_content")
        encrypted_sender_name = payload.get("encrypted_sender_name")
        encrypted_category = payload.get("encrypted_category")
        # Get encrypted chat fields from preprocessing
        encrypted_title = payload.get("encrypted_title")
        encrypted_icon = payload.get("encrypted_icon")
        encrypted_chat_category = payload.get("encrypted_chat_category")  # Chat metadata category
        encrypted_chat_tags = payload.get("encrypted_chat_tags")
        encrypted_chat_key = payload.get("encrypted_chat_key")
        created_at = payload.get("created_at")
        versions = payload.get("versions", {})

        # Log encrypted_chat_key status for debugging
        if encrypted_chat_key:
            logger.info(f"✅ Received encrypted_chat_key for chat {chat_id}: {encrypted_chat_key[:20]}... (length: {len(encrypted_chat_key)})")
        else:
            logger.warning(f"⚠️ No encrypted_chat_key in payload for chat {chat_id} - this will prevent decryption on other devices!")

        if not chat_id:
            logger.error(f"Missing chat_id in encrypted metadata from {user_id}/{device_fingerprint_hash}")
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Missing chat_id in encrypted metadata"}},
                user_id,
                device_fingerprint_hash
            )
            return

        logger.info(f"Processing encrypted metadata for chat {chat_id} from {user_id}")
        
        # DEBUG: Log what we received in the payload
        logger.debug(f"Payload received for chat {chat_id}: message_id={message_id}, has_encrypted_content={bool(encrypted_content)}, "
                    f"has_encrypted_title={bool(encrypted_title)}, has_encrypted_icon={bool(encrypted_icon)}, "
                    f"has_encrypted_chat_category={bool(encrypted_chat_category)}, has_encrypted_chat_key={bool(encrypted_chat_key)}")

        # Validate that we have encrypted content (zero-knowledge enforcement)
        if payload.get("content"):  # Plaintext content should not be present
            logger.warning(f"Removing plaintext content from encrypted metadata to enforce zero-knowledge architecture")
            payload = {k: v for k, v in payload.items() if k != "content"}

        # Store encrypted user message if provided
        # CRITICAL: Check if we have both message_id and encrypted_content
        if message_id:
            if encrypted_content:
                logger.info(f"Storing encrypted user message {message_id} for chat {chat_id}")
            else:
                logger.warning(f"⚠️ Message ID {message_id} provided but encrypted_content is missing/null for chat {chat_id}! "
                             f"This means the user message will NOT be stored in Directus. Payload keys: {list(payload.keys())}")
        elif encrypted_content:
            logger.warning(f"⚠️ Encrypted content provided but message_id is missing for chat {chat_id}! Cannot store message without ID.")
        
        if message_id and encrypted_content:
            
            # Store encrypted user message in Directus
            # CRITICAL: Pass user_id (not hashed) for sync cache updates
            # Sync cache is updated FIRST (before Directus persistence) - cache has priority!
            celery_app.send_task(
                name='app.tasks.persistence_tasks.persist_new_chat_message',
                kwargs={
                    'message_id': message_id,
                    'chat_id': chat_id,
                    'hashed_user_id': user_id_hash,
                    'role': 'user',  # This handler only stores user messages
                    'encrypted_sender_name': encrypted_sender_name,
                    'encrypted_category': encrypted_category,
                    'encrypted_content': encrypted_content,
                    'created_at': created_at or int(datetime.now(timezone.utc).timestamp()),
                    'new_chat_messages_version': versions.get("messages_v"),  # Frontend sends messages_v, server uses messages_v
                    'new_last_edited_overall_timestamp': versions.get("last_edited_overall_timestamp", int(datetime.now(timezone.utc).timestamp())),
                    'encrypted_chat_key': encrypted_chat_key,
                    'user_id': user_id,  # Pass user_id for sync cache updates (cache has priority!)
                },
                queue='persistence'
            )
            logger.debug(f"Queued encrypted user message storage task for message {message_id}")

        # Store encrypted chat metadata from preprocessing
        chat_update_fields = {}
        if encrypted_title:
            chat_update_fields["encrypted_title"] = encrypted_title
            # Use the incremented title_v from frontend (frontend already incremented it)
            chat_update_fields["title_v"] = versions.get("title_v")  # Frontend sends incremented value
        if encrypted_icon:
            chat_update_fields["encrypted_icon"] = encrypted_icon
        if encrypted_chat_category:
            chat_update_fields["encrypted_category"] = encrypted_chat_category
        if encrypted_chat_tags:
            chat_update_fields["encrypted_chat_tags"] = encrypted_chat_tags
        if encrypted_chat_key:
            chat_update_fields["encrypted_chat_key"] = encrypted_chat_key
        
        if chat_update_fields:
            logger.info(f"Storing encrypted chat metadata for chat {chat_id}: {list(chat_update_fields.keys())}")
            
            now_ts = int(datetime.now(timezone.utc).timestamp())
            chat_update_fields["updated_at"] = now_ts
            
            # Add version info for chat creation/update
            # The metadata task will use these when creating the chat
            # Use sensible defaults if not provided (current timestamp, messages_v=1 since we just got a message)
            chat_update_fields["messages_v"] = versions.get("messages_v", 1)  # At least 1 message exists
            chat_update_fields["last_edited_overall_timestamp"] = versions.get("last_edited_overall_timestamp", created_at or now_ts)
            chat_update_fields["last_message_timestamp"] = versions.get("last_edited_overall_timestamp", created_at or now_ts)
            
            # Send task to update/create chat metadata
            # Pass hashed_user_id so the task can create the chat if it doesn't exist
            celery_app.send_task(
                "app.tasks.persistence_tasks.persist_encrypted_chat_metadata",
                args=[chat_id, chat_update_fields, user_id_hash],
                queue="persistence"
            )
            logger.info(f"Queued encrypted chat metadata update task for chat {chat_id}")

        # Send message confirmation to client after successful storage
        if message_id:
            try:
                # Send message confirmation to client
                await manager.send_personal_message(
                    {
                        "type": "chat_message_confirmed",
                        "payload": {
                            "chat_id": chat_id,
                            "message_id": message_id,
                            "status": "synced"
                        }
                    },
                    user_id,
                    device_fingerprint_hash
                )
                logger.info(f"Sent message confirmation for {message_id} to client")
                
            except Exception as e:
                logger.error(f"Error sending message confirmation for {message_id}: {e}", exc_info=True)

        # Send confirmation to client
        await manager.send_personal_message(
            {
                "type": "encrypted_metadata_stored",
                "payload": {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "status": "queued_for_storage"
                }
            },
            user_id,
            device_fingerprint_hash
        )

        logger.info(f"Confirmed encrypted metadata storage for chat {chat_id}")
        
        # CRITICAL: Broadcast encrypted_chat_metadata update to other devices
        # This ensures that when a chat is hidden/unhidden on one device, other devices receive the update
        # and can properly identify the chat as hidden/visible based on the new encrypted_chat_key
        # Broadcast if encrypted_chat_key was provided (even if it's the only field being updated)
        if encrypted_chat_key:
            broadcast_payload = {
                "type": "encrypted_chat_metadata",
                "payload": {
                    "chat_id": chat_id,
                    "encrypted_chat_key": encrypted_chat_key,
                    "versions": versions if versions else {}
                }
            }
            try:
                await manager.broadcast_to_user(
                    message=broadcast_payload,
                    user_id=user_id,
                    exclude_device_hash=device_fingerprint_hash  # Exclude the sender's device
                )
                logger.info(f"Broadcasted encrypted_chat_metadata update for chat {chat_id} to other devices of user {user_id}")
            except Exception as broadcast_error:
                logger.error(f"Error broadcasting encrypted_chat_metadata update for chat {chat_id}: {broadcast_error}", exc_info=True)

    except Exception as e:
        logger.error(f"Error handling encrypted chat metadata from {user_id}/{device_fingerprint_hash}: {e}", exc_info=True)
        try:
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Failed to process encrypted chat metadata"}},
                user_id,
                device_fingerprint_hash
            )
        except Exception as send_err:
            logger.error(f"Failed to send error message to {user_id}/{device_fingerprint_hash}: {send_err}")
