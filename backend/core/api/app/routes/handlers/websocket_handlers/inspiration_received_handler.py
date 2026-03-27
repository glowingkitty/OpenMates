# backend/core/api/app/routes/handlers/websocket_handlers/inspiration_received_handler.py
# WebSocket handler for the `daily_inspiration_received` client->server ACK message.
#
# HISTORY: Originally the ACK cleared the pending delivery cache, but this caused
# a multi-device race condition — the first device to ACK would clear the cache,
# so any other device connecting later would never receive the pending inspirations.
#
# The pending cache is now cleared server-side after a brief delay following
# the broadcast in _deliver_pending_inspirations() (websockets.py). This ACK
# handler is kept for backwards compatibility (old clients still send it) but
# is now a no-op: it just logs receipt without clearing the cache.
#
# Message format (client -> server):
#   { "type": "daily_inspiration_received", "payload": {} }
#
# Privacy: no content is exchanged in this message, only a signal.

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def handle_inspiration_received(
    cache_service: Any,
    user_id: str,
    payload: dict,
    user_otel_attrs: dict = None,) -> None:
    """
    ACK handler: client confirms it received daily inspirations.

    Previously this cleared the pending cache, but that caused a multi-device
    race condition (first device to ACK wiped the cache for all devices).
    The pending cache is now cleared server-side after broadcast with a delay.

    This handler is kept for backwards compatibility — old clients still send
    the ACK message. It logs receipt but does not clear the cache.

    Args:
        cache_service: CacheService instance (with InspirationCacheMixin)
        user_id: User UUID (not hashed - used as cache key)
        payload: WebSocket message payload dict (currently unused)
    """
    _otel_span, _otel_token = None, None
    try:
        from backend.shared.python_utils.tracing.ws_span_helper import start_ws_handler_span, end_ws_handler_span
        _otel_span, _otel_token = start_ws_handler_span("inspiration_received", user_id, payload, user_otel_attrs)
    except Exception:
        pass
    try:
        logger.debug(
            f"[InspirationReceived] Received client ACK from user {user_id[:8]}... "
            f"(no-op — pending cache is cleared server-side after broadcast)"
        )

    finally:
        if _otel_span is not None:
            try:
                from backend.shared.python_utils.tracing.ws_span_helper import end_ws_handler_span as _end_span
                _end_span(_otel_span, _otel_token)
            except Exception:
                pass
