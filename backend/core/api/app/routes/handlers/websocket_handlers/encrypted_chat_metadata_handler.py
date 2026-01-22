# backend/core/api/app/routes/handlers/websocket_handlers/encrypted_chat_metadata_handler.py
import logging
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
        
        logger.info(f"📥 RECEIVED encrypted_chat_metadata for chat {chat_id}: message_id={message_id}, has_content={bool(encrypted_content)}")
        
        # NOTE: encrypted_model_name is NOT accepted for user messages - it should only be stored on assistant messages
        # The model_name indicates which AI model generated the assistant's response, not which model will respond
        # Get encrypted chat fields from preprocessing
        encrypted_title = payload.get("encrypted_title")
        encrypted_icon = payload.get("encrypted_icon")
        encrypted_chat_category = payload.get("encrypted_chat_category")  # Chat metadata category
        encrypted_chat_tags = payload.get("encrypted_chat_tags")
        encrypted_chat_key = payload.get("encrypted_chat_key")
        # Explicit opt-in for key rotation (e.g., hidden chat hide/unhide flows).
        # This prevents accidental chat key overwrites from misconfigured devices.
        allow_chat_key_rotation = payload.get("allow_chat_key_rotation", False)
        chat_key_rotation_reason = payload.get("chat_key_rotation_reason")
        created_at = payload.get("created_at")
        versions = payload.get("versions", {})

        # Log encrypted_chat_key status for debugging
        if encrypted_chat_key:
            logger.info(
                f"✅ Received encrypted_chat_key for chat {chat_id}: {encrypted_chat_key[:20]}... "
                f"(length: {len(encrypted_chat_key)}), allow_rotation={allow_chat_key_rotation}, "
                f"reason={chat_key_rotation_reason}"
            )
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

        # Verify chat ownership
        is_owner = await directus_service.chat.check_chat_ownership(chat_id, user_id)
        
        if not is_owner:
            # For new chats (which don't have metadata yet), check if it exists in DB
            existing_chat = await directus_service.chat.get_chat_metadata(chat_id)
            if existing_chat:
                # Chat exists but belongs to someone else
                logger.warning(f"User {user_id} attempted to update metadata for chat {chat_id} they don't own. Rejecting.")
                await manager.send_personal_message(
                    {"type": "error", "payload": {"message": "You do not have permission to modify this chat.", "chat_id": chat_id}},
                    user_id,
                    device_fingerprint_hash
                )
                return
            else:
                # Chat doesn't exist - this is a new chat creation
                logger.info(f"New chat {chat_id} detected in encrypted_chat_metadata_handler")

        # ---------------------------------------------------------------------
        # Chat key conflict detection (server-side guardrail)
        # ---------------------------------------------------------------------

        # Validate that we have encrypted content (zero-knowledge enforcement)
        if payload.get("content"):  # Plaintext content should not be present
            logger.warning("Removing plaintext content from encrypted metadata to enforce zero-knowledge architecture")
            payload = {k: v for k, v in payload.items() if k != "content"}

        # Determine if this is an existing chat by checking Directus messages_v
        # This is more reliable than client-provided chat_has_title, especially after server restarts
        # NOTE: is_existing_chat must be defined before duplication check
        is_existing_chat = False
        chat_metadata_from_db = await directus_service.chat.get_chat_metadata(chat_id)
        if chat_metadata_from_db:
            messages_v_from_db = chat_metadata_from_db.get("messages_v", 0)
            is_existing_chat = messages_v_from_db > 1  # > 1 means there are previous messages
            logger.debug(f"Chat {chat_id} messages_v from DB: {messages_v_from_db}, is_existing_chat: {is_existing_chat}")
        else:
            # Fallback to client-provided flag if DB check failed
            chat_has_title_from_client = payload.get("chat_has_title", False)
            is_existing_chat = chat_has_title_from_client
            logger.debug(f"Chat {chat_id} not found in DB, using client flag chat_has_title: {chat_has_title_from_client}")

        # ---------------------------------------------------------------------
        # History Injection Flow (e.g. Duplication from Demo)
        # ---------------------------------------------------------------------
        # If the payload includes a message_history with encrypted content,
        # we persist those messages. This allows cloning history into a new chat.
        # Detection: if it's a new chat (is_owner is false) and history is provided.
        history_messages = payload.get("message_history")
        if not is_owner and history_messages and isinstance(history_messages, list):
            logger.info(f"📜 History Injection: Persisting {len(history_messages)} messages for new chat {chat_id}")
            for hist_msg in history_messages:
                hist_msg_id = hist_msg.get("message_id")
                hist_encrypted_content = hist_msg.get("encrypted_content")
                
                # Only persist if it actually has encrypted content (not just cleartext for AI)
                if hist_msg_id and hist_encrypted_content:
                    celery_app.send_task(
                        "app.tasks.persistence_tasks.persist_new_chat_message",
                        args=[
                            hist_msg_id, 
                            chat_id, 
                            user_id_hash, 
                            hist_msg.get("role", "user"),
                            hist_msg.get("encrypted_sender_name"),
                            hist_msg.get("encrypted_category"),
                            hist_msg.get("encrypted_model_name"),
                            hist_encrypted_content,
                            hist_msg.get("created_at"),
                            None, None, # messages_v, last_edited_overall_timestamp
                            hist_msg.get("task_id"),
                            encrypted_chat_key,
                            user_id
                        ]
                    )

        # ---------------------------------------------------------------------
        # Chat key conflict detection (server-side guardrail)
        # ---------------------------------------------------------------------

        # ---------------------------------------------------------------------
        # Chat key conflict detection (server-side guardrail)
        # ---------------------------------------------------------------------

        # ---------------------------------------------------------------------
        # Chat key conflict detection (server-side guardrail)
        # ---------------------------------------------------------------------
        # If the chat already has an encrypted_chat_key, we must NOT broadcast a
        # different key unless rotation is explicitly requested. This prevents
        # a single device from corrupting the chat key across other devices.
        existing_chat_key = None
        if encrypted_chat_key and not allow_chat_key_rotation:
            try:
                cached_chat = await cache_service.get_chat_list_item_data(user_id, chat_id)
                if cached_chat and getattr(cached_chat, "encrypted_chat_key", None):
                    existing_chat_key = cached_chat.encrypted_chat_key
            except Exception as cache_error:
                logger.warning(
                    f"Failed to read cached chat key for chat {chat_id} (will fall back to Directus): {cache_error}",
                    exc_info=True
                )

            if not existing_chat_key:
                try:
                    chat_metadata = await directus_service.chat.get_chat_metadata(chat_id)
                    if chat_metadata:
                        existing_chat_key = chat_metadata.get("encrypted_chat_key")
                except Exception as directus_error:
                    logger.warning(
                        f"Failed to read Directus chat key for chat {chat_id}: {directus_error}",
                        exc_info=True
                    )

            if existing_chat_key and existing_chat_key != encrypted_chat_key:
                logger.warning(
                    f"[CHAT_KEY_GUARD] ⚠️ Incoming encrypted_chat_key for chat {chat_id} does not match existing key. "
                    f"Blocking key broadcast to protect other devices. "
                    f"(allow_chat_key_rotation=False)"
                )
                # Drop the incoming key from further processing to avoid broadcast corruption.
                encrypted_chat_key = None

        # Store encrypted user message if provided
        # CRITICAL: Check if we have both message_id and encrypted_content
        if message_id:
            if encrypted_content:
                # DIAGNOSTIC: Log encrypted content details for debugging sync/encryption issues
                # This helps identify if the client is sending correctly encrypted content
                import base64
                is_valid_base64 = False
                try:
                    # Check if it's valid base64
                    decoded = base64.b64decode(encrypted_content)
                    is_valid_base64 = True
                    # Client-encrypted content should have: 12-byte IV + ciphertext + 16-byte auth tag
                    # Minimum length: 12 + 1 + 16 = 29 bytes (for 1-char plaintext)
                    # Base64 of 29 bytes = ~40 chars minimum
                    decoded_len = len(decoded)
                    if decoded_len < 29:
                        logger.warning(
                            f"⚠️ [ENCRYPTION_VALIDATION] Message {message_id} encrypted_content is suspiciously short: "
                            f"decoded_len={decoded_len} bytes (expected >= 29 bytes for AES-GCM). "
                            f"This may indicate malformed encryption or wrong encryption method!"
                        )
                except Exception as decode_err:
                    logger.error(
                        f"❌ [ENCRYPTION_VALIDATION] Message {message_id} encrypted_content is NOT valid base64: {decode_err}. "
                        f"Content preview: {encrypted_content[:50]}..."
                    )
                
                logger.info(
                    f"Storing encrypted user message {message_id} for chat {chat_id}. "
                    f"encrypted_content_length={len(encrypted_content)}, is_valid_base64={is_valid_base64}, "
                    f"content_preview={encrypted_content[:30]}..."
                )
            else:
                logger.warning(f"⚠️ Message ID {message_id} provided but encrypted_content is missing/null for chat {chat_id}! "
                             f"This means the user message will NOT be stored in Directus. Payload keys: {list(payload.keys())}")
        elif encrypted_content:
            logger.warning(f"⚠️ Encrypted content provided but message_id is missing for chat {chat_id}! Cannot store message without ID.")
        
        # ---------------------------------------------------------------------
        # Chat key conflict detection (server-side guardrail)
        # ---------------------------------------------------------------------

        if message_id and encrypted_content:
            
            # Store encrypted user message in Directus
            # CRITICAL: Pass user_id (not hashed) for sync cache updates
            # Sync cache is updated FIRST (before Directus persistence) - cache has priority!
            # DEBUG: Log task queuing attempt
            logger.info(f"📤 ATTEMPTING to queue persist_new_chat_message task for message {message_id}, chat {chat_id}")
            task_result = celery_app.send_task(
                name='app.tasks.persistence_tasks.persist_new_chat_message',
                args=[
                    message_id,
                    chat_id,
                    user_id_hash,
                    'user',  # role
                    encrypted_sender_name,
                    encrypted_category,
                    None,    # encrypted_model_name (always None for user messages)
                    encrypted_content,
                    created_at or int(datetime.now(timezone.utc).timestamp()),
                    versions.get("messages_v"),
                    versions.get("last_edited_overall_timestamp", int(datetime.now(timezone.utc).timestamp())),
                    encrypted_chat_key,
                    user_id
                ],
                queue='persistence'
            )
            logger.info(f"✅ QUEUED persist_new_chat_message task for message {message_id}, task_id: {task_result.id}")

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
            # Pass rotation intent to persistence task (these flags are stripped before Directus update).
            if allow_chat_key_rotation:
                chat_update_fields["allow_chat_key_rotation"] = True
            if chat_key_rotation_reason:
                chat_update_fields["chat_key_rotation_reason"] = chat_key_rotation_reason
        
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
            # CRITICAL: Pass user_id (not hashed) for cache updates
            celery_app.send_task(
                "app.tasks.persistence_tasks.persist_encrypted_chat_metadata",
                args=[chat_id, chat_update_fields, user_id_hash, user_id],  # Added user_id for cache updates
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
        # This ensures that when a chat is hidden/unhidden, or when metadata (title, category, icon) is set
        # on one device, other devices receive the update and keep their local state consistent.
        # Broadcast if ANY metadata was updated
        if chat_update_fields:
            broadcast_payload = {
                "type": "encrypted_chat_metadata",
                "payload": {
                    "chat_id": chat_id,
                    "versions": versions if versions else {}
                }
            }
            # Add all updated fields to broadcast
            if encrypted_chat_key:
                broadcast_payload["payload"]["encrypted_chat_key"] = encrypted_chat_key
            if encrypted_title:
                broadcast_payload["payload"]["encrypted_title"] = encrypted_title
            if encrypted_icon:
                broadcast_payload["payload"]["encrypted_icon"] = encrypted_icon
            if encrypted_chat_category:
                broadcast_payload["payload"]["encrypted_category"] = encrypted_chat_category
            
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
