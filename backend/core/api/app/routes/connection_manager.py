import asyncio
import logging
from fastapi import WebSocket, WebSocketDisconnect
from typing import Dict, Tuple

logger = logging.getLogger(__name__)

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
        if ws_id not in self.reverse_lookup:
            # If not in reverse_lookup, it might have been fully processed already,
            # or was never properly connected. Log this as debug or info.
            logger.debug(f"WebSocket {ws_id} not in reverse_lookup during disconnect attempt. Already processed or never fully connected.")
            return

        user_id, device_fingerprint_hash = self.reverse_lookup.pop(ws_id)
        
        user_connections = self.active_connections.get(user_id)
        if user_connections and device_fingerprint_hash in user_connections:
            del user_connections[device_fingerprint_hash]
            logger.info(f"WebSocket disconnected: User {user_id}, Device {device_fingerprint_hash}")
            if not user_connections: # If no devices left for this user
                del self.active_connections[user_id]
                logger.info(f"Removed user {user_id} from active_connections as no devices are left.")
        else:
            # This case means ws_id was in reverse_lookup, but the specific connection
            # was not in active_connections. This could happen if disconnect was called
            # multiple times and another call already cleaned up active_connections.
            # This is no longer a warning, but an expected state in multiple calls.
            logger.info(f"WebSocket {ws_id} for {user_id}/{device_fingerprint_hash} was already removed from active_connections or user entry was cleared.")

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
                        failed_device_hash = next((dh for dh, ws in self.active_connections.get(user_id, {}).items() if id(ws) == ws_id), "unknown")
                        logger.error(f"Error broadcasting event '{event_name}' to User {user_id}, Device {failed_device_hash} (WS ID: {ws_id}): {result}")
                        if isinstance(result, WebSocketDisconnect):
                            logger.warning(f"WebSocket disconnected during event broadcast to {user_id}/{failed_device_hash}. Cleaning up.")
                            self.disconnect(failed_websocket)
                
                logger.debug(f"Broadcasted event '{event_name}' to User {user_id}. Payload: {payload}")

    def is_user_active(self, user_id: str) -> bool:
        """Checks if a user has any active WebSocket connections."""
        return user_id in self.active_connections and bool(self.active_connections[user_id])