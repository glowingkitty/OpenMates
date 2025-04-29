import asyncio
import logging
import time
import uuid # <-- Add import
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Request, HTTPException, status, Cookie
from typing import List, Dict, Any, Optional, Tuple # Added Tuple

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
# Import device fingerprint utils
from app.utils.device_fingerprint import get_websocket_device_fingerprint, get_websocket_client_ip, get_location_from_ip
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
from .handlers.initial_sync import handle_initial_sync


manager = ConnectionManager()

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

    # --- Helper function to extract title from draft content ---
    def _extract_title_from_draft_content(content: Any, max_length: int = 50) -> str:
        """Extracts a title snippet from TipTap JSON content."""
        if not content or not isinstance(content, dict):
            return "New Chat"
        try:
            # Find first text node in the document structure
            first_text_node = content.get('content', [{}])[0].get('content', [{}])[0]
            if first_text_node and first_text_node.get('type') == 'text':
                text = first_text_node.get('text', '')
                return text[:max_length] + ('...' if len(text) > max_length else '')
        except (IndexError, KeyError, TypeError) as e:
            logger.warning(f"Error extracting title from draft content: {e}. Content: {str(content)[:100]}...")
        return "New Chat" # Default title if extraction fails
    # user_data = auth_data["user_data"] # Full user data available if needed

    await manager.connect(websocket, user_id, device_fingerprint_hash)

    try:
        # --- Send REAL initial sync data (Cache-First Approach) ---
        await handle_initial_sync(
            cache_service=cache_service,
            directus_service=directus_service,
            encryption_service=encryption_service,
            manager=manager,
            user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash,
            websocket=websocket
        )
        # --- End initial sync data ---

        while True:
            data = await websocket.receive_json()
            logger.debug(f"Received message from User {user_id}, Device {device_fingerprint_hash}: {data}")

            message_type = data.get("type")
            payload = data.get("payload", {})

            # Process different message types
            if message_type == "draft_update":
                chat_id = payload.get("chatId") # Will be None for a new chat
                draft_id = payload.get("draftId") # Should be present even for new chats
                content = payload.get("content")
                based_on_version = payload.get("basedOnVersion") # Should be None or 0 for new chats

                if not draft_id or content is None: # Check only essential fields for both cases
                    logger.warning(f"Received invalid draft_update from {user_id}/{device_fingerprint_hash}: Missing draftId or content.")
                    await manager.send_personal_message(
                        {"type": "error", "payload": {"message": "Invalid draft_update payload: Missing draftId or content"}},
                        user_id, device_fingerprint_hash
                    )
                    continue

                if chat_id is None:
                    # --- Handle new chat draft with encryption, Vault, and correct ID format ---
                    logger.info(f"Received draft for a new chat from {user_id}/{device_fingerprint_hash}. Generating new chat ID and Vault key.")

                    import hashlib
                    temp_chat_id = payload.get("tempChatId") or draft_id or str(uuid.uuid4())
                    hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
                    new_chat_id = f"{hashed_user_id[:8]}_{temp_chat_id}"

                    # 1. Create a Vault key for this chat (id = new_chat_id)
                    vault_key_reference = new_chat_id
                    vault_key_created = await encryption_service.create_chat_key(vault_key_reference)
                    if not vault_key_created:
                        logger.error(f"Failed to create Vault key for chat {new_chat_id}")
                        await manager.send_personal_message(
                            {
                                "type": "error",
                                "payload": {
                                    "message": "Failed to create encryption key for new chat.",
                                    "draftId": draft_id
                                }
                            },
                            user_id,
                            device_fingerprint_hash
                        )
                        continue

                    # 2. Encrypt draft content and title
                    import json
                    draft_json = json.dumps(content)
                    encrypted_draft, _ = await encryption_service.encrypt_with_chat_key(draft_json, vault_key_reference)
                    # Extract title from draft content
                    title = _extract_title_from_draft_content(content)
                    encrypted_title, _ = await encryption_service.encrypt_with_chat_key(title, vault_key_reference)

                    # 3. Prepare chat metadata for cache
                    now_ts = int(time.time())
                    chat_metadata = {
                        "id": new_chat_id,
                        "hashed_user_id": hashed_user_id,
                        "vault_key_reference": vault_key_reference,
                        "encrypted_title": encrypted_title,
                        "encrypted_draft": encrypted_draft,
                        "version": 1,
                        "created_at": now_ts,
                        "updated_at": now_ts,
                        "last_message_timestamp": None
                    }

                    # 4. Store chat metadata in cache (Dragonfly)
                    await cache_service.set_chat_metadata(new_chat_id, chat_metadata)

                    # 5. Store draft in cache (for quick lookup by draft id if needed)
                    draft_cache_key = cache_service._get_draft_key(user_id, new_chat_id, draft_id)
                    draft_cache_value = {
                        "content": content,
                        "version": 1,
                        "lastUpdated": now_ts
                    }
                    await cache_service.set_draft(user_id, new_chat_id, draft_id, draft_cache_value)

                    logger.info(f"New chat draft {draft_id} saved successfully for chat {new_chat_id}, version 1 by {user_id}/{device_fingerprint_hash}")

                    # 6. Broadcast 'draft_updated' to ALL devices (including sender) with the NEW chat_id
                    # Use DraftUpdateRequestData for payload
                    draft_update_payload = DraftUpdateRequestData(
                        tempChatId=None,
                        chatId=new_chat_id,
                        content=content,
                        basedOnVersion=1
                    )
                    await manager.broadcast_to_user(
                        {
                            "type": "draft_updated",
                            "payload": draft_update_payload.dict()
                        },
                        user_id,
                        exclude_device_hash=None
                    )

                    # 7. Broadcast 'activity_history_update' to sync the new chat stub
                    # Use ChatResponse for chat payload
                    chat_response = ChatResponse(
                        id=new_chat_id,
                        title=title,
                        draft=content,
                        version=1,
                        created_at=now_ts,
                        updated_at=now_ts,
                        last_message_timestamp=None,
                        messages=[]
                    )
                    await manager.broadcast_to_user(
                        {
                            "type": "activity_history_update",
                            "payload": {
                                "type": "chat_added",
                                "chat": chat_response.dict()
                            }
                        },
                        user_id,
                        exclude_device_hash=None
                    )

                else:
                    # --- Handle existing chat draft update ---
                    if based_on_version is None: # Should have a version if chat_id exists
                         logger.warning(f"Received draft_update for existing chat {chat_id} without basedOnVersion from {user_id}/{device_fingerprint_hash}. Rejecting.")
                         await manager.send_personal_message(
                             {"type": "error", "payload": {"message": "Missing basedOnVersion for existing chat draft update", "chatId": chat_id, "draftId": draft_id}},
                             user_id, device_fingerprint_hash
                         )
                         continue

                    # --- Encrypt draft content and update chat metadata in cache ---
                    import json
                    chat_meta_key = f"chat:{chat_id}:metadata"
                    chat_metadata = await cache_service.get(chat_meta_key)
                    if not chat_metadata or not isinstance(chat_metadata, dict):
                        logger.error(f"Chat metadata not found in cache for chat_id {chat_id} (user {user_id})")
                        await manager.send_personal_message(
                            {"type": "error", "payload": {"message": "Chat metadata not found for draft update", "chatId": chat_id, "draftId": draft_id}},
                            user_id, device_fingerprint_hash
                        )
                        continue

                    vault_key_reference = chat_metadata.get("vault_key_reference")
                    if not vault_key_reference:
                        logger.error(f"Vault key reference missing in chat metadata for chat_id {chat_id}")
                        await manager.send_personal_message(
                            {"type": "error", "payload": {"message": "Encryption key missing for chat", "chatId": chat_id, "draftId": draft_id}},
                            user_id, device_fingerprint_hash
                        )
                        continue

                    draft_json = json.dumps(content)
                    encrypted_draft, _ = await encryption_service.encrypt_with_chat_key(draft_json, vault_key_reference)

                    # Attempt to update the draft using the cache service (optimistic locking)
                    update_result = await cache_service.update_draft_content(
                        user_id=user_id,
                        chat_id=chat_id,
                        draft_id=draft_id,
                        content=content,
                        expected_version=based_on_version,
                    )

                    if isinstance(update_result, int): # Success, returns new version number
                        new_version = update_result
                        now_ts = int(time.time())
                        # Update chat metadata in cache with new encrypted draft and updated_at/version
                        chat_metadata["encrypted_draft"] = encrypted_draft
                        chat_metadata["updated_at"] = now_ts
                        chat_metadata["version"] = new_version
                        await cache_service.set_chat_metadata(chat_id, chat_metadata)

                        # Update draft cache entry (for quick lookup by draft id)
                        draft_cache_key = cache_service._get_draft_key(user_id, chat_id, draft_id)
                        draft_cache_value = {
                            "content": content,
                            "version": new_version,
                            "lastUpdated": now_ts
                        }
                        await cache_service.set_draft(user_id, chat_id, draft_id, draft_cache_value)

                        logger.info(f"Draft {draft_id} for chat {chat_id} updated successfully to version {new_version} by {user_id}/{device_fingerprint_hash}")
                        # Broadcast the update to other devices of the same user
                        await manager.broadcast_to_user(
                            {
                                "type": "draft_updated",
                                "payload": DraftUpdateRequestData(
                                    tempChatId=None,
                                    chatId=chat_id,
                                    content=content,
                                    basedOnVersion=new_version
                                ).dict()
                            },
                            user_id,
                            exclude_device_hash=device_fingerprint_hash # Exclude sender
                        )
                        # Send confirmation back to sender including the new version
                        await manager.send_personal_message(
                             {
                                "type": "draft_updated", # Send confirmation back to sender too
                                "payload": DraftUpdateRequestData(
                                    tempChatId=None,
                                    chatId=chat_id,
                                    content=content,
                                    basedOnVersion=new_version
                                ).dict()
                            },
                            user_id,
                            device_fingerprint_hash
                        )
                    elif update_result is False: # Conflict or other cache error
                        logger.warning(f"Draft update conflict or error for {user_id}/{device_fingerprint_hash} on draft {draft_id} (Chat: {chat_id}). Expected version: {based_on_version}")
                        # Send conflict message back to the originating client
                        await manager.send_personal_message(
                            {
                                "type": "draft_conflict",
                                "payload": {
                                    "chatId": chat_id,
                                    "draftId": draft_id
                                }
                            },
                            user_id,
                            device_fingerprint_hash
                        )
                    # Handle True case? update_draft_content currently doesn't return True.

            elif message_type == "ping":
                await manager.send_personal_message({"type": "pong"}, user_id, device_fingerprint_hash)

            # --- Placeholder Handlers for Other Message Types ---

            elif message_type == "chat_message_update":
                # TODO: Handle real-time streaming updates for an open chat
                # - Likely involves checking if the user/device has this chat open
                # - Forwarding updates received from LLM processing (e.g., via Redis Pub/Sub or another mechanism)
                logger.info(f"Placeholder: Received chat_message_update from {user_id}/{device_fingerprint_hash}: {payload}")
                # Example broadcast (adjust based on actual logic):
                # await manager.broadcast_to_user(data, user_id) # Or send only to specific devices?

            elif message_type == "chat_message_received":
                # Handle receiving a full new message (for background chats)
                logger.info(f"Received chat_message_received from {user_id}/{device_fingerprint_hash}: {payload}")

                chat_id = payload.get("chatId")
                message_content = payload.get("content")
                sender_name = payload.get("sender_name")
                created_at = payload.get("created_at")
                message_id = payload.get("message_id")
                encrypted_content = payload.get("encrypted_content")
                # Additional fields as needed

                # 1. Check if chat exists in Directus
                chat_in_directus = await get_chat_metadata(directus_service, chat_id)
                if not chat_in_directus:
                    # Fetch chat metadata from cache to persist
                    chat_meta_key = f"chat:{chat_id}:metadata"
                    chat_metadata = await cache_service.get(chat_meta_key)
                    if chat_metadata:
                        await create_chat_in_directus(directus_service, chat_metadata)
                        # Optionally, refresh cache here if needed

                # 2. Create the message in Directus
                message_data = {
                    "id": message_id,
                    "chat_id": chat_id,
                    "encrypted_content": encrypted_content,
                    "sender_name": sender_name,
                    "created_at": created_at
                }
                await create_message_in_directus(directus_service, message_data)

                # 3. Invalidate/refresh cache as needed (handled in create_* methods)

                # 4. Broadcast the new message to all user devices (except sender)
                await manager.broadcast_to_user(
                    {
                        "type": "chat_message_received",
                        "payload": payload  # You may want to use a Pydantic model here
                    },
                    user_id,
                    exclude_device_hash=device_fingerprint_hash
                )

            elif message_type == "chat_added":
                # TODO: Handle notification that a new chat was added (likely triggered by backend action)
                # - This handler might not be needed if 'chat_added' is only broadcast FROM the server
                # - If clients can trigger this, validate and persist, then broadcast.
                logger.info(f"Placeholder: Received chat_added from {user_id}/{device_fingerprint_hash}: {payload}")
                # Example broadcast (if server initiates):
                # await manager.broadcast_to_user({"type": "chat_added", "payload": new_chat_data}, user_id)

            elif message_type == "chat_deleted":
                # TODO: Handle notification that a chat was deleted (likely triggered by backend action)
                # - Similar to chat_added, might only be broadcast FROM server.
                # - If clients trigger, validate, delete from DB/cache, then broadcast.
                logger.info(f"Placeholder: Received chat_deleted from {user_id}/{device_fingerprint_hash}: {payload}")
                # Example broadcast (if server initiates):
                # await manager.broadcast_to_user({"type": "chat_deleted", "payload": {"chatId": deleted_chat_id}}, user_id)

            elif message_type == "chat_metadata_updated":
                # TODO: Handle notification that chat metadata (title, settings) was updated
                # - Similar to chat_added, might only be broadcast FROM server after validation.
                # - Needs versioning check if triggered by chat_update_request.
                logger.info(f"Placeholder: Received chat_metadata_updated from {user_id}/{device_fingerprint_hash}: {payload}")
                # Example broadcast (if server initiates after update):
                # await manager.broadcast_to_user(
                #     {"type": "chat_metadata_updated", "payload": updated_metadata_with_version},
                #     user_id
                # )

            elif message_type == "chat_update_request":
                # TODO: Handle client request to update chat metadata (e.g., title)
                # - Requires version checking against DB/cache.
                # - Fetch current metadata + version.
                # - Compare basedOnVersion from payload.
                # - On match: Update DB/cache, increment version, broadcast 'chat_metadata_updated'.
                # - On mismatch: Send 'chat_metadata_conflict' back to sender.
                logger.info(f"Placeholder: Received chat_update_request from {user_id}/{device_fingerprint_hash}: {payload}")
                # Example conflict response:
                # await manager.send_personal_message(
                #     {"type": "chat_metadata_conflict", "payload": {"chatId": payload.get("chatId")}},
                #     user_id, device_fingerprint_hash
                # )

            # --- End Placeholder Handlers ---

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