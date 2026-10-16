"""Receive safely when a session watcher has already closed the socket."""

from enum import Enum
import logging
import re
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


class SessionAuthorityCloseCategory(str, Enum):
    """Bounded categories for the existing session watcher close decisions."""

    SESSION_LINK_MISSING = "session_link_missing"
    SESSION_LINK_MISMATCH = "session_link_mismatch"
    STATE_MISSING = "state_missing"
    RISK_PENDING = "risk_pending"
    AUTHORITY_REJECTED = "authority_rejected"
    AUTHORITY_UNAVAILABLE = "authority_unavailable"


def log_session_authority_close(
    logger: logging.Logger,
    *,
    connection_hash: str,
    category: SessionAuthorityCloseCategory,
    authority_status: int = 0,
) -> None:
    """Log only bounded scalars and the existing non-credential connection hash.

    Logging failures must not change the watcher decision or prevent closure.
    No exception text, authority records, token digests or user IDs are retained.
    """
    correlation = (connection_hash if isinstance(connection_hash, str)
                   and re.fullmatch(r"[0-9a-f]{64}", connection_hash) else "unavailable")
    safe_status = (authority_status if type(authority_status) is int
                   and 100 <= authority_status <= 599 else 0)
    try:
        logger.warning(
            "[WS_SESSION_AUTHORITY_CLOSE] category=%s authority_status=%s connection_hash=%s",
            category.value, safe_status, correlation,
            extra={"event_type": "ws_session_authority_close",
                   "close_category": category.value,
                   "authority_status": safe_status,
                   "connection_hash": correlation},
        )
    except Exception:
        # Diagnostics are best effort; the unchanged close remains authoritative.
        return
