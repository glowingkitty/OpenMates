# backend/core/api/app/routes/handlers/websocket_handlers/inspiration_viewed_handler.py
# WebSocket handler for the `inspiration_viewed` client→server message.
#
# The client sends this message as soon as a Daily Inspiration banner becomes
# visible in the viewport (≥50% intersection via IntersectionObserver), and also
# when the carousel advances to a new slide while the banner is already visible.
# A user who passively scrolls past all 3 inspirations without clicking any will
# still have all 3 counted, resulting in all 3 being replaced the next cycle.
# The client deduplicates per session: each inspiration_id is reported at most
# once even if the user scrolls away and back.
#
# Message format (client → server):
#   { "type": "inspiration_viewed", "payload": { "inspiration_id": "<uuid>" } }
#
# Privacy: only the inspiration UUID is stored, not the content.

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def handle_inspiration_viewed(
    cache_service: Any,
    user_id: str,
    payload: dict,
) -> None:
    """
    Record that the user viewed a specific Daily Inspiration banner.

    Args:
        cache_service: CacheService instance (with InspirationCacheMixin)
        user_id: User UUID (not hashed — used as cache key)
        payload: WebSocket message payload dict containing `inspiration_id`
    """
    inspiration_id = payload.get("inspiration_id")
    if not inspiration_id:
        logger.warning(
            f"[InspirationViewed] Missing inspiration_id in payload from user {user_id[:8]}..."
        )
        return

    try:
        success = await cache_service.track_inspiration_viewed(
            user_id=user_id,
            inspiration_id=str(inspiration_id),
        )
        if success:
            logger.debug(
                f"[InspirationViewed] Tracked view of inspiration {str(inspiration_id)[:8]}... "
                f"for user {user_id[:8]}..."
            )
        else:
            logger.warning(
                f"[InspirationViewed] Failed to track view for user {user_id[:8]}..."
            )
    except Exception as e:
        logger.error(
            f"[InspirationViewed] Error tracking inspiration view for user {user_id[:8]}...: {e}",
            exc_info=True,
        )
