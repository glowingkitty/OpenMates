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