# backend/core/api/app/routes/handlers/websocket_handlers/post_processing_metadata_handler.py
import logging
from typing import Dict, Any
from datetime import datetime, timezone

from fastapi import WebSocket

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.routes.connection_manager import ConnectionManager
from backend.core.api.app.tasks.celery_config import app as celery_app

logger = logging.getLogger(__name__)


async def handle_post_processing_metadata(
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    encryption_service: EncryptionService,
    user_id: str,
    user_id_hash: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any]
):
    """
    Handles client-encrypted post-processing metadata sync to Directus.
    Client sends encrypted suggestions, summary, and tags after receiving plaintext from server.

    Expected payload structure:
    {
        "chat_id": "...",
        "encrypted_follow_up_suggestions": "...",  // Encrypted array (max 18)
        "encrypted_new_chat_suggestions": ["...", "..."],  // Array of encrypted strings (max 6)
        "encrypted_chat_summary": "...",  // Encrypted summary
        "encrypted_chat_tags": "..."  // Encrypted array of tags (max 10)
    }

    All fields are encrypted CLIENT-SIDE (not server-encrypted) for zero-knowledge storage.
    """
    try:
        chat_id = payload.get("chat_id")
        encrypted_follow_up_suggestions = payload.get("encrypted_follow_up_suggestions")
        encrypted_new_chat_suggestions = payload.get("encrypted_new_chat_suggestions", [])
        encrypted_chat_summary = payload.get("encrypted_chat_summary")
        encrypted_chat_tags = payload.get("encrypted_chat_tags")

        if not chat_id:
            logger.error(f"Missing chat_id in post-processing metadata from {user_id}")
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Missing chat_id in post-processing metadata"}},
                user_id,
                device_fingerprint_hash
            )
            return

        logger.info(f"Processing post-processing metadata for chat {chat_id} from {user_id}")

        # Build update fields for Directus
        chat_update_fields = {}

        if encrypted_follow_up_suggestions:
            chat_update_fields["encrypted_follow_up_request_suggestions"] = encrypted_follow_up_suggestions

        if encrypted_new_chat_suggestions and len(encrypted_new_chat_suggestions) > 0:
            celery_app.send_task(
                "app.tasks.persistence_tasks.persist_new_chat_suggestions",
                args=[user_id_hash, chat_id, encrypted_new_chat_suggestions[:6]],
                queue="persistence"
            )
            logger.info(f"Queued new chat suggestions task for chat {chat_id} ({len(encrypted_new_chat_suggestions[:6])} suggestions)")

        if encrypted_chat_summary:
            chat_update_fields["encrypted_chat_summary"] = encrypted_chat_summary

        if encrypted_chat_tags:
            chat_update_fields["encrypted_chat_tags"] = encrypted_chat_tags

        if not chat_update_fields:
            logger.warning(f"No metadata fields to update for chat {chat_id}")
            return

        # Add updated_at timestamp
        now_ts = int(datetime.now(timezone.utc).timestamp())
        chat_update_fields["updated_at"] = now_ts

        logger.info(f"Storing encrypted post-processing metadata for chat {chat_id}: {list(chat_update_fields.keys())}")

        # Queue task to update chat metadata in Directus
        celery_app.send_task(
            "app.tasks.persistence_tasks.persist_encrypted_chat_metadata",
            args=[chat_id, chat_update_fields, user_id_hash],
            queue="persistence"
        )
        logger.info(f"Queued post-processing metadata update task for chat {chat_id}")

        # Send confirmation to client
        await manager.send_personal_message(
            {
                "type": "post_processing_metadata_stored",
                "payload": {
                    "chat_id": chat_id,
                    "status": "queued_for_storage"
                }
            },
            user_id,
            device_fingerprint_hash
        )

        logger.info(f"Confirmed post-processing metadata storage for chat {chat_id}")

    except Exception as e:
        logger.error(f"Error handling post-processing metadata from {user_id}: {e}", exc_info=True)
        # Raise error instead of swallowing it
        raise RuntimeError(f"Failed to process post-processing metadata: {e}")
