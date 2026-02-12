import logging
from typing import Dict, Any

from fastapi import WebSocket

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.routes.connection_manager import ConnectionManager
# Import the Celery app instance
from backend.core.api.app.tasks.celery_config import app

logger = logging.getLogger(__name__)


async def handle_delete_message(
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    encryption_service: EncryptionService,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any]
):
    """
    Handles deletion of a single message from a chat.
    
    Flow:
    1. Validate payload (chatId + messageId required)
    2. Verify chat ownership
    3. Remove message from cache (both AI and sync lists)
    4. Queue Celery task to delete from Directus
    5. Broadcast message_deleted event to all user devices
    """
    chat_id = payload.get("chatId")
    message_id = payload.get("messageId")
    # Optional: embed IDs the client determined should be deleted (client computed hashes and checked sharing)
    embed_ids_to_delete = payload.get("embedIdsToDelete") or []

    if not chat_id or not message_id:
        logger.warning(f"Received delete_message without chatId or messageId from {user_id}/{device_fingerprint_hash}")
        await manager.send_personal_message(
            message={"type": "error", "payload": {"message": "Missing chatId or messageId for delete_message"}},
            user_id=user_id, device_fingerprint_hash=device_fingerprint_hash
        )
        return

    logger.info(
        f"Received delete_message request for message {message_id} in chat {chat_id} from {user_id}/{device_fingerprint_hash}"
        f" (embed_ids_to_delete: {len(embed_ids_to_delete)})"
    )

    try:
        # 1. Verify chat ownership before processing deletion
        try:
            is_owner = await directus_service.chat.check_chat_ownership(chat_id, user_id)
            if not is_owner:
                # Check if the chat exists at all - if not, treat as new/local chat (allowed)
                chat_metadata = await directus_service.chat.get_chat_metadata(chat_id)
                if chat_metadata:
                    logger.warning(
                        f"User {user_id} attempted to delete message {message_id} from chat {chat_id} they don't own. Rejecting."
                    )
                    await manager.send_personal_message(
                        message={
                            "type": "error",
                            "payload": {
                                "message": "You do not have permission to delete messages in this chat.",
                                "chat_id": chat_id,
                            },
                        },
                        user_id=user_id,
                        device_fingerprint_hash=device_fingerprint_hash,
                    )
                    return
                else:
                    # Chat does not exist in Directus - treat as local-only chat
                    logger.debug(
                        f"Chat {chat_id} not found in Directus during delete_message - treating as new/local chat (allowed)."
                    )
        except Exception as ownership_error:
            logger.error(
                f"Error verifying ownership for chat {chat_id}, user {user_id} during delete_message: {ownership_error}",
                exc_info=True,
            )
            # Fail open for local-only chats, fail closed for existing chats
            try:
                chat_metadata = await directus_service.chat.get_chat_metadata(chat_id)
                if chat_metadata:
                    await manager.send_personal_message(
                        message={
                            "type": "error",
                            "payload": {
                                "message": "Unable to verify chat permissions. Please try again.",
                                "chat_id": chat_id,
                            },
                        },
                        user_id=user_id,
                        device_fingerprint_hash=device_fingerprint_hash,
                    )
                    return
            except Exception:
                await manager.send_personal_message(
                    message={
                        "type": "error",
                        "payload": {
                            "message": "Unable to verify chat permissions. Please try again.",
                            "chat_id": chat_id,
                        },
                    },
                    user_id=user_id,
                    device_fingerprint_hash=device_fingerprint_hash,
                )
                return

        # 2. Remove message from cache (both AI inference cache and sync cache)
        try:
            removed = await cache_service.remove_message_from_cache(user_id, chat_id, message_id)
            if removed:
                logger.info(f"Removed message {message_id} from cache for chat {chat_id}")
            else:
                logger.debug(f"Message {message_id} not found in cache for chat {chat_id} (may not be cached)")
        except Exception as cache_error:
            logger.error(f"Error removing message {message_id} from cache: {cache_error}", exc_info=True)
            # Continue even if cache removal fails - Directus deletion is more important

        # 2b. Remove associated embeds from cache (if any)
        if embed_ids_to_delete:
            for embed_id in embed_ids_to_delete:
                try:
                    await cache_service.remove_embed_from_chat_cache(chat_id, embed_id)
                except Exception as embed_cache_err:
                    logger.warning(f"Failed to remove embed {embed_id} from cache: {embed_cache_err}")

        # 3. Queue Celery task to delete message (and embeds) from Directus
        try:
            app.send_task(
                name='app.tasks.persistence_tasks.persist_delete_message',
                kwargs={
                    'user_id': user_id,
                    'chat_id': chat_id,
                    'client_message_id': message_id,
                    'embed_ids_to_delete': embed_ids_to_delete,
                },
                queue='persistence'
            )
            logger.info(f"Queued Celery task persist_delete_message for message {message_id} in chat {chat_id}")
        except Exception as celery_e:
            logger.error(f"Failed to queue Celery task for message deletion {message_id}: {celery_e}", exc_info=True)

        # 4. Broadcast deletion confirmation to all user's devices
        # Include embed_ids_to_delete so other devices can clean up IndexedDB
        broadcast_payload = {"chat_id": chat_id, "message_id": message_id}
        if embed_ids_to_delete:
            broadcast_payload["embed_ids_to_delete"] = embed_ids_to_delete
        await manager.broadcast_to_user(
            {
                "type": "message_deleted",
                "payload": broadcast_payload
            },
            user_id,
            exclude_device_hash=None  # Send to ALL devices including the requesting one
        )
        logger.info(f"Broadcasted message_deleted event for message {message_id} in chat {chat_id} to user {user_id}")

    except Exception as e:
        logger.error(f"Error processing delete_message for message {message_id} in chat {chat_id}: {e}", exc_info=True)
        await manager.send_personal_message(
            message={"type": "error", "payload": {"message": f"Failed to delete message {message_id}", "chat_id": chat_id}},
            user_id=user_id, device_fingerprint_hash=device_fingerprint_hash
        )
