# backend/core/api/app/routes/handlers/websocket_handlers/delete_draft_embed_handler.py
#
# Handles the 'delete_draft_embed' WebSocket message.
#
# Background: When a user uploads a file (image, PDF, recording) to the message
# input draft and then removes it before sending the message, the file already
# exists in S3 and has an upload_files record in Directus (created at upload time).
# This handler cleans up that orphaned uploaded file so:
#   - The S3 storage is reclaimed
#   - The upload_files Directus record is removed
#   - The user's storage_used_bytes counter is decremented
#   - Other devices of the same user are notified to clean up their IndexedDB

import logging
from typing import Dict, Any

from fastapi import WebSocket

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.routes.connection_manager import ConnectionManager
from backend.core.api.app.tasks.celery_config import app

logger = logging.getLogger(__name__)


async def handle_delete_draft_embed(
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any],
    user_otel_attrs: dict = None,) -> None:
    """
    Handle the 'delete_draft_embed' message from a WebSocket client.

    Expected payload:
        {
            "embed_id": "<uuid>",   # The embed UUID returned by POST /v1/upload/file
            "chat_id": "<uuid>"     # The draft chat this embed belongs to (for context / logging)
        }

    Flow:
      1. Validate payload.
      2. Queue Celery task 'persist_delete_draft_embed' to:
         - Delete S3 variant files (original, full, preview) from the chatfiles bucket.
         - Delete the upload_files Directus record.
         - Decrement the user's storage_used_bytes counter.
      3. Remove embed from Redis cache (if cached by app skills).
      4. Broadcast 'draft_embed_deleted' to ALL other devices of the same user so
         they can clean up their local IndexedDB EmbedStore entry.
    """
    _otel_span, _otel_token = None, None
    try:
        from backend.shared.python_utils.tracing.ws_span_helper import start_ws_handler_span, end_ws_handler_span
        _otel_span, _otel_token = start_ws_handler_span("delete_draft_embed", user_id, payload, user_otel_attrs)
    except Exception:
        pass
    try:
        embed_id = payload.get("embed_id")
        chat_id = payload.get("chat_id")  # Optional context — not required for deletion

        if not embed_id:
            logger.warning(
                f"User {user_id}, Device {device_fingerprint_hash}: "
                "Received delete_draft_embed without embed_id."
            )
            await manager.send_personal_message(
                message={
                    "type": "error",
                    "payload": {"message": "Missing embed_id for delete_draft_embed"},
                },
                user_id=user_id,
                device_fingerprint_hash=device_fingerprint_hash,
            )
            return

        logger.info(
            f"User {user_id}, Device {device_fingerprint_hash}: "
            f"Received delete_draft_embed for embed_id={embed_id} (chat_id={chat_id})."
        )

        # Remove embed from Redis cache — it was cached by the upload server immediately
        # after upload (via /internal/uploads/cache-embed) so that app skills like
        # images-view and pdf-read could find it server-side.  Now that the user has
        # removed it from the draft, clear it from the cache so skill tools don't
        # accidentally use a deleted file.
        try:
            if chat_id:
                await cache_service.remove_embed_from_chat_cache(chat_id, embed_id)
                logger.debug(
                    f"User {user_id}: Removed embed {embed_id} from Redis cache (chat {chat_id})."
                )
        except Exception as cache_err:
            # Non-fatal — the embed will expire from Redis naturally.
            logger.warning(
                f"User {user_id}: Failed to remove draft embed {embed_id} from cache: {cache_err}"
            )

        # Queue Celery task to delete S3 files and the upload_files Directus record.
        # This runs asynchronously so the WebSocket response is not blocked by slow S3 I/O.
        try:
            app.send_task(
                name="app.tasks.persistence_tasks.persist_delete_draft_embed",
                kwargs={
                    "user_id": user_id,
                    "embed_id": embed_id,
                    "chat_id": chat_id,
                },
                queue="persistence",
            )
            logger.info(
                f"User {user_id}: Queued Celery task persist_delete_draft_embed "
                f"for embed_id={embed_id}."
            )
        except Exception as celery_err:
            # Log but do not block the client response.
            logger.error(
                f"User {user_id}: Failed to queue persist_delete_draft_embed "
                f"for embed_id={embed_id}: {celery_err}",
                exc_info=True,
            )

        # Broadcast 'draft_embed_deleted' to all other devices of the same user so they
        # can delete the embed from their local IndexedDB EmbedStore (if it was synced
        # there via update_draft cross-device sync).
        await manager.broadcast_to_user(
            message={
                "type": "draft_embed_deleted",
                "payload": {
                    "embed_id": embed_id,
                    "chat_id": chat_id,
                },
            },
            user_id=user_id,
            exclude_device_hash=device_fingerprint_hash,  # Don't send back to the originating device
        )
        logger.info(
            f"User {user_id}: Broadcasted draft_embed_deleted for embed_id={embed_id} to other devices."
        )

    finally:
        if _otel_span is not None:
            try:
                from backend.shared.python_utils.tracing.ws_span_helper import end_ws_handler_span as _end_span
                _end_span(_otel_span, _otel_token)
            except Exception:
                pass
