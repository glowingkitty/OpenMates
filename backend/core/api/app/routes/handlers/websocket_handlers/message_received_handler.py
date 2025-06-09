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
from backend.core.api.app.schemas.chat import MessageInCache, AIHistoryMessage
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
        # Extract role, category, and sender_name from the client payload
        role = message_payload_from_client.get("role") 
        category = message_payload_from_client.get("category") # Optional
        sender_name_from_client = message_payload_from_client.get("sender_name") # Optional, actual name
        
        content_plain = message_payload_from_client.get("content") # This is the Tiptap JSON
        timestamp = message_payload_from_client.get("timestamp") # Unix timestamp (int/float)

        # Validate required fields
        if not message_id or not role or content_plain is None or not timestamp:
            logger.error(f"Missing fields in message data from {user_id}/{device_fingerprint_hash}: message_id={message_id}, role={role}, content_exists={content_plain is not None}, timestamp_exists={timestamp is not None}")
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Missing required fields (message_id, role, content, timestamp) in message data"}},
                user_id,
                device_fingerprint_hash
            )
            return

        # Prepare message for cache (content remains plain for cache)
        # Ensure client_timestamp_unix is derived as an integer.
        client_timestamp_unix: int
        try:
            # Expecting timestamp to be an int or float from the client.
            client_timestamp_unix = int(timestamp)
        except (ValueError, TypeError) as e_ts:
            logger.warning(f"Invalid or missing timestamp from client (type: {type(timestamp)}, value: {timestamp}). Error: {e_ts}. Using current server time.")
            client_timestamp_unix = int(datetime.now(timezone.utc).timestamp())

        # For user messages, sender_name can be derived or set to 'user' if not provided
        # For assistant messages, sender_name might be the specific AI's name.
        # The `role` field is now the primary differentiator.
        final_sender_name = sender_name_from_client
        if role == "user" and not final_sender_name:
            # Optionally, fetch user's display name from profile if available, otherwise default
            # For now, if role is 'user', sender_name might be less critical if UI uses role for alignment
            # and a generic user avatar. If a specific user name is needed for 'user' role messages,
            # it should be consistently provided or fetched.
            # Let's assume for now client sends 'user' as sender_name for user messages if needed, or it's handled by UI.
            # If sender_name_from_client is None for a user, we can default it.
            final_sender_name = "user" # Default if not provided for user role

        message_for_cache = MessageInCache(
            id=message_id,
            chat_id=chat_id,
            role=role,
            category=category,
            sender_name=final_sender_name, # Use the determined sender_name
            content=content_plain,
            created_at=client_timestamp_unix,
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
        # client_timestamp_unix is already defined and parsed above as an integer.

        celery_app.send_task(
            name='app.tasks.persistence_tasks.persist_new_chat_message',
            kwargs={
                'message_id': message_id,
                'chat_id': chat_id,
                'hashed_user_id': hashlib.sha256(user_id.encode()).hexdigest(),
                'role': role,
                'category': category,
                'sender_name': final_sender_name, # Pass the determined sender_name
                'content': encrypted_content_for_db,
                'created_at': client_timestamp_unix,
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
                "role": role,
                "category": category,
                "sender_name": final_sender_name,
                "content": content_plain,
                "created_at": client_timestamp_unix,
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
        
        message_history_for_ai: List[AIHistoryMessage] = []
        try:
            # 1. Fetch message history for the chat
            cached_messages_str_list = await cache_service.get_chat_messages_history(user_id, chat_id) # Fetches all
            
            if cached_messages_str_list:
                logger.info(f"Found {len(cached_messages_str_list)} messages in cache for chat {chat_id} for AI history.")
                for msg_str in reversed(cached_messages_str_list): # Cache stores newest first (LPUSH), reverse for chronological
                    try:
                        msg_cache_data = json.loads(msg_str)
                        # Determine role and category for history messages
                        history_role = msg_cache_data.get("role", "user" if msg_cache_data.get("sender_name") == final_sender_name else "assistant")
                        history_category = msg_cache_data.get("category")
                        history_sender_name = msg_cache_data.get("sender_name", "user" if history_role == "user" else "assistant")

                        # Ensure timestamp is an int
                        history_timestamp_val: int
                        try:
                            history_timestamp_val = int(msg_cache_data.get("created_at"))
                        except (ValueError, TypeError):
                            logger.warning(f"Cached message for chat {chat_id} has non-integer or missing timestamp '{msg_cache_data.get('created_at')}'. Defaulting to current time.")
                            history_timestamp_val = int(datetime.now(timezone.utc).timestamp())

                        message_history_for_ai.append(
                            AIHistoryMessage(
                                role=history_role,
                                category=history_category,
                                sender_name=history_sender_name,
                                content=msg_cache_data.get("content"), # Tiptap JSON
                                created_at=history_timestamp_val
                            )
                        )
                    except json.JSONDecodeError:
                        logger.warning(f"Could not parse cached message string for chat {chat_id}: {msg_str[:100]}...")
                    except Exception as e_hist_parse:
                        logger.warning(f"Error processing cached message for AI history: {e_hist_parse}")
            else:
                logger.info(f"No messages in cache for chat {chat_id} for AI history. Fetching from Directus.")
                from backend.core.api.app.services.directus import chat_methods as directus_chat_api
                
                db_messages = await directus_service.chat.get_all_messages_for_chat(
                    chat_id, decrypt_content=True # Decrypts content to Tiptap JSON
                ) # Fetches all, sorted by created_at
                if db_messages:
                    for msg_db_data in db_messages:
                        # Determine role and category for DB messages
                        history_role_db = msg_db_data.get("role", "user" if msg_db_data.get("sender_name") == final_sender_name else "assistant")
                        history_category_db = msg_db_data.get("category")
                        history_sender_name_db = msg_db_data.get("sender_name", "user" if history_role_db == "user" else "assistant")
                        
                        history_timestamp_val: int
                        try:
                            # Directus stores datetime objects, convert to Unix timestamp
                            created_at_dt = msg_db_data.get("created_at")
                            if isinstance(created_at_dt, datetime):
                                history_timestamp_val = int(created_at_dt.timestamp())
                            elif isinstance(created_at_dt, (int, float)): # Already a timestamp
                                history_timestamp_val = int(created_at_dt)
                            else:
                                raise ValueError("Unsupported timestamp format from DB")
                        except (ValueError, TypeError, AttributeError):
                            logger.warning(f"DB message for chat {chat_id} has invalid or missing timestamp '{msg_db_data.get('created_at')}'. Defaulting to current time.")
                            history_timestamp_val = int(datetime.now(timezone.utc).timestamp())

                        message_history_for_ai.append(
                            AIHistoryMessage(
                                role=history_role_db,
                                category=history_category_db,
                                sender_name=history_sender_name_db,
                                content=msg_db_data.get("content"), # Decrypted Tiptap JSON
                                created_at=history_timestamp_val
                            )
                        )
            
            # Ensure the current message (which triggered the AI) is the last one in the history.
            current_message_in_history = any(
                m.content == content_plain and 
                m.created_at == client_timestamp_unix and 
                m.role == role # Check role instead of sender_name for "user"
                for m in message_history_for_ai
            )

            if not current_message_in_history:
                logger.info(f"Current user message {message_id} not found in history. Appending it now.")
                message_history_for_ai.append(
                    AIHistoryMessage(
                        role=role, # Current message's role
                        category=category, # Current message's category (likely None for user)
                        sender_name=final_sender_name, # Current message's sender_name
                        content=content_plain, # Tiptap JSON
                        created_at=client_timestamp_unix
                    )
                )
            # Ensure the current message is the last one if it was added or already present
            message_history_for_ai = sorted(message_history_for_ai, key=lambda m: m.created_at)


            logger.info(f"Final AI message history for chat {chat_id} has {len(message_history_for_ai)} messages.")

        except Exception as e_hist:
            logger.error(f"Failed to construct message history for AI for chat {chat_id}: {e_hist}", exc_info=True)
            # Proceed with at least the current message if history construction failed
            message_history_for_ai = [
                AIHistoryMessage(sender_name="user", content=content_plain, created_at=client_timestamp_unix)
            ]


        # 2. Fetch active_focus_id from chat metadata
        active_focus_id_for_ai: Optional[str] = None
        # mate_id_for_ask_request: Optional[str] = None # Mate ID is determined by preprocessor

        try:
            from backend.core.api.app.services.directus import chat_methods as directus_chat_api
            chat_directus_metadata = await directus_service.chat.get_chat_metadata(chat_id)
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
        
        # Extract current_chat_title from the client's message payload
        client_sent_chat_title = message_payload_from_client.get("current_chat_title")

        ai_request_payload = AskSkillRequestSchema(
            chat_id=chat_id,
            message_id=message_id,
            user_id=user_id, # Pass the actual user_id
            user_id_hash=hashlib.sha256(user_id.encode()).hexdigest(), # Pass the hashed user_id
            message_history=message_history_for_ai,
            current_chat_title=client_sent_chat_title, # Pass the title from client message
            mate_id=None, # Let preprocessor determine the mate unless a specific one is tied to the chat
            active_focus_id=active_focus_id_for_ai,
            user_preferences={}
        )
        logger.info(f"Constructed AskSkillRequest with current_chat_title: {client_sent_chat_title}")

        # 4. Dispatch Celery task to AI app
        skill_config_for_ask = {}  # Default to empty dict
        ai_celery_task_id = None   # Initialize to None

        try:
            # Attempt to fetch skill_config for 'ask' skill
            if hasattr(websocket.app.state, 'discovered_apps_metadata') and websocket.app.state.discovered_apps_metadata:
                ai_app_metadata = websocket.app.state.discovered_apps_metadata.get("ai")
                if ai_app_metadata and hasattr(ai_app_metadata, 'skills') and ai_app_metadata.skills:
                    ask_skill_def = next((s for s in ai_app_metadata.skills if s.id == "ask"), None)
                    # Corrected to look for 'skill_config' which is present in app.yml
                    if ask_skill_def and hasattr(ask_skill_def, 'skill_config') and ask_skill_def.skill_config is not None:
                        skill_config_for_ask = ask_skill_def.skill_config
                        logger.info("Successfully loaded 'skill_config' for 'ask' skill.")
                    # Check for 'default_config' as a fallback or if the attribute name is different in the Pydantic model
                    elif ask_skill_def and hasattr(ask_skill_def, 'default_config') and ask_skill_def.default_config is not None:
                        skill_config_for_ask = ask_skill_def.default_config
                        logger.info("Successfully loaded 'default_config' (as fallback) for 'ask' skill.")
                    else:
                        logger.warning("Could not find 'skill_config' or 'default_config' for 'ask' skill in 'ai' app metadata. Using Pydantic defaults.")
                else:
                    logger.warning("Could not find 'skills' or 'ai' app metadata. Using Pydantic defaults for skill_config.")
            else:
                logger.warning("discovered_apps_metadata not found in app.state. Using Pydantic defaults for skill_config.")

            kwargs_for_celery = {
                "request_data_dict": ai_request_payload.model_dump(),
                "skill_config_dict": skill_config_for_ask  # Pass the retrieved or default {}
            }

            task_result = celery_app.send_task(
                name='apps.ai.tasks.skill_ask',
                kwargs=kwargs_for_celery,
                queue='app_ai' # Corrected queue name to match celery_config.py
            )
            ai_celery_task_id = task_result.id
            logger.info(f"Dispatched Celery task 'apps.ai.tasks.skill_ask' with ID {ai_celery_task_id} for chat {chat_id}, user message {message_id}")

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
            logger.error(f"Failed to dispatch 'apps.ai.tasks.skill_ask' Celery task for chat {chat_id}: {e_ai_task}", exc_info=True)
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
