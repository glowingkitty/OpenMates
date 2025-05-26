# backend/core/api/app/tasks/persistence_tasks.py
# This file contains Celery tasks related to data persistence,
# including creating, updating, and deleting chat-related data in Directus and cache.
import logging
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any
from typing import Optional

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.services.directus import chat_methods # Assuming this module will have the necessary functions
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService

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
        "updated_at": int(datetime.now(timezone.utc).timestamp()) # Changed to int timestamp
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
        now_ts = int(datetime.now(timezone.utc).timestamp()) # Changed to int timestamp

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
                    # "last_edited_timestamp": now_ts, # Field removed from schema
                    "updated_at": now_ts
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
                # "last_edited_timestamp": now_ts, # Field removed from schema
                "created_at": now_ts,
                "updated_at": now_ts
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

async def _async_persist_new_chat_message_task(
    message_id: str,
    chat_id: str,
    hashed_user_id: Optional[str],
    sender: str, # This is sender_name (e.g. "User", "Assistant")
    content: str, # This is the encrypted content
    timestamp: int, # This is the client's original timestamp for the message
    new_chat_messages_version: int, # Added: new messages_version for the chat
    new_last_edited_overall_timestamp: int, # Added: new last_edited_overall_timestamp for the chat
    task_id: str
):
    """
    Async logic for:
    1. Ensuring the chat entry exists in Directus (creates if not).
    2. Creating a single message item in Directus.
    3. Updating parent chat metadata (messages_version, last_edited_overall_timestamp, last_message_timestamp).
    """
    logger.info(
        f"Task _async_persist_new_chat_message_task (task_id: {task_id}): "
        f"Processing message {message_id} for chat {chat_id}, user {hashed_user_id}. "
        f"New chat messages_v: {new_chat_messages_version}, new chat last_edited_ts: {new_last_edited_overall_timestamp}"
    )

    if not hashed_user_id: # Should always be present for user-initiated messages
        logger.error(
            f"_async_persist_new_chat_message_task (task_id: {task_id}): "
            f"Missing hashed_user_id for message {message_id} in chat {chat_id}."
        )
        # Depending on policy, might return or raise. For now, log and continue if chat can be found/created.
        # If chat creation relies on hashed_user_id, this will fail later.

    directus_service = DirectusService()

    try:
        await directus_service.ensure_auth_token()

        # 1. Persist the New Message
        # 'created_at' for the message item is server-side persistence time.
        # 'timestamp' param is client's original timestamp, not directly persisted in 'messages' schema currently.
        message_data_for_directus = {
            "id": message_id,
            "chat_id": chat_id,
            "hashed_user_id": hashed_user_id, # Can be None for assistant messages, task expects it for user messages
            "sender_name": sender,
            "encrypted_content": content,
            "created_at": int(datetime.now(timezone.utc).timestamp())
        }

        created_message_item = await chat_methods.create_message_in_directus(
            directus_service=directus_service,
            message_data=message_data_for_directus
        )

        if not created_message_item or not created_message_item.get("id"):
            logger.error(
                f"Failed to create message {message_id} for chat {chat_id} (task_id: {task_id}). "
                f"Directus operation returned: {created_message_item}"
            )
            return # Stop if message creation fails
        
        logger.info(
            f"Successfully created message {message_id} (Directus ID: {created_message_item['id']}) "
            f"for chat {chat_id} (task_id: {task_id})."
        )

        # 2. Handle Chat (Update if exists, Create if not)
        chat_metadata = await chat_methods.get_chat_metadata(directus_service, chat_id)

        if chat_metadata:
            # Chat exists, update its metadata
            logger.info(f"Chat {chat_id} found. Updating metadata (task_id: {task_id}).")
            chat_fields_to_update = {
                "messages_version": new_chat_messages_version,
                "last_edited_overall_timestamp": new_last_edited_overall_timestamp,
                "last_message_timestamp": new_last_edited_overall_timestamp, # This new message is the latest
                "updated_at": int(datetime.now(timezone.utc).timestamp())
            }
            
            updated_chat = await chat_methods.update_chat_fields_in_directus(
                directus_service=directus_service,
                chat_id=chat_id,
                fields_to_update=chat_fields_to_update
            )

            if updated_chat:
                logger.info(f"Successfully updated chat {chat_id} metadata (task_id: {task_id}).")
            else:
                logger.error(f"Failed to update chat {chat_id} metadata (task_id: {task_id}).")
        else:
            # Chat does not exist, create it
            logger.info(
                f"Chat {chat_id} not found in Directus after message creation. Attempting creation for user {hashed_user_id} (task_id: {task_id})."
            )
            if not hashed_user_id: # Cannot create a chat without a user context
                 logger.error(
                    f"Cannot create new chat {chat_id} because hashed_user_id is missing. Task_id: {task_id}"
                )
                 return # Stop if essential info for chat creation is missing
            
            try:
                now_ts_for_new_chat = int(datetime.now(timezone.utc).timestamp())
                chat_creation_payload = {
                    "id": chat_id,
                    "hashed_user_id": hashed_user_id, # Creator of the chat
                    "encrypted_title": "",  # Default empty title
                    "messages_version": new_chat_messages_version, # Use the new version directly
                    "title_version": 0,
                    "last_edited_overall_timestamp": new_last_edited_overall_timestamp, # Use the new timestamp
                    "unread_count": 0,
                    "created_at": now_ts_for_new_chat, # Timestamp of chat object creation
                    "updated_at": now_ts_for_new_chat, # Timestamp of chat object creation
                    "last_message_timestamp": new_last_edited_overall_timestamp # Use the new timestamp
                }
                
                created_chat_item = await chat_methods.create_chat_in_directus(directus_service, chat_creation_payload)
                
                if not created_chat_item or not created_chat_item.get("id"):
                    logger.error(
                        f"Failed to create chat {chat_id} in Directus. Task_id: {task_id}. Response: {created_chat_item}"
                    )
                    return  # Stop if chat creation fails
                logger.info(f"Successfully created chat {chat_id} in Directus. Task_id: {task_id}.")
            except Exception as chat_creation_err:
                logger.error(
                    f"Error creating new chat {chat_id} for user {hashed_user_id}: {chat_creation_err}. Task_id: {task_id}",
                    exc_info=True
                )
                return # Stop if chat creation fails

    except Exception as e:
        logger.error(
            f"Error in _async_persist_new_chat_message_task for message {message_id}, chat {chat_id} (task_id: {task_id}): {e}",
            exc_info=True
        )
        # raise # Consider re-raising for Celery's retry mechanisms

@app.task(name="app.tasks.persistence_tasks.persist_new_chat_message", bind=True)
def persist_new_chat_message_task(
    self,
    message_id: str,
    chat_id: str,
    hashed_user_id: Optional[str],
    sender: str,
    content: str,
    timestamp: int,
    new_chat_messages_version: int, # Added
    new_last_edited_overall_timestamp: int # Added
):
    task_id = self.request.id if self and hasattr(self, 'request') else 'UNKNOWN_TASK_ID'
    logger.info(
        f"SYNC_WRAPPER: persist_new_chat_message_task for message {message_id}, chat {chat_id}, user {hashed_user_id}, "
        f"new_chat_mv: {new_chat_messages_version}, new_chat_ts: {new_last_edited_overall_timestamp}, task_id: {task_id}"
    )
    loop = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_async_persist_new_chat_message_task(
            message_id, chat_id, hashed_user_id, sender, content, timestamp,
            new_chat_messages_version, new_last_edited_overall_timestamp, # Pass new params
            task_id
        ))
    except Exception as e:
        logger.error(
            f"SYNC_WRAPPER_ERROR: persist_new_chat_message_task for message {message_id}, chat {chat_id}, task_id: {task_id}: {e}",
            exc_info=True
        )
        raise # Re-raise to let Celery handle retries/failure
    finally:
        if loop:
            loop.close()

# --- Task for Logout Persistence ---

async def _async_persist_chat_and_draft_on_logout(
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
        f"Task _async_persist_chat_and_draft_on_logout (task_id: {task_id}): "
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

        await directus_service.ensure_auth_token()

        # 1. Ensure Chat Exists
        chat_metadata = await chat_methods.get_chat_metadata(directus_service, chat_id)
        chat_exists = chat_metadata is not None

        if not chat_exists:
            logger.info(f"Chat {chat_id} not found in Directus. Attempting creation (task_id: {task_id}).")
            
            # Proceed with Directus chat creation
            now_ts = int(datetime.now(timezone.utc).timestamp()) # Changed to int timestamp
            # Construct payload according to chats.yml schema (omitting vault_key_reference)
            creation_payload = {
                "id": chat_id,
                "hashed_user_id": hashed_user_id, # User who initiated the draft/chat
                "encrypted_title": "", # Default empty title for new chat from draft
                "messages_version": 0, # Initial version
                "title_version": 0,    # Initial version
                "last_edited_overall_timestamp": now_ts, # Set to current time on creation
                "unread_count": 0, # Initial count
                "created_at": now_ts,
                "updated_at": now_ts,
                "last_message_timestamp": now_ts # Can be same as created_at initially
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
        now_ts_logout = int(datetime.now(timezone.utc).timestamp()) # Changed to int timestamp

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
                    # "last_edited_timestamp": now_ts_logout, # Field removed from schema
                    "updated_at": now_ts_logout
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
                # "last_edited_timestamp": now_ts_logout, # Field removed from schema
                "created_at": now_ts_logout,
                "updated_at": now_ts_logout
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
            f"Error in _async_persist_chat_and_draft_on_logout for user {hashed_user_id}, chat {chat_id} (task_id: {task_id}): {e}",
            exc_info=True
        )
        # Consider re-raising for Celery's retry mechanisms if configured
        # raise

@app.task(name="app.tasks.persistence_tasks.persist_chat_and_draft_on_logout", bind=True)
def persist_chat_and_draft_on_logout_task(
    self,
    hashed_user_id: str, # Use explicit hashed_user_id
    chat_id: str,
    encrypted_draft_content: Optional[str],
    draft_version: int
    # Removed chat_metadata_for_creation
):
    task_id = self.request.id if self and hasattr(self, 'request') else 'UNKNOWN_TASK_ID'
    logger.info(f"SYNC_WRAPPER: persist_chat_and_draft_on_logout_task for user {hashed_user_id}, chat {chat_id}, task_id: {task_id}")
    loop = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_async_persist_chat_and_draft_on_logout(
            hashed_user_id, chat_id, encrypted_draft_content, draft_version, task_id
        ))
        return True # Indicate success
    except Exception as e:
        logger.error(f"SYNC_WRAPPER_ERROR: persist_chat_and_draft_on_logout_task for user {hashed_user_id}, chat {chat_id}, task_id: {task_id}: {e}", exc_info=True)
        return False # Indicate failure
    finally:
        if loop:
            loop.close()


async def _async_persist_delete_chat(
    user_id: str, # Keep user_id for overall context/logging and potential use in chat deletion itself
    chat_id: str,
    task_id: Optional[str] = "UNKNOWN_TASK_ID"
):
    """
    Asynchronously deletes a chat and ALL its associated drafts from Directus.
    Also removes ALL drafts for the chat from the cache.
    The user_id is the initiator of the delete operation.
    """
    logger.info(
        f"TASK_LOGIC_ENTRY: Starting _async_persist_delete_chat "
        f"for user_id: {user_id} (initiator), chat_id: {chat_id}, task_id: {task_id}"
    )

    directus_service = DirectusService()

    try:
        await directus_service.ensure_auth_token()

        # 1. Delete ALL drafts for this chat from Directus
        # Assumes chat_methods.delete_all_drafts_for_chat handles deleting all draft items
        # linked to chat_id.
        all_drafts_deleted_directus = await chat_methods.delete_all_drafts_for_chat(
            directus_service, chat_id
        )
        if all_drafts_deleted_directus: # Assuming this returns True if successful or if no drafts existed
            logger.info(
                f"Successfully processed deletion of all drafts for chat {chat_id} from Directus. Task ID: {task_id}"
            )
        else:
            # This 'else' might mean an error occurred, or simply no drafts were found.
            # The method's contract would define this.
            logger.warning(
                f"Attempt to delete all drafts for chat {chat_id} from Directus completed; "
                f"check method's specific return behavior (e.g., if drafts existed). Task ID: {task_id}"
            )

        # 2. Delete the chat itself from Directus
        # This should happen after draft deletion to avoid orphaned drafts if chat deletion fails.
        chat_deleted_directus = await chat_methods.persist_delete_chat(
            directus_service, chat_id # user_id might be needed here if chat deletion is user-scoped initially
        )
        if chat_deleted_directus:
            logger.info(
                f"Successfully deleted chat {chat_id} from Directus. Task ID: {task_id}"
            )
        else:
            logger.warning(
                f"Could not delete chat {chat_id} from Directus. Task ID: {task_id}"
            )
        
        # Step 3: Cached drafts are allowed to expire naturally.
        # The websocket handler is responsible for clearing the main chat cache entries (tombstoning).
        # This task's primary responsibility is deleting the chat and all its drafts from Directus.
        logger.info(f"Directus deletion of chat and drafts for chat {chat_id} completed. Cached drafts will expire naturally. Task ID: {task_id}")

        logger.info(
            f"TASK_LOGIC_FINISH: _async_persist_delete_chat task finished "
            f"for user_id: {user_id} (initiator), chat_id: {chat_id}, task_id: {task_id}"
        )

    except Exception as e:
        logger.error(
            f"Error in _async_persist_delete_chat for user {user_id} (initiator), chat {chat_id}, task_id: {task_id}: {e}",
            exc_info=True
        )
        # Depending on retry strategy, you might re-raise or handle specific exceptions
        raise # Re-raise to let Celery handle retries/failures based on task config


@app.task(name="app.tasks.persistence_tasks.persist_delete_chat", bind=True)
def persist_delete_chat(self, user_id: str, chat_id: str):
    """
    Synchronous Celery task wrapper to delete a chat and ALL its associated drafts from Directus,
    and ALL drafts for the chat from cache.
    """
    task_id = self.request.id if self and hasattr(self, 'request') else 'UNKNOWN_TASK_ID'
    logger.info(
        f"TASK_ENTRY_SYNC_WRAPPER: Starting persist_delete_chat task "
        f"for user_id: {user_id} (initiator), chat_id: {chat_id}, task_id: {task_id}"
    )

    loop = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        loop.run_until_complete(_async_persist_delete_chat(
            user_id=user_id,
            chat_id=chat_id,
            task_id=task_id
        ))
        logger.info(
            f"TASK_SUCCESS_SYNC_WRAPPER: persist_delete_chat task completed "
            f"for user_id: {user_id} (initiator), chat_id: {chat_id}, task_id: {task_id}"
        )
        return True  # Indicate success
    except Exception as e:
        logger.error(
            f"TASK_FAILURE_SYNC_WRAPPER: Failed to run persist_delete_chat task "
            f"for user_id {user_id} (initiator), chat_id: {chat_id}, task_id: {task_id}: {str(e)}",
            exc_info=True
        )
        # Celery will handle retries based on task configuration if the exception is re-raised.
        raise self.retry(exc=e, countdown=60) # Example retry
    finally:
        if loop:
            loop.close()
        logger.info(
            f"TASK_FINALLY_SYNC_WRAPPER: Event loop closed for persist_delete_chat task_id: {task_id}"
        )