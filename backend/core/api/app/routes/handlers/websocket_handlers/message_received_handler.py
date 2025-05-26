# backend/core/api/app/routes/handlers/websocket_handlers/message_received_handler.py
import logging
import json
import hashlib # Import hashlib for hashing user_id
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone

from fastapi import WebSocket

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService # Keep if directus_service is used by Celery tasks or future direct calls
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.routes.connection_manager import ConnectionManager
from backend.core.api.app.schemas.chat import MessageInCache, MessageBase as AIMessageHistoryEntry
from backend.core.api.app.schemas.ai_skill_schemas import AskSkillRequest as AskSkillRequestSchema
from backend.core.api.app.tasks.celery_config import app as celery_app # Renamed for clarity

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

        celery_app.send_task(
            name='app.tasks.persistence_tasks.persist_new_chat_message',
            kwargs={
                'message_id': message_id,
                'chat_id': chat_id,
                'hashed_user_id': hashlib.sha256(user_id.encode()).hexdigest(), # Hash user_id
                'sender': sender_name,
                'content': encrypted_content_for_db,
                'timestamp': client_timestamp_unix,
                'new_chat_messages_version': new_messages_v,
                'new_last_edited_overall_timestamp': new_last_edited_overall_timestamp,
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
        await manager.broadcast_to_user_specific_event(
            user_id=user_id,
            event_name=confirmation_payload["type"],
            payload=confirmation_payload["payload"]
        )
        logger.info(f"Broadcasted chat_message_confirmed event for message {message_id} to user {user_id}")

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

        # --- BEGIN AI SKILL INVOCATION ---
        logger.info(f"Preparing to invoke AI for chat {chat_id} after user message {message_id}")
        
        message_history_for_ai: List[AIMessageHistoryEntry] = []
        try:
            # 1. Fetch message history for the chat
            cached_messages_str_list = await cache_service.get_chat_messages_history(user_id, chat_id) # Fetches all
            
            if cached_messages_str_list:
                logger.info(f"Found {len(cached_messages_str_list)} messages in cache for chat {chat_id} for AI history.")
                for msg_str in reversed(cached_messages_str_list): # Cache stores newest first (LPUSH), reverse for chronological
                    try:
                        msg_cache_data = json.loads(msg_str)
                        # Sender: if current user's message (based on sender_name), use "user". Otherwise, use sender_name (e.g., "Sophia").
                        history_sender = "user" if msg_cache_data.get("sender_name") == sender_name else msg_cache_data.get("sender_name", "assistant")
                        
                        # Ensure timestamp is an int
                        history_timestamp = msg_cache_data.get("created_at")
                        if not isinstance(history_timestamp, int):
                            logger.warning(f"Cached message for chat {chat_id} has non-integer timestamp '{history_timestamp}'. Attempting parse or defaulting.")
                            # Assuming _parse_timestamp_to_unix is robust or MessageInCache ensures int
                            history_timestamp = int(history_timestamp) if isinstance(history_timestamp, (str, float)) else int(datetime.now(timezone.utc).timestamp())


                        message_history_for_ai.append(
                            AIMessageHistoryEntry(
                                sender=history_sender,
                                content=msg_cache_data.get("content"), # Tiptap JSON
                                timestamp=history_timestamp
                            )
                        )
                    except json.JSONDecodeError:
                        logger.warning(f"Could not parse cached message string for chat {chat_id}: {msg_str[:100]}...")
                    except Exception as e_hist_parse:
                        logger.warning(f"Error processing cached message for AI history: {e_hist_parse}")
            else:
                logger.info(f"No messages in cache for chat {chat_id} for AI history. Fetching from Directus.")
                from backend.core.api.app.services.directus import chat_methods as directus_chat_api
                
                db_messages = await directus_chat_api.get_all_messages_for_chat(
                    directus_service, encryption_service, chat_id, decrypt_content=True # Decrypts content to Tiptap JSON
                ) # Fetches all, sorted by created_at
                if db_messages:
                    for msg_db_data in db_messages:
                        history_sender = "user" if msg_db_data.get("sender_name") == sender_name else msg_db_data.get("sender_name", "assistant")
                        
                        history_timestamp = msg_db_data.get("created_at")
                        if not isinstance(history_timestamp, int):
                             history_timestamp = int(history_timestamp) if isinstance(history_timestamp, (str, float)) else int(datetime.now(timezone.utc).timestamp())

                        message_history_for_ai.append(
                            AIMessageHistoryEntry(
                                sender=history_sender,
                                content=msg_db_data.get("content"), # Decrypted Tiptap JSON
                                timestamp=history_timestamp
                            )
                        )
            
            # Ensure the current message (which triggered the AI) is the last one in the history.
            # It should have been added to cache by save_chat_message_and_update_versions.
            # If history was fetched from DB, it might not include the very latest if DB persistence is slower than this call.
            # For robustness, check if the current message is present and add if not, or ensure it's last.
            current_message_found_and_last = False
            if message_history_for_ai:
                last_msg_in_hist = message_history_for_ai[-1]
                if last_msg_in_hist.content == content_plain and last_msg_in_hist.timestamp == client_timestamp_unix and last_msg_in_hist.sender == "user":
                    current_message_found_and_last = True
            
            if not current_message_found_and_last:
                logger.info(f"Current user message {message_id} not found as last in history or history empty. Appending it now.")
                # Remove if it exists elsewhere (e.g. if cache was slightly stale)
                message_history_for_ai = [m for m in message_history_for_ai if not (m.content == content_plain and m.timestamp == client_timestamp_unix and m.sender == "user")]
                message_history_for_ai.append(
                    AIMessageHistoryEntry(
                        sender="user",
                        content=content_plain, # Tiptap JSON
                        timestamp=client_timestamp_unix
                    )
                )

            logger.info(f"Final AI message history for chat {chat_id} has {len(message_history_for_ai)} messages.")

        except Exception as e_hist:
            logger.error(f"Failed to construct message history for AI for chat {chat_id}: {e_hist}", exc_info=True)
            # Proceed with at least the current message if history construction failed
            message_history_for_ai = [
                AIMessageHistoryEntry(sender="user", content=content_plain, timestamp=client_timestamp_unix)
            ]


        # 2. Fetch active_focus_id from chat metadata
        active_focus_id_for_ai: Optional[str] = None
        # mate_id_for_ask_request: Optional[str] = None # Mate ID is determined by preprocessor

        try:
            from backend.core.api.app.services.directus import chat_methods as directus_chat_api
            chat_directus_metadata = await directus_chat_api.get_chat_metadata(directus_service, chat_id)
            if chat_directus_metadata:
                encrypted_focus_id = chat_directus_metadata.get("encrypted_active_focus_id")
                if encrypted_focus_id:
                    try:
                        active_focus_id_for_ai = await encryption_service.decrypt_with_chat_key(
                            key_id=chat_id, # chat_id is the key_id for chat-specific encryption
                            ciphertext=encrypted_focus_id
                        )
                        logger.info(f"Decrypted active_focus_id for chat {chat_id}: {active_focus_id_for_ai}")
                    except Exception as e_dec_focus:
                        logger.error(f"Failed to decrypt active_focus_id for chat {chat_id}: {e_dec_focus}")
                
                # If a chat has a pre-selected mate_id, it could be fetched here.
                # For now, we assume mate_id is primarily determined by the AI preprocessor.
                # mate_id_for_ask_request = chat_directus_metadata.get("selected_mate_id") # Example if field existed
            else:
                logger.warning(f"Could not fetch chat metadata from Directus for chat {chat_id}. Using defaults for AI request.")
        except Exception as e_meta:
            logger.error(f"Error fetching/processing chat metadata for AI request (chat {chat_id}): {e_meta}", exc_info=True)
        
        # 3. Construct AskSkillRequest payload
        # mate_id is set to None here; the AI app's preprocessor will select the appropriate mate.
        # If the user could explicitly select a mate for a chat, that pre-selected mate_id would be passed here.
        ai_request_payload = AskSkillRequestSchema(
            chat_id=chat_id,
            message_id=message_id,
            user_id_hash=hashlib.sha256(user_id.encode()).hexdigest(),
            message_history=[hist.model_dump() for hist in message_history_for_ai],
            mate_id=None, # Let preprocessor determine the mate unless a specific one is tied to the chat
            active_focus_id=active_focus_id_for_ai,
            user_preferences={}
        )

        # 4. Dispatch Celery task to AI app
        skill_config_for_ask = {}  # Default to empty dict
        ai_celery_task_id = None   # Initialize to None

        try:
            # Attempt to fetch skill_config for 'ask' skill
            if hasattr(websocket.app.state, 'discovered_apps_metadata') and websocket.app.state.discovered_apps_metadata:
                ai_app_metadata = websocket.app.state.discovered_apps_metadata.get("ai")
                if ai_app_metadata and hasattr(ai_app_metadata, 'skills') and ai_app_metadata.skills:
                    ask_skill_def = next((s for s in ai_app_metadata.skills if s.id == "ask"), None)
                    if ask_skill_def and ask_skill_def.default_config:
                        skill_config_for_ask = ask_skill_def.default_config
                        logger.info("Successfully loaded 'default_config' for 'ask' skill.")
                    else:
                        logger.warning("Could not find 'default_config' for 'ask' skill in 'ai' app metadata. Using Pydantic defaults.")
                else:
                    logger.warning("Could not find 'skills' or 'ai' app metadata. Using Pydantic defaults for skill_config.")
            else:
                logger.warning("discovered_apps_metadata not found in app.state. Using Pydantic defaults for skill_config.")

            kwargs_for_celery = {
                "request_data_dict": ai_request_payload.model_dump(),
                "skill_config_dict": skill_config_for_ask  # Pass the retrieved or default {}
            }

            task_result = celery_app.send_task(
                name='ai.process_skill_ask',
                kwargs=kwargs_for_celery,
                queue='ai_processing'
            )
            ai_celery_task_id = task_result.id
            logger.info(f"Dispatched Celery task 'ai.process_skill_ask' with ID {ai_celery_task_id} for chat {chat_id}, user message {message_id}")

            # Send acknowledgement with task_id to the originating client
            await manager.send_personal_message(
                message={
                    "type": "ai_task_initiated",
                    "payload": {
                        "chat_id": chat_id,
                        "user_message_id": message_id,
                        "ai_task_id": ai_celery_task_id,
                        "status": "processing_started"
                    }
                },
                user_id=user_id,
                device_fingerprint_hash=device_fingerprint_hash
            )
            logger.info(f"Sent 'ai_task_initiated' ack to client for task {ai_celery_task_id}")

        except Exception as e_ai_task:
            logger.error(f"Failed to dispatch 'ai.process_skill_ask' Celery task for chat {chat_id}: {e_ai_task}", exc_info=True)
            # Attempt to send an error message to the client
            try:
                await manager.send_personal_message(
                    {"type": "error", "payload": {"message": "Could not initiate AI response. Please try again."}},
                    user_id, device_fingerprint_hash
                )
            except Exception as e_send_err:
                logger.error(f"Failed to send error to client after AI task dispatch failure: {e_send_err}")
        # --- END AI SKILL INVOCATION ---

    except Exception as e: # This is the outer try-except for the whole handler
        logger.error(f"Error in handle_message_received (new message) from {user_id}/{device_fingerprint_hash}: {e}", exc_info=True)
        try:
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Error processing your message on the server."}},
                user_id,
                device_fingerprint_hash
            )
        except Exception as e_send:
            logger.error(f"Failed to send error to {user_id}/{device_fingerprint_hash} after main error: {e_send}")