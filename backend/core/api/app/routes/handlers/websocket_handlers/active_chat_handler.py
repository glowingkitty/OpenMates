# backend/core/api/app/routes/handlers/websocket_handlers/active_chat_handler.py
#
# Handles active-chat selection for WebSocket connections.
# This is intentionally lightweight because set_active_chat often runs directly
# before chat_message_added during new-chat sends. A slow last_opened write must
# not block the socket receive loop before the AI message handler can run.

import asyncio
import logging
import re
from typing import Optional, TYPE_CHECKING

from backend.shared.python_utils.tracing.ws_span_helper import end_ws_handler_span, start_ws_handler_span

if TYPE_CHECKING:
    from backend.core.api.app.routes.connection_manager import ConnectionManager
    from backend.core.api.app.services.cache import CacheService
    from backend.core.api.app.services.directus import DirectusService


logger = logging.getLogger(__name__)

_REAL_CHAT_UUID_PATTERN = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)


def _is_real_chat_id(active_chat_id: Optional[str]) -> bool:
    if not active_chat_id:
        return False
    return (
        not active_chat_id.startswith("demo-")
        and not active_chat_id.startswith("legal-")
        and (_REAL_CHAT_UUID_PATTERN.match(active_chat_id) or active_chat_id.startswith("/chat/"))
    )


async def _persist_active_chat_selection(
    manager: "ConnectionManager",
    cache_service: "CacheService",
    directus_service: "DirectusService",
    user_id: str,
    device_fingerprint_hash: str,
    active_chat_id: str,
) -> None:
    try:
        update_payload = {"last_opened": active_chat_id, "signup_completed": True}

        # Update Redis first so phased sync/cache warming sees the newest value.
        try:
            await cache_service.update_user(user_id, update_payload)
            logger.debug(f"User {user_id}: Updated last_opened in cache to {active_chat_id}")
        except Exception as cache_err:
            logger.warning(f"User {user_id}: Failed to update last_opened in cache: {cache_err}")
            # Non-critical: Directus update below is the persistent fallback.

        await directus_service.update_user(user_id, update_payload)
        logger.info(f"User {user_id}: Updated last_opened to chat {active_chat_id}")

        await manager.broadcast_to_user(
            message={
                "type": "last_opened_updated",
                "payload": {"chat_id": active_chat_id},
            },
            user_id=user_id,
            exclude_device_hash=device_fingerprint_hash,
        )
        logger.debug(f"User {user_id}: Broadcasted last_opened_updated to other devices for chat {active_chat_id}")
    except Exception as err:
        logger.error(
            f"User {user_id}: Failed to persist/broadcast last_opened for chat {active_chat_id}: {err}",
            exc_info=True,
        )


async def handle_set_active_chat(
    manager: "ConnectionManager",
    cache_service: "CacheService",
    directus_service: "DirectusService",
    user_id: str,
    device_fingerprint_hash: str,
    active_chat_id: Optional[str],
    user_otel_attrs: dict | None = None,
) -> None:
    payload = {"chat_id": active_chat_id}
    _otel_span, _otel_token = start_ws_handler_span(
        "set_active_chat",
        user_id,
        payload,
        user_otel_attrs,
    )
    try:
        manager.set_active_chat(user_id, device_fingerprint_hash, active_chat_id)
        logger.debug(f"User {user_id}, Device {device_fingerprint_hash}: Set active chat to '{active_chat_id}'.")

        # Acknowledge before persistence so the WebSocket receive loop can process an
        # immediately following chat_message_added from a newly-created chat.
        await manager.send_personal_message(
            {"type": "active_chat_set_ack", "payload": {"chat_id": active_chat_id}},
            user_id,
            device_fingerprint_hash,
        )

        if _is_real_chat_id(active_chat_id):
            asyncio.create_task(
                _persist_active_chat_selection(
                    manager,
                    cache_service,
                    directus_service,
                    user_id,
                    device_fingerprint_hash,
                    active_chat_id,
                )
            )
        elif active_chat_id:
            logger.debug(f"User {user_id}: Skipping last_opened update for non-real chat ID: {active_chat_id}")
        else:
            logger.debug(f"User {user_id}: Skipping last_opened update (no active chat)")
    finally:
        end_ws_handler_span(_otel_span, _otel_token)
