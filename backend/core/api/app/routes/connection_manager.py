import asyncio
import logging
from fastapi import WebSocket, WebSocketDisconnect
from typing import Dict, Tuple, Optional

logger = logging.getLogger(__name__)

class ConnectionManager:
    GRACE_PERIOD_SECONDS = 30  # 30 seconds grace period

    def __init__(self):
        # Structure: {user_id: {device_fingerprint_hash: WebSocket}}
        self.active_connections: Dict[str, Dict[str, WebSocket]] = {}
        # Structure: {websocket_id: (user_id, device_fingerprint_hash)} for reverse lookup
        self.reverse_lookup: Dict[int, Tuple[str, str]] = {}
        # Structure: {(user_id, device_fingerprint_hash): chat_id} to track active chat per device
        self.active_chat_per_connection: Dict[Tuple[str, str], Optional[str]] = {}
        # Structure: {(user_id, device_fingerprint_hash): asyncio.Task} for disconnect grace period tasks
        self.grace_period_tasks: Dict[Tuple[str, str], asyncio.Task] = {}

    async def connect(self, websocket: WebSocket, user_id: str, device_fingerprint_hash: str):
        await websocket.accept()
        connection_key = (user_id, device_fingerprint_hash)
        new_ws_id = id(websocket)

        # Cancel pending disconnect task if client reconnects within grace period
        if connection_key in self.grace_period_tasks:
            task = self.grace_period_tasks.pop(connection_key)
            task.cancel()
            logger.info(f"Reconnected: User {user_id}, Device {device_fingerprint_hash}. Pending disconnect cancelled.")

        # Clean up old websocket's reverse lookup if this is a replacement
        if user_id in self.active_connections and device_fingerprint_hash in self.active_connections[user_id]:
            old_websocket = self.active_connections[user_id][device_fingerprint_hash]
            old_ws_id = id(old_websocket)
            if old_ws_id != new_ws_id and old_ws_id in self.reverse_lookup:
                del self.reverse_lookup[old_ws_id]
                logger.debug(f"Cleaned up reverse_lookup for old ws_id {old_ws_id} during connect.")
        
        if user_id not in self.active_connections:
            self.active_connections[user_id] = {}
        
        self.active_connections[user_id][device_fingerprint_hash] = websocket
        self.reverse_lookup[new_ws_id] = connection_key
        
        # Preserve active chat if connection_key already exists (reconnection)
        if connection_key not in self.active_chat_per_connection:
            self.active_chat_per_connection[connection_key] = None # Initially no active chat for a brand new connection
            logger.info(f"WebSocket connected: User {user_id}, Device {device_fingerprint_hash}. Initial active chat: None.")
        else:
            logger.info(f"WebSocket re-established: User {user_id}, Device {device_fingerprint_hash}. Active chat: {self.active_chat_per_connection[connection_key]}.")

    def disconnect(self, websocket: WebSocket, reason: str = "Unknown"):
        ws_id = id(websocket)
        if ws_id not in self.reverse_lookup:
            # This can happen if disconnect is called multiple times for the same ws_id after it's been processed by the first call
            # or if the websocket was never fully registered in reverse_lookup.
            logger.debug(f"WebSocket {ws_id} not in reverse_lookup during disconnect attempt (reason: {reason}). Already processed or never fully connected.")
            return

        user_id, device_fingerprint_hash = self.reverse_lookup[ws_id] # Don't pop yet, _finalize_disconnect will handle it
        connection_key = (user_id, device_fingerprint_hash)

        if connection_key in self.grace_period_tasks and self.grace_period_tasks[connection_key].done() is False:
            logger.debug(f"Disconnect for {user_id}/{device_fingerprint_hash} (ws_id: {ws_id}, reason: {reason}) called while already in grace period. Timer will continue.")
            return

        logger.info(f"WebSocket {ws_id} for {user_id}/{device_fingerprint_hash} disconnected (reason: {reason}). Starting grace period of {self.GRACE_PERIOD_SECONDS}s for session removal.")
        
        # Schedule the finalization of the disconnect
        # Pass the original ws_id that initiated this disconnect sequence
        task = asyncio.create_task(self._schedule_finalize_disconnect(user_id, device_fingerprint_hash, ws_id, reason))
        self.grace_period_tasks[connection_key] = task

    async def _schedule_finalize_disconnect(self, user_id: str, device_fingerprint_hash: str, original_ws_id: int, disconnect_reason: str):
        connection_key = (user_id, device_fingerprint_hash)
        try:
            await asyncio.sleep(self.GRACE_PERIOD_SECONDS)
            # Check if the task was cancelled just before _finalize_disconnect is called
            # This check is somewhat redundant if the cancel happens during sleep, but good for clarity
            if connection_key not in self.grace_period_tasks or self.grace_period_tasks[connection_key].cancelled():
                 logger.info(f"Finalize disconnect task for {user_id}/{device_fingerprint_hash} (original ws_id: {original_ws_id}, reason: {disconnect_reason}) was cancelled before finalization logic.")
                 return # Task was cancelled, likely by a reconnect

            logger.info(f"Grace period ended for {user_id}/{device_fingerprint_hash} (original ws_id: {original_ws_id}, reason: {disconnect_reason}). Finalizing disconnect.")
            await self._finalize_disconnect(user_id, device_fingerprint_hash, original_ws_id)
        except asyncio.CancelledError:
            logger.info(f"Finalize disconnect task for {user_id}/{device_fingerprint_hash} (original ws_id: {original_ws_id}, reason: {disconnect_reason}) was cancelled (likely due to reconnect).")
        finally:
            # Ensure task is removed from tracking if it completes or is cancelled here
            # This handles the case where the task is cancelled *after* the check above but *before* pop
            self.grace_period_tasks.pop(connection_key, None)

    async def _finalize_disconnect(self, user_id: str, device_fingerprint_hash: str, ws_id_to_finalize: int):
        connection_key = (user_id, device_fingerprint_hash)

        # Critical check: Only proceed if the websocket that triggered this finalization
        # is still the one associated with this connection_key in active_connections.
        # If a new websocket has taken over (reconnect), we should not tear down the session.
        current_ws_object_in_active_connections = self.active_connections.get(user_id, {}).get(device_fingerprint_hash)
        
        if current_ws_object_in_active_connections and id(current_ws_object_in_active_connections) != ws_id_to_finalize:
            logger.info(f"Finalize disconnect for {user_id}/{device_fingerprint_hash}: Original ws_id {ws_id_to_finalize} was replaced by new ws_id {id(current_ws_object_in_active_connections)}. Session preserved. Cleaning up reverse_lookup for old ws_id {ws_id_to_finalize} if present.")
            if ws_id_to_finalize in self.reverse_lookup and self.reverse_lookup[ws_id_to_finalize] == connection_key:
                del self.reverse_lookup[ws_id_to_finalize]
            return # Session is active with a new websocket, do not remove from active_connections or active_chat

        # If we reach here, either:
        # 1. The websocket in active_connections is the same one that disconnected (ws_id_to_finalize).
        # 2. There's no websocket in active_connections for this user/device (already cleaned up or never reconnected).

        # Clean up reverse_lookup for the specific WebSocket instance that triggered this process
        if ws_id_to_finalize in self.reverse_lookup and self.reverse_lookup[ws_id_to_finalize] == connection_key:
            del self.reverse_lookup[ws_id_to_finalize]
            logger.info(f"Finalized: Removed ws_id {ws_id_to_finalize} from reverse_lookup for {user_id}/{device_fingerprint_hash}.")
        
        # Clean up active_connections and active_chat_per_connection
        user_connections = self.active_connections.get(user_id)
        if user_connections and device_fingerprint_hash in user_connections:
            # Ensure we are removing the correct websocket instance if it's still there
            if id(user_connections[device_fingerprint_hash]) == ws_id_to_finalize:
                del user_connections[device_fingerprint_hash]
                logger.info(f"Finalized: WebSocket session removed for User {user_id}, Device {device_fingerprint_hash} (ws_id: {ws_id_to_finalize}) after grace period.")
                if not user_connections:
                    del self.active_connections[user_id]
                    logger.info(f"Finalized: Removed user {user_id} from active_connections as no devices are left after grace period.")
                
                # Clean up active chat tracking only if we actually removed the connection
                if connection_key in self.active_chat_per_connection:
                    del self.active_chat_per_connection[connection_key]
                    logger.info(f"Finalized: Cleared active chat tracking for {user_id}/{device_fingerprint_hash} (ws_id: {ws_id_to_finalize}) after grace period.")
            else:
                # This case should ideally be caught by the check at the beginning of this method.
                logger.warning(f"Finalize disconnect for {user_id}/{device_fingerprint_hash}: ws_id {ws_id_to_finalize} was expected, but found ws_id {id(user_connections[device_fingerprint_hash])}. Session might have been rapidly replaced. Reverse lookup for {ws_id_to_finalize} cleaned if it was still pointing here.")
        else:
            # Connection was already removed from active_connections or user_id not found.
            # This can happen if _finalize_disconnect is called for an old ws_id after a new one reconnected and then also disconnected,
            # leading to its own finalization path that might have already cleaned up the user entry.
            logger.info(f"Finalize disconnect for {user_id}/{device_fingerprint_hash} (ws_id: {ws_id_to_finalize}): Connection not found in active_connections. It might have been fully cleaned up by another process or a subsequent reconnect/disconnect cycle.")
            # Still ensure active_chat_per_connection is cleaned if it somehow lingers for this key
            if connection_key in self.active_chat_per_connection:
                 # This is a safeguard; ideally, it's cleaned when the actual connection is removed.
                 # Only remove if no current websocket is associated with this key.
                if not (self.active_connections.get(user_id, {}).get(device_fingerprint_hash)):
                    del self.active_chat_per_connection[connection_key]
                    logger.info(f"Finalized: Cleared lingering active chat tracking for {user_id}/{device_fingerprint_hash} as no active connection exists.")

    async def send_personal_message(self, message: dict, user_id: str, device_fingerprint_hash: str):
        websocket = self.active_connections.get(user_id, {}).get(device_fingerprint_hash)
        if websocket:
            try:
                await websocket.send_json(message)
                logger.debug(f"Sent message to User {user_id}, Device {device_fingerprint_hash}: {message}")
            except Exception as e: # Catch any exception during send
                logger.error(f"Error sending message to User {user_id}, Device {device_fingerprint_hash} (ws_id: {id(websocket)}): {e}. Initiating disconnect process.")
                self.disconnect(websocket, reason=f"Send error: {type(e).__name__}") # Pass reason
        else:
            logger.warning(f"Attempted to send personal message to {user_id}/{device_fingerprint_hash}, but no active WebSocket found (possibly in grace period or fully disconnected).")

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
                        # This lookup might fail if the connection was already removed by a rapid disconnect.
                        failed_device_hash_lookup = "unknown"
                        if ws_id in self.reverse_lookup:
                             # Ensure the reverse_lookup entry actually belongs to this user_id to be safe, though ws_id should be unique
                             ru_user_id, ru_device_hash = self.reverse_lookup[ws_id]
                             if ru_user_id == user_id:
                                 failed_device_hash_lookup = ru_device_hash
                        
                        logger.error(f"Error broadcasting to User {user_id}, Device {failed_device_hash_lookup} (WS ID: {ws_id}): {result}. Initiating disconnect process.")
                        self.disconnect(failed_websocket, reason=f"Broadcast error: {type(result).__name__}") # Pass reason

                logger.debug(f"Broadcasted message to User {user_id} (excluding {exclude_device_hash}): {message}")

    async def broadcast_to_user_specific_event(self, user_id: str, event_name: str, payload: dict):
        """Sends a specific event message to all connected devices for a specific user."""
        if user_id in self.active_connections:
            message = {"type": event_name, "payload": payload}
            tasks = []
            websockets_to_send = []

            for device_hash, websocket in list(self.active_connections[user_id].items()):
                tasks.append(websocket.send_json(message))
                websockets_to_send.append(websocket)
            
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        failed_websocket = websockets_to_send[i]
                        ws_id = id(failed_websocket)
                        failed_device_hash_lookup = "unknown"
                        if ws_id in self.reverse_lookup:
                             ru_user_id, ru_device_hash = self.reverse_lookup[ws_id]
                             if ru_user_id == user_id:
                                 failed_device_hash_lookup = ru_device_hash
                        logger.error(f"Error broadcasting event '{event_name}' to User {user_id}, Device {failed_device_hash_lookup} (WS ID: {ws_id}): {result}. Initiating disconnect process.")
                        self.disconnect(failed_websocket, reason=f"Broadcast event error: {type(result).__name__}") # Pass reason
                
                logger.debug(f"Broadcasted event '{event_name}' to User {user_id}. Payload: {payload}")

    def is_user_active(self, user_id: str) -> bool:
        """Checks if a user has any active WebSocket connections or connections in grace period."""
        # A user is considered active if they have entries in active_connections (live websockets)
        # OR if they have tasks in grace_period_tasks (recently disconnected, might reconnect).
        if user_id in self.active_connections and bool(self.active_connections[user_id]):
            return True
        for (uid, _), task in self.grace_period_tasks.items():
            if uid == user_id and not task.done(): # Check if task is for the user and not yet completed/cancelled
                return True
        return False

    def set_active_chat(self, user_id: str, device_fingerprint_hash: str, chat_id: Optional[str]):
        """Sets the currently active chat for a specific user device connection."""
        connection_key = (user_id, device_fingerprint_hash)
        # Check if the connection actually exists in active_connections OR is in a grace period
        websocket_instance = self.active_connections.get(user_id, {}).get(device_fingerprint_hash)
        grace_task = self.grace_period_tasks.get(connection_key)
        is_in_grace = grace_task is not None and not grace_task.done()

        if websocket_instance or is_in_grace:
            self.active_chat_per_connection[connection_key] = chat_id
            logger.info(f"User {user_id}, Device {device_fingerprint_hash}: Active chat set to '{chat_id}'. Connection state: {'active' if websocket_instance else 'in grace period'}.")
        else:
            logger.warning(f"User {user_id}, Device {device_fingerprint_hash}: Attempted to set active chat, but connection not found (neither active nor in grace period).")

    def get_active_chat(self, user_id: str, device_fingerprint_hash: str) -> Optional[str]:
        """Gets the currently active chat for a specific user device connection."""
        connection_key = (user_id, device_fingerprint_hash)
        # Check if the connection is active or in grace period before returning chat
        # This prevents returning a chat_id for a connection that has been fully finalized.
        websocket_instance = self.active_connections.get(user_id, {}).get(device_fingerprint_hash)
        grace_task = self.grace_period_tasks.get(connection_key)
        is_in_grace = grace_task is not None and not grace_task.done()

        if websocket_instance or is_in_grace:
            return self.active_chat_per_connection.get(connection_key)
        
        logger.debug(f"Requested active chat for {user_id}/{device_fingerprint_hash}, but connection is not active or in grace. Returning None.")
        return None

    def get_connections_for_user(self, user_id: str) -> Dict[str, WebSocket]:
        """Gets all currently live WebSocket connections for a given user_id."""
        # This will return only connections that have a live WebSocket object in active_connections.
        # Connections that are only in a grace period (i.e., their WebSocket object might have been
        # removed from active_connections or is otherwise stale) are not returned here,
        # as they cannot be reliably used for sending messages directly.
        return self.active_connections.get(user_id, {})
