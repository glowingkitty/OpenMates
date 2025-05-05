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
                    draft_data = DraftUpdateRequestData(**payload)
                except Exception as e: # Catch Pydantic validation errors
                    logger.warning(f"Received invalid draft_update payload from {user_id}/{device_fingerprint_hash}: {e}")
                    await manager.send_personal_message(
                        {"type": "error", "payload": {"message": f"Invalid draft_update payload: {e}"}},
                        user_id, device_fingerprint_hash
                    )
                    continue

                chat_id = draft_data.chatId
                temp_chat_id = draft_data.tempChatId # Use validated tempChatId
                content = draft_data.content
                based_on_version = draft_data.basedOnVersion # Will be 0 for new chats if client sends it

                # Validate based on new/existing chat logic
                if chat_id is None and temp_chat_id is None:
                     logger.warning(f"Received invalid draft_update from {user_id}/{device_fingerprint_hash}: Missing chatId or tempChatId.")
                     await manager.send_personal_message(
                         {"type": "error", "payload": {"message": "Invalid draft_update: Missing chatId or tempChatId"}},
                         user_id, device_fingerprint_hash
                     )
                     continue
                # Content is implicitly checked by Pydantic model

                if chat_id is None:
                    # --- Handle new chat draft ---
                    logger.info(f"Received draft for a new chat (temp ID: {temp_chat_id}) from {user_id}/{device_fingerprint_hash}.")

                    # Ensure temp_chat_id is present (already checked above, but good practice)
                    if not temp_chat_id:
                         logger.error(f"Internal logic error: temp_chat_id is None for a new chat draft from {user_id}/{device_fingerprint_hash}.")
                         continue # Should not happen if initial validation passed

                    import hashlib
                    # Use the validated temp_chat_id
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
                                    "tempChatId": temp_chat_id # Reference the temporary ID
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
                    # Encrypt an empty title initially
                    encrypted_title, _ = await encryption_service.encrypt_with_chat_key("", vault_key_reference)

                    # 3. Prepare chat metadata for cache
                    now_ts = int(time.time())
                    chat_metadata = {
                        "id": new_chat_id,
                        "hashed_user_id": hashed_user_id,
                        "vault_key_reference": vault_key_reference,
                        "encrypted_title": encrypted_title, # Store encrypted title
                        "encrypted_draft": encrypted_draft,
                        "version": 1,
                        "created_at": now_ts,
                        "updated_at": now_ts,
                        "last_message_timestamp": None
                    }

                    # 4. Store chat metadata in cache (Dragonfly)
                    await cache_service.set_chat_metadata(new_chat_id, chat_metadata)

                    # 5. Store draft content directly in chat metadata cache (no separate draft cache entry needed per old draftId)
                    # The chat_metadata already contains the encrypted_draft
                    # If a separate draft *lookup* is needed (unlikely now), it would use chatId/tempChatId

                    logger.info(f"New chat {new_chat_id} (from temp: {temp_chat_id}) metadata and initial draft saved to cache, version 1 by {user_id}/{device_fingerprint_hash}")

                    # 6. Broadcast 'draft_updated' to ALL devices (including sender) with the NEW chat_id
                    # Use the validated DraftUpdateRequestData, ensuring tempChatId is cleared and chatId is set
                    # The client expects basedOnVersion to be the *new* version after the update.
                    draft_update_payload_dict = draft_data.dict()
                    draft_update_payload_dict["chatId"] = new_chat_id
                    draft_update_payload_dict["tempChatId"] = temp_chat_id # Include original temp ID
                    draft_update_payload_dict["basedOnVersion"] = 1 # Set the new version
                    draft_update_payload_dict["content"] = content # <<< Include the decrypted draft content

                    await manager.broadcast_to_user(
                        {
                            "type": "draft_updated", # Broadcast the confirmed update
                            "payload": draft_update_payload_dict
                        },
                        user_id,
                        exclude_device_hash=None
                    )

                    # 7. Broadcast 'activity_history_update' to sync the new chat stub
                    # Use ChatResponse for chat payload, include the extracted plaintext title
                    chat_response = ChatResponse(
                        id=new_chat_id, # Use the new chat ID
                        title="", # Send empty title for new drafts
                        draft=content, # Send the draft content itself
                        version=1,
                        created_at=now_ts,
                        updated_at=now_ts,
                        last_message_timestamp=None,
                        messages=[]
                    )
                    await manager.broadcast_to_user(
                        {
                            "type": "activity_history_update", # Changed from 'chat_added' to be more generic
                            "payload": {
                                "type": "chat_added", # Keep specific type within payload
                                "chat": chat_response.model_dump(mode='json') # Use model_dump for JSON serialization
                            }
                        },
                        user_id,
                        exclude_device_hash=None
                    )

                else:
                    # --- Handle existing chat draft update ---
                    # basedOnVersion is guaranteed by DraftUpdateRequestData Pydantic model
                    # if based_on_version is None: # Check removed, handled by Pydantic
                    #      logger.warning(f"Received draft_update for existing chat {chat_id} without basedOnVersion from {user_id}/{device_fingerprint_hash}. Rejecting.")
                    #      await manager.send_personal_message(
                    #          {"type": "error", "payload": {"message": "Missing basedOnVersion for existing chat draft update", "chatId": chat_id}}, # Removed draftId
                    #          user_id, device_fingerprint_hash
                    #      )
                    #      continue

                    # --- Encrypt draft content and update chat metadata in cache ---
                    import json
                    chat_meta_key = f"chat:{chat_id}:metadata"
                    chat_metadata = await cache_service.get(chat_meta_key)
                    metadata_reconstructed = False # Flag to track if we rebuilt metadata

                    if not chat_metadata or not isinstance(chat_metadata, dict):
                        logger.warning(f"Chat metadata not found in cache for chat_id {chat_id} (user {user_id}). Attempting reconstruction from Directus.")
                        # --- Attempt to reconstruct from Directus ---
                        try:
                            directus_chat_data = await get_chat_metadata(directus_service, chat_id)
                            if directus_chat_data:
                                logger.info(f"Found chat {chat_id} in Directus. Reconstructing cache metadata.")
                                # Reconstruct essential metadata. Ensure vault_key_reference is present.
                                # Note: Directus data might not have encrypted_draft or the latest version.
                                # We will overwrite these with the incoming draft update.
                                chat_metadata = {
                                    "id": directus_chat_data.get("id"),
                                    "hashed_user_id": directus_chat_data.get("hashed_user_id"), # Assuming this is stored
                                    "vault_key_reference": directus_chat_data.get("vault_key_reference"),
                                    "encrypted_title": directus_chat_data.get("encrypted_title"), # Use title from DB initially
                                    "encrypted_draft": None, # Will be set by the current update
                                    "version": directus_chat_data.get("version", 0), # Use DB version or default
                                    "created_at": int(directus_chat_data.get("created_at").timestamp()) if directus_chat_data.get("created_at") else int(time.time()),
                                    "updated_at": int(time.time()), # Set fresh update time
                                    "last_message_timestamp": int(directus_chat_data.get("last_message_timestamp").timestamp()) if directus_chat_data.get("last_message_timestamp") else None,
                                }
                                # Validate essential fields after reconstruction
                                if not chat_metadata.get("id") or not chat_metadata.get("vault_key_reference"):
                                    logger.error(f"Failed to reconstruct essential metadata (id or vault_key_reference) for chat {chat_id} from Directus data.")
                                    chat_metadata = None # Mark as failed
                                else:
                                    metadata_reconstructed = True
                            else:
                                logger.error(f"Chat {chat_id} not found in Directus either. Cannot process draft update.")
                                chat_metadata = None # Mark as failed

                        except Exception as e:
                            logger.error(f"Error fetching chat {chat_id} from Directus during cache miss handling: {e}", exc_info=True)
                            chat_metadata = None # Mark as failed

                        # If reconstruction failed, send error and continue
                        if not chat_metadata:
                            await manager.send_personal_message(
                                {"type": "error", "payload": {"message": "Chat not found or failed to reconstruct for draft update", "chatId": chat_id}},
                                user_id, device_fingerprint_hash
                            )
                            continue
                        # --- End Reconstruction ---

                    vault_key_reference = chat_metadata.get("vault_key_reference")
                    if not vault_key_reference:
                        logger.error(f"Vault key reference missing in chat metadata for chat_id {chat_id}")
                        await manager.send_personal_message(
                            {"type": "error", "payload": {"message": "Encryption key missing for chat", "chatId": chat_id}}, # Removed draftId
                            user_id, device_fingerprint_hash
                        )
                        continue

                    # Title should be updated via a separate mechanism, not automatically from draft content.
                    # We still need the old title for potential comparison if broadcasting metadata update,
                    # but we won't encrypt or store a *new* title derived from the draft here.
                    # Keep the existing encrypted_title in the metadata.
                    encrypted_new_title = chat_metadata.get("encrypted_title") # Keep existing title

                    draft_json = json.dumps(content) # Move draft encryption after title handling
                    encrypted_draft, _ = await encryption_service.encrypt_with_chat_key(draft_json, vault_key_reference)

                    # --- Update Cache ---
                    # If metadata was reconstructed, we overwrite; otherwise, use optimistic lock update.
                    cache_updated = False
                    new_version = -1 # Initialize

                    if metadata_reconstructed:
                        # Overwrite cache entry with reconstructed data + new draft/title
                        # Determine new version - increment based on client's base or reset if unsure
                        # Let's increment based on client's version for now
                        new_version = based_on_version + 1
                        now_ts = int(time.time())

                        chat_metadata["encrypted_draft"] = encrypted_draft
                        chat_metadata["encrypted_title"] = encrypted_new_title # Store new encrypted title
                        chat_metadata["updated_at"] = now_ts
                        chat_metadata["version"] = new_version

                        await cache_service.set_chat_metadata(chat_id, chat_metadata) # Overwrite/Set with TTL
                        cache_updated = True
                        logger.info(f"Reconstructed metadata for chat {chat_id} saved to cache with updated draft, version {new_version}.")

                    else:
                        # Attempt optimistic lock update using existing cache service method
                        encrypted_draft_str = json.dumps(encrypted_draft) # Assuming cache service expects string
                        update_result = await cache_service.update_chat_draft(
                            chat_id=chat_id,
                            encrypted_draft=encrypted_draft_str, # Pass encrypted draft
                            expected_version=based_on_version,
                        )

                        if isinstance(update_result, int): # Success, returns new version number
                            new_version = update_result
                            now_ts = int(time.time())
                            # Update other metadata fields in the existing cache entry
                            chat_metadata["encrypted_draft"] = encrypted_draft # Already updated by update_chat_draft? Assume yes.
                            chat_metadata["encrypted_title"] = encrypted_new_title
                            chat_metadata["updated_at"] = now_ts
                            chat_metadata["version"] = new_version # Already updated by update_chat_draft? Assume yes.
                            await cache_service.set_chat_metadata(chat_id, chat_metadata) # Ensure title/timestamp update
                            cache_updated = True
                            logger.info(f"Draft for chat {chat_id} updated successfully to version {new_version} by {user_id}/{device_fingerprint_hash}")
                        elif update_result is False: # Conflict or other cache error
                            logger.warning(f"Draft update conflict or error for {user_id}/{device_fingerprint_hash} on chat {chat_id}. Expected version: {based_on_version}")
                            # Send conflict message back to the originating client
                            await manager.send_personal_message(
                                {
                                    "type": "draft_conflict",
                                    "payload": {
                                        "chatId": chat_id
                                        # Removed draftId
                                    }
                                },
                                user_id,
                                device_fingerprint_hash
                            )
                        # Handle True case? update_draft_content currently doesn't return True.

                    # --- Broadcast if Cache Update Succeeded ---
                    if cache_updated and new_version != -1:
                        # Note: The set_chat_metadata call was moved into the conditional blocks above
                        # await cache_service.set_chat_metadata(chat_id, chat_metadata) # This line is redundant here now
                        # Broadcast the 'draft_updated' confirmation
                        draft_update_payload_dict = draft_data.dict()
                        draft_update_payload_dict["tempChatId"] = None # Ensure temp ID is cleared
                        draft_update_payload_dict["basedOnVersion"] = new_version # Set the new version
                        draft_update_payload_dict["content"] = content # <<< Include the decrypted draft content

                        await manager.broadcast_to_user(
                            {
                                "type": "draft_updated",
                                "payload": draft_update_payload_dict
                            },
                            user_id,
                            exclude_device_hash=None # Send confirmation to sender too
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