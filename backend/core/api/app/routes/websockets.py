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
                # Use DraftUpdateRequestData for validation and access
                try:
                    # Assuming DraftUpdateRequestData is updated to:
                    # client_id: str (UUID from client, replaces tempChatId)
                    # user_hash_suffix: Optional[str] (10-char server hash if known by client for existing chat)
                    # content: Optional[Dict[str, Any]]
                    # basedOnVersion: int
                    draft_data = DraftUpdateRequestData(**payload)
                except Exception as e: # Catch Pydantic validation errors
                    logger.warning(f"Received invalid draft_update payload from {user_id}/{device_fingerprint_hash}: {e}")
                    await manager.send_personal_message(
                        {"type": "error", "payload": {"message": f"Invalid draft_update payload: {e}"}},
                        user_id, device_fingerprint_hash
                    )
                    continue

                client_uuid = draft_data.client_id # This is the UUID from the client
                content = draft_data.content
                based_on_version = draft_data.basedOnVersion
                user_hash_suffix_from_payload = draft_data.user_hash_suffix # This will be None for new chats

                if not client_uuid:
                     logger.warning(f"Received invalid draft_update from {user_id}/{device_fingerprint_hash}: Missing client_id.")
                     await manager.send_personal_message(
                         {"type": "error", "payload": {"message": "Invalid draft_update: Missing client_id"}},
                         user_id, device_fingerprint_hash
                     )
                     continue

                if user_hash_suffix_from_payload is None: # Indicates a new chat
                    # --- Handle new chat draft ---
                    logger.info(f"Received draft for a new chat (client UUID: {client_uuid}) from {user_id}/{device_fingerprint_hash}.")

                    import hashlib
                    hashed_user_id_full = hashlib.sha256(user_id.encode()).hexdigest()
                    server_generated_user_hash_suffix = hashed_user_id_full[-10:]
                    server_chat_id = f"{server_generated_user_hash_suffix}_{client_uuid}" # Server's composite ID

                    # 1. Create a Vault key for this chat
                    vault_key_reference = server_chat_id
                    vault_key_created = await encryption_service.create_chat_key(vault_key_reference)
                    if not vault_key_created:
                        logger.error(f"Failed to create Vault key for chat {server_chat_id}")
                        await manager.send_personal_message(
                            {"type": "error", "payload": {"message": "Failed to create encryption key for new chat.", "id": client_uuid }}, # Return client's UUID
                            user_id, device_fingerprint_hash
                        )
                        continue

                    # 2. Encrypt draft content and title
                    import json
                    draft_json = json.dumps(content)
                    encrypted_draft, _ = await encryption_service.encrypt_with_chat_key(draft_json, vault_key_reference)
                    encrypted_title, _ = await encryption_service.encrypt_with_chat_key("", vault_key_reference) # Empty title for new

                    # 3. Prepare chat metadata for cache
                    now_ts = int(time.time())
                    chat_metadata = {
                        "id": server_chat_id, # Server's composite ID
                        "client_uuid": client_uuid, # Store client's original UUID
                        "user_hash_suffix": server_generated_user_hash_suffix, # Store the 10-char suffix
                        "hashed_user_id": hashed_user_id_full,
                        "vault_key_reference": vault_key_reference,
                        "encrypted_title": encrypted_title,
                        "encrypted_draft": encrypted_draft,
                        "version": 1,
                        "created_at": now_ts,
                        "updated_at": now_ts,
                        "last_message_timestamp": None
                    }

                    # 4. Store chat metadata in cache
                    await cache_service.set_chat_metadata(server_chat_id, chat_metadata)
                    logger.info(f"New chat {server_chat_id} (client UUID: {client_uuid}) metadata and initial draft saved to cache, version 1 by {user_id}/{device_fingerprint_hash}")

                    # 5. Broadcast 'draft_updated'
                    # Payload: chatId (server_chat_id), id (client_uuid), user_id (suffix), content, basedOnVersion (new version)
                    draft_update_broadcast_payload = {
                        "chatId": server_chat_id,
                        "id": client_uuid,
                        "user_id": server_generated_user_hash_suffix,
                        "content": content,
                        "basedOnVersion": 1 # New version
                    }
                    await manager.broadcast_to_user(
                        {"type": "draft_updated", "payload": draft_update_broadcast_payload},
                        user_id, exclude_device_hash=None
                    )

                    # 6. Broadcast 'activity_history_update'
                    # ChatResponse payload: id (client_uuid), user_id (suffix), title, draft, version, timestamps
                    # Assuming ChatResponse model is updated to include user_id
                    chat_response_data = ChatResponse(
                        id=client_uuid,
                        user_id=server_generated_user_hash_suffix,
                        title="", # Empty for new draft
                        draft=content,
                        version=1,
                        created_at=now_ts,
                        updated_at=now_ts,
                        last_message_timestamp=None,
                        messages=[]
                    ).model_dump(mode='json')

                    await manager.broadcast_to_user(
                        {"type": "activity_history_update", "payload": {"type": "chat_added", "chat": chat_response_data}},
                        user_id, exclude_device_hash=None
                    )

                else: # Existing chat, user_hash_suffix_from_payload is present
                    # --- Handle existing chat draft update ---
                    server_chat_id = f"{user_hash_suffix_from_payload}_{client_uuid}"
                    logger.info(f"Received draft update for existing chat (server ID: {server_chat_id}, client UUID: {client_uuid}) from {user_id}/{device_fingerprint_hash}.")

                    import json
                    chat_meta_key = f"chat:{server_chat_id}:metadata"
                    chat_metadata = await cache_service.get(chat_meta_key)
                    metadata_reconstructed = False

                    if not chat_metadata or not isinstance(chat_metadata, dict):
                        logger.warning(f"Chat metadata not found in cache for server_chat_id {server_chat_id}. Attempting reconstruction.")
                        try:
                            directus_chat_data = await get_chat_metadata(directus_service, server_chat_id)
                            if directus_chat_data:
                                logger.info(f"Found chat {server_chat_id} in Directus. Reconstructing cache metadata.")
                                chat_metadata = {
                                    "id": directus_chat_data.get("id"), # server_chat_id
                                    "client_uuid": client_uuid, # Add client_uuid
                                    "user_hash_suffix": user_hash_suffix_from_payload, # Add suffix
                                    "hashed_user_id": directus_chat_data.get("hashed_user_id"),
                                    "vault_key_reference": directus_chat_data.get("vault_key_reference"),
                                    "encrypted_title": directus_chat_data.get("encrypted_title"),
                                    "encrypted_draft": None, # Will be set by current update
                                    "version": directus_chat_data.get("version", 0),
                                    "created_at": int(directus_chat_data.get("created_at").timestamp()) if directus_chat_data.get("created_at") else int(time.time()),
                                    "updated_at": int(time.time()),
                                    "last_message_timestamp": int(directus_chat_data.get("last_message_timestamp").timestamp()) if directus_chat_data.get("last_message_timestamp") else None,
                                }
                                if not chat_metadata.get("id") or not chat_metadata.get("vault_key_reference"):
                                    logger.error(f"Failed to reconstruct essential metadata for chat {server_chat_id}.")
                                    chat_metadata = None
                                else:
                                    metadata_reconstructed = True
                            else:
                                logger.error(f"Chat {server_chat_id} not found in Directus. Cannot process draft update.")
                                chat_metadata = None
                        except Exception as e:
                            logger.error(f"Error fetching/reconstructing chat {server_chat_id}: {e}", exc_info=True)
                            chat_metadata = None

                        if not chat_metadata:
                            await manager.send_personal_message(
                                {"type": "error", "payload": {"message": "Chat not found or failed to reconstruct.", "chatId": server_chat_id, "id": client_uuid}},
                                user_id, device_fingerprint_hash)
                            continue

                    vault_key_reference = chat_metadata.get("vault_key_reference")
                    if not vault_key_reference:
                        logger.error(f"Vault key reference missing for chat_id {server_chat_id}")
                        await manager.send_personal_message(
                            {"type": "error", "payload": {"message": "Encryption key missing for chat.", "chatId": server_chat_id, "id": client_uuid}},
                            user_id, device_fingerprint_hash)
                        continue

                    encrypted_new_title = chat_metadata.get("encrypted_title") # Keep existing title
                    draft_json = json.dumps(content)
                    encrypted_draft, _ = await encryption_service.encrypt_with_chat_key(draft_json, vault_key_reference)

                    cache_updated = False
                    new_version = -1

                    if metadata_reconstructed:
                        new_version = based_on_version + 1
                        now_ts = int(time.time())
                        chat_metadata["encrypted_draft"] = encrypted_draft
                        chat_metadata["encrypted_title"] = encrypted_new_title
                        chat_metadata["updated_at"] = now_ts
                        chat_metadata["version"] = new_version
                        await cache_service.set_chat_metadata(server_chat_id, chat_metadata)
                        cache_updated = True
                        logger.info(f"Reconstructed metadata for chat {server_chat_id} saved to cache, new version {new_version}.")
                    else:
                        encrypted_draft_str = json.dumps(encrypted_draft)
                        update_result = await cache_service.update_chat_draft(
                            chat_id=server_chat_id,
                            encrypted_draft=encrypted_draft_str,
                            expected_version=based_on_version,
                        )
                        if isinstance(update_result, int):
                            new_version = update_result
                            now_ts = int(time.time())
                            chat_metadata["encrypted_draft"] = encrypted_draft # Already updated by update_chat_draft
                            chat_metadata["encrypted_title"] = encrypted_new_title
                            chat_metadata["updated_at"] = now_ts
                            chat_metadata["version"] = new_version # Already updated by update_chat_draft
                            await cache_service.set_chat_metadata(server_chat_id, chat_metadata) # Ensure other fields like title/ts are set
                            cache_updated = True
                            logger.info(f"Draft for chat {server_chat_id} updated to version {new_version} by {user_id}/{device_fingerprint_hash}")
                        elif update_result is False:
                            logger.warning(f"Draft update conflict for {user_id}/{device_fingerprint_hash} on chat {server_chat_id}. Expected: {based_on_version}")
                            await manager.send_personal_message(
                                {"type": "draft_conflict", "payload": {"chatId": server_chat_id, "id": client_uuid}},
                                user_id, device_fingerprint_hash)

                    if cache_updated and new_version != -1:
                        draft_update_broadcast_payload = {
                            "chatId": server_chat_id,
                            "id": client_uuid,
                            "user_id": user_hash_suffix_from_payload,
                            "content": content,
                            "basedOnVersion": new_version
                        }
                        await manager.broadcast_to_user(
                            {"type": "draft_updated", "payload": draft_update_broadcast_payload},
                            user_id, exclude_device_hash=None
                        )

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

            elif message_type == "delete_chat":
                chat_id = payload.get("chatId")
                if not chat_id:
                    logger.warning(f"Received delete_chat without chatId from {user_id}/{device_fingerprint_hash}")
                    await manager.send_personal_message(
                        {"type": "error", "payload": {"message": "Missing chatId for delete_chat"}},
                        user_id, device_fingerprint_hash
                    )
                    continue

                logger.info(f"Received delete_chat request for chat {chat_id} from {user_id}/{device_fingerprint_hash}")

                try:
                    # Attempt to delete chat metadata from cache
                    # Assuming cache_service has a method like delete_chat_metadata or a generic delete
                    # Using a generic delete pattern here for broader compatibility
                    cache_key = f"chat:{chat_id}:metadata"
                    deleted_count = await cache_service.delete(cache_key) # delete returns number of keys deleted (0 or 1)

                    if deleted_count > 0:
                        logger.info(f"Deleted chat metadata for chat {chat_id} from cache (key: {cache_key}).")
                    else:
                        # This might happen if the chat was already deleted or never existed in cache
                        logger.info(f"Chat metadata for chat {chat_id} not found in cache or already deleted (key: {cache_key}).")

                    # Broadcast deletion confirmation regardless of cache state to ensure UI consistency
                    await manager.broadcast_to_user(
                        {
                            "type": "chat_deleted",
                            "payload": {"chatId": chat_id}
                        },
                        user_id,
                        exclude_device_hash=None # Send to all devices, including sender
                    )

                except Exception as e:
                    logger.error(f"Error deleting chat {chat_id} from cache for {user_id}/{device_fingerprint_hash}: {e}", exc_info=True)
                    await manager.send_personal_message(
                        {"type": "error", "payload": {"message": f"Failed to delete chat {chat_id} from cache", "chatId": chat_id}},
                        user_id, device_fingerprint_hash
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