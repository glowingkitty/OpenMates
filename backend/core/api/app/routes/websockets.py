import asyncio
import logging
import time
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Request, HTTPException, status, Cookie
from typing import List, Dict, Any, Optional, Tuple # Added Tuple

# Import necessary services and utilities
from app.services.cache import CacheService
from app.services.directus import DirectusService # Keep this
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
    # Access cache service directly from websocket state
    cache_service: CacheService = websocket.app.state.cache_service
    user_id = auth_data["user_id"]
    device_fingerprint_hash = auth_data["device_fingerprint_hash"]
    # user_data = auth_data["user_data"] # Full user data available if needed

    await manager.connect(websocket, user_id, device_fingerprint_hash)

    try:
        # TODO: Send initial sync data (fetch from DB/Cache)
        logger.info(f"Sending placeholder initial_sync_data to {user_id}/{device_fingerprint_hash}")
        await manager.send_personal_message(
            {"type": "initial_sync_data", "payload": {"chats": [], "lastOpenChatId": None, "message": "Placeholder - Fetch actual data"}},
            user_id,
            device_fingerprint_hash
        )

        while True:
            data = await websocket.receive_json()
            logger.debug(f"Received message from User {user_id}, Device {device_fingerprint_hash}: {data}")

            message_type = data.get("type")
            payload = data.get("payload", {})

            # Process different message types
            if message_type == "draft_update":
                chat_id = payload.get("chatId")
                draft_id = payload.get("draftId")
                content = payload.get("content")
                based_on_version = payload.get("basedOnVersion") # Can be None for new drafts

                if not all([chat_id, draft_id, content is not None]): # content can be empty string
                    logger.warning(f"Received invalid draft_update from {user_id}/{device_fingerprint_hash}: Missing fields.")
                    # Optionally send an error back
                    await manager.send_personal_message(
                        {"type": "error", "payload": {"message": "Invalid draft_update payload"}},
                        user_id, device_fingerprint_hash
                    )
                    continue # Skip processing this message

                # Attempt to update the draft using the cache service
                update_result = await cache_service.update_draft_content(
                    user_id=user_id,
                    chat_id=chat_id,
                    draft_id=draft_id,
                    content=content,
                    expected_version=based_on_version,
                    # ttl=... # Use default TTL from cache service for now
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
                        exclude_device_hash=device_fingerprint_hash
                    )
                    # Optionally send confirmation back to sender? Usually broadcast is enough.
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
                # If it did (e.g., for creation success), handle similarly to the int case.

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