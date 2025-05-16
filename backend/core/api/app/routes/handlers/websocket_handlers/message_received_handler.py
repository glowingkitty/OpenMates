# backend/core/api/app/routes/handlers/websocket_handlers/message_received_handler.py
import logging
import json
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone

from fastapi import WebSocket

from app.services.cache import CacheService
from app.services.directus.directus import DirectusService # Keep if directus_service is used by Celery tasks or future direct calls
from app.utils.encryption import EncryptionService
from app.routes.connection_manager import ConnectionManager
from app.schemas.chat import MessageInCache # For typing if needed, or direct dict usage
from app.tasks.celery_config import app # Renamed for clarity

logger = logging.getLogger(__name__)

async def handle_message_received( # Renamed from handle_new_message, logic moved here
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService, # Passed but might only be used by Celery task
    encryption_service: EncryptionService,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any] # Expected: {"chat_id": "...", "message": {"message_id": ..., "sender": ..., "content": ..., "timestamp": ...}}
):
    """
    Handles a new message sent from the client (now via "chat_message_added" type).
    1. Validates payload.
    2. Saves the message to cache.
    3. Encrypts content for persistence.
    4. Sends a task to Celery to persist to Directus.
    5. Sends confirmation to the originating client device.
    6. Broadcasts the new message to other connected devices of the same user.
    """
    try:
        chat_id = payload.get("chat_id")
        # The client sends the message details within a "message" sub-dictionary in the payload
        message_payload_from_client = payload.get("message")

        if not chat_id or not message_payload_from_client or not isinstance(message_payload_from_client, dict):
            logger.error(f"Invalid message payload structure from {user_id}/{device_fingerprint_hash}: {payload}")
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Invalid message payload structure"}},
                user_id,
                device_fingerprint_hash
            )
            return

        message_id = message_payload_from_client.get("message_id")
        sender_name = message_payload_from_client.get("sender") # This should ideally be derived from user_id or a profile
        content_plain = message_payload_from_client.get("content") # This is the Tiptap JSON or plain text
        timestamp = message_payload_from_client.get("timestamp") # Unix timestamp (int/float) or ISO format string

        if not message_id or sender_name is None or content_plain is None or not timestamp:
            logger.error(f"Missing fields in message data from {user_id}/{device_fingerprint_hash}: {message_payload_from_client}")
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Missing required fields in message data"}},
                user_id,
                device_fingerprint_hash
            )
            return

        # Prepare message for cache (content remains plain for cache)
        message_for_cache = MessageInCache(
            id=message_id,
            chat_id=chat_id,
            sender_name=sender_name,
            content=content_plain, # Store plain content in cache for quick display if needed by client
            created_at=timestamp,
            status="sending"
        )
        
        # Save to cache first
        # This also updates chat versions (messages_v, last_edited_overall_timestamp)
        # and returns the new versions.
        version_update_result = await cache_service.save_chat_message_and_update_versions(
            user_id=user_id,
            chat_id=chat_id,
            message_data=message_for_cache
        )

        if not version_update_result:
            logger.error(f"Failed to save message {message_id} to cache or update versions for chat {chat_id}. User: {user_id}")
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Failed to process message due to cache error.", "chat_id": chat_id, "message_id": message_id}},
                user_id, device_fingerprint_hash
            )
            return
            
        new_messages_v = version_update_result["messages_v"]
        new_last_edited_overall_timestamp = version_update_result["last_edited_overall_timestamp"]
        
        logger.info(f"Saved message {message_id} to cache for chat {chat_id} by user {user_id}. New messages_v: {new_messages_v}")

        # Encrypt content for persistence task
        content_to_encrypt_str: str
        if isinstance(content_plain, dict):
            content_to_encrypt_str = json.dumps(content_plain)
        elif isinstance(content_plain, str):
            content_to_encrypt_str = content_plain
        else:
            logger.warning(f"Message content for chat {chat_id}, msg {message_id} is unexpected type {type(content_plain)}. Converting to string.")
            content_to_encrypt_str = str(content_plain)

        encrypted_content_data: Optional[Tuple[str, str]] = None
        encrypted_content_for_db: Optional[str] = None
        try:
            encrypted_content_data = await encryption_service.encrypt_with_chat_key(
                content_to_encrypt_str,
                chat_id # Use chat_id as key_id for chat messages
            )
            if not encrypted_content_data or not encrypted_content_data[0]:
                raise ValueError("Encryption returned None or empty ciphertext.")
            encrypted_content_for_db = encrypted_content_data[0]
        except Exception as e_enc:
            logger.error(f"Failed to encrypt message content for chat {chat_id}, msg {message_id}: {e_enc}", exc_info=True)
            # Inform sender of encryption failure. Message is in cache but won't persist.
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Failed to secure message for storage.", "chat_id": chat_id, "message_id": message_id}},
                user_id, device_fingerprint_hash
            )
            # Decide if we should proceed without encrypted_content_for_db or stop. For now, stop.
            return
        
        # Send to Celery for async persistence
        client_timestamp_unix: int
        try:
            if isinstance(timestamp, (int, float)):
                client_timestamp_unix = int(timestamp)
            elif isinstance(timestamp, str):
                if timestamp.endswith("Z"):
                    dt_object = datetime.fromisoformat(timestamp[:-1] + "+00:00")
                else:
                    dt_object = datetime.fromisoformat(timestamp)
                client_timestamp_unix = int(dt_object.timestamp())
            else:  # Covers None or other unexpected types
                if timestamp is None:
                    log_msg = "Missing timestamp from client."
                else:
                    log_msg = f"Invalid timestamp type from client (type: {type(timestamp)}, value: {timestamp})."
                logger.warning(f"{log_msg} Using current server time for task's 'timestamp' arg.")
                client_timestamp_unix = int(datetime.now(timezone.utc).timestamp())
        except ValueError as e_ts:  # Catches parsing errors for string timestamps
            logger.error(f"Error parsing client string timestamp '{timestamp}': {e_ts}. Using current server time for task's 'timestamp' arg.")
            client_timestamp_unix = int(datetime.now(timezone.utc).timestamp())

        app.send_task(
            name='app.tasks.persistence_tasks.persist_new_chat_message',
            kwargs={
                'message_id': message_id,
                'chat_id': chat_id,
                'hashed_user_id': user_id,
                'sender': sender_name,
                'content': encrypted_content_for_db,
                'timestamp': client_timestamp_unix,
            },
            queue='persistence'
        )
        logger.info(f"Dispatched Celery task 'persist_new_chat_message' for message {message_id} in chat {chat_id} by user {user_id}")

        # Send confirmation to the originating client device
        confirmation_payload = {
            "type": "chat_message_confirmed", # Client expects this for their sent message
            "payload": {
                "chat_id": chat_id,
                "message_id": message_id,
                "temp_id": message_payload_from_client.get("temp_id"), # Echo back temp_id if client sent one
                "new_messages_v": new_messages_v,
                "new_last_edited_overall_timestamp": new_last_edited_overall_timestamp
            }
        }
        await manager.send_personal_message(
            confirmation_payload,
            user_id,
            device_fingerprint_hash # Only to the sender's device
        )
        logger.info(f"Sent chat_message_confirmed for {message_id} to {user_id}/{device_fingerprint_hash}")

        # Broadcast the new message to other connected devices of the same user
        broadcast_payload_content = {
            "type": "new_chat_message", # A distinct type for other clients receiving a new message
            "payload": {
                "chat_id": chat_id,
                "message_id": message_id,
                "sender_name": sender_name,
                "content": content_plain, # Send plain content to other clients
                "created_at": timestamp,
                "messages_v": new_messages_v,
                "last_edited_overall_timestamp": new_last_edited_overall_timestamp
                # Add any other fields clients expect for a new message display
            }
        }
        await manager.broadcast_to_user(
            message=broadcast_payload_content,
            user_id=user_id,
            exclude_device_hash=device_fingerprint_hash # Exclude the sender's device
        )
        logger.info(f"Broadcasted new_chat_message for {message_id} to other devices of user {user_id}")

    except Exception as e:
        logger.error(f"Error in handle_message_received (new message) from {user_id}/{device_fingerprint_hash}: {e}", exc_info=True)
        try:
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Error processing your message on the server."}},
                user_id,
                device_fingerprint_hash
            )
        except Exception as e_send:
            logger.error(f"Failed to send error to {user_id}/{device_fingerprint_hash} after main error: {e_send}")