# backend/core/api/app/routes/handlers/websocket_handlers/key_received_handler.py
# WebSocket handler for the 'key_received' client->server acknowledgment message.
#
# When a recipient device successfully receives and decrypts a chat encryption key
# (via WebSocket key delivery), it sends a 'key_received' ACK back to the server.
# This handler relays the acknowledgment to all OTHER connected devices of the same
# user as a 'key_delivery_confirmed' message, so the originating sender device knows
# the key was delivered successfully.
#
# Part of SYNC-01: WebSocket key delivery acknowledgment protocol.
# Architecture: docs/architecture/encryption.md

import logging
from typing import Dict, Any

from backend.core.api.app.routes.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)


async def handle_key_received(
    manager: ConnectionManager,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any],
    user_otel_attrs: dict = None,) -> None:
    """
    Handles key_received ACK from a recipient device after successful key injection.

    Broadcasts 'key_delivery_confirmed' to all OTHER connected devices of the same
    user so the sender knows the key was delivered. This is observational — no action
    is required by the sender; it provides confidence and audit trail.

    Args:
        manager: WebSocket ConnectionManager for broadcasting to user devices
        user_id: User UUID (not hashed)
        device_fingerprint_hash: SHA-256 hash of the acknowledging device fingerprint
        payload: Must contain 'chat_id' (the chat whose key was received)
    """
    _otel_span, _otel_token = None, None
    try:
        from backend.shared.python_utils.tracing.ws_span_helper import start_ws_handler_span, end_ws_handler_span
        _otel_span, _otel_token = start_ws_handler_span("key_received", user_id, payload, user_otel_attrs)
    except Exception:
        pass
    try:
        chat_id = payload.get("chat_id")

        if not chat_id:
            logger.warning(
                f"[KeyReceived] Missing chat_id in key_received from "
                f"device {device_fingerprint_hash[:8]}... — ignoring"
            )
            return

        logger.info(
            f"Key received ack from device {device_fingerprint_hash[:8]} for chat {chat_id}"
        )

        # Relay acknowledgment to all OTHER devices of this user (the sender device(s))
        await manager.broadcast_to_user(
            {
                "type": "key_delivery_confirmed",
                "payload": {
                    "chat_id": chat_id,
                    "device_hash": device_fingerprint_hash,
                },
            },
            user_id,
            exclude_device_hash=device_fingerprint_hash,
        )

    finally:
        if _otel_span is not None:
            try:
                from backend.shared.python_utils.tracing.ws_span_helper import end_ws_handler_span as _end_span
                _end_span(_otel_span, _otel_token)
            except Exception:
                pass
