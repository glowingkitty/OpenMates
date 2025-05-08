import logging
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any

from app.tasks.celery_config import celery_app
from app.services.directus.directus import DirectusService
from app.services.directus import chat_methods # Assuming this module will have the necessary functions

logger = logging.getLogger(__name__)

@celery_app.task(name="persistence.persist_chat_title")
async def persist_chat_title_task(chat_id: str, encrypted_title: str, title_version: int):
    """
    Persists an updated chat title and its version to Directus.
    """
    logger.info(f"Task persist_chat_title_task: Persisting title for chat {chat_id}, version: {title_version}")
    directus_service = DirectusService()
    await directus_service.ensure_auth_token()

    fields_to_update = {
        "encrypted_title": encrypted_title,
        "title_version": title_version,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }

    try:
        updated = await chat_methods.update_chat_fields_in_directus(
            directus_service=directus_service,
            chat_id=chat_id,
            fields_to_update=fields_to_update
        )
        if updated:
            logger.info(f"Successfully persisted title for chat {chat_id} to Directus. New title_version: {title_version}")
        else:
            logger.error(f"Failed to persist title for chat {chat_id} to Directus. Update operation returned false.")
    except Exception as e:
        logger.error(f"Error in persist_chat_title_task for chat {chat_id}: {e}", exc_info=True)
        # Consider re-raising for Celery's retry mechanisms if configured
        # raise


@celery_app.task(name="persistence.persist_new_message")
async def persist_new_message_task(message_payload: Dict[str, Any], new_chat_messages_version: int, new_last_edited_overall_timestamp: int):
    """
    Persists a new message to Directus and updates the parent chat's messages_version 
    and last_edited_overall_timestamp.
    
    message_payload should conform to the structure needed by chat_methods.create_message_in_directus,
    e.g., {"id": "...", "chat_id": "...", "encrypted_content": "...", "sender_name": "...", "timestamp": "..."}
    """
    chat_id = message_payload.get("chat_id")
    message_id = message_payload.get("id")
    logger.info(f"Task persist_new_message_task: Persisting message {message_id} for chat {chat_id}. New chat messages_v: {new_chat_messages_version}")
    
    if not chat_id or not message_id:
        logger.error(f"persist_new_message_task: Missing chat_id or message_id in payload. Payload: {message_payload}")
        return

    directus_service = DirectusService()
    await directus_service.ensure_auth_token()

    try:
        # 1. Create the message in Directus
        # Assuming chat_methods.create_message_in_directus handles the creation
        # It should take the directus_service and the message_payload
        created_message = await chat_methods.create_message_in_directus(
            directus_service=directus_service,
            message_data=message_payload # Ensure this payload matches what create_message_in_directus expects
        )

        if not created_message:
            logger.error(f"Failed to create message {message_id} for chat {chat_id} in Directus.")
            # Depending on desired atomicity, might stop here or attempt chat update anyway
            return

        logger.info(f"Successfully created message {message_id} for chat {chat_id} in Directus.")

        # 2. Update the parent chat's metadata
        chat_fields_to_update = {
            "messages_version": new_chat_messages_version,
            "last_edited_overall_timestamp": datetime.fromtimestamp(new_last_edited_overall_timestamp, tz=timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        updated_chat = await chat_methods.update_chat_fields_in_directus(
            directus_service=directus_service,
            chat_id=chat_id,
            fields_to_update=chat_fields_to_update
        )

        if updated_chat:
            logger.info(f"Successfully updated chat {chat_id} metadata (messages_version: {new_chat_messages_version}, last_edited_overall_timestamp) in Directus.")
        else:
            logger.error(f"Failed to update chat {chat_id} metadata in Directus after message creation.")

    except Exception as e:
        logger.error(f"Error in persist_new_message_task for message {message_id}, chat {chat_id}: {e}", exc_info=True)
        # Consider re-raising for Celery's retry mechanisms
        # raise

# Note: The `chat_methods.update_chat_fields_in_directus` and `chat_methods.create_message_in_directus`
# are assumed to exist or will be created in the `app.services.directus.chat_methods` module.
# These methods would encapsulate the actual Directus SDK calls.