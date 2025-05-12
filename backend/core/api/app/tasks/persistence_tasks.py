import logging
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any
from typing import Optional

from app.tasks.celery_config import app
from app.services.directus import chat_methods # Assuming this module will have the necessary functions
from app.services.directus import DirectusService
from app.services.cache import CacheService
from app.utils.encryption import EncryptionService # Assuming EncryptionService handles Vault interactions

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

@app.task(name="app.tasks.persistence_tasks.persist_chat_title", bind=True)
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

@app.task(name="app.tasks.persistence_tasks.persist_new_message", bind=True)
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

@app.task(name="app.tasks.persistence_tasks.persist_user_draft", bind=True)
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
# --- Task for Logout Persistence ---

async def _async_ensure_chat_and_persist_draft_on_logout(
    hashed_user_id: str, # Hashed user ID, used for both cache and DB operations
    chat_id: str,
    encrypted_draft_content: Optional[str],
    draft_version: int,
    # Removed chat_metadata_for_creation - Task generates/fetches needed data itself.
    task_id: str
):
    """
    Async logic called during logout:
    1. Ensures the chat entry exists in Directus (creates if not).
    2. Persists the user's draft (creates or updates).
    3. Deletes the draft from cache upon successful persistence.
    """
    logger.info(
        f"Task _async_ensure_chat_and_persist_draft_on_logout (task_id: {task_id}): "
        f"Processing chat {chat_id}, draft version {draft_version} for user (hashed) {hashed_user_id}"
    )
    directus_service = None
    cache_service = None
    try:
        # Need instances of services within the task
        # Ensure proper initialization/dependency injection if needed in a real setup
        # Need instances of services within the task
        directus_service = DirectusService()
        cache_service = CacheService()
        encryption_service = EncryptionService() # Assuming default constructor works

        await directus_service.ensure_auth_token()

        # 1. Ensure Chat Exists
        chat_metadata = await chat_methods.get_chat_metadata(directus_service, chat_id)
        chat_exists = chat_metadata is not None

        if not chat_exists:
            logger.info(f"Chat {chat_id} not found in Directus. Attempting creation (task_id: {task_id}).")

            # Generate a new chat-specific key and get its reference from Vault
            # Ensure the Vault key exists for this chat_id.
            # create_chat_key returns True on success/existence, False on failure.
            try:
                success = await encryption_service.create_chat_key(chat_id)
                if not success:
                    # If create_chat_key returned False, raise an error.
                    raise ValueError("Encryption service failed to create/ensure the chat key in Vault.")
                logger.info(f"Successfully created/ensured Vault key for chat {chat_id} (using chat_id as key name). Task_id: {task_id}")
            except Exception as key_gen_err:
                 logger.error(f"Failed to create/ensure Vault key for new chat {chat_id}: {key_gen_err}. Task_id: {task_id}", exc_info=True)
                 return # Stop if key creation/check fails

            # Vault key is ensured, proceed with Directus chat creation without storing the reference.
            now_iso = datetime.now(timezone.utc).isoformat()
            # Construct payload according to chats.yml schema (omitting vault_key_reference)
            creation_payload = {
                "id": chat_id,
                "hashed_user_id": hashed_user_id, # User who initiated the draft/chat
                "encrypted_title": "", # Default empty title for new chat from draft
                "messages_version": 0, # Initial version
                "title_version": 0,    # Initial version
                "last_edited_overall_timestamp": now_iso, # Set to current time on creation
                "unread_count": 0, # Initial count
                "created_at": now_iso,
                "updated_at": now_iso,
                "last_message_timestamp": now_iso # Can be same as created_at initially
            }

            logger.debug(f"Attempting to create chat {chat_id} with payload keys: {creation_payload.keys()}")
            created_chat = await chat_methods.create_chat_in_directus(directus_service, creation_payload)
            if not created_chat:
                logger.error(f"Failed to create chat {chat_id} in Directus during logout persistence (task_id: {task_id}). Aborting draft persistence.")
                return # Stop if chat creation fails
            logger.info(f"Successfully created chat {chat_id} in Directus (task_id: {task_id}).")
            chat_exists = True # Mark as existing now

        if not chat_exists:
             logger.error(f"Chat {chat_id} still not found after creation attempt (task_id: {task_id}). Aborting draft persistence.")
             return # Should not happen if creation succeeded or it existed initially

        # 2. Persist Draft (Create or Update)
        persist_success = False
        existing_draft = await chat_methods.get_user_draft_from_directus(
            directus_service, hashed_user_id, chat_id
        )
        now_iso = datetime.now(timezone.utc).isoformat()

        if existing_draft:
            existing_draft_id = existing_draft["id"]
            existing_version = existing_draft.get("version", -1) # Use -1 to ensure first version (0) is newer
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
                updated_draft = await chat_methods.update_user_draft_in_directus(
                    directus_service, existing_draft_id, fields_to_update
                )
                if updated_draft:
                    logger.info(f"Successfully updated draft {existing_draft_id} (task_id: {task_id}).")
                    persist_success = True
                else:
                    logger.error(f"Failed to update draft {existing_draft_id} (task_id: {task_id}).")
            else:
                logger.info(
                    f"Skipping update for draft {existing_draft_id} (task_id: {task_id}). Incoming version {draft_version} "
                    f"not newer than existing {existing_version}."
                )
                persist_success = True # No update needed, count as success for cache deletion
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
            # create_user_draft_in_directus now returns the created item dict or None
            created_draft_data = await chat_methods.create_user_draft_in_directus(
                directus_service, draft_payload
            )
            if created_draft_data:
                logger.info(f"Successfully created new draft for user {hashed_user_id}, chat {chat_id} (task_id: {task_id}). ID: {created_draft_data.get('id')}")
                persist_success = True
            else:
                logger.error(f"Failed to create new draft for user {hashed_user_id}, chat {chat_id} (task_id: {task_id}).")

        # 3. Delete Draft from Cache if Persistence Succeeded
        if persist_success:
            # Use the hashed_user_id for the cache key
            draft_cache_key = cache_service._get_user_chat_draft_key(hashed_user_id, chat_id)
            deleted = await cache_service.delete(draft_cache_key)
            if deleted:
                logger.info(f"Successfully deleted draft from cache key {draft_cache_key} (task_id: {task_id}).")
            else:
                logger.warning(f"Failed to delete draft from cache key {draft_cache_key} (task_id: {task_id}). Might have already expired or been deleted.")
        else:
             logger.warning(f"Skipping cache deletion for chat {chat_id}, user {hashed_user_id} as persistence failed (task_id: {task_id}).")

    except Exception as e:
        logger.error(
            f"Error in _async_ensure_chat_and_persist_draft_on_logout for user {hashed_user_id}, chat {chat_id} (task_id: {task_id}): {e}",
            exc_info=True
        )
        # Consider re-raising for Celery's retry mechanisms if configured
        # raise

@app.task(name="app.tasks.persistence_tasks.ensure_chat_and_persist_draft_on_logout", bind=True)
def ensure_chat_and_persist_draft_on_logout_task(
    self,
    hashed_user_id: str, # Use explicit hashed_user_id
    chat_id: str,
    encrypted_draft_content: Optional[str],
    draft_version: int
    # Removed chat_metadata_for_creation
):
    task_id = self.request.id if self and hasattr(self, 'request') else 'UNKNOWN_TASK_ID'
    logger.info(f"SYNC_WRAPPER: ensure_chat_and_persist_draft_on_logout_task for user {hashed_user_id}, chat {chat_id}, task_id: {task_id}")
    loop = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_async_ensure_chat_and_persist_draft_on_logout(
            hashed_user_id, chat_id, encrypted_draft_content, draft_version, task_id
        ))
        return True # Indicate success
    except Exception as e:
        logger.error(f"SYNC_WRAPPER_ERROR: ensure_chat_and_persist_draft_on_logout_task for user {hashed_user_id}, chat {chat_id}, task_id: {task_id}: {e}", exc_info=True)
        return False # Indicate failure
    finally:
        if loop:
            loop.close()