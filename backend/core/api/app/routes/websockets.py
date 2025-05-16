import logging
import time
import hashlib
import json
import asyncio # Added asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Request, HTTPException, status, Cookie, FastAPI, Response as FastAPIResponse
from typing import List, Dict, Any, Optional, Tuple

# Import necessary services and utilities
from app.services.cache import CacheService
from app.services.directus import DirectusService
from app.utils.encryption import EncryptionService # <-- Add EncryptionService import
from app.services.directus.chat_methods import create_chat_in_directus, create_message_in_directus, get_chat_metadata
from app.schemas.chat import (
    MessageBase, ChatBase, MessageInDB, ChatInDB, MessageInCache,
    MessageResponse, ChatResponse, DraftUpdateRequestData,
    WebSocketMessage, ChatInitiatedPayload, NewMessagePayload
)
# Import device cache utils
from app.utils.device_cache import check_device_in_cache, store_device_in_cache
from app.routes.auth_routes.auth_dependencies import get_cache_service, get_directus_service # Use existing dependencies

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
# Removed: from .handlers.websocket_handlers.message_handler import handle_new_message
# handle_message_received now handles new messages sent by clients.
from .handlers.websocket_handlers.delete_draft_handler import handle_delete_draft # Add new handler

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
    logger.info("Starting Redis Pub/Sub listener for cache events...")
    
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
                    logger.info(f"Redis Listener: Received '{event_type}' for user {user_id}. Payload: {payload}")

                    if event_type == "priority_chat_ready":
                        await manager.broadcast_to_user_specific_event(
                            user_id=user_id,
                            event_name="priority_chat_ready",
                            payload=payload
                        )
                        logger.info(f"Redis Listener: Sent 'priority_chat_ready' WebSocket to user {user_id}.")
                    elif event_type == "cache_primed":
                        await manager.broadcast_to_user_specific_event(
                            user_id=user_id,
                            event_name="cache_primed",
                            payload=payload
                        )
                        logger.info(f"Redis Listener: Sent 'cache_primed' WebSocket to user {user_id}.")
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

# Authentication logic is now in auth_ws.py
@router.websocket("")
async def websocket_endpoint(
    websocket: WebSocket,
    auth_data: dict = Depends(get_current_user_ws),
):
    # Access services directly from websocket state
    cache_service: CacheService = websocket.app.state.cache_service
    directus_service: DirectusService = websocket.app.state.directus_service # <-- Get DirectusService
    encryption_service: EncryptionService = websocket.app.state.encryption_service # <-- Get EncryptionService
    user_id = auth_data["user_id"]
    device_fingerprint_hash = auth_data["device_fingerprint_hash"]

    logger.info("WebSocket connection established and authenticated for user")
    await manager.connect(websocket, user_id, device_fingerprint_hash)

    try:
        while True:
            data = await websocket.receive_json()
            logger.debug(f"Received message from User {user_id}, Device {device_fingerprint_hash}: {data}")

            message_type = data.get("type")
            payload = data.get("payload", {})

            # Process different message types
            if message_type == "initial_sync_request":
                logger.info(f"Received initial_sync_request from {user_id}/{device_fingerprint_hash}")
                client_chat_versions = payload.get("chat_versions", {})
                await handle_initial_sync(
                    cache_service=cache_service,
                    directus_service=directus_service,
                    encryption_service=encryption_service,
                    manager=manager,
                    user_id=user_id,
                    device_fingerprint_hash=device_fingerprint_hash,
                    websocket=websocket,
                    client_chat_versions=client_chat_versions # Pass the versions
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
                logger.info(f"User {user_id}, Device {device_fingerprint_hash}: Received 'request_cache_status'.")
                try:
                    # cache_service is already available from line 109
                    is_primed = await cache_service.is_user_cache_primed(user_id)
                    await manager.send_personal_message(
                        message={"type": "cache_status_response", "payload": {"is_primed": is_primed}},
                        user_id=user_id,
                        device_fingerprint_hash=device_fingerprint_hash
                    )
                    logger.info(f"User {user_id}, Device {device_fingerprint_hash}: Sent 'cache_status_response', is_primed: {is_primed}.")
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
                    directus_service=directus_service,
                    user_id=user_id,
                    device_fingerprint_hash=device_fingerprint_hash,
                    payload=payload
                )
            else:
                logger.warning(f"Received unknown message type from {user_id}/{device_fingerprint_hash}: {message_type}")
                # Optionally send an error back to the client
                # await manager.send_personal_message(
                #     {"type": "error", "payload": {"message": f"Unknown message type: {message_type}"}},
                #     user_id,
                #     device_fingerprint_hash
                # )


    except WebSocketDisconnect as e:
        # Disconnect handled by the manager now
        logger.info(f"WebSocket connection closed for User {user_id}, Device {device_fingerprint_hash}. Reason: {e.reason} (Code: {e.code})")
        # No need to call manager.disconnect here if it's called within send/broadcast errors
        # Ensure manager.disconnect(websocket) is called if the exception originates from receive_json
        manager.disconnect(websocket)

    except Exception as e:
        # Log unexpected errors during communication
        logger.error(f"WebSocket error for User {user_id}, Device {device_fingerprint_hash}: {e}", exc_info=True)
        # Attempt to close gracefully if possible, although the connection might already be broken
        try:
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        except Exception:
            pass # Ignore errors during close after another error occurred
        finally:
            # Ensure cleanup happens even with unexpected errors
            manager.disconnect(websocket)

# Note: Fingerprint and device cache logic now correctly uses imported utility functions