# update_chat_pinned_handler.py
# Handles the "update_chat" WebSocket message for pin/unpin actions.
# Persists pinned state to Redis cache and Directus, then broadcasts
# the change to all other connected devices for cross-device sync.
# Architecture: follows the same pattern as chat_read_status_update (inline in websockets.py)
# Tests: N/A (manual cross-device verification)

import logging
from typing import Dict, Any

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.routes.connection_manager import ConnectionManager
from backend.core.api.app.tasks.celery_config import app as celery_app_instance

logger = logging.getLogger(__name__)


async def handle_update_chat_pinned(
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any],
) -> None:
    """
    Handles pin/unpin updates from a client device.

    Flow:
    1. Validate payload (chat_id + pinned boolean required)
    2. Update pinned field in Redis list_item_data cache
    3. Dispatch Celery task to persist pinned state to Directus
    4. Broadcast chat_pinned_updated to all OTHER devices of this user
    """
    chat_id = payload.get("chat_id")
    pinned = payload.get("pinned")

    if not chat_id or pinned is None:
        logger.warning(
            f"Invalid update_chat (pinned) payload from {user_id}/{device_fingerprint_hash}: "
            f"missing chat_id or pinned. payload={payload}"
        )
        return

    # Normalize to bool
    pinned = bool(pinned)

    logger.info(
        f"Processing update_chat pinned={pinned} for chat {chat_id} "
        f"from {user_id}/{device_fingerprint_hash}"
    )

    # 1. Update Redis cache (list_item_data hash)
    try:
        await cache_service.update_chat_pinned_status(
            user_id=user_id,
            chat_id=chat_id,
            pinned=pinned,
        )
    except Exception as e:
        logger.error(
            f"Failed to update pinned status in cache for chat {chat_id}, "
            f"user {user_id}: {e}",
            exc_info=True,
        )
        # Continue — Directus persistence and broadcast are still valuable
        # even if the cache update fails (cache will self-heal on next warm)

    # 2. Persist to Directus via Celery task (async, non-blocking)
    celery_app_instance.send_task(
        "app.tasks.persistence_tasks.persist_chat_pinned",
        kwargs={
            "chat_id": chat_id,
            "pinned": pinned,
        },
        queue="persistence",
    )
    logger.debug(
        f"Dispatched persist_chat_pinned task for chat {chat_id}, pinned={pinned}"
    )

    # 3. Broadcast to all OTHER devices of this user
    await manager.broadcast_to_user(
        message={
            "type": "chat_pinned_updated",
            "payload": {
                "chat_id": chat_id,
                "pinned": pinned,
            },
        },
        user_id=user_id,
        exclude_device_hash=device_fingerprint_hash,
    )
    logger.info(
        f"Broadcasted chat_pinned_updated for chat {chat_id} (pinned={pinned}) "
        f"to user {user_id} (excluding device {device_fingerprint_hash})"
    )
