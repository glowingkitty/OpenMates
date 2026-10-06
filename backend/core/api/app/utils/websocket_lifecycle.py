"""Receive safely when a session watcher has already closed the socket."""

from typing import Any

from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState


async def receive_json_or_disconnect(websocket: WebSocket) -> Any:
    """Route server-close races through the ordinary disconnect cleanup."""
    try:
        return await websocket.receive_json()
    except RuntimeError:
        if websocket.application_state != WebSocketState.DISCONNECTED:
            raise
        raise WebSocketDisconnect(code=1000, reason="Server closed connection") from None
