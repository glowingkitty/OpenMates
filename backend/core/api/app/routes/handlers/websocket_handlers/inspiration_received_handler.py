# backend/core/api/app/routes/handlers/websocket_handlers/inspiration_received_handler.py
# WebSocket handler for the `daily_inspiration_received` client->server ACK message.
#
# After the server delivers pending daily inspirations via the `daily_inspiration`
# WebSocket event, the client sends this ACK once it has successfully processed
# and stored the inspirations locally (in the dailyInspirationStore).
#
# On receiving this ACK, the server clears the pending delivery cache so the
# inspirations are not re-delivered on subsequent connections.
#
# This ACK-based flow prevents data loss when the WebSocket disconnects between
# delivery and client processing (the original bug where inspirations were lost).
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
) -> None:
    """
    ACK handler: client confirms it received and stored pending daily inspirations.

    Clears the pending delivery cache for this user so the same inspirations
    are not re-delivered on subsequent WebSocket connections.

    Args:
        cache_service: CacheService instance (with InspirationCacheMixin)
        user_id: User UUID (not hashed - used as cache key)
        payload: WebSocket message payload dict (currently unused, reserved for future fields)
    """
    try:
        success = await cache_service.clear_pending_inspirations(user_id)
        if success:
            logger.info(
                f"[InspirationReceived] Cleared pending inspirations for user {user_id[:8]}... "
                f"after client ACK"
            )
        else:
            logger.warning(
                f"[InspirationReceived] Failed to clear pending inspirations for user {user_id[:8]}..."
            )
    except Exception as e:
        logger.error(
            f"[InspirationReceived] Error clearing pending inspirations for user {user_id[:8]}...: {e}",
            exc_info=True,
        )
