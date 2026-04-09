import asyncio
import logging
from fastapi import WebSocket
from starlette.websockets import WebSocketState
from typing import Dict, Tuple, Optional

logger = logging.getLogger(__name__)


def _safe_message_summary(message: object) -> str:
    """Return metadata-only message summary for logs."""
    if isinstance(message, dict):
        keys = sorted(message.keys())
        return f"keys={keys}, key_count={len(keys)}"
    if isinstance(message, list):
        return f"list_len={len(message)}"
    return f"type={type(message).__name__}"


def _ws_is_live(websocket: WebSocket) -> bool:
    """
    True iff the server-side application state of the WebSocket is still
    CONNECTED. During the 30s disconnect grace period the ws stays in
    active_connections but Starlette has already closed the transport —
    calling send_json() then raises RuntimeError('Unexpected ASGI message
    "websocket.send", after sending "websocket.close"...'). Callers must
    check this before broadcasting to avoid the race.
    """
    try:
        return websocket.application_state == WebSocketState.CONNECTED
    except Exception:
        return False


def _is_closed_ws_error(exc: BaseException) -> bool:
    """
    Identifies the benign race where a broadcast reached a ws that was
    already closed (grace-period remnant). Logged at DEBUG — not an error.
    """
    if isinstance(exc, RuntimeError):
        msg = str(exc)
        return (
            "Unexpected ASGI message" in msg
            or "websocket.close" in msg
            or "response already completed" in msg
        )
    return False

class ConnectionManager:
    """
    Manages WebSocket connections with support for multiple browser instances per device.
    
    Dual-Hash Architecture:
        1. Device Hash (without sessionId): SHA256(OS:Country:UserID)
           - Used for: Device verification, "new device" email detection
           - Stored in: Directus user_devices table
           - Persists across browser sessions on same physical device
        
        2. Connection Hash (with sessionId): SHA256(OS:Country:UserID:SessionID)
           - Used for: WebSocket connection routing (stored as device_fingerprint_hash key)
           - SessionID: UUID generated per browser tab/instance, stored in sessionStorage
           - Each browser instance (Arc, Firefox, Chrome) = unique connection hash
           - Allows multiple instances on same physical device without conflicts
    
    Connection Structure:
        - active_connections: {user_id: {connection_hash: WebSocket}}
        - Each connection_hash = one specific browser instance
        - Example: Arc = connection_hash_A, Firefox = connection_hash_B on same device
        - Both coexist independently without connection overwrites
        - Each receives its own ping/pong and messages
    """
    GRACE_PERIOD_SECONDS = 30  # 30 seconds grace period

    def __init__(self):
        # Structure: {user_id: {device_fingerprint_hash: WebSocket}}
        # Note: Each browser instance has unique sessionId → unique device_fingerprint_hash
        # Example: {user123: {hash_arc: ws_arc, hash_firefox: ws_firefox}}
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
            logger.debug(f"Reconnected: User {user_id}, Device {device_fingerprint_hash}. Pending disconnect cancelled.")

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
            logger.debug(f"WebSocket connected: User {user_id}, Device {device_fingerprint_hash}. Initial active chat: None.")
        else:
            logger.debug(f"WebSocket re-established: User {user_id}, Device {device_fingerprint_hash}. Active chat: {self.active_chat_per_connection[connection_key]}.")

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

        logger.debug(f"WebSocket {ws_id} for {user_id}/{device_fingerprint_hash} disconnected (reason: {reason}). Starting grace period of {self.GRACE_PERIOD_SECONDS}s for session removal.")
        
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
                 logger.debug(f"Finalize disconnect task for {user_id}/{device_fingerprint_hash} (original ws_id: {original_ws_id}, reason: {disconnect_reason}) was cancelled before finalization logic.")
                 return # Task was cancelled, likely by a reconnect

            logger.debug(f"Grace period ended for {user_id}/{device_fingerprint_hash} (original ws_id: {original_ws_id}, reason: {disconnect_reason}). Finalizing disconnect.")
            await self._finalize_disconnect(user_id, device_fingerprint_hash, original_ws_id)
        except asyncio.CancelledError:
            logger.debug(f"Finalize disconnect task for {user_id}/{device_fingerprint_hash} (original ws_id: {original_ws_id}, reason: {disconnect_reason}) was cancelled (likely due to reconnect).")
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
            logger.debug(f"Finalize disconnect for {user_id}/{device_fingerprint_hash}: Original ws_id {ws_id_to_finalize} was replaced by new ws_id {id(current_ws_object_in_active_connections)}. Session preserved. Cleaning up reverse_lookup for old ws_id {ws_id_to_finalize} if present.")
            if ws_id_to_finalize in self.reverse_lookup and self.reverse_lookup[ws_id_to_finalize] == connection_key:
                del self.reverse_lookup[ws_id_to_finalize]
            return # Session is active with a new websocket, do not remove from active_connections or active_chat

        # If we reach here, either:
        # 1. The websocket in active_connections is the same one that disconnected (ws_id_to_finalize).
        # 2. There's no websocket in active_connections for this user/device (already cleaned up or never reconnected).

        # Clean up reverse_lookup for the specific WebSocket instance that triggered this process
        if ws_id_to_finalize in self.reverse_lookup and self.reverse_lookup[ws_id_to_finalize] == connection_key:
            del self.reverse_lookup[ws_id_to_finalize]
            logger.debug(f"Finalized: Removed ws_id {ws_id_to_finalize} from reverse_lookup for {user_id}/{device_fingerprint_hash}.")
        
        # Clean up active_connections and active_chat_per_connection
        user_connections = self.active_connections.get(user_id)
        if user_connections and device_fingerprint_hash in user_connections:
            # Ensure we are removing the correct websocket instance if it's still there
            if id(user_connections[device_fingerprint_hash]) == ws_id_to_finalize:
                del user_connections[device_fingerprint_hash]
                logger.debug(f"Finalized: WebSocket session removed for User {user_id}, Device {device_fingerprint_hash} (ws_id: {ws_id_to_finalize}) after grace period.")
                if not user_connections:
                    del self.active_connections[user_id]
                    logger.debug(f"Finalized: Removed user {user_id} from active_connections as no devices are left after grace period.")
                
                # Clean up active chat tracking only if we actually removed the connection
                if connection_key in self.active_chat_per_connection:
                    del self.active_chat_per_connection[connection_key]
                    logger.debug(f"Finalized: Cleared active chat tracking for {user_id}/{device_fingerprint_hash} (ws_id: {ws_id_to_finalize}) after grace period.")
            else:
                # This case should ideally be caught by the check at the beginning of this method.
                logger.warning(f"Finalize disconnect for {user_id}/{device_fingerprint_hash}: ws_id {ws_id_to_finalize} was expected, but found ws_id {id(user_connections[device_fingerprint_hash])}. Session might have been rapidly replaced. Reverse lookup for {ws_id_to_finalize} cleaned if it was still pointing here.")
        else:
            # Connection was already removed from active_connections or user_id not found.
            # This can happen if _finalize_disconnect is called for an old ws_id after a new one reconnected and then also disconnected,
            # leading to its own finalization path that might have already cleaned up the user entry.
            logger.debug(f"Finalize disconnect for {user_id}/{device_fingerprint_hash} (ws_id: {ws_id_to_finalize}): Connection not found in active_connections. It might have been fully cleaned up by another process or a subsequent reconnect/disconnect cycle.")
            # Still ensure active_chat_per_connection is cleaned if it somehow lingers for this key
            if connection_key in self.active_chat_per_connection:
                 # This is a safeguard; ideally, it's cleaned when the actual connection is removed.
                 # Only remove if no current websocket is associated with this key.
                if not (self.active_connections.get(user_id, {}).get(device_fingerprint_hash)):
                    del self.active_chat_per_connection[connection_key]
                    logger.debug(f"Finalized: Cleared lingering active chat tracking for {user_id}/{device_fingerprint_hash} as no active connection exists.")

    async def send_personal_message(self, message: dict, user_id: str, device_fingerprint_hash: str):
        websocket = self.active_connections.get(user_id, {}).get(device_fingerprint_hash)
        if websocket:
            # Skip silently if the server-side socket has already transitioned
            # to DISCONNECTED (30s grace period remnant). Trying to send_json
            # on a closed ws raises the "Unexpected ASGI message" RuntimeError.
            if not _ws_is_live(websocket):
                logger.debug(
                    f"Skipped personal message for {user_id}/{device_fingerprint_hash}: "
                    f"ws already closed (grace period). Triggering disconnect cleanup."
                )
                self.disconnect(websocket, reason="ws already closed when sending")
                return
            try:
                await websocket.send_json(message)
                logger.debug(
                    f"Sent message to User {user_id}, Device {device_fingerprint_hash} "
                    f"(message_summary={_safe_message_summary(message)})"
                )
            except Exception as e: # Catch any exception during send
                if _is_closed_ws_error(e):
                    logger.debug(
                        f"Send raced with close for {user_id}/{device_fingerprint_hash} "
                        f"(ws_id: {id(websocket)}): {e}. Disconnecting."
                    )
                else:
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
            stale_websockets = []  # Grace-period remnants to clean up after iteration

            # Iterate safely over a copy of items in case disconnect modifies the dict
            for device_hash, websocket in list(self.active_connections[user_id].items()):
                if device_hash == exclude_device_hash:
                    continue
                # Skip sockets whose server-side transport is already closed
                # (grace-period remnants). Sending would raise RuntimeError
                # and the broadcast would reach live peers anyway — but the
                # noisy error log was masking real broadcast failures.
                if not _ws_is_live(websocket):
                    stale_websockets.append(websocket)
                    continue
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

                        if _is_closed_ws_error(result):
                            logger.debug(
                                f"Broadcast raced with close for User {user_id}, Device "
                                f"{failed_device_hash_lookup} (WS ID: {ws_id}): {result}. Disconnecting."
                            )
                        else:
                            logger.error(f"Error broadcasting to User {user_id}, Device {failed_device_hash_lookup} (WS ID: {ws_id}): {result}. Initiating disconnect process.")
                        self.disconnect(failed_websocket, reason=f"Broadcast error: {type(result).__name__}") # Pass reason

                logger.debug(
                    f"Broadcasted message to User {user_id} (excluding {exclude_device_hash}) "
                    f"(message_summary={_safe_message_summary(message)})"
                )

            # Kick off disconnect cleanup for any stale sockets we skipped.
            for stale_ws in stale_websockets:
                self.disconnect(stale_ws, reason="ws closed before broadcast")

    async def broadcast_to_user_specific_event(
        self,
        user_id: str,
        event_name: str,
        payload: dict,
        exclude_device_hash: Optional[str] = None,
    ):
        """
        Sends a specific event message to all connected devices for a specific user.

        exclude_device_hash: if provided, skip the connection with this hash.
        Used by force_logout broadcasts so the revoking device does not log itself out.
        """
        if user_id in self.active_connections:
            message = {"type": event_name, "payload": payload}
            tasks = []
            websockets_to_send = []
            stale_websockets = []
            connection_count = len(self.active_connections[user_id])

            for device_hash, websocket in list(self.active_connections[user_id].items()):
                if device_hash == exclude_device_hash:
                    continue
                # Skip dead sockets in the 30s grace period — see _ws_is_live.
                if not _ws_is_live(websocket):
                    stale_websockets.append(websocket)
                    continue
                tasks.append(websocket.send_json(message))
                websockets_to_send.append(websocket)

            if tasks:
                # Enhanced logging for send_embed_data events
                if event_name == "send_embed_data":
                    embed_id = payload.get("embed_id", "unknown")
                    status = payload.get("status", "unknown")
                    logger.info(
                        f"[EMBED_EVENT] Broadcasting 'send_embed_data' for embed {embed_id} (status={status}) "
                        f"to User {user_id} across {len(tasks)} live WebSocket connection(s) "
                        f"({len(stale_websockets)} stale skipped of {connection_count} total)"
                    )

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
                        if _is_closed_ws_error(result):
                            logger.debug(
                                f"Event broadcast raced with close ('{event_name}') for User {user_id}, "
                                f"Device {failed_device_hash_lookup} (WS ID: {ws_id}): {result}. Disconnecting."
                            )
                        else:
                            logger.error(f"Error broadcasting event '{event_name}' to User {user_id}, Device {failed_device_hash_lookup} (WS ID: {ws_id}): {result}. Initiating disconnect process.")
                        self.disconnect(failed_websocket, reason=f"Broadcast event error: {type(result).__name__}") # Pass reason

                if event_name != "send_embed_data":  # Avoid duplicate logging for send_embed_data
                    payload_keys = sorted(payload.keys()) if isinstance(payload, dict) else []
                    logger.debug(
                        f"Broadcasted event '{event_name}' to User {user_id}. "
                        f"Payload summary: keys={payload_keys}, key_count={len(payload_keys)}"
                    )

            # Clean up stale grace-period sockets we skipped.
            for stale_ws in stale_websockets:
                self.disconnect(stale_ws, reason=f"ws closed before '{event_name}' broadcast")

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
            logger.debug(f"User {user_id}, Device {device_fingerprint_hash}: Active chat set to '{chat_id}'. Connection state: {'active' if websocket_instance else 'in grace period'}.")
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
        """Gets all currently live WebSocket connections for a given user_id.

        Returns a shallow *copy* of the inner device→WebSocket mapping so that
        callers can safely iterate the result while concurrent disconnects
        modify the live ``active_connections`` dict without raising
        ``RuntimeError: dictionary changed size during iteration``.
        """
        # Shallow copy — safe for iteration; callers must not store this beyond
        # a single event-handler invocation since the WebSocket objects may
        # become stale at any point after the copy is taken.
        return dict(self.active_connections.get(user_id, {}))

    async def broadcast_to_all(self, message: dict, timeout_seconds: float = 2.0) -> None:
        """Broadcast a message to every connected WebSocket across all users.

        Intended for server-wide notifications such as ``server_restarting``,
        which is sent once during the lifespan shutdown sequence before the
        process exits.  The ``timeout_seconds`` cap ensures a hung TCP send
        buffer on a single slow client never delays the shutdown process.

        Uses ``return_exceptions=True`` so that one broken socket does not
        abort delivery to the remaining connections.
        """
        # Snapshot all sockets at this moment — iterate a flat copy so that
        # concurrent disconnects can't mutate the dict mid-loop.
        all_sockets = [
            ws
            for user_sockets in self.active_connections.values()
            for ws in user_sockets.values()
        ]

        if not all_sockets:
            logger.info("broadcast_to_all: no active connections, nothing to send.")
            return

        logger.info(
            f"broadcast_to_all: sending '{message.get('type', '?')}' to "
            f"{len(all_sockets)} connection(s) (timeout={timeout_seconds}s)"
        )

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    *[ws.send_json(message) for ws in all_sockets],
                    return_exceptions=True,
                ),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning(
                f"broadcast_to_all: timed out after {timeout_seconds}s — "
                f"some clients may not have received the '{message.get('type', '?')}' message."
            )
