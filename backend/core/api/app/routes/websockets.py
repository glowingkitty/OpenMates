import logging
import time
import hashlib
import json
import asyncio # Added asyncio
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, status, FastAPI
# Import necessary services and utilities
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1/ws",
    tags=["websockets"],
)

# Import ConnectionManager from the new module
from .connection_manager import ConnectionManager
from .auth_ws import get_current_user_ws
from .handlers.websocket_handlers.title_update_handler import handle_update_title
from .handlers.websocket_handlers.draft_update_handler import handle_update_draft
from .handlers.websocket_handlers.message_received_handler import handle_message_received
from .handlers.websocket_handlers.delete_chat_handler import handle_delete_chat
from .handlers.websocket_handlers.offline_sync_handler import handle_sync_offline_changes
from .handlers.websocket_handlers.initial_sync_handler import handle_initial_sync
from .handlers.websocket_handlers.get_chat_messages_handler import handle_get_chat_messages
from .handlers.websocket_handlers.delete_draft_handler import handle_delete_draft
from .handlers.websocket_handlers.chat_content_batch_handler import handle_chat_content_batch # New handler
from .handlers.websocket_handlers.cancel_ai_task_handler import handle_cancel_ai_task # New handler for cancelling AI tasks
from .handlers.websocket_handlers.ai_response_completed_handler import handle_ai_response_completed # Handler for completed AI responses
from .handlers.websocket_handlers.encrypted_chat_metadata_handler import handle_encrypted_chat_metadata # Handler for encrypted chat metadata
from .handlers.websocket_handlers.post_processing_metadata_handler import handle_post_processing_metadata # Handler for post-processing metadata sync
from .handlers.websocket_handlers.phased_sync_handler import handle_phased_sync_request, handle_sync_status_request # Handlers for phased sync
from .handlers.websocket_handlers.app_settings_memories_confirmed_handler import handle_app_settings_memories_confirmed # Handler for app settings/memories confirmations

manager = ConnectionManager() # This is the correct manager instance for websockets

# --- Redis Pub/Sub Listener for Cache Events ---
# This function will be imported and started by main.py
async def listen_for_cache_events(app: FastAPI):
    """Listens to Redis Pub/Sub for cache-related events and notifies clients via WebSocket."""
    # Ensure services are available on app.state, initialized by main.py's lifespan
    if not hasattr(app.state, 'cache_service'):
        logger.critical("Cache service not found on app.state. Pub/Sub listener cannot start.")
        return
    
    cache_service: CacheService = app.state.cache_service
    logger.debug("Starting Redis Pub/Sub listener for cache events...")
    
    # Ensure the client is connected before starting the subscription loop
    # This should have been handled during CacheService initialization in main.py
    # but an extra check or await client won't hurt if client is a property.
    await cache_service.client # Make sure connection is established

    async for message in cache_service.subscribe_to_channel("user_cache_events:*"):
        try:
            if message and isinstance(message.get("data"), dict):
                channel_str = message.get("channel", "") # e.g., "user_cache_events:some_user_id"
                event_data = message["data"]
                event_type = event_data.get("event_type")
                payload = event_data.get("payload")

                parts = channel_str.split(":")
                if len(parts) == 2 and parts[0] == "user_cache_events":
                    user_id = parts[1]
                    logger.debug(f"Redis Listener: Received '{event_type}' for user {user_id}. Payload: {payload}")

                    if event_type == "phase_1_last_chat_ready":
                        await manager.broadcast_to_user_specific_event(
                            user_id=user_id,
                            event_name="phase_1_last_chat_ready",
                            payload=payload
                        )
                        logger.debug(f"Redis Listener: Sent 'phase_1_last_chat_ready' WebSocket to user {user_id}.")
                    elif event_type == "phase_2_last_20_chats_ready":
                        await manager.broadcast_to_user_specific_event(
                            user_id=user_id,
                            event_name="phase_2_last_20_chats_ready",
                            payload=payload
                        )
                        logger.debug(f"Redis Listener: Sent 'phase_2_last_20_chats_ready' WebSocket to user {user_id}.")
                    elif event_type == "phase_3_last_100_chats_ready":
                        await manager.broadcast_to_user_specific_event(
                            user_id=user_id,
                            event_name="phase_3_last_100_chats_ready",
                            payload=payload
                        )
                        logger.debug(f"Redis Listener: Sent 'phase_3_last_100_chats_ready' WebSocket to user {user_id}.")
                    elif event_type == "cache_primed":
                        await manager.broadcast_to_user_specific_event(
                            user_id=user_id,
                            event_name="cache_primed",
                            payload=payload
                        )
                        logger.debug(f"Redis Listener: Sent 'cache_primed' WebSocket to user {user_id}.")
                    elif event_type == "send_app_settings_memories_request":
                        # Send app settings/memories request to client via WebSocket
                        # This is triggered from Celery tasks via Redis pub/sub
                        request_id = payload.get("request_id")
                        requested_keys = payload.get("requested_keys", [])
                        if request_id and requested_keys:
                            user_connections = manager.get_connections_for_user(user_id)
                            if user_connections:
                                # Send to first available device
                                target_device = list(user_connections.keys())[0]
                                await manager.send_personal_message(
                                    {
                                        "type": "request_app_settings_memories",
                                        "payload": {
                                            "request_id": request_id,
                                            "requested_keys": requested_keys
                                        }
                                    },
                                    user_id,
                                    target_device
                                )
                                logger.info(f"Redis Listener: Sent app_settings_memories request {request_id} to user {user_id} via WebSocket")
                            else:
                                logger.warning(f"Redis Listener: User {user_id} has no active connections for app_settings_memories request {request_id}")
                    else:
                        logger.warning(f"Redis Listener: Unknown event_type '{event_type}' for user {user_id}.")
                else:
                    logger.warning(f"Redis Listener: Could not parse user_id from channel: {channel_str}")

            elif message and message.get("error") == "json_decode_error":
                logger.error(f"Redis Listener: JSON decode error from channel '{message.get('channel')}': {message.get('data')}")
            elif message:
                logger.debug(f"Redis Listener: Received non-data message or timeout: {message}")

        except Exception as e:
            logger.error(f"Redis Listener: Error processing message: {e}", exc_info=True)
            await asyncio.sleep(1) # Prevent tight loop on continuous errors


async def listen_for_ai_chat_streams(app: FastAPI):
    """Listens to Redis Pub/Sub for AI chat stream events and forwards them to relevant users."""
    if not hasattr(app.state, 'cache_service'):
        logger.critical("Cache service not found on app.state. AI chat stream listener cannot start.")
        return
    
    cache_service: CacheService = app.state.cache_service
    logger.debug("Starting Redis Pub/Sub listener for AI chat stream events (channel: chat_stream::*)...")

    await cache_service.client # Ensure connection

    async for message in cache_service.subscribe_to_channel("chat_stream::*"): # Subscribes to chat_stream::{chat_id}
        logger.debug(f"AI Stream Listener: Raw message from pubsub channel chat_stream::*: {message}")
        try:
            if message and isinstance(message.get("data"), dict):
                # The 'data' field from cache_service.subscribe_to_channel is already a dict if it was JSON
                redis_payload = message["data"]
                redis_channel_name = message.get("channel", "") # e.g., "chat_stream::some_chat_id"
                
                # Validate payload structure (basic check)
                if not all(k in redis_payload for k in ["type", "chat_id", "user_id_hash", "message_id"]):
                    logger.warning(f"AI Stream Listener: Received malformed payload on channel '{redis_channel_name}': {redis_payload}")
                    continue

                event_type = redis_payload.get("type")
                if event_type == "ai_message_chunk":
                    user_id_uuid = redis_payload.get("user_id_uuid") # Use UUID for ConnectionManager
                    user_id_hash_for_logging = redis_payload.get("user_id_hash") # Keep for logging if needed
                    chat_id_from_payload = redis_payload.get("chat_id")

                    if not user_id_uuid:
                        logger.warning(f"AI Stream Listener: Missing user_id_uuid in payload from channel '{redis_channel_name}': {redis_payload}")
                        continue
                    
                    logger.debug(f"AI Stream Listener: Received '{event_type}' for user_id_uuid {user_id_uuid} (hash: {user_id_hash_for_logging}), chat_id {chat_id_from_payload} from Redis channel '{redis_channel_name}'. Processing for selective forwarding.")
                    logger.debug(f"AI Stream Listener: Full Redis Payload: {json.dumps(redis_payload, indent=2)}")

                    # Iterate over all connections for this user (using UUID)
                    user_connections = manager.get_connections_for_user(user_id_uuid)
                    for device_hash, websocket_conn in user_connections.items():
                        active_chat_on_device = manager.get_active_chat(user_id_uuid, device_hash)
                        
                        if chat_id_from_payload == active_chat_on_device:
                            # Check for errors in the stream content
                            if redis_payload.get("full_content_so_far") and isinstance(redis_payload["full_content_so_far"], str) and "[ERROR" in redis_payload["full_content_so_far"]:
                                logger.warning(f"AI Stream Listener: Detected error in stream for chat {chat_id_from_payload}. Original error: {redis_payload['full_content_so_far']}")
                                # Overwrite with a generic key for the frontend
                                redis_payload["full_content_so_far"] = "chat.an_error_occured.text"

                            # This device has the chat open, send the full stream update
                            await manager.send_personal_message(
                                message={"type": "ai_message_update", "payload": redis_payload},
                                user_id=user_id_uuid, # Use UUID
                                device_fingerprint_hash=device_hash
                            )
                            logger.debug(f"AI Stream Listener: Sent 'ai_message_update' to active chat on {user_id_uuid}/{device_hash}.")
                        else:
                            # Chat is not active on this device.
                            # For background processing: only send completed response when final marker arrives
                            is_final_marker = redis_payload.get("is_final_chunk", False)

                            if is_final_marker:
                                # For inactive devices, send the completed AI response as a background update
                                # This allows AI processing to continue in the background
                                # Client will store the completed message and show it when the chat is opened
                                
                                # Check for errors in the stream content (same as active chat)
                                full_content = redis_payload.get("full_content_so_far", "")
                                if full_content and isinstance(full_content, str) and "[ERROR" in full_content:
                                    logger.warning(f"AI Stream Listener: Detected error in background stream for chat {chat_id_from_payload}. Original error: {full_content}")
                                    # Overwrite with a generic key for the frontend
                                    full_content = "chat.an_error_occured.text"
                                
                                # Send background completion event with full response
                                background_completion_payload = {
                                    "chat_id": chat_id_from_payload,
                                    "message_id": redis_payload.get("message_id"), # AI's message ID
                                    "user_message_id": redis_payload.get("user_message_id"),
                                    "task_id": redis_payload.get("task_id"),
                                    "full_content": full_content,
                                    "interrupted_by_soft_limit": redis_payload.get("interrupted_by_soft_limit", False),
                                    "interrupted_by_revocation": redis_payload.get("interrupted_by_revocation", False)
                                }
                                await manager.send_personal_message(
                                    message={"type": "ai_background_response_completed", "payload": background_completion_payload},
                                    user_id=user_id_uuid,
                                    device_fingerprint_hash=device_hash
                                )
                                logger.debug(f"AI Stream Listener: Sent 'ai_background_response_completed' to inactive chat device {user_id_uuid}/{device_hash}.")
                                
                                # Also send typing ended event for UI cleanup
                                typing_ended_payload = {
                                    "chat_id": chat_id_from_payload,
                                    "message_id": redis_payload.get("message_id") # AI's message ID
                                }
                                await manager.send_personal_message(
                                     message={"type": "ai_typing_ended", "payload": typing_ended_payload},
                                     user_id=user_id_uuid, # Use UUID
                                     device_fingerprint_hash=device_hash
                                )
                                logger.debug(f"AI Stream Listener: Sent 'ai_typing_ended' for chat {chat_id_from_payload} to inactive device {user_id_uuid}/{device_hash}.")
                else:
                    logger.warning(f"AI Stream Listener: Unknown event_type '{event_type}' on channel '{redis_channel_name}'.")
            
            elif message and message.get("error") == "json_decode_error":
                logger.error(f"AI Stream Listener: JSON decode error from channel '{message.get('channel')}': {message.get('data')}")
            elif message:
                # This can happen on initial subscription confirmation or if non-JSON data is published.
                logger.debug(f"AI Stream Listener: Received non-data message or confirmation: {message}")

        except Exception as e:
            logger.error(f"AI Stream Listener: Error processing message: {e}", exc_info=True)
            await asyncio.sleep(1) # Prevent tight loop on continuous errors


async def listen_for_ai_typing_indicator_events(app: FastAPI):
    """Listens to Redis Pub/Sub for AI processing started events to send typing indicators."""
    if not hasattr(app.state, 'cache_service'):
        logger.critical("Cache service not found on app.state. AI typing indicator listener cannot start.")
        return
    
    cache_service: CacheService = app.state.cache_service
    logger.debug("Starting Redis Pub/Sub listener for AI typing indicator events (channel: ai_typing_indicator_events::*)...")

    await cache_service.client # Ensure connection

    async for message in cache_service.subscribe_to_channel("ai_typing_indicator_events::*"):
        logger.debug(f"AI Typing Indicator Listener: Raw message from pubsub channel ai_typing_indicator_events::*: {message}")
        try:
            if message and isinstance(message.get("data"), dict):
                redis_payload = message["data"]
                redis_channel_name = message.get("channel", "")
                
                internal_event_type = redis_payload.get("type")

                # Handle ai_processing_started_event (typing indicator)
                if internal_event_type == "ai_processing_started_event":
                    client_event_name = redis_payload.get("event_for_client") # Should be "ai_typing_started"
                    user_id_uuid = redis_payload.get("user_id_uuid")
                    user_id_hash_for_logging = redis_payload.get("user_id_hash")
                    chat_id = redis_payload.get("chat_id")
                    ai_task_id = redis_payload.get("task_id") # This is the AI's message_id
                    user_message_id = redis_payload.get("user_message_id")
                    category = redis_payload.get("category")
                    model_name = redis_payload.get("model_name") # Extract model_name
                    title = redis_payload.get("title") # Extract title

                    # Title is optional in the payload for now, but other fields are essential
                    if not all([client_event_name, user_id_uuid, chat_id, ai_task_id, user_message_id, category]):
                        logger.warning(f"AI Typing Listener: Malformed payload on channel '{redis_channel_name}' (missing essential fields like category, user_id_uuid, etc.): {redis_payload}")
                        continue

                    logger.debug(f"AI Typing Listener: Received '{internal_event_type}' for user_id_uuid {user_id_uuid} (hash: {user_id_hash_for_logging}) from Redis channel '{redis_channel_name}'. Forwarding as '{client_event_name}'. Category: {category}, Model Name: {model_name}, Title: {title}")

                    client_payload = {
                        "chat_id": chat_id,
                        "message_id": ai_task_id, # AI's message ID
                        "user_message_id": user_message_id,
                        "category": category,
                        "model_name": model_name, # Include model_name in the client payload
                        "title": title, # Include title in the client payload
                        "icon_names": redis_payload.get("icon_names", []) # Include icon names in the client payload
                    }

                    # This event should go to all devices of the user, as it's a UI update.
                    await manager.broadcast_to_user_specific_event(
                        user_id=user_id_uuid,
                        event_name=client_event_name, # "ai_typing_started"
                        payload=client_payload
                    )
                    logger.debug(f"AI Typing Listener: Broadcasted '{client_event_name}' to user {user_id_uuid} with payload: {client_payload}")

                # Handle post_processing_completed event
                elif internal_event_type == "post_processing_completed":
                    client_event_name = redis_payload.get("event_for_client") # Should be "post_processing_completed"
                    user_id_uuid = redis_payload.get("user_id_uuid")
                    user_id_hash_for_logging = redis_payload.get("user_id_hash")
                    chat_id = redis_payload.get("chat_id")
                    task_id = redis_payload.get("task_id")

                    if not all([client_event_name, user_id_uuid, chat_id, task_id]):
                        logger.warning(f"AI Typing Listener: Malformed post_processing_completed payload on channel '{redis_channel_name}': {redis_payload}")
                        continue

                    logger.debug(f"AI Typing Listener: Received '{internal_event_type}' for user_id_uuid {user_id_uuid} (hash: {user_id_hash_for_logging}) from Redis channel '{redis_channel_name}'. Forwarding as '{client_event_name}'.")

                    # Forward entire payload to client (includes suggestions, summary, tags)
                    client_payload = {
                        "chat_id": chat_id,
                        "task_id": task_id,
                        "follow_up_request_suggestions": redis_payload.get("follow_up_request_suggestions", []),
                        "new_chat_request_suggestions": redis_payload.get("new_chat_request_suggestions", []),
                        "chat_summary": redis_payload.get("chat_summary", ""),
                        "chat_tags": redis_payload.get("chat_tags", []),
                        "harmful_response": redis_payload.get("harmful_response", 0.0)
                    }

                    await manager.broadcast_to_user_specific_event(
                        user_id=user_id_uuid,
                        event_name=client_event_name, # "post_processing_completed"
                        payload=client_payload
                    )
                    logger.debug(f"AI Typing Listener: Broadcasted '{client_event_name}' to user {user_id_uuid} with payload: {client_payload}")

                # Handle skill_execution_status event
                elif internal_event_type == "skill_execution_status":
                    client_event_name = redis_payload.get("event_for_client") # Should be "skill_execution_status"
                    user_id_uuid = redis_payload.get("user_id_uuid")
                    user_id_hash_for_logging = redis_payload.get("user_id_hash")
                    chat_id = redis_payload.get("chat_id")
                    message_id = redis_payload.get("message_id")
                    task_id = redis_payload.get("task_id")
                    app_id = redis_payload.get("app_id")
                    skill_id = redis_payload.get("skill_id")
                    status = redis_payload.get("status")
                    preview_data = redis_payload.get("preview_data", {})

                    if not all([client_event_name, user_id_uuid, chat_id, message_id, task_id, app_id, skill_id, status]):
                        logger.warning(f"AI Typing Listener: Malformed skill_execution_status payload on channel '{redis_channel_name}': {redis_payload}")
                        continue

                    logger.debug(
                        f"AI Typing Listener: Received '{internal_event_type}' for user_id_uuid {user_id_uuid} "
                        f"(hash: {user_id_hash_for_logging}) from Redis channel '{redis_channel_name}'. "
                        f"Forwarding as '{client_event_name}'. Skill: {app_id}.{skill_id}, Status: {status}"
                    )

                    # Construct client payload matching frontend SkillExecutionStatusUpdatePayload interface
                    client_payload = {
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "task_id": task_id,
                        "app_id": app_id,
                        "skill_id": skill_id,
                        "status": status,
                        "preview_data": preview_data
                    }

                    # Add error if present
                    if "error" in redis_payload:
                        client_payload["error"] = redis_payload["error"]

                    await manager.broadcast_to_user_specific_event(
                        user_id=user_id_uuid,
                        event_name=client_event_name, # "skill_execution_status"
                        payload=client_payload
                    )
                    logger.debug(f"AI Typing Listener: Broadcasted '{client_event_name}' to user {user_id_uuid} for skill {app_id}.{skill_id} with status {status}")

                else:
                    logger.warning(f"AI Typing Listener: Received unexpected event type '{internal_event_type}' on channel '{redis_channel_name}'. Skipping.")

            elif message and message.get("error") == "json_decode_error":
                logger.error(f"AI Typing Listener: JSON decode error from channel '{message.get('channel')}': {message.get('data')}")
            elif message:
                logger.debug(f"AI Typing Listener: Received non-data message or confirmation: {message}")

        except Exception as e:
            logger.error(f"AI Typing Listener: Error processing message: {e}", exc_info=True)
            await asyncio.sleep(1)


async def listen_for_chat_updates(app: FastAPI):
    """Listens to Redis Pub/Sub for chat update events like title changes."""
    if not hasattr(app.state, 'cache_service'):
        logger.critical("Cache service not found on app.state. Chat updates listener cannot start.")
        return
    
    cache_service: CacheService = app.state.cache_service
    logger.debug("Starting Redis Pub/Sub listener for chat update events (channel: chat_updates::*)...")

    await cache_service.client # Ensure connection

    async for message in cache_service.subscribe_to_channel("chat_updates::*"): # Subscribes to chat_updates::{user_id_hash}
        logger.debug(f"Chat Updates Listener: Raw message from pubsub channel chat_updates::*: {message}")
        try:
            if message and isinstance(message.get("data"), dict):
                redis_payload = message["data"]
                redis_channel_name = message.get("channel", "")
                
                internal_event_type = redis_payload.get("type") # e.g., "chat_title_updated_event"
                event_for_client = redis_payload.get("event_for_client") # e.g., "chat_title_updated"
                user_id_uuid = redis_payload.get("user_id_uuid")
                user_id_hash_for_logging = redis_payload.get("user_id_hash")
                
                # Specific data for the event, e.g., for title update:
                # chat_id = redis_payload.get("chat_id")
                # data_for_client = redis_payload.get("data") # e.g., {"title": "New Title"}
                # versions_for_client = redis_payload.get("versions") # e.g., {"title_v": 2}

                if not all([internal_event_type, event_for_client, user_id_uuid]):
                    logger.warning(f"Chat Updates Listener: Malformed base payload on channel '{redis_channel_name}': {redis_payload}")
                    continue
                
                logger.debug(f"Chat Updates Listener: Received '{internal_event_type}' for user_id_uuid {user_id_uuid} (hash: {user_id_hash_for_logging}) from Redis channel '{redis_channel_name}'. Forwarding as '{event_for_client}'.")

                # Construct the client payload carefully based on what chatSyncService expects for each event type
                client_payload_data = {
                    "chat_id": redis_payload.get("chat_id"),
                    "data": redis_payload.get("data"),
                    "versions": redis_payload.get("versions"),
                    # Add other common fields if necessary, or handle per event_for_client
                }
                
                # Ensure essential parts for known events are present
                # Note: chat_metadata_for_encryption event removed - metadata now sent via ai_typing_started
                # Add more event_for_client checks here if this listener handles more types

                await manager.broadcast_to_user_specific_event(
                    user_id=user_id_uuid,
                    event_name=event_for_client,
                    payload=client_payload_data # Send the structured data
                )
                logger.debug(f"Chat Updates Listener: Broadcasted '{event_for_client}' to user {user_id_uuid} with payload: {client_payload_data}")

            elif message and message.get("error") == "json_decode_error":
                logger.error(f"Chat Updates Listener: JSON decode error from channel '{message.get('channel')}': {message.get('data')}")
            elif message:
                logger.debug(f"Chat Updates Listener: Received non-data message or confirmation: {message}")

        except Exception as e:
            logger.error(f"Chat Updates Listener: Error processing message: {e}", exc_info=True)
            await asyncio.sleep(1)


async def listen_for_ai_message_persisted_events(app: FastAPI):
    """Listens to Redis Pub/Sub for events indicating an AI message has been persisted."""
    if not hasattr(app.state, 'cache_service'):
        logger.critical("Cache service not found on app.state. AI message persisted listener cannot start.")
        return
    
    cache_service: CacheService = app.state.cache_service
    logger.debug("Starting Redis Pub/Sub listener for AI message persisted events (channel: ai_message_persisted::*)...")

    await cache_service.client # Ensure connection

    async for message in cache_service.subscribe_to_channel("ai_message_persisted::*"):
        logger.debug(f"AI Persisted Listener: Raw message from pubsub channel ai_message_persisted::*: {message}")
        try:
            if message and isinstance(message.get("data"), dict):
                redis_payload = message["data"]
                redis_channel_name = message.get("channel", "")
                
                internal_event_type = redis_payload.get("type")
                if internal_event_type != "ai_message_persisted":
                    logger.warning(f"AI Persisted Listener: Received unexpected event type '{internal_event_type}' on channel '{redis_channel_name}'. Skipping.")
                    continue

                user_id_uuid = redis_payload.get("user_id_uuid") # Use UUID for ConnectionManager
                user_id_hash_for_logging = redis_payload.get("user_id_hash") # Keep for logging
                event_for_client = redis_payload.get("event_for_client")
                message_content_for_client = redis_payload.get("message")
                versions_for_client = redis_payload.get("versions")
                last_edited_ts_for_client = redis_payload.get("last_edited_overall_timestamp")

                if not all([user_id_uuid, event_for_client, message_content_for_client, versions_for_client, last_edited_ts_for_client is not None]):
                    logger.warning(f"AI Persisted Listener: Malformed payload on channel '{redis_channel_name}' (missing user_id_uuid or other fields): {redis_payload}")
                    continue
                
                logger.debug(f"AI Persisted Listener: Received '{internal_event_type}' for user_id_uuid {user_id_uuid} (hash: {user_id_hash_for_logging}) from Redis channel '{redis_channel_name}'. Forwarding as '{event_for_client}'.")

                # Check for and replace error messages before sending to client
                if message_content_for_client:
                    try:
                        # The content is nested within the message structure
                        text_content = message_content_for_client.get("content", {}).get("content", [{}])[0].get("content", [{}])[0].get("text", "")
                        if isinstance(text_content, str) and "[ERROR" in text_content:
                            logger.warning(f"AI Persisted Listener: Detected error in persisted message for chat {redis_payload.get('chat_id')}. Original error: {text_content}")
                            # Overwrite with a generic key for the frontend
                            message_content_for_client["content"]["content"][0]["content"][0]["text"] = "chat.an_error_occured.text"
                    except (IndexError, KeyError, AttributeError) as e:
                        logger.debug(f"AI Persisted Listener: Could not find text content in message, structure may be different or not an error. Error: {e}")

                # Construct the payload exactly as the client's handleChatMessageReceived expects
                # for a 'chat_message_added' event.
                client_payload = {
                    "chat_id": redis_payload.get("chat_id"), # Ensure chat_id is in the redis_payload
                    "message": message_content_for_client,
                    "versions": versions_for_client,
                    "last_edited_overall_timestamp": last_edited_ts_for_client
                }

                await manager.broadcast_to_user_specific_event(
                    user_id=user_id_uuid, # Use UUID for ConnectionManager
                    event_name=event_for_client, # Should be "chat_message_added"
                    payload=client_payload
                )
                logger.debug(f"AI Persisted Listener: Broadcasted '{event_for_client}' to user {user_id_uuid} with payload: {client_payload}")

            elif message and message.get("error") == "json_decode_error":
                logger.error(f"AI Persisted Listener: JSON decode error from channel '{message.get('channel')}': {message.get('data')}")
            elif message:
                logger.debug(f"AI Persisted Listener: Received non-data message or confirmation: {message}")

        except Exception as e:
            logger.error(f"AI Persisted Listener: Error processing message: {e}", exc_info=True)
            await asyncio.sleep(1)


async def listen_for_user_updates(app: FastAPI):
    """Listens to Redis Pub/Sub for general user update events like credit changes."""
    if not hasattr(app.state, 'cache_service'):
        logger.critical("Cache service not found on app.state. User updates listener cannot start.")
        return
    
    cache_service: CacheService = app.state.cache_service
    logger.debug("Starting Redis Pub/Sub listener for user update events (channel: user_updates::*)...")

    await cache_service.client # Ensure connection

    async for message in cache_service.subscribe_to_channel("user_updates::*"):
        logger.debug(f"User Updates Listener: Raw message from pubsub channel user_updates::*: {message}")
        try:
            if message and isinstance(message.get("data"), dict):
                redis_payload = message["data"]
                redis_channel_name = message.get("channel", "")
                
                event_for_client = redis_payload.get("event_for_client")
                user_id_uuid = redis_payload.get("user_id_uuid")
                client_payload = redis_payload.get("payload", {})

                if not all([event_for_client, user_id_uuid]):
                    logger.warning(f"User Updates Listener: Malformed payload on channel '{redis_channel_name}': {redis_payload}")
                    continue
                
                logger.debug(f"User Updates Listener: Received event for user {user_id_uuid}. Forwarding as '{event_for_client}'.")

                await manager.broadcast_to_user_specific_event(
                    user_id=user_id_uuid,
                    event_name=event_for_client,
                    payload=client_payload
                )
                logger.debug(f"User Updates Listener: Broadcasted '{event_for_client}' to user {user_id_uuid} with payload: {client_payload}")

            elif message and message.get("error") == "json_decode_error":
                logger.error(f"User Updates Listener: JSON decode error from channel '{message.get('channel')}': {message.get('data')}")
            elif message:
                logger.debug(f"User Updates Listener: Received non-data message or confirmation: {message}")

        except Exception as e:
            logger.error(f"User Updates Listener: Error processing message: {e}", exc_info=True)
            await asyncio.sleep(1)


# Authentication logic is now in auth_ws.py
@router.websocket("")
async def websocket_endpoint(
    websocket: WebSocket,
    auth_data: Optional[dict] = Depends(get_current_user_ws),
):
    # Check if authentication failed (connection already closed by auth function)
    if auth_data is None:
        logger.debug("WebSocket endpoint called with None auth_data - connection already closed by auth")
        return  # Exit gracefully, connection already closed
    
    # Access services directly from websocket state
    cache_service: CacheService = websocket.app.state.cache_service
    directus_service: DirectusService = websocket.app.state.directus_service # <-- Get DirectusService
    encryption_service: EncryptionService = websocket.app.state.encryption_service # <-- Get EncryptionService
    user_id = auth_data["user_id"]
    device_fingerprint_hash = auth_data["device_fingerprint_hash"]
    user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()

    logger.debug("WebSocket connection established and authenticated for user")
    await manager.connect(websocket, user_id, device_fingerprint_hash)

    try:
        while True:
            data = await websocket.receive_json()
            logger.debug(f"Received message from User {user_id}, Device {device_fingerprint_hash}: {data}")

            message_type = data.get("type")
            payload = data.get("payload", {})

            # Process different message types
            if message_type == "initial_sync_request":
                logger.debug(f"Received initial_sync_request from {user_id}/{device_fingerprint_hash}")
                
                # Extract required fields
                client_chat_ids = payload.get("chat_ids")  # REQUIRED: explicit list of chat IDs
                client_chat_count = payload.get("chat_count")  # REQUIRED: number of chats
                
                # Validate required fields immediately
                if client_chat_ids is None:
                    logger.error(f"Missing required field 'chat_ids' in sync request from {user_id}/{device_fingerprint_hash}")
                    await manager.send_personal_message(
                        message={"type": "initial_sync_error", "payload": {"message": "Missing required field: chat_ids. Please update your client."}},
                        user_id=user_id,
                        device_fingerprint_hash=device_fingerprint_hash
                    )
                    continue
                
                if client_chat_count is None:
                    logger.error(f"Missing required field 'chat_count' in sync request from {user_id}/{device_fingerprint_hash}")
                    await manager.send_personal_message(
                        message={"type": "initial_sync_error", "payload": {"message": "Missing required field: chat_count. Please update your client."}},
                        user_id=user_id,
                        device_fingerprint_hash=device_fingerprint_hash
                    )
                    continue
                
                # Extract optional fields
                client_chat_versions = payload.get("chat_versions", {})
                last_sync_timestamp = payload.get("last_sync_timestamp", None)
                immediate_view_chat_id = payload.get("immediate_view_chat_id", None)
                pending_message_ids = payload.get("pending_message_ids", {})
                
                await handle_initial_sync(
                    cache_service=cache_service,
                    directus_service=directus_service,
                    encryption_service=encryption_service,
                    manager=manager,
                    user_id=user_id,
                    device_fingerprint_hash=device_fingerprint_hash,
                    websocket=websocket,
                    client_chat_versions=client_chat_versions,
                    client_chat_ids=client_chat_ids,
                    client_chat_count=client_chat_count,
                    last_sync_timestamp=last_sync_timestamp,
                    immediate_view_chat_id=immediate_view_chat_id,
                    pending_message_ids=pending_message_ids
                )

            elif message_type == "update_draft":
                await handle_update_draft(
                    websocket=websocket,
                    manager=manager,
                    cache_service=cache_service,
                    directus_service=directus_service,
                    encryption_service=encryption_service,
                    user_id=user_id,
                    device_fingerprint_hash=device_fingerprint_hash,
                    payload=payload
                )
            elif message_type == "update_title":
                await handle_update_title(
                    websocket=websocket,
                    manager=manager,
                    cache_service=cache_service,
                    directus_service=directus_service,
                    encryption_service=encryption_service,
                    user_id=user_id,
                    device_fingerprint_hash=device_fingerprint_hash,
                    payload=payload
                )
            elif message_type == "sync_offline_changes":
                 await handle_sync_offline_changes(
                    websocket=websocket,
                    manager=manager,
                    cache_service=cache_service,
                    directus_service=directus_service,
                    encryption_service=encryption_service,
                    user_id=user_id,
                    device_fingerprint_hash=device_fingerprint_hash,
                    payload=payload
                 )
            elif message_type == "get_chat_messages":
                await handle_get_chat_messages(
                    websocket=websocket,
                    manager=manager,
                    directus_service=directus_service,
                    encryption_service=encryption_service,
                    user_id=user_id,
                    device_fingerprint_hash=device_fingerprint_hash,
                    payload=payload
                )
            
            elif message_type == "ping":
                await manager.send_personal_message({"type": "pong"}, user_id, device_fingerprint_hash)
            

            elif message_type == "chat_message_added":
                # This now handles new messages sent by the client.
                # The handler itself was refactored to include logic from the old handle_new_message.
                await handle_message_received(
                    websocket=websocket,
                    manager=manager,
                    cache_service=cache_service,
                    directus_service=directus_service, # Pass DirectusService
                    encryption_service=encryption_service,
                    user_id=user_id,
                    device_fingerprint_hash=device_fingerprint_hash,
                    payload=payload
                )

            elif message_type == "delete_chat":
                await handle_delete_chat(
                    websocket=websocket,
                    manager=manager,
                    cache_service=cache_service,
                    directus_service=directus_service, # Pass if needed by handler
                    encryption_service=encryption_service, # Pass if needed by handler
                    user_id=user_id,
                    device_fingerprint_hash=device_fingerprint_hash,
                    payload=payload
                )
            
            elif message_type == "request_cache_status":
                logger.debug(f"User {user_id}, Device {device_fingerprint_hash}: Received 'request_cache_status'.")
                try:
                    # Call the proper handler that returns both is_primed AND chat_count
                    await handle_sync_status_request(
                        websocket=websocket,
                        manager=manager,
                        cache_service=cache_service,
                        directus_service=directus_service,
                        encryption_service=encryption_service,
                        user_id=user_id,
                        device_fingerprint_hash=device_fingerprint_hash,
                        payload=payload
                    )
                except Exception as e_status_req:
                    logger.error(f"User {user_id}, Device {device_fingerprint_hash}: Error handling 'request_cache_status': {e_status_req}", exc_info=True)
                    try:
                        await manager.send_personal_message(
                            {"type": "error", "payload": {"message": "Failed to retrieve cache status."}},
                            user_id, device_fingerprint_hash
                        )
                    except Exception as send_err:
                        logger.error(f"User {user_id}, Device {device_fingerprint_hash}: Failed to send error for 'request_cache_status': {send_err}")

            elif message_type == "delete_draft":
                await handle_delete_draft(
                    websocket=websocket,
                    manager=manager,
                    cache_service=cache_service,
                    directus_service=directus_service,
                    user_id=user_id,
                    device_fingerprint_hash=device_fingerprint_hash,
                    payload=payload
                )
            elif message_type == "request_chat_content_batch":
                await handle_chat_content_batch(
                    cache_service=cache_service,
                    directus_service=directus_service,
                    encryption_service=encryption_service,
                    manager=manager,
                    user_id=user_id,
                    device_fingerprint_hash=device_fingerprint_hash,
                    payload=payload
                )
            elif message_type == "set_active_chat":
                active_chat_id = payload.get("chat_id") # Can be None to indicate no chat is active
                manager.set_active_chat(user_id, device_fingerprint_hash, active_chat_id)
                logger.debug(f"User {user_id}, Device {device_fingerprint_hash}: Set active chat to '{active_chat_id}'.")
                
                # Update user's last_opened field in Directus for Phase 1 sync
                # This ensures the last opened chat is synced first on next login/reload
                if active_chat_id:
                    # Only update if a real chat is selected (not None/"new chat")
                    try:
                        await directus_service.update_user(user_id, {"last_opened": active_chat_id})
                        logger.info(f"User {user_id}: Updated last_opened to chat {active_chat_id}")
                    except Exception as e:
                        logger.error(f"User {user_id}: Failed to update last_opened: {str(e)}")
                        # Don't fail the whole operation if Directus update fails
                else:
                    logger.debug(f"User {user_id}: Skipping last_opened update (no active chat)")
                
                # Send acknowledgement to client
                await manager.send_personal_message(
                    {"type": "active_chat_set_ack", "payload": {"chat_id": active_chat_id}},
                    user_id,
                    device_fingerprint_hash
                )
            elif message_type == "cancel_ai_task":
                await handle_cancel_ai_task(
                    websocket=websocket,
                    manager=manager,
                    user_id=user_id,
                    device_fingerprint_hash=device_fingerprint_hash,
                    payload=payload
                )
            elif message_type == "ai_response_completed":
                # Handle completed AI response sent by client for encrypted Directus storage
                await handle_ai_response_completed(
                    websocket=websocket,
                    manager=manager,
                    cache_service=cache_service,
                    directus_service=directus_service,
                    encryption_service=encryption_service,
                    user_id=user_id,
                    user_id_hash=user_id_hash,
                    device_fingerprint_hash=device_fingerprint_hash,
                    payload=payload
                )

            elif message_type == "encrypted_chat_metadata":
                # Handle encrypted chat metadata and user message storage
                # This is the SEPARATE handler for encrypted data after preprocessing
                await handle_encrypted_chat_metadata(
                    websocket=websocket,
                    manager=manager,
                    cache_service=cache_service,
                    directus_service=directus_service,
                    encryption_service=encryption_service,
                    user_id=user_id,
                    user_id_hash=user_id_hash,
                    device_fingerprint_hash=device_fingerprint_hash,
                    payload=payload
                )

            elif message_type == "update_post_processing_metadata":
                # Handle client-encrypted post-processing metadata sync to Directus
                # Client sends encrypted suggestions, summary, and tags after receiving plaintext
                await handle_post_processing_metadata(
                    websocket=websocket,
                    manager=manager,
                    cache_service=cache_service,
                    directus_service=directus_service,
                    encryption_service=encryption_service,
                    user_id=user_id,
                    user_id_hash=user_id_hash,
                    device_fingerprint_hash=device_fingerprint_hash,
                    payload=payload
                )

            elif message_type == "phased_sync_request":
                # Handle phased sync requests (Phase 1, 2, 3)
                await handle_phased_sync_request(
                    websocket=websocket,
                    manager=manager,
                    cache_service=cache_service,
                    directus_service=directus_service,
                    encryption_service=encryption_service,
                    user_id=user_id,
                    device_fingerprint_hash=device_fingerprint_hash,
                    payload=payload
                )

            elif message_type == "sync_status_request":
                # Handle sync status requests
                await handle_sync_status_request(
                    websocket=websocket,
                    manager=manager,
                    cache_service=cache_service,
                    directus_service=directus_service,
                    encryption_service=encryption_service,
                    user_id=user_id,
                    device_fingerprint_hash=device_fingerprint_hash,
                    payload=payload
                )

            elif message_type == "app_settings_memories_confirmed":
                # Handle app settings/memories confirmation from client
                # Client sends decrypted data when user confirms, server encrypts and caches
                await handle_app_settings_memories_confirmed(
                    websocket=websocket,
                    manager=manager,
                    cache_service=cache_service,
                    directus_service=directus_service,
                    encryption_service=encryption_service,
                    user_id=user_id,
                    device_fingerprint_hash=device_fingerprint_hash,
                    payload=payload
                )

            elif message_type == "scroll_position_update":
                # Handle scroll position updates
                chat_id = payload.get("chat_id")
                message_id = payload.get("message_id")
                
                if not chat_id or not message_id:
                    logger.warning(f"Invalid scroll_position_update payload from user {user_id}")
                    continue
                
                # Update Redis cache immediately
                try:
                    await cache_service.update_chat_scroll_position(
                        user_id=user_id,
                        chat_id=chat_id,
                        message_id=message_id
                    )
                    logger.debug(f"User {user_id}: Updated scroll position for chat {chat_id} to message {message_id}")
                except Exception as e:
                    logger.error(f"User {user_id}: Failed to update scroll position: {str(e)}")

            elif message_type == "chat_read_status_update":
                # Handle read status updates
                chat_id = payload.get("chat_id")
                unread_count = payload.get("unread_count", 0)
                
                if not chat_id:
                    logger.warning(f"Invalid chat_read_status_update payload from user {user_id}")
                    continue
                
                # Update Redis cache and Directus immediately for read status (important for badges)
                try:
                    await cache_service.update_chat_read_status(
                        user_id=user_id,
                        chat_id=chat_id,
                        unread_count=unread_count
                    )
                    
                    # Update Directus immediately for read status (important for badges)
                    await directus_service.chat.update_chat_read_status(
                        chat_id=chat_id,
                        unread_count=unread_count
                    )
                    
                    logger.info(f"User {user_id}: Updated read status for chat {chat_id}: unread_count = {unread_count}")
                except Exception as e:
                    logger.error(f"User {user_id}: Failed to update read status: {str(e)}")

            else:
                logger.warning(f"Received unknown message type from {user_id}/{device_fingerprint_hash}: {message_type}")


    except WebSocketDisconnect as e:
        # Disconnect handled by the manager now
        disconnect_reason_str = f"Client closed connection - Code: {e.code}, Reason: {e.reason if e.reason else 'No reason provided'}"
        logger.debug(f"WebSocket connection closed for User {user_id}, Device {device_fingerprint_hash}. {disconnect_reason_str}")
        # Ensure manager.disconnect(websocket) is called if the exception originates from receive_json or an explicit client close.
        # The manager's disconnect method now handles the grace period.
        manager.disconnect(websocket, reason=disconnect_reason_str)

    except Exception as e:
        # Log unexpected errors during communication
        logger.error(f"Unexpected WebSocket error for User {user_id}, Device {device_fingerprint_hash}: {e}", exc_info=True)
        # Attempt to close gracefully if possible, although the connection might already be broken
        # Provide a reason for the disconnect call
        unexpected_error_reason = f"Unexpected server error: {type(e).__name__}"
        try:
            # Try to inform the client about an internal error before closing from server-side.
            # This might fail if the connection is already too broken.
            # Check websocket state before attempting to close
            if hasattr(websocket, 'client_state') and hasattr(websocket.client_state, 'DISCONNECTED'): # Check if attributes exist
                if websocket.client_state != websocket.client_state.DISCONNECTED:
                    await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="Internal server error")
                    logger.debug(f"Sent close frame to User {user_id}, Device {device_fingerprint_hash} due to unexpected error.")
            else: # Fallback if client_state is not available as expected
                logger.warning(f"WebSocket client_state attribute not found as expected for User {user_id}, Device {device_fingerprint_hash}. Proceeding with disconnect without sending close frame.")

        except Exception as close_exc:
            logger.warning(f"Error attempting to send close frame to User {user_id}, Device {device_fingerprint_hash} after unexpected error: {close_exc}")
        finally:
            # Ensure cleanup happens even with unexpected errors, passing the reason.
            manager.disconnect(websocket, reason=unexpected_error_reason)

# Note: Fingerprint and device cache logic now correctly uses imported utility functions
