import logging
from typing import Dict, Any, Optional
import datetime # For compliance log timestamp

from fastapi import WebSocket

from app.services.cache import CacheService
from app.services.directus.directus import DirectusService # Keep for Celery task context if needed
from app.utils.encryption import EncryptionService # Keep for Celery task context if needed
from app.routes.connection_manager import ConnectionManager
from app.services.compliance import ComplianceService # For compliance logging
# Import the Celery app instance
from app.tasks.celery_config import app

logger = logging.getLogger(__name__)

async def handle_delete_chat(
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService, # Passed to handler, may not be directly used but available
    encryption_service: EncryptionService, # Passed to handler, may not be directly used but available
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any]
):
    chat_id = payload.get("chatId")
    if not chat_id:
        logger.warning(f"Received delete_chat without chatId from {user_id}/{device_fingerprint_hash}")
        await manager.send_personal_message(
            message={"type": "error", "payload": {"message": "Missing chatId for delete_chat"}},
            user_id=user_id, device_fingerprint_hash=device_fingerprint_hash
        )
        return

    logger.info(f"Received delete_chat request for chat {chat_id} from {user_id}/{device_fingerprint_hash}")

    try:
        # 1. Mark chat as deleted in general cache (tombstone)
        # Cached drafts will be allowed to expire naturally.
        # The Celery task is responsible for deleting all drafts from Directus.
        removed_from_set = await cache_service.remove_chat_from_ids_versions(user_id, chat_id)
        if removed_from_set:
             logger.info(f"Removed chat {chat_id} from user:{user_id}:chat_ids_versions sorted set.")
        else:
             logger.warning(f"Chat {chat_id} not found in user:{user_id}:chat_ids_versions sorted set during delete.")

        client = await cache_service.client
        deleted_specific_keys_count = 0
        if client:
            async with client.pipeline(transaction=False) as pipe:
                pipe.delete(cache_service._get_chat_versions_key(user_id, chat_id))
                pipe.delete(cache_service._get_chat_list_item_data_key(user_id, chat_id))
                pipe.delete(cache_service._get_chat_messages_key(user_id, chat_id))
                results = await pipe.execute()
                deleted_specific_keys_count = sum(results)
                logger.info(f"Deleted specific general cache keys for chat {chat_id} (user: {user_id}). Results: {results}")
        else:
             logger.error(f"Cache client not available, cannot delete specific general keys for chat {chat_id}.")
        
        tombstone_success = removed_from_set or deleted_specific_keys_count > 0
        if tombstone_success:
            logger.info(f"Successfully tombstoned chat {chat_id} in cache for user {user_id}.")
        else:
            logger.warning(f"Failed to fully tombstone chat {chat_id} in cache for user {user_id}.")

        # 3. Trigger Celery task to delete chat from Directus and ALL associated drafts
        try:
            # Use app.send_task for explicit task dispatch
            app.send_task(
                name='app.tasks.persistence_tasks.persist_delete_chat', # Full path to the task
                kwargs={'user_id': user_id, 'chat_id': chat_id},
                queue='persistence' # Assign to the 'persistence' queue
            )
            logger.info(f"Successfully queued Celery task persist_delete_chat for chat {chat_id}, initiated by user {user_id}, to queue 'persistence'.")
        except Exception as celery_e:
            logger.error(f"Failed to queue Celery task for chat deletion {chat_id}, user {user_id}: {celery_e}", exc_info=True)

        # 4. Log compliance event
        ComplianceService.log_chat_deletion(
            user_id=user_id,
            chat_id=chat_id,
            device_fingerprint_hash=device_fingerprint_hash,
            details={"source": "websocket_request"}
        )
        logger.info(f"Compliance event logged for chat deletion: chat_id {chat_id}, user_id {user_id}")

        # 5. Broadcast deletion confirmation to all user's devices
        await manager.broadcast_to_user(
            {
                "type": "chat_deleted",
                "payload": {"chat_id": chat_id, "tombstone": True}
            },
            user_id,
            exclude_device_hash=None
        )
        logger.info(f"Broadcasted chat_deleted event for chat {chat_id} to user {user_id}.")

    except Exception as e:
        logger.error(f"Error processing delete_chat for chat {chat_id}, user {user_id}: {e}", exc_info=True)
        await manager.send_personal_message(
            message={"type": "error", "payload": {"message": f"Failed to process delete request for chat {chat_id}", "chat_id": chat_id}},
            user_id=user_id, device_fingerprint_hash=device_fingerprint_hash
        )