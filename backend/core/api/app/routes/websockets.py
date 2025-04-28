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

class ConnectionManager:
    def __init__(self):
        # Structure: {user_id: {device_fingerprint_hash: WebSocket}}
        self.active_connections: Dict[str, Dict[str, WebSocket]] = {}
        # Structure: {websocket_id: (user_id, device_fingerprint_hash)} for reverse lookup on disconnect
        self.reverse_lookup: Dict[int, Tuple[str, str]] = {}

    async def connect(self, websocket: WebSocket, user_id: str, device_fingerprint_hash: str):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = {}
        self.active_connections[user_id][device_fingerprint_hash] = websocket
        self.reverse_lookup[id(websocket)] = (user_id, device_fingerprint_hash)
        logger.info(f"WebSocket connected: User {user_id}, Device {device_fingerprint_hash}")

    def disconnect(self, websocket: WebSocket):
        ws_id = id(websocket)
        if ws_id in self.reverse_lookup:
            user_id, device_fingerprint_hash = self.reverse_lookup.pop(ws_id)
            if user_id in self.active_connections and device_fingerprint_hash in self.active_connections[user_id]:
                del self.active_connections[user_id][device_fingerprint_hash]
                if not self.active_connections[user_id]: # Remove user entry if no devices left
                    del self.active_connections[user_id]
                logger.info(f"WebSocket disconnected: User {user_id}, Device {device_fingerprint_hash}")
            else:
                 logger.warning(f"WebSocket {ws_id} not found in active_connections during disconnect for {user_id}/{device_fingerprint_hash}")
        else:
            logger.warning(f"WebSocket {ws_id} not found in reverse_lookup during disconnect.")


    async def send_personal_message(self, message: dict, user_id: str, device_fingerprint_hash: str):
        if user_id in self.active_connections and device_fingerprint_hash in self.active_connections[user_id]:
            websocket = self.active_connections[user_id][device_fingerprint_hash]
            try:
                await websocket.send_json(message)
                logger.debug(f"Sent message to User {user_id}, Device {device_fingerprint_hash}: {message}")
            except WebSocketDisconnect:
                 logger.warning(f"WebSocket disconnected while trying to send message to {user_id}/{device_fingerprint_hash}. Cleaning up.")
                 self.disconnect(websocket) # Clean up connection if send fails due to disconnect
            except Exception as e:
                logger.error(f"Error sending message to User {user_id}, Device {device_fingerprint_hash}: {e}")
                # Consider disconnecting if sending fails persistently

    async def broadcast_to_user(self, message: dict, user_id: str, exclude_device_hash: str = None):
        """Sends a message to all connected devices for a specific user, optionally excluding one."""
        if user_id in self.active_connections:
            # Create a list of tasks to send messages concurrently
            tasks = []
            websockets_to_send = [] # Keep track of websockets we attempt to send to

            # Iterate safely over a copy of items in case disconnect modifies the dict
            for device_hash, websocket in list(self.active_connections[user_id].items()):
                if device_hash != exclude_device_hash:
                    tasks.append(websocket.send_json(message))
                    websockets_to_send.append(websocket)

            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        # Log error for the specific device that failed
                        failed_websocket = websockets_to_send[i]
                        ws_id = id(failed_websocket)
                        # Find the device hash associated with the failed websocket
                        failed_device_hash = next((dh for dh, ws in self.active_connections.get(user_id, {}).items() if id(ws) == ws_id), "unknown")
                        logger.error(f"Error broadcasting to User {user_id}, Device {failed_device_hash} (WS ID: {ws_id}): {result}")
                        if isinstance(result, WebSocketDisconnect):
                             logger.warning(f"WebSocket disconnected during broadcast to {user_id}/{failed_device_hash}. Cleaning up.")
                             self.disconnect(failed_websocket) # Clean up connection

                logger.debug(f"Broadcasted message to User {user_id} (excluding {exclude_device_hash}): {message}")


manager = ConnectionManager()

# --- Authentication Dependency for WebSocket ---
async def get_current_user_ws(
    websocket: WebSocket
) -> Dict[str, Any]:
    """
    Verify WebSocket connection using auth token from cookie and device fingerprint.
    Closes connection and raises WebSocketDisconnect on failure.
    Returns user_id and device_fingerprint_hash on success.
    """
    # Access services directly from websocket state
    cache_service: CacheService = websocket.app.state.cache_service
    directus_service: DirectusService = websocket.app.state.directus_service

    # Access cookies directly from the websocket object
    auth_refresh_token = websocket.cookies.get("auth_refresh_token")

    if not auth_refresh_token:
        logger.warning("WebSocket connection denied: Missing or inaccessible 'auth_refresh_token' cookie.")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Authentication required")
        raise WebSocketDisconnect(code=status.WS_1008_POLICY_VIOLATION, reason="Authentication required")

    try:
        # 1. Get user data from cache using the extracted token
        user_data = await cache_service.get_user_by_token(auth_refresh_token)
        if not user_data:
            logger.warning(f"WebSocket connection denied: Invalid or expired token (not found in cache for token ending ...{auth_refresh_token[-6:]}).")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid session")
            raise WebSocketDisconnect(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid session")

        user_id = user_data.get("user_id")
        if not user_id:
            logger.error("WebSocket connection denied: User data in cache is invalid (missing user_id).")
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="Server error")
            raise WebSocketDisconnect(code=status.WS_1011_INTERNAL_ERROR, reason="Server error")

        # 2. Verify device fingerprint using the dedicated utility functions
        try:
            # Use the specific functions for WebSockets
            device_fingerprint_hash = get_websocket_device_fingerprint(websocket)
            client_ip = get_websocket_client_ip(websocket) # Get IP for logging/cache update
            logger.debug(f"Calculated WebSocket fingerprint for user {user_id}: Hash={device_fingerprint_hash}")
        except Exception as e:
             logger.error(f"Error calculating WebSocket fingerprint for user {user_id}: {e}", exc_info=True)
             # Ensure connection is closed before raising disconnect
             await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="Fingerprint error")
             raise WebSocketDisconnect(code=status.WS_1011_INTERNAL_ERROR, reason="Fingerprint error")

        # Check if device is known using device_cache utility (checks cache first)
        device_exists_in_cache, _ = await check_device_in_cache(
            cache_service, user_id, device_fingerprint_hash
        )

        if not device_exists_in_cache:
            # Not in cache, check database as fallback
            logger.debug(f"Device {device_fingerprint_hash} not in cache for user {user_id}, checking DB.")
            device_in_db = await directus_service.check_user_device(user_id, device_fingerprint_hash)
            if not device_in_db:
                logger.warning(f"WebSocket connection denied: Device mismatch for user {user_id}. Fingerprint: {device_fingerprint_hash}")
                # Check if 2FA is enabled for the user
                if user_data.get("tfa_enabled", False):
                    reason = "Device mismatch, 2FA required"
                    await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=reason)
                    raise WebSocketDisconnect(code=status.WS_1008_POLICY_VIOLATION, reason=reason)
                else:
                    reason = "Device mismatch"
                    await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=reason)
                    raise WebSocketDisconnect(code=status.WS_1008_POLICY_VIOLATION, reason=reason)
            else:
                # Device is in DB but not cache - add it to cache using device_cache utility
                logger.info(f"Device {device_fingerprint_hash} found in DB for user {user_id}, adding to cache.")
                # Fetch location info first
                try:
                    location_info = get_location_from_ip(client_ip)
                except Exception as loc_e:
                    logger.error(f"Error getting location for IP {client_ip} during cache update: {loc_e}")
                    # Use a default/error location string for the cache entry
                    location_info = {"location_string": "Location Error"} # Ensure this dict structure is handled by store_device_in_cache or adjust

                # Store using the utility function
                await store_device_in_cache(
                    cache_service=cache_service,
                    user_id=user_id,
                    device_fingerprint=device_fingerprint_hash,
                    # Pass the location string extracted from location_info
                    device_location=location_info.get("location_string", "Unknown"),
                    is_new_device=False # It existed in DB, so not strictly new
                )
                # Note: store_device_in_cache handles setting the correct cache key and TTL

        # 3. Authentication successful, device known
        logger.info(f"WebSocket authenticated: User {user_id}, Device {device_fingerprint_hash}")
        return {"user_id": user_id, "device_fingerprint_hash": device_fingerprint_hash, "user_data": user_data}

    except WebSocketDisconnect as e:
        # Re-raise exceptions related to auth failure that already closed the connection
        raise e
    except Exception as e:
        # Ensure token exists before trying to slice it for logging
        token_suffix = auth_refresh_token[-6:] if auth_refresh_token else "N/A"
        logger.error(f"Unexpected error during WebSocket authentication for token ending ...{token_suffix}: {e}", exc_info=True)
        # Attempt to close gracefully before raising disconnect
        try:
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="Authentication error")
        except Exception:
            pass # Ignore errors during close after another error
        raise WebSocketDisconnect(code=status.WS_1011_INTERNAL_ERROR, reason="Authentication error")


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
        logger.info(f"Fetching initial sync data for {user_id}/{device_fingerprint_hash}")
        final_chat_entries_dict: Dict[str, Dict[str, Any]] = {}
        processed_metadata_list: List[Dict[str, Any]] = [] # To store metadata from cache or fetched from DB

        try:
            # 1. Try fetching chat list metadata from cache
            cached_metadata = await cache_service.get_chat_list_metadata(user_id)

            if cached_metadata:
                logger.debug(f"Cache HIT for chat list metadata for user {user_id}. Found {len(cached_metadata)} entries.")
                processed_metadata_list = cached_metadata # Already has decrypted titles
            else:
                logger.debug(f"Cache MISS for chat list metadata for user {user_id}. Fetching from Directus.")
                # 2. Fetch from Directus if cache miss
                directus_chats_metadata = await directus_service.get_user_chats_metadata(user_id)
                logger.debug(f"Fetched {len(directus_chats_metadata)} chats from Directus for user {user_id}")

                # Decrypt titles and prepare list for caching
                decrypted_metadata_for_cache = []
                for chat_meta in directus_chats_metadata:
                    chat_id = chat_meta.get("id")
                    encrypted_title = chat_meta.get("encrypted_title")
                    vault_key_id = chat_meta.get("vault_key_id")
                    last_updated = chat_meta.get("updated_at") # Keep as is

                    decrypted_title = "Untitled Chat"
                    if encrypted_title and vault_key_id:
                        try:
                            decrypted_title = await encryption_service.decrypt_with_chat_key(encrypted_title, vault_key_id)
                            if not decrypted_title: decrypted_title = "Decryption Error"
                        except Exception as decrypt_err:
                            logger.error(f"Failed to decrypt title for chat {chat_id}: {decrypt_err}")
                            decrypted_title = "Decryption Error"
                    elif not encrypted_title:
                         logger.warning(f"Chat {chat_id} has no encrypted_title.")

                    processed_entry = {
                        "id": chat_id,
                        "title": decrypted_title,
                        "lastUpdated": last_updated,
                        # Add other necessary fields from CHAT_METADATA_FIELDS if needed by frontend/cache
                        "_version": chat_meta.get("_version") # Keep version if needed later
                    }
                    decrypted_metadata_for_cache.append(processed_entry)

                # Store the processed list in cache
                if decrypted_metadata_for_cache:
                    await cache_service.set_chat_list_metadata(user_id, decrypted_metadata_for_cache)
                    logger.debug(f"Stored fetched & decrypted chat list metadata in cache for user {user_id}")

                processed_metadata_list = decrypted_metadata_for_cache

            # 3. Fetch all active drafts from Redis
            draft_keys_pattern = f"draft:{user_id}:*:*"
            active_draft_keys = await cache_service.get_keys_by_pattern(draft_keys_pattern)
            user_drafts: Dict[str, Dict[str, Any]] = {} # Store draft data by chat_id
            logger.debug(f"Found {len(active_draft_keys)} potential draft keys for user {user_id}")
            for key in active_draft_keys:
                draft_data = await cache_service.get(key) # Assumes get returns the dict {content, version, lastUpdated?}
                if draft_data and isinstance(draft_data, dict):
                    parts = key.split(':')
                    if len(parts) >= 4: # Ensure key format is draft:user:chat:draft_id
                        draft_chat_id = parts[2]
                        # Store draft data, ensuring lastUpdated exists (use current time as fallback)
                        draft_data['lastUpdated'] = draft_data.get('lastUpdated', time.time()) # Use draft's timestamp
                        user_drafts[draft_chat_id] = draft_data
                        logger.debug(f"Fetched draft data for chat_id: {draft_chat_id}")
                    else:
                        logger.warning(f"Skipping draft key with unexpected format: {key}")
                else:
                     logger.warning(f"Could not fetch or parse draft data for key: {key}")


            # 4. Merge & Format
            # Process chats from metadata (cache/Directus)
            for chat_entry in processed_metadata_list:
                chat_id = chat_entry.get("id")
                if not chat_id: continue

                is_draft = chat_id in user_drafts
                final_chat_entries_dict[chat_id] = {
                    "id": chat_id,
                    "title": chat_entry.get("title", "Untitled Chat"),
                    "lastUpdated": chat_entry.get("lastUpdated"), # Use timestamp from metadata
                    "isDraft": is_draft,
                    # "unreadCount": 0 # Omit if not available
                }
                # If it's a draft, potentially update lastUpdated from draft data if newer?
                # For simplicity, let's use the metadata lastUpdated for now. Frontend sorting handles draft priority.

            # Process "New Chat" drafts (drafts whose chat_id isn't in the metadata list)
            for draft_chat_id, draft_data in user_drafts.items():
                if draft_chat_id not in final_chat_entries_dict:
                    # This is a draft without a corresponding chat in Directus yet
                    draft_content = draft_data.get('content')
                    draft_title = _extract_title_from_draft_content(draft_content)
                    draft_last_updated = draft_data.get('lastUpdated') # Use draft's timestamp

                    final_chat_entries_dict[draft_chat_id] = {
                        "id": draft_chat_id,
                        "title": draft_title,
                        "lastUpdated": draft_last_updated,
                        "isDraft": True,
                    }
                    logger.debug(f"Added 'new chat' draft entry for chat_id: {draft_chat_id}")

            # 5. Convert to list and sort (optional, frontend also sorts)
            chat_list_for_payload = sorted(
                list(final_chat_entries_dict.values()),
                # Sort by lastUpdated (descending). Assumes lastUpdated is comparable (e.g., ISO string or timestamp number)
                # Frontend will apply more complex sorting (draft priority etc.)
                key=lambda x: x.get('lastUpdated', 0), # Use 0 if missing for sorting
                reverse=True
            )

            logger.info(f"Sending initial_sync_data with {len(chat_list_for_payload)} entries to {user_id}/{device_fingerprint_hash}")
            await manager.send_personal_message(
                {"type": "initial_sync_data", "payload": {"chats": chat_list_for_payload, "lastOpenChatId": None}}, # TODO: Add lastOpenChatId
                user_id,
                device_fingerprint_hash
            )

        except Exception as sync_err:
            logger.error(f"Error preparing initial_sync_data for {user_id}/{device_fingerprint_hash}: {sync_err}", exc_info=True)
            await manager.send_personal_message(
                {"type": "initial_sync_data", "payload": {"chats": [], "lastOpenChatId": None, "error": "Failed to load chat list"}},
                user_id,
                device_fingerprint_hash
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
                    # --- Handle new chat draft ---
                    logger.info(f"Received draft for a new chat from {user_id}/{device_fingerprint_hash}. Generating new chat ID.")
                    new_chat_id = f"{user_id[:6]}-{uuid.uuid4()}"
                    logger.debug(f"Generated new chat ID: {new_chat_id} for user {user_id}")

                    # Attempt to create/update the draft in cache with the new chat ID
                    # Expect version None or 0 for the very first save of a draft
                    update_result = await cache_service.update_draft_content(
                        user_id=user_id,
                        chat_id=new_chat_id, # Use the newly generated chat ID
                        draft_id=draft_id,   # Use the draft ID from the client
                        content=content,
                        expected_version=None, # First save, no prior version expected
                        # ttl=... # Use default TTL
                    )

                    if isinstance(update_result, int): # Success, returns new version (likely 1)
                        new_version = update_result
                        logger.info(f"New chat draft {draft_id} saved successfully for chat {new_chat_id}, version {new_version} by {user_id}/{device_fingerprint_hash}")

                        # Broadcast 'draft_updated' to ALL devices (including sender) with the NEW chat_id
                        await manager.broadcast_to_user(
                            {
                                "type": "draft_updated",
                                "payload": {
                                    "chatId": new_chat_id, # Send the generated chat ID
                                    "draftId": draft_id,
                                    "content": content,
                                    "version": new_version
                                }
                            },
                            user_id,
                            exclude_device_hash=None # Send to all, including the sender
                        )

                        # Broadcast 'activity_history_update' to sync the new chat stub
                        await manager.broadcast_to_user(
                            {
                                "type": "activity_history_update",
                                "payload": {
                                    "type": "chat_added", # Indicate a new chat was added
                                    "chat": {
                                        "id": new_chat_id,
                                        "draft_content": content, # Include initial draft content
                                        "draft_version": new_version,
                                        "draft_id": draft_id,
                                        "last_updated": time.time(), # Add timestamp
                                        # Add other minimal necessary fields for ActivityHistory UI if needed
                                        # e.g., "title": "New Chat" (or derive from content later)
                                    }
                                }
                            },
                            user_id,
                            exclude_device_hash=None # Send to all
                        )
                    else: # Conflict or error during initial save (less likely but possible)
                        logger.error(f"Failed to save initial draft for new chat {new_chat_id} from {user_id}/{device_fingerprint_hash}. Draft ID: {draft_id}")
                        # Send error back to the originating client
                        await manager.send_personal_message(
                            {
                                "type": "error", # Use a generic error or a specific one like 'draft_save_failed'
                                "payload": {
                                    "message": "Failed to save initial draft for new chat.",
                                    "draftId": draft_id # Include draftId for context
                                }
                            },
                            user_id,
                            device_fingerprint_hash
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

                    # Attempt to update the draft using the cache service
                    update_result = await cache_service.update_draft_content(
                        user_id=user_id,
                        chat_id=chat_id,
                        draft_id=draft_id,
                        content=content,
                        expected_version=based_on_version,
                        # ttl=... # Use default TTL
                    )

                    if isinstance(update_result, int): # Success, returns new version number
                        new_version = update_result
                        logger.info(f"Draft {draft_id} for chat {chat_id} updated successfully to version {new_version} by {user_id}/{device_fingerprint_hash}")
                        # Broadcast the update to other devices of the same user
                        await manager.broadcast_to_user(
                            {
                                "type": "draft_updated",
                                "payload": {
                                    "chatId": chat_id,
                                    "draftId": draft_id,
                                    "content": content, # Send the updated content back
                                    "version": new_version
                                }
                            },
                            user_id,
                            exclude_device_hash=device_fingerprint_hash # Exclude sender
                        )
                        # Send confirmation back to sender including the new version
                        await manager.send_personal_message(
                             {
                                "type": "draft_updated", # Send confirmation back to sender too
                                "payload": {
                                    "chatId": chat_id,
                                    "draftId": draft_id,
                                    "content": content, # Send content back to sender too
                                    "version": new_version
                                }
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
                # TODO: Handle receiving a full new message (for background chats)
                # - Persist the message
                # - Broadcast 'chat_message_received' to all user devices (except sender?)
                logger.info(f"Placeholder: Received chat_message_received from {user_id}/{device_fingerprint_hash}: {payload}")
                # Example broadcast:
                # await manager.broadcast_to_user(
                #     {"type": "chat_message_received", "payload": payload}, # Adjust payload as needed
                #     user_id,
                #     exclude_device_hash=device_fingerprint_hash
                # )

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