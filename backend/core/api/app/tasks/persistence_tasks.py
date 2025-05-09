import logging
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any

from app.tasks.celery_config import celery_app
from app.services.directus.directus import DirectusService
from app.services.directus import chat_methods # Assuming this module will have the necessary functions

logger = logging.getLogger(__name__)

async def _async_persist_chat_title_task(chat_id: str, encrypted_title: str, title_version: int, task_id: str):
    """
    Async logic for persisting an updated chat title.
    """
    logger.info(f"Task _async_persist_chat_title_task (task_id: {task_id}): Persisting title for chat {chat_id}, version: {title_version}")
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
            logger.info(f"Successfully persisted title for chat {chat_id} (task_id: {task_id}). New title_version: {title_version}")
        else:
            logger.error(f"Failed to persist title for chat {chat_id} (task_id: {task_id}). Update operation returned false.")
    except Exception as e:
        logger.error(f"Error in _async_persist_chat_title_task for chat {chat_id} (task_id: {task_id}): {e}", exc_info=True)
        # Consider re-raising for Celery's retry mechanisms if configured
        # raise

@celery_app.task(name="persistence.persist_chat_title", bind=True)
def persist_chat_title_task(self, chat_id: str, encrypted_title: str, title_version: int):
    task_id = self.request.id if self and hasattr(self, 'request') else 'UNKNOWN_TASK_ID'
    logger.info(f"SYNC_WRAPPER: persist_chat_title_task for chat {chat_id}, task_id: {task_id}")
    loop = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_async_persist_chat_title_task(chat_id, encrypted_title, title_version, task_id))
    except Exception as e:
        logger.error(f"SYNC_WRAPPER_ERROR: persist_chat_title_task for chat {chat_id}, task_id: {task_id}: {e}", exc_info=True)
        raise # Re-raise to let Celery handle retries/failure
    finally:
        if loop:
            loop.close()

async def _async_persist_new_message_task(message_payload: Dict[str, Any], new_chat_messages_version: int, new_last_edited_overall_timestamp: int, task_id: str):
    """
    Async logic for persisting a new message and updating parent chat metadata.
    """
    chat_id = message_payload.get("chat_id")
    message_id = message_payload.get("id")
    logger.info(f"Task _async_persist_new_message_task (task_id: {task_id}): Persisting message {message_id} for chat {chat_id}. New chat messages_v: {new_chat_messages_version}")
    
    if not chat_id or not message_id:
        logger.error(f"_async_persist_new_message_task (task_id: {task_id}): Missing chat_id or message_id. Payload: {message_payload}")
        return

    directus_service = DirectusService()
    await directus_service.ensure_auth_token()

    try:
        created_message = await chat_methods.create_message_in_directus(
            directus_service=directus_service,
            message_data=message_payload
        )

        if not created_message:
            logger.error(f"Failed to create message {message_id} for chat {chat_id} (task_id: {task_id}) in Directus.")
            return

        logger.info(f"Successfully created message {message_id} for chat {chat_id} (task_id: {task_id}) in Directus.")

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
            logger.info(f"Successfully updated chat {chat_id} metadata (task_id: {task_id}).")
        else:
            logger.error(f"Failed to update chat {chat_id} metadata (task_id: {task_id}) after message creation.")

    except Exception as e:
        logger.error(f"Error in _async_persist_new_message_task for message {message_id}, chat {chat_id} (task_id: {task_id}): {e}", exc_info=True)
        # raise

@celery_app.task(name="persistence.persist_new_message", bind=True)
def persist_new_message_task(self, message_payload: Dict[str, Any], new_chat_messages_version: int, new_last_edited_overall_timestamp: int):
    task_id = self.request.id if self and hasattr(self, 'request') else 'UNKNOWN_TASK_ID'
    logger.info(f"SYNC_WRAPPER: persist_new_message_task for chat {message_payload.get('chat_id')}, task_id: {task_id}")
    loop = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_async_persist_new_message_task(message_payload, new_chat_messages_version, new_last_edited_overall_timestamp, task_id))
    except Exception as e:
        logger.error(f"SYNC_WRAPPER_ERROR: persist_new_message_task for chat {message_payload.get('chat_id')}, task_id: {task_id}: {e}", exc_info=True)
        raise
    finally:
        if loop:
            loop.close()

async def _async_persist_user_draft_task(
    hashed_user_id: str,
    chat_id: str,
    encrypted_draft_content: Optional[str],
    draft_version: int,
    task_id: str
):
    """
    Async logic for persisting a user's specific draft.
    """
    logger.info(
        f"Task _async_persist_user_draft_task (task_id: {task_id}): Persisting draft for user (hashed): {hashed_user_id}, "
        f"chat {chat_id}, version: {draft_version}"
    )
    directus_service = DirectusService()
    await directus_service.ensure_auth_token()

    try:
        existing_draft = await chat_methods.get_user_draft_from_directus(
            directus_service, hashed_user_id, chat_id
        )
        now_iso = datetime.now(timezone.utc).isoformat()

        if existing_draft:
            existing_draft_id = existing_draft["id"]
            existing_version = existing_draft.get("version", 0)
            if draft_version > existing_version:
                logger.info(
                    f"Updating existing draft {existing_draft_id} (task_id: {task_id}) "
                    f"from version {existing_version} to {draft_version}."
                )
                fields_to_update = {
                    "encrypted_content": encrypted_draft_content,
                    "version": draft_version,
                    "last_edited_timestamp": now_iso,
                    "updated_at": now_iso
                }
                updated = await chat_methods.update_user_draft_in_directus(
                    directus_service, existing_draft_id, fields_to_update
                )
                if updated:
                    logger.info(f"Successfully updated draft {existing_draft_id} (task_id: {task_id}).")
                else:
                    logger.error(f"Failed to update draft {existing_draft_id} (task_id: {task_id}).")
            else:
                logger.info(
                    f"Skipping update for draft {existing_draft_id} (task_id: {task_id}). Incoming version {draft_version} "
                    f"not newer than {existing_version}."
                )
        else:
            logger.info(f"Creating new draft for user {hashed_user_id}, chat {chat_id}, version {draft_version} (task_id: {task_id}).")
            draft_payload = {
                "chat_id": chat_id,
                "hashed_user_id": hashed_user_id,
                "encrypted_content": encrypted_draft_content,
                "version": draft_version,
                "last_edited_timestamp": now_iso,
                "created_at": now_iso,
                "updated_at": now_iso
            }
            created = await chat_methods.create_user_draft_in_directus(
                directus_service, draft_payload
            )
            if created:
                logger.info(f"Successfully created new draft for user {hashed_user_id}, chat {chat_id} (task_id: {task_id}). ID: {created.get('id')}")
            else:
                logger.error(f"Failed to create new draft for user {hashed_user_id}, chat {chat_id} (task_id: {task_id}).")
    except Exception as e:
        logger.error(
            f"Error in _async_persist_user_draft_task for user {hashed_user_id}, chat {chat_id} (task_id: {task_id}): {e}",
            exc_info=True
        )
        # raise

@celery_app.task(name="persistence.persist_user_draft", bind=True)
def persist_user_draft_task(
    self,
    hashed_user_id: str,
    chat_id: str,
    encrypted_draft_content: Optional[str],
    draft_version: int
):
    task_id = self.request.id if self and hasattr(self, 'request') else 'UNKNOWN_TASK_ID'
    logger.info(f"SYNC_WRAPPER: persist_user_draft_task for user {hashed_user_id}, chat {chat_id}, task_id: {task_id}")
    loop = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_async_persist_user_draft_task(
            hashed_user_id, chat_id, encrypted_draft_content, draft_version, task_id
        ))
    except Exception as e:
        logger.error(f"SYNC_WRAPPER_ERROR: persist_user_draft_task for user {hashed_user_id}, chat {chat_id}, task_id: {task_id}: {e}", exc_info=True)
        raise
    finally:
        if loop:
            loop.close()

# TODO: Implement the following methods in app.services.directus.chat_methods:
# - get_user_draft_from_directus(directus_service, hashed_user_id, chat_id) -> Optional[Dict]
# - create_user_draft_in_directus(directus_service, draft_data: Dict) -> Optional[Dict]
# - update_user_draft_in_directus(directus_service, draft_id: str, fields_to_update: Dict) -> Optional[Dict]

# TODO: Implement periodic task for persisting drafts approaching cache TTL expiry.
# This task would scan relevant cache keys (e.g., user:{user_id}:chat:{chat_id}:draft),
# compare versions with Directus 'Drafts' table, and dispatch persist_user_draft_task if needed.

# TODO: Implement draft persistence on user logout/deactivation.
# This would iterate through the user's cached drafts and dispatch persist_user_draft_task.