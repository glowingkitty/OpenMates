# backend/core/api/app/routes/handlers/websocket_handlers/cancel_pdf_processing_handler.py
#
# Handles the 'cancel_pdf_processing' WebSocket message.
#
# Background: When a user uploads a PDF and OCR processing has started (embed
# status='processing'), they can press the Stop button to cancel the task.
# This handler:
#   1. Calls POST /internal/pdf/cancel to revoke the Celery OCR task.
#   2. Triggers deletion of the S3 files and Directus record (same as delete_draft_embed).
#   3. Broadcasts 'draft_embed_deleted' to other devices for IndexedDB cleanup.
#
# The client-side node deletion (removing the embed from the TipTap editor) is
# handled by Embed.ts before this WS message is sent.

import logging
import os
from typing import Dict, Any

import httpx
from fastapi import WebSocket

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.routes.connection_manager import ConnectionManager
from backend.core.api.app.tasks.celery_config import app

logger = logging.getLogger(__name__)

# Internal API config — same constants used by other handlers (e.g. process_task.py).
INTERNAL_API_BASE_URL = os.environ.get("INTERNAL_API_BASE_URL", "http://api:8000")
INTERNAL_API_SHARED_TOKEN = os.environ.get("INTERNAL_API_SHARED_TOKEN", "")


async def handle_cancel_pdf_processing(
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any],
) -> None:
    """
    Handle the 'cancel_pdf_processing' message from a WebSocket client.

    Expected payload:
        {
            "embed_id": "<uuid>",   # The server-assigned embed UUID
            "chat_id":  "<uuid>"    # The draft chat this embed belongs to (optional, for logging)
        }

    Flow:
      1. Validate payload.
      2. POST to /internal/pdf/cancel to revoke the Celery OCR task.
      3. Queue Celery task 'persist_delete_draft_embed' to delete S3 + Directus record.
      4. Remove embed from Redis cache (if cached).
      5. Broadcast 'draft_embed_deleted' to ALL other devices so they clean up IndexedDB.
    """
    embed_id = payload.get("embed_id")
    chat_id = payload.get("chat_id")  # Optional context

    if not embed_id:
        logger.warning(
            f"User {user_id}, Device {device_fingerprint_hash}: "
            "Received cancel_pdf_processing without embed_id."
        )
        await manager.send_personal_message(
            message={
                "type": "error",
                "payload": {"message": "Missing embed_id for cancel_pdf_processing"},
            },
            user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash,
        )
        return

    logger.info(
        f"User {user_id}, Device {device_fingerprint_hash}: "
        f"Received cancel_pdf_processing for embed_id={embed_id} (chat_id={chat_id})."
    )

    # 1. Revoke the Celery OCR task via the internal API.
    #    This is a best-effort call — if the task already finished, the cancel is a no-op.
    try:
        headers = {
            "Content-Type": "application/json",
            "X-Internal-Service-Token": INTERNAL_API_SHARED_TOKEN,
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{INTERNAL_API_BASE_URL}/internal/pdf/cancel",
                json={"embed_id": embed_id, "user_id": user_id},
                headers=headers,
            )
        if resp.status_code == 200:
            result = resp.json()
            logger.info(
                f"User {user_id}: PDF cancel response: status={result.get('status')}, "
                f"embed={embed_id[:8]}..."
            )
        else:
            logger.warning(
                f"User {user_id}: PDF cancel returned {resp.status_code}: {resp.text[:200]}"
            )
    except Exception as cancel_err:
        # Non-fatal — proceed with cleanup even if revocation failed.
        logger.error(
            f"User {user_id}: Failed to call /internal/pdf/cancel for embed {embed_id[:8]}: {cancel_err}",
            exc_info=True,
        )

    # 2. Remove embed from Redis cache.
    try:
        if chat_id:
            await cache_service.remove_embed_from_chat_cache(chat_id, embed_id)
            logger.debug(
                f"User {user_id}: Removed embed {embed_id} from Redis cache (chat {chat_id})."
            )
    except Exception as cache_err:
        # Non-fatal.
        logger.warning(
            f"User {user_id}: Failed to remove PDF embed {embed_id} from cache: {cache_err}"
        )

    # 3. Queue Celery task to delete S3 files and the upload_files Directus record.
    #    Same task used by delete_draft_embed_handler — handles the file cleanup generically.
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
            f"User {user_id}: Queued persist_delete_draft_embed for cancelled PDF embed {embed_id}."
        )
    except Exception as celery_err:
        # Log but do not block the client response.
        logger.error(
            f"User {user_id}: Failed to queue persist_delete_draft_embed "
            f"for embed {embed_id}: {celery_err}",
            exc_info=True,
        )

    # 4. Broadcast 'draft_embed_deleted' to all other devices so they clean up IndexedDB.
    await manager.broadcast_to_user(
        message={
            "type": "draft_embed_deleted",
            "payload": {
                "embed_id": embed_id,
                "chat_id": chat_id,
            },
        },
        user_id=user_id,
        exclude_device_hash=device_fingerprint_hash,
    )
    logger.info(
        f"User {user_id}: Broadcasted draft_embed_deleted for cancelled PDF embed {embed_id}."
    )
