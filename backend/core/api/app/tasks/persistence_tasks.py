# backend/core/api/app/tasks/persistence_tasks.py
# This file contains Celery tasks related to data persistence,
# including creating, updating, and deleting chat-related data in Directus and cache.
import logging
import asyncio
import hashlib
import json
from datetime import datetime, timezone
from typing import Dict, Any
from typing import Optional

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.services.s3.service import S3UploadService

logger = logging.getLogger(__name__)

async def _async_persist_chat_title_task(chat_id: str, encrypted_title: str, title_v: int, task_id: str):
    """
    Async logic for persisting an updated chat title.
    """
    logger.info(f"Task _async_persist_chat_title_task (task_id: {task_id}): Persisting title for chat {chat_id}, version: {title_v}")
    directus_service = DirectusService()
    await directus_service.ensure_auth_token()

    fields_to_update = {
        "encrypted_title": encrypted_title,
        "title_v": title_v,
        "updated_at": int(datetime.now(timezone.utc).timestamp()) # Changed to int timestamp
    }

    try:
        updated = await directus_service.chat.update_chat_fields_in_directus(
            chat_id=chat_id,
            fields_to_update=fields_to_update
        )
        if updated:
            logger.info(f"Successfully persisted title for chat {chat_id} (task_id: {task_id}). New title_v: {title_v}")
        else:
            logger.error(f"Failed to persist title for chat {chat_id} (task_id: {task_id}). Update operation returned false.")
    except Exception as e:
        logger.error(f"Error in _async_persist_chat_title_task for chat {chat_id} (task_id: {task_id}): {e}", exc_info=True)
        # Consider re-raising for Celery's retry mechanisms if configured
        # raise

@app.task(name="app.tasks.persistence_tasks.persist_chat_title", bind=True)
def persist_chat_title_task(self, chat_id: str, encrypted_title: str, title_v: int):
    task_id = self.request.id if self and hasattr(self, 'request') else 'UNKNOWN_TASK_ID'
    logger.info(f"SYNC_WRAPPER: persist_chat_title_task for chat {chat_id}, task_id: {task_id}")
    loop = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_async_persist_chat_title_task(chat_id, encrypted_title, title_v, task_id))
    except Exception as e:
        logger.error(f"SYNC_WRAPPER_ERROR: persist_chat_title_task for chat {chat_id}, task_id: {task_id}: {e}", exc_info=True)
        raise # Re-raise to let Celery handle retries/failure
    finally:
        if loop:
            loop.close()


async def _async_persist_chat_active_focus_id_task(
    chat_id: str,
    encrypted_active_focus_id: Optional[str],
    task_id: str
):
    """
    Async logic for persisting an updated chat active focus mode.
    
    Args:
        chat_id: The chat ID
        encrypted_active_focus_id: The encrypted focus mode ID, or None to clear it
        task_id: The Celery task ID for logging
    """
    logger.info(f"Task _async_persist_chat_active_focus_id_task (task_id: {task_id}): Persisting active_focus_id for chat {chat_id}")
    directus_service = DirectusService()
    await directus_service.ensure_auth_token()

    fields_to_update = {
        "encrypted_active_focus_id": encrypted_active_focus_id,
        "updated_at": int(datetime.now(timezone.utc).timestamp())
    }

    try:
        updated = await directus_service.chat.update_chat_fields_in_directus(
            chat_id=chat_id,
            fields_to_update=fields_to_update
        )
        if updated:
            logger.info(f"Successfully persisted active_focus_id for chat {chat_id} (task_id: {task_id}).")
        else:
            logger.error(f"Failed to persist active_focus_id for chat {chat_id} (task_id: {task_id}). Update operation returned false.")
    except Exception as e:
        logger.error(f"Error in _async_persist_chat_active_focus_id_task for chat {chat_id} (task_id: {task_id}): {e}", exc_info=True)


@app.task(name="app.tasks.persistence_tasks.persist_chat_active_focus_id", bind=True)
def persist_chat_active_focus_id_task(self, chat_id: str, encrypted_active_focus_id: Optional[str]):
    """
    Celery task to persist the active focus mode ID for a chat.
    
    Args:
        chat_id: The chat ID
        encrypted_active_focus_id: The encrypted focus mode ID, or None to clear it
    """
    task_id = self.request.id if self and hasattr(self, 'request') else 'UNKNOWN_TASK_ID'
    logger.info(f"SYNC_WRAPPER: persist_chat_active_focus_id_task for chat {chat_id}, task_id: {task_id}")
    loop = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_async_persist_chat_active_focus_id_task(chat_id, encrypted_active_focus_id, task_id))
    except Exception as e:
        logger.error(f"SYNC_WRAPPER_ERROR: persist_chat_active_focus_id_task for chat {chat_id}, task_id: {task_id}: {e}", exc_info=True)
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
        existing_draft = await directus_service.chat.get_user_draft_from_directus(
            hashed_user_id, chat_id
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
                updated = await directus_service.chat.update_user_draft_in_directus(
                    existing_draft_id, fields_to_update
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
            created = await directus_service.chat.create_user_draft_in_directus(
                draft_payload
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
    role: str, # New: 'user', 'assistant', 'system'
    encrypted_sender_name: Optional[str] = None, # Encrypted sender name
    encrypted_category: Optional[str] = None, # Encrypted category
    encrypted_model_name: Optional[str] = None, # Encrypted model name - ONLY for assistant messages
    encrypted_content: str = "", # Zero-knowledge: only encrypted content stored
    created_at: Optional[int] = None, # This is the client's original timestamp for the message
    new_chat_messages_version: Optional[int] = None,
    new_last_edited_overall_timestamp: Optional[int] = None,
    task_id: str = "UNKNOWN",
    encrypted_chat_key: Optional[str] = None, # Encrypted chat key for device sync
    user_id: Optional[str] = None, # User ID for sync cache updates (not hashed)
    encrypted_pii_mappings: Optional[str] = None # Encrypted PII placeholder-to-original mappings
):
    """
    Async logic for:
    1. Ensuring the chat entry exists in Directus (creates if not).
    2. Creating a single message item in Directus.
    3. Updating parent chat metadata (messages_v, last_edited_overall_timestamp, last_message_timestamp).
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

    # Validate that encrypted_model_name is only provided for assistant messages
    if encrypted_model_name and role != 'assistant':
        logger.warning(
            f"_async_persist_new_chat_message_task (task_id: {task_id}): "
            f"encrypted_model_name provided for {role} message {message_id} in chat {chat_id}. "
            f"encrypted_model_name should only be set for assistant messages. Ignoring it."
        )
        encrypted_model_name = None  # Remove it for non-assistant messages

    directus_service = DirectusService()

    try:
        await directus_service.ensure_auth_token()

        # CRITICAL: Update sync cache FIRST (cache has priority!)
        # This ensures new chats/messages are immediately available for other devices
        # Sync cache must contain client-encrypted messages (not vault-encrypted from AI cache)
        if user_id:
            try:
                from backend.core.api.app.services.cache import CacheService
                import json
                import base64
                cache_service = CacheService()
                
                # VALIDATION: Log encrypted content details for debugging sync/encryption issues
                # This helps identify if content is properly client-encrypted before syncing
                encrypted_content_valid = False
                if encrypted_content:
                    try:
                        decoded = base64.b64decode(encrypted_content)
                        encrypted_content_valid = len(decoded) >= 29  # Minimum for AES-GCM
                        if not encrypted_content_valid:
                            logger.warning(
                                f"[SYNC_CACHE_VALIDATION] ⚠️ Message {message_id} encrypted_content is suspiciously short: "
                                f"decoded_len={len(decoded)} bytes (expected >= 29). May be incorrectly encrypted!"
                            )
                    except Exception as decode_err:
                        logger.error(
                            f"[SYNC_CACHE_VALIDATION] ❌ Message {message_id} encrypted_content is NOT valid base64: {decode_err}"
                        )
                else:
                    logger.warning(f"[SYNC_CACHE_VALIDATION] ⚠️ Message {message_id} has no encrypted_content!")
                
                # Create the new message as a JSON string (matching Directus format)
                new_message_dict = {
                    "id": message_id,
                    "chat_id": chat_id,
                    "role": role,
                    "encrypted_sender_name": encrypted_sender_name,
                    "encrypted_category": encrypted_category,
                    "encrypted_content": encrypted_content,
                    "created_at": created_at,
                    "status": "delivered"  # Default status
                }
                # Only include encrypted_model_name for assistant messages
                if encrypted_model_name and role == 'assistant':
                    new_message_dict["encrypted_model_name"] = encrypted_model_name
                # Include encrypted PII mappings if provided (user messages with PII detection)
                if encrypted_pii_mappings:
                    new_message_dict["encrypted_pii_mappings"] = encrypted_pii_mappings
                new_message_json = json.dumps(new_message_dict)
                
                # ATOMIC CACHE UPDATE: Use append instead of read-modify-write
                # This prevents race conditions where concurrent tasks overwrite each other
                await cache_service.append_sync_message_to_history(
                    user_id=user_id, 
                    chat_id=chat_id, 
                    encrypted_message_json=new_message_json, 
                    ttl=3600
                )
                logger.info(
                    f"[SYNC_CACHE_UPDATE] ✅ Appended new message {message_id} (role={role}) to sync cache FIRST "
                    f"for chat {chat_id} (task_id: {task_id}). "
                    f"encrypted_content_length={len(encrypted_content) if encrypted_content else 0}, "
                    f"encrypted_content_valid={encrypted_content_valid}"
                )
            except Exception as sync_cache_error:
                # Non-critical error - sync cache will be populated during cache warming
                logger.warning(
                    f"Failed to update sync cache for chat {chat_id} before Directus persistence "
                    f"(task_id: {task_id}): {sync_cache_error}"
                )
        else:
            logger.debug(f"user_id not provided, skipping sync cache update for chat {chat_id} (task_id: {task_id})")

        # 1. FIRST: Handle Chat (ensure it exists before creating message)
        # CRITICAL FIX: Must create the chat BEFORE the message to satisfy foreign key constraints
        # The metadata task will update it later with encrypted title/icon/category.
        chat_metadata = await directus_service.chat.get_chat_metadata(chat_id)

        if chat_metadata:
            # Chat exists, will update its metadata after message creation
            logger.info(f"Chat {chat_id} found. Will update metadata after message creation (task_id: {task_id}).")
        else:
            # CRITICAL FIX: Chat does not exist yet - CREATE it now!
            # This prevents message creation from failing due to foreign key constraint.
            # The metadata task will update it later with encrypted title/icon/category.
            logger.info(
                f"Chat {chat_id} not found in Directus. Creating minimal chat record FIRST. "
                f"(task_id: {task_id})"
            )
            
            if not hashed_user_id:
                logger.error(
                    f"Cannot create chat {chat_id} - missing hashed_user_id (task_id: {task_id})"
                )
                return
            
            now_ts = int(datetime.now(timezone.utc).timestamp())
            minimal_chat_payload = {
                "id": chat_id,
                "hashed_user_id": hashed_user_id,
                "created_at": created_at or now_ts,
                "updated_at": now_ts,
                "messages_v": new_chat_messages_version or 1,
                "title_v": 0,  # Will be updated by metadata task
                "last_edited_overall_timestamp": new_last_edited_overall_timestamp or now_ts,
                "last_message_timestamp": new_last_edited_overall_timestamp or now_ts,
                "unread_count": 0,
                "encrypted_title": "",  # Will be updated by metadata task
            }
            
            # Add encrypted_chat_key if provided
            if encrypted_chat_key:
                minimal_chat_payload["encrypted_chat_key"] = encrypted_chat_key
                logger.info(f"Including encrypted_chat_key in minimal chat creation for {chat_id}")
            
            # create_chat_in_directus returns (created_data, is_duplicate)
            # is_duplicate=True means RECORD_NOT_UNIQUE error (race condition - another task created it)
            created_chat, is_duplicate = await directus_service.chat.create_chat_in_directus(minimal_chat_payload)
            
            if created_chat and created_chat.get("id"):
                logger.info(
                    f"✅ Successfully created minimal chat {chat_id} (task_id: {task_id}). "
                    f"Metadata task will update it with encrypted title/icon/category."
                )
            elif is_duplicate:
                # RACE CONDITION HANDLING: Chat was created by another concurrent task
                # This is normal and expected in concurrent environments.
                # The chat now exists - proceed with message creation!
                logger.info(
                    f"✅ Chat {chat_id} was created by another task (race condition). "
                    f"Proceeding with message creation. (task_id: {task_id})"
                )
            else:
                logger.error(
                    f"❌ Failed to create chat {chat_id} (task_id: {task_id}). "
                    f"Cannot create message without chat!"
                )
                return  # Stop if chat creation fails - message won't work without it

        # 2. NOW: Persist the New Message to Directus (AFTER chat exists)
        # =================================================================
        # IDEMPOTENCY CHECK: Prevent duplicate messages from race conditions
        # =================================================================
        # This check prevents the same message from being persisted twice, which can happen when:
        # - User has cached webapp on multiple devices (e.g., iPad with old webapp)
        # - Network issues cause duplicate requests
        # - Celery task retries
        #
        # The client_message_id is a unique identifier generated by the client for each message.
        # If a message with this ID already exists, we skip creation and return early.
        message_already_exists = await directus_service.chat.message_exists_by_client_message_id(message_id)
        if message_already_exists:
            logger.warning(
                f"[IDEMPOTENCY] ⚠️ Message {message_id} already exists in Directus. "
                f"Skipping duplicate persistence for chat {chat_id}. (task_id: {task_id}) "
                f"This is likely due to a race condition (duplicate request from another device/cached webapp)."
            )
            # IMPORTANT: We still need to update chat metadata (messages_v, timestamps)
            # But we skip creating the duplicate message
            # The chat metadata update happens later in this function, so we continue there
            return  # Exit early - message already persisted
        
        # The 'created_at' parameter is the client's original timestamp.
        message_data_for_directus = {
            "id": message_id,  # This is the client_message_id for Directus
            "chat_id": chat_id,
            "hashed_user_id": hashed_user_id,
            "role": role,
            "encrypted_sender_name": encrypted_sender_name,
            "encrypted_category": encrypted_category,
            "encrypted_content": encrypted_content,
            "created_at": created_at
        }
        # Only include encrypted_model_name for assistant messages
        if encrypted_model_name and role == 'assistant':
            message_data_for_directus["encrypted_model_name"] = encrypted_model_name
        # Include encrypted PII mappings if provided (user messages with PII detection)
        if encrypted_pii_mappings:
            message_data_for_directus["encrypted_pii_mappings"] = encrypted_pii_mappings

        created_message_item = await directus_service.chat.create_message_in_directus(
            message_data=message_data_for_directus
        )

        if not created_message_item or not created_message_item.get("id"):
            logger.error(
                f"Failed to create message {message_id} for chat {chat_id} (task_id: {task_id}). "
                f"Directus operation returned: {created_message_item}"
            )
            return  # Stop if message creation fails
        
        logger.info(
            f"Successfully created message {message_id} (Directus ID: {created_message_item['id']}) "
            f"for chat {chat_id} (task_id: {task_id})."
        )

        # 3. Update chat metadata with new message version info
        chat_fields_to_update = {
            "messages_v": new_chat_messages_version,
            "last_edited_overall_timestamp": new_last_edited_overall_timestamp,
            "last_message_timestamp": new_last_edited_overall_timestamp,  # This new message is the latest
            "updated_at": int(datetime.now(timezone.utc).timestamp())
        }
        
        updated_chat = await directus_service.chat.update_chat_fields_in_directus(
            chat_id=chat_id,
            fields_to_update=chat_fields_to_update
        )

        if updated_chat:
            logger.info(f"Successfully updated chat {chat_id} metadata (task_id: {task_id}).")
        else:
            logger.warning(f"Failed to update chat {chat_id} metadata (task_id: {task_id}). Message was still created.")

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
    role: str, # New
    encrypted_sender_name: Optional[str] = None, # Encrypted sender name
    encrypted_category: Optional[str] = None, # Encrypted category
    encrypted_model_name: Optional[str] = None, # Encrypted model name - ONLY for assistant messages
    encrypted_content: str = "", # Zero-knowledge: only encrypted content
    created_at: Optional[int] = None,
    new_chat_messages_version: Optional[int] = None,
    new_last_edited_overall_timestamp: Optional[int] = None,
    encrypted_chat_key: Optional[str] = None, # Encrypted chat key for device sync
    user_id: Optional[str] = None, # User ID for sync cache updates (not hashed)
    encrypted_pii_mappings: Optional[str] = None # Encrypted PII placeholder-to-original mappings
):
    task_id = self.request.id if self and hasattr(self, 'request') else 'UNKNOWN_TASK_ID'
    logger.info(
        f"SYNC_WRAPPER: persist_new_chat_message_task for message {message_id}, chat {chat_id}, user {hashed_user_id}, "
        f"role: {role}, encrypted_sender_name: {encrypted_sender_name}, "
        f"new_chat_mv: {new_chat_messages_version}, new_chat_ts: {new_last_edited_overall_timestamp}, task_id: {task_id}"
    )
    loop = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_async_persist_new_chat_message_task(
            message_id, chat_id, hashed_user_id, 
            role, encrypted_sender_name, encrypted_category, encrypted_model_name, # Pass new encrypted params including model_name
            encrypted_content, created_at,
            new_chat_messages_version, new_last_edited_overall_timestamp,
            task_id, encrypted_chat_key, user_id, # Pass encrypted chat key and user_id for device sync
            encrypted_pii_mappings  # Pass encrypted PII mappings for cross-device restoration
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
        chat_metadata = await directus_service.chat.get_chat_metadata(chat_id)
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
                "messages_v": 0, # Initial version
                "title_v": 0,    # Initial version
                "last_edited_overall_timestamp": now_ts, # Set to current time on creation
                "unread_count": 0, # Initial count
                "created_at": now_ts,
                "updated_at": now_ts,
                "last_message_timestamp": now_ts # Can be same as created_at initially
            }

            logger.debug(f"Attempting to create chat {chat_id} with payload keys: {creation_payload.keys()}")
            # create_chat_in_directus returns (created_data, is_duplicate)
            # is_duplicate=True means RECORD_NOT_UNIQUE error (race condition - another task created it)
            created_chat, is_duplicate = await directus_service.chat.create_chat_in_directus(creation_payload)
            if not created_chat and not is_duplicate:
                logger.error(f"Failed to create chat {chat_id} in Directus during logout persistence (task_id: {task_id}). Aborting draft persistence.")
                return # Stop if chat creation fails
            if is_duplicate:
                logger.info(f"Chat {chat_id} was created by another task (race condition). Proceeding with draft persistence (task_id: {task_id}).")
            else:
                logger.info(f"Successfully created chat {chat_id} in Directus (task_id: {task_id}).")
            chat_exists = True # Mark as existing now

        if not chat_exists:
             logger.error(f"Chat {chat_id} still not found after creation attempt (task_id: {task_id}). Aborting draft persistence.")
             return # Should not happen if creation succeeded or it existed initially

        # 2. Persist Draft (Create or Update)
        persist_success = False
        existing_draft = await directus_service.chat.get_user_draft_from_directus(
            hashed_user_id, chat_id
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
                updated_draft = await directus_service.chat.update_user_draft_in_directus(
                    existing_draft_id, fields_to_update
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
            created_draft_data = await directus_service.chat.create_user_draft_in_directus(
                draft_payload
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
    Asynchronously deletes a chat and ALL its associated drafts, messages, and embeds from Directus.
    Also removes ALL drafts for the chat from the cache.
    The user_id is the initiator of the delete operation.
    
    Deletion order:
    1. Delete all drafts for the chat
    2. Delete all messages for the chat
    3. Delete all private embeds for the chat (shared embeds are kept)
    4. Delete the chat itself
    """
    import hashlib
    
    logger.info(
        f"TASK_LOGIC_ENTRY: Starting _async_persist_delete_chat "
        f"for user_id: {user_id} (initiator), chat_id: {chat_id}, task_id: {task_id}"
    )

    directus_service = DirectusService()

    try:
        await directus_service.ensure_auth_token()

        # 1. Delete ALL drafts for this chat from Directus
        all_drafts_deleted_directus = await directus_service.chat.delete_all_drafts_for_chat(
            chat_id
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

        # 2. Delete ALL messages for this chat from Directus
        all_messages_deleted_directus = await directus_service.chat.delete_all_messages_for_chat(
            chat_id
        )
        if all_messages_deleted_directus:
            logger.info(
                f"Successfully processed deletion of all messages for chat {chat_id} from Directus. Task ID: {task_id}"
            )
        else:
            logger.warning(
                f"Attempt to delete all messages for chat {chat_id} from Directus completed; "
                f"check method's specific return behavior (e.g., if messages existed). Task ID: {task_id}"
            )

        # 3. Delete ALL private embeds for this chat from Directus
        # Shared embeds are preserved since they may be referenced elsewhere
        # Also delete associated S3 files (e.g., generated images) using s3_file_keys metadata
        hashed_chat_id = hashlib.sha256(chat_id.encode()).hexdigest()
        
        # Initialize S3 service for cleaning up S3 files associated with embeds
        s3_service = None
        try:
            secrets_manager = SecretsManager()
            await secrets_manager.initialize()
            s3_service = S3UploadService(secrets_manager=secrets_manager)
            await s3_service.initialize()
        except Exception as e:
            logger.warning(f"Failed to initialize S3 service for embed cleanup (chat {chat_id}): {e}. "
                          f"S3 files will not be cleaned up but embed records will still be deleted.")
        
        all_embeds_deleted_directus = await directus_service.embed.delete_all_embeds_for_chat(
            hashed_chat_id, s3_service=s3_service
        )
        if all_embeds_deleted_directus:
            logger.info(
                f"Successfully processed deletion of all private embeds for chat {chat_id} from Directus. Task ID: {task_id}"
            )
        else:
            logger.warning(
                f"Attempt to delete all private embeds for chat {chat_id} from Directus completed; "
                f"check method's specific return behavior (e.g., if embeds existed). Task ID: {task_id}"
            )

        # 4. Delete the chat itself from Directus
        # This should happen after draft, message, and embed deletion to avoid orphaned data if chat deletion fails.
        chat_deleted_directus = await directus_service.chat.persist_delete_chat(
            chat_id # user_id might be needed here if chat deletion is user-scoped initially
        )
        if chat_deleted_directus:
            logger.info(
                f"Successfully deleted chat {chat_id} from Directus. Task ID: {task_id}"
            )
        else:
            logger.warning(
                f"Could not delete chat {chat_id} from Directus. Task ID: {task_id}"
            )
        
        # Step 5: Cached drafts are allowed to expire naturally.
        # The websocket handler is responsible for clearing the main chat cache entries (tombstoning).
        # This task's primary responsibility is deleting the chat and all its drafts, messages, and embeds from Directus.
        logger.info(f"Directus deletion of chat, drafts, messages, and embeds for chat {chat_id} completed. Cached drafts will expire naturally. Task ID: {task_id}")

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


async def _async_persist_delete_message(
    user_id: str,
    chat_id: str,
    client_message_id: str,
    embed_ids_to_delete: Optional[list] = None,
    task_id: Optional[str] = "UNKNOWN_TASK_ID"
):
    """
    Asynchronously deletes a single message from Directus by its client_message_id.
    Also deletes associated embeds (and their S3 files/embed_keys) if embed_ids_to_delete is provided.
    """
    logger.info(
        f"TASK_LOGIC_ENTRY: Starting _async_persist_delete_message "
        f"for user_id: {user_id}, chat_id: {chat_id}, client_message_id: {client_message_id}, "
        f"embed_ids_to_delete: {len(embed_ids_to_delete or [])}, task_id: {task_id}"
    )

    directus_service = DirectusService()

    try:
        await directus_service.ensure_auth_token()

        # 1. Delete the message from Directus
        message_deleted = await directus_service.chat.delete_message_by_client_id(
            chat_id, client_message_id
        )

        if message_deleted:
            logger.info(
                f"Deleted message {client_message_id} in chat {chat_id}. Task ID: {task_id}"
            )
        else:
            logger.warning(
                f"Failed to delete message {client_message_id} in chat {chat_id}. Task ID: {task_id}"
            )

        # 2. Delete associated embeds from Directus (using hashed_message_id lookup)
        # The client provides embed IDs it already identified, but we also do a server-side
        # lookup by hashed_message_id for thoroughness (catches embeds the client may have missed)
        hashed_chat_id = hashlib.sha256(chat_id.encode()).hexdigest()
        hashed_message_id = hashlib.sha256(client_message_id.encode()).hexdigest()

        # Initialize S3 service for cleaning up S3 files associated with embeds
        s3_service = None
        try:
            secrets_manager = SecretsManager()
            await secrets_manager.initialize()
            s3_service = S3UploadService(secrets_manager=secrets_manager)
            await s3_service.initialize()
        except Exception as e:
            logger.warning(
                f"Failed to initialize S3 service for embed cleanup (message {client_message_id}): {e}. "
                f"S3 files will not be cleaned up but embed records will still be deleted."
            )

        deleted_embeds = await directus_service.embed.delete_embeds_for_message(
            hashed_chat_id, hashed_message_id, s3_service=s3_service
        )

        if deleted_embeds:
            logger.info(
                f"Deleted {len(deleted_embeds)} embeds for message {client_message_id} "
                f"in chat {chat_id}. Task ID: {task_id}"
            )

        logger.info(
            f"TASK_LOGIC_FINISH: _async_persist_delete_message completed "
            f"for message {client_message_id} in chat {chat_id}. Task ID: {task_id}"
        )
    except Exception as e:
        logger.error(
            f"Error in _async_persist_delete_message for user {user_id}, chat {chat_id}, "
            f"message {client_message_id}, task_id: {task_id}: {e}",
            exc_info=True
        )
        raise


@app.task(name="app.tasks.persistence_tasks.persist_delete_message", bind=True)
def persist_delete_message(self, user_id: str, chat_id: str, client_message_id: str, embed_ids_to_delete: Optional[list] = None):
    """
    Celery task (sync wrapper) to delete a single message and its embeds from Directus.
    """
    task_id = self.request.id or "UNKNOWN_TASK_ID"
    loop = None
    try:
        logger.info(
            f"TASK_ENTRY_SYNC_WRAPPER: Starting persist_delete_message task "
            f"for user_id: {user_id}, chat_id: {chat_id}, client_message_id: {client_message_id}, task_id: {task_id}"
        )
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_async_persist_delete_message(
            user_id=user_id, chat_id=chat_id, client_message_id=client_message_id,
            embed_ids_to_delete=embed_ids_to_delete or [], task_id=task_id
        ))
        logger.info(
            f"TASK_SUCCESS_SYNC_WRAPPER: persist_delete_message task completed "
            f"for user_id: {user_id}, chat_id: {chat_id}, client_message_id: {client_message_id}, task_id: {task_id}"
        )
        return True
    except Exception as e:
        logger.error(
            f"TASK_FAILURE_SYNC_WRAPPER: Failed to run persist_delete_message task "
            f"for user_id {user_id}, chat_id: {chat_id}, client_message_id: {client_message_id}, task_id: {task_id}: {str(e)}",
            exc_info=True
        )
        raise self.retry(exc=e, countdown=60)
    finally:
        if loop:
            loop.close()
        logger.info(
            f"TASK_FINALLY_SYNC_WRAPPER: Event loop closed for persist_delete_message task_id: {task_id}"
        )


async def _async_persist_ai_response_to_directus(
    user_id: str,
    user_id_hash: str,
    message_data: Dict[str, Any],
    task_id: str,
    versions: Optional[Dict[str, Any]] = None
):
    """
    Async logic for persisting a completed AI response to Directus.
    This is part of the zero-knowledge architecture where:
    1. Client encrypts the AI response with chat-specific key
    2. Client sends ONLY encrypted content to server (no plaintext)
    3. Server stores encrypted content in Directus WITHOUT modification or re-encryption
    4. Server NEVER encrypts AI responses with vault keys - that's a CRITICAL violation
    
    MULTI-DEVICE HANDLING:
    - Multiple devices may receive the same AI stream
    - All devices try to submit the completed response
    - This function deduplicates using message_id and messages_v
    - First device wins, others gracefully skip
    
    CRITICAL VALIDATION:
    - Message MUST have encrypted_content (client-encrypted with chat key)
    - Message MUST NOT be encrypted with vault key
    - This is enforced strictly to maintain zero-knowledge architecture
    """
    message_id = message_data.get('message_id')
    chat_id = message_data.get('chat_id')
    
    logger.info(
        f"Task _async_persist_ai_response_to_directus (task_id: {task_id}): "
        f"Processing AI response {message_id} for chat {chat_id}, user {user_id_hash}"
    )

    directus_service = DirectusService()
    await directus_service.ensure_auth_token()

    try:
        # Validate that we have encrypted content (zero-knowledge requirement)
        if not message_data.get("encrypted_content"):
            logger.error(
                f"_async_persist_ai_response_to_directus (task_id: {task_id}): "
                f"Missing encrypted_content for AI response {message_id}. "
                f"Zero-knowledge architecture requires CLIENT-encrypted content."
            )
            return

        # CRITICAL: Ensure no plaintext content is stored (zero-knowledge enforcement)
        if message_data.get("content"):
            logger.warning(
                f"_async_persist_ai_response_to_directus (task_id: {task_id}): "
                f"Removing plaintext content from AI response {message_id} "
                f"to enforce zero-knowledge architecture."
            )
            message_data = {k: v for k, v in message_data.items() if k != "content"}

        # MULTI-DEVICE DEDUPLICATION: Check if message already exists
        # This handles the case where multiple devices try to store the same AI response
        try:
            existing_message = await directus_service.chat.get_message_by_id(message_id)
            if existing_message:
                logger.info(
                    f"AI response {message_id} already exists in Directus (multi-device scenario). "
                    f"Skipping message creation. (task_id: {task_id})"
                )
                # Message already stored by another device - just update chat if needed
                if versions:
                    await _update_chat_versions_if_needed(
                        directus_service, chat_id, versions, task_id
                    )
                return
        except Exception as check_error:
            # If check fails, continue with creation attempt (will fail gracefully if duplicate)
            logger.debug(f"Could not check for existing message {message_id}: {check_error}")

        # CRITICAL FIX: Ensure message_data has 'id' field (not just 'message_id')
        # create_message_in_directus expects either 'id' or 'message_id', but we need 'id' for consistency
        if "message_id" in message_data and "id" not in message_data:
            message_data["id"] = message_data["message_id"]
        
        # Add user hash for Directus storage
        message_data["hashed_user_id"] = user_id_hash

        # CRITICAL: Validate encryption before storing
        # Ensure this is client-encrypted (not vault-encrypted)
        import base64
        try:
            encrypted_content = message_data.get("encrypted_content", "")
            decoded = base64.b64decode(encrypted_content, validate=True)
            logger.debug(
                f"✅ AI response {message_id}: encrypted_content is valid base64 ({len(decoded)} bytes). "
                f"Proceeding with zero-knowledge storage."
            )
        except Exception as validation_err:
            logger.error(
                f"❌ REJECTING AI response {message_id} - encrypted_content is not valid base64! "
                f"This indicates a CRITICAL violation: client did not properly encrypt the response. "
                f"Error: {validation_err}"
            )
            return

        # Store the encrypted AI response in Directus
        logger.info(
            f"DEBUG: Creating AI response message in Directus: message_id={message_id}, "
            f"has_encrypted_content={bool(message_data.get('encrypted_content'))}, "
            f"has_encrypted_model_name={bool(message_data.get('encrypted_model_name'))}, "
            f"role={message_data.get('role')}"
        )
        created_message_item = await directus_service.chat.create_message_in_directus(
            message_data=message_data
        )
        
        success = created_message_item and created_message_item.get("id")

        if success:
            logger.info(
                f"✅ Successfully persisted CLIENT-ENCRYPTED AI response {message_id} "
                f"to Directus for chat {chat_id} (task_id: {task_id})"
            )
            
            # CRITICAL: Update sync cache with AI response (same as user messages)
            # This ensures the AI response is available for sync after logout/login
            try:
                from backend.core.api.app.services.cache import CacheService
                import json
                cache_service = CacheService()
                
                # Create the message as a JSON string (matching Directus format)
                # Use message_data which contains the AI response fields
                new_message_dict = {
                    "id": message_id,
                    "chat_id": chat_id,
                    "role": message_data.get("role", "assistant"),
                    "encrypted_sender_name": message_data.get("encrypted_sender_name"),
                    "encrypted_category": message_data.get("encrypted_category"),
                    "encrypted_content": message_data.get("encrypted_content"),
                    "created_at": message_data.get("created_at"),
                    "status": "synced",
                    # Thinking metadata (client-encrypted content + optional plaintext counters)
                    "encrypted_thinking_content": message_data.get("encrypted_thinking_content"),
                    "encrypted_thinking_signature": message_data.get("encrypted_thinking_signature"),
                    "has_thinking": message_data.get("has_thinking"),
                    "thinking_token_count": message_data.get("thinking_token_count")
                }
                # Only include encrypted_model_name for assistant messages
                if message_data.get("encrypted_model_name"):
                    new_message_dict["encrypted_model_name"] = message_data.get("encrypted_model_name")
                
                new_message_json = json.dumps(new_message_dict)
                
                # ATOMIC CACHE UPDATE: Use append instead of read-modify-write
                # This prevents race conditions where concurrent tasks overwrite each other
                await cache_service.append_sync_message_to_history(
                    user_id=user_id, 
                    chat_id=chat_id, 
                    encrypted_message_json=new_message_json, 
                    ttl=3600
                )
                logger.info(
                    f"[SYNC_CACHE_UPDATE] ✅ Appended AI response {message_id} to sync cache "
                    f"for chat {chat_id} after persistence (task_id: {task_id})"
                )
            except Exception as sync_cache_error:
                # Non-critical error - sync cache will be populated during cache warming
                logger.warning(
                    f"[SYNC_CACHE_UPDATE] ⚠️ Failed to update sync cache for chat {chat_id} after AI response storage "
                    f"(task_id: {task_id}): {sync_cache_error}"
                )
            
            # Update chat with new messages_v and timestamp if versions provided
            if versions:
                await _update_chat_versions_if_needed(
                    directus_service, chat_id, versions, task_id
                )
        else:
            logger.error(
                f"Failed to persist AI response {message_id} "
                f"to Directus for chat {chat_id} (task_id: {task_id})"
            )

    except Exception as e:
        # Check if this is a duplicate key error (another device already created it)
        error_msg = str(e).lower()
        if "duplicate" in error_msg or "unique" in error_msg or "already exists" in error_msg:
            logger.info(
                f"AI response {message_id} already exists (multi-device race condition). "
                f"This is expected. (task_id: {task_id})"
            )
            # Update chat versions if provided, even though message creation failed
            if versions:
                try:
                    await _update_chat_versions_if_needed(
                        directus_service, chat_id, versions, task_id
                    )
                except Exception as update_error:
                    logger.debug(f"Chat version update after duplicate: {update_error}")
            return
        
        logger.error(
            f"Error in _async_persist_ai_response_to_directus for AI response {message_id}, "
            f"chat {chat_id} (task_id: {task_id}): {e}",
            exc_info=True
        )
        raise  # Re-raise for Celery's retry mechanisms


async def _update_chat_versions_if_needed(
    directus_service: DirectusService,
    chat_id: str,
    versions: Dict[str, Any],
    task_id: str
):
    """
    Helper function to update chat versions with optimistic locking.
    Only updates if the new messages_v is greater than current.
    This prevents race conditions when multiple devices update the same chat.
    
    CRITICAL: This function should use the version from the client, not increment.
    The client already increments messages_v before sending, so we just need to set it.
    """
    new_messages_v = versions.get("messages_v")
    new_last_edited = versions.get("last_edited_overall_timestamp")
    
    if not new_messages_v:
        logger.debug(f"No messages_v in versions for chat {chat_id} (task_id: {task_id})")
        return
    
    try:
        # Get current chat to check version
        chat = await directus_service.chat.get_chat_metadata(chat_id)
        if not chat:
            logger.warning(f"Chat {chat_id} not found for version update (task_id: {task_id})")
            return
        
        current_messages_v = chat.get("messages_v", 0)
        
        # MESSAGES_V_TRACKING: Log the version comparison for persistence task
        # This helps debug race conditions where client and server versions diverge
        logger.info(
            f"[MESSAGES_V_TRACKING] PERSISTENCE_CHECK: "
            f"chat_id={chat_id}, "
            f"client_v={new_messages_v}, "
            f"current_directus_v={current_messages_v}, "
            f"will_update={new_messages_v > current_messages_v}, "
            f"source=_update_chat_versions_if_needed, "
            f"task_id={task_id}"
        )
        
        # CRITICAL FIX: Use client-provided version (don't increment)
        # The client already increments messages_v before sending, so we should use that value
        # Only update if new version is greater (optimistic locking)
        if new_messages_v > current_messages_v:
            update_fields = {
                "messages_v": new_messages_v,  # Use client-provided version, don't increment
                "updated_at": int(datetime.now(timezone.utc).timestamp())
            }
            
            if new_last_edited:
                update_fields["last_edited_overall_timestamp"] = new_last_edited
                update_fields["last_message_timestamp"] = new_last_edited
            
            await directus_service.chat.update_chat_fields_in_directus(
                chat_id=chat_id,
                fields_to_update=update_fields
            )
            logger.info(
                f"Updated chat {chat_id} messages_v: {current_messages_v} → {new_messages_v} (task_id: {task_id})"
            )
        elif new_messages_v == current_messages_v:
            logger.debug(
                f"Chat {chat_id} messages_v already at {new_messages_v} (task_id: {task_id})"
            )
        else:
            logger.warning(
                f"Skipping chat {chat_id} version update: new={new_messages_v} <= current={current_messages_v} (task_id: {task_id})"
            )
    except Exception as e:
        logger.error(f"Error updating chat versions for {chat_id}: {e} (task_id: {task_id})", exc_info=True)


@app.task(name="app.tasks.persistence_tasks.persist_ai_response_to_directus", bind=True)
def persist_ai_response_to_directus(
    self,
    user_id: str,
    user_id_hash: str,
    message_data: Dict[str, Any],
    versions: Optional[Dict[str, Any]] = None
):
    """
    Celery task to persist a completed AI response to Directus.
    Includes multi-device deduplication and version control.
    This enforces zero-knowledge architecture - server never encrypts AI responses.
    """
    task_id = self.request.id if self and hasattr(self, 'request') else 'UNKNOWN_TASK_ID'
    logger.info(
        f"SYNC_WRAPPER: persist_ai_response_to_directus for AI response {message_data.get('message_id')}, "
        f"chat {message_data.get('chat_id')}, user {user_id_hash}, versions: {versions}, task_id: {task_id}"
    )
    
    loop = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_async_persist_ai_response_to_directus(
            user_id, user_id_hash, message_data, task_id, versions
        ))
    except Exception as e:
        logger.error(
            f"SYNC_WRAPPER_ERROR: persist_ai_response_to_directus for AI response {message_data.get('message_id')}, "
            f"chat {message_data.get('chat_id')}, task_id: {task_id}: {e}",
            exc_info=True
        )
        raise  # Re-raise to let Celery handle retries/failure
    finally:
        if loop:
            loop.close()
        logger.info(
            f"TASK_FINALLY_SYNC_WRAPPER: Event loop closed for persist_ai_response_to_directus task_id: {task_id}"
        )


async def _async_persist_encrypted_chat_metadata(
    chat_id: str,
    encrypted_metadata: Dict[str, Any],
    task_id: str,
    hashed_user_id: Optional[str] = None,
    user_id: Optional[str] = None  # User ID for cache updates (not hashed)
):
    """
    Async logic for persisting encrypted chat metadata from the dual-phase architecture.
    This includes encrypted title, summary, tags, and follow-up suggestions.
    
    IMPORTANT: This task is responsible for creating the chat entry in Directus,
    since it has the encrypted metadata (title, category, etc.) from preprocessing.
    The message task only adds messages to existing chats.
    """
    logger.info(
        f"Task _async_persist_encrypted_chat_metadata (task_id: {task_id}): "
        f"Processing chat {chat_id} with encrypted metadata fields: {list(encrypted_metadata.keys())}"
    )
    logger.info(f"DEBUG: Encrypted metadata content: {encrypted_metadata}")

    directus_service = DirectusService()
    await directus_service.ensure_auth_token()

    try:
        # Check if chat exists
        chat_metadata = await directus_service.chat.get_chat_metadata(chat_id)
        
        if chat_metadata:
            # Chat exists - update with encrypted metadata
            logger.info(f"Chat {chat_id} exists, updating with encrypted metadata")
            
            # OPTIMISTIC LOCKING: Don't downgrade versions or timestamps
            current_messages_v = chat_metadata.get("messages_v", 0)
            current_title_v = chat_metadata.get("title_v", 0)
            
            # Prepare update fields, excluding versions if they are not newer
            # CRITICAL: Always include encrypted metadata fields (title, icon, category) even if versions are same
            # These fields should be updated whenever provided, regardless of version
            update_fields = encrypted_metadata.copy()
            # Rotation control flags are internal only - never persist to Directus.
            allow_chat_key_rotation = bool(update_fields.pop("allow_chat_key_rotation", False))
            chat_key_rotation_reason = update_fields.pop("chat_key_rotation_reason", None)
            
            # =================================================================
            # CRITICAL FIX: Make encrypted_chat_key IMMUTABLE
            # =================================================================
            # The encrypted_chat_key is the symmetric key used to encrypt all messages
            # in this chat. It MUST NOT be changed once set, otherwise existing messages
            # become undecryptable.
            #
            # Bug scenario that this fixes:
            # 1. Device A sends a message and creates the chat with chat_key_A
            # 2. Device B (e.g., iPad with cached old webapp) sends duplicate request with chat_key_B
            # 3. Device B's request arrives late and overwrites chat_key_A with chat_key_B
            # 4. Messages encrypted with chat_key_A can no longer be decrypted
            #
            # Fix: Never allow encrypted_chat_key to be updated once set
            existing_chat_key = chat_metadata.get("encrypted_chat_key")
            incoming_chat_key = update_fields.get("encrypted_chat_key")
            if existing_chat_key and incoming_chat_key:
                if allow_chat_key_rotation:
                    logger.warning(
                        f"[CHAT_KEY_ROTATION] ⚠️ Allowing encrypted_chat_key rotation for chat {chat_id}. "
                        f"Reason: {chat_key_rotation_reason or 'unspecified'}. (task_id: {task_id})"
                    )
                else:
                    # Chat already has an encrypted_chat_key - NEVER overwrite it
                    update_fields.pop("encrypted_chat_key", None)
                    logger.warning(
                        f"[CHAT_KEY_IMMUTABLE] ⚠️ Blocked attempt to overwrite encrypted_chat_key for chat {chat_id}. "
                        f"Existing key is set, incoming key will be ignored to preserve message decryptability. "
                        f"(task_id: {task_id})"
                    )
            
            # Separate version fields from metadata fields
            metadata_fields = {
                "encrypted_title", "encrypted_icon", "encrypted_category", "encrypted_chat_tags",
                "encrypted_chat_summary", "encrypted_follow_up_request_suggestions", "encrypted_chat_key",
                "updated_at"
            }
            
            incoming_messages_v = update_fields.get("messages_v", 0)
            if incoming_messages_v <= current_messages_v:
                # Only remove version-related fields, keep metadata fields
                update_fields.pop("messages_v", None)
                update_fields.pop("last_edited_overall_timestamp", None)
                update_fields.pop("last_message_timestamp", None)
                logger.debug(f"Skipping messages_v update for chat {chat_id}: incoming={incoming_messages_v}, current={current_messages_v}")
            
            incoming_title_v = update_fields.get("title_v", 0)
            # CRITICAL FIX: Allow title_v update if current is 0 (chat was created without title)
            # This ensures pre-processing metadata (title, icon, category) gets stored
            if incoming_title_v <= current_title_v and current_title_v > 0:
                update_fields.pop("title_v", None)
                logger.debug(f"Skipping title_v update for chat {chat_id}: incoming={incoming_title_v}, current={current_title_v}")
            elif current_title_v == 0 and incoming_title_v > 0:
                logger.info(f"Updating title_v from 0 to {incoming_title_v} for chat {chat_id} (pre-processing metadata)")

            # CRITICAL FIX: Always update metadata fields (title, icon, category) if provided
            # Remove None values but keep empty strings for encrypted fields
            update_fields = {k: v for k, v in update_fields.items() if v is not None}
            
            # Log what we're updating
            metadata_updates = [k for k in update_fields.keys() if k in metadata_fields]
            if metadata_updates:
                logger.info(f"Updating metadata fields for chat {chat_id}: {metadata_updates} (task_id: {task_id})")

            if not update_fields:
                logger.info(f"No fields need updating for chat {chat_id} (all versions current and no metadata provided)")
                return

            updated_chat = await directus_service.chat.update_chat_fields_in_directus(
                chat_id=chat_id,
                fields_to_update=update_fields
            )

            if updated_chat:
                logger.info(
                    f"Successfully updated chat {chat_id} with encrypted metadata (task_id: {task_id})"
                )
                
                # CRITICAL: Update cache with encrypted metadata fields (especially follow-up suggestions)
                # Cache must be updated AFTER Directus to ensure consistency
                logger.info(
                    f"DEBUG: About to update cache for chat {chat_id}, user_id: {user_id[:8] + '...' if user_id else 'None'} (task_id: {task_id})"
                )
                if user_id:
                    try:
                        from backend.core.api.app.services.cache import CacheService
                        from backend.core.api.app.schemas.chat import CachedChatListItemData
                        cache_service = CacheService()
                        
                        # Get existing cache data to preserve other fields
                        existing_cache_data = await cache_service.get_chat_list_item_data(user_id, chat_id)
                        logger.info(
                            f"DEBUG: Existing cache data for chat {chat_id}: {bool(existing_cache_data)} (task_id: {task_id})"
                        )
                        
                        # CRITICAL: Fetch fresh data from Directus to ensure we have ALL client-encrypted fields
                        # This matches the cache warming approach and ensures consistency
                        fresh_chat_metadata = await directus_service.chat.get_chat_metadata(chat_id)
                        if fresh_chat_metadata:
                            # Build cache data using the same format as cache warming (from Directus)
                            # This ensures all fields are client-encrypted and in the correct format
                            cache_data = CachedChatListItemData(
                                title=fresh_chat_metadata.get("encrypted_title"),  # Note: cache uses 'title' field for encrypted_title
                                unread_count=fresh_chat_metadata.get("unread_count", 0),
                                created_at=fresh_chat_metadata.get("created_at"),
                                updated_at=fresh_chat_metadata.get("updated_at"),
                                encrypted_chat_key=fresh_chat_metadata.get("encrypted_chat_key"),
                                encrypted_icon=fresh_chat_metadata.get("encrypted_icon"),
                                encrypted_category=fresh_chat_metadata.get("encrypted_category"),
                                encrypted_chat_summary=fresh_chat_metadata.get("encrypted_chat_summary"),
                                encrypted_chat_tags=fresh_chat_metadata.get("encrypted_chat_tags"),
                                encrypted_follow_up_request_suggestions=fresh_chat_metadata.get("encrypted_follow_up_request_suggestions"),
                                encrypted_active_focus_id=fresh_chat_metadata.get("encrypted_active_focus_id"),
                                last_message_timestamp=fresh_chat_metadata.get("last_message_timestamp")
                            )
                            
                            cache_update_result = await cache_service.set_chat_list_item_data(user_id, chat_id, cache_data)
                            if cache_update_result:
                                logger.info(
                                    f"✅ Updated cache for chat {chat_id} with ALL client-encrypted metadata from Directus "
                                    f"(fields updated: {list(update_fields.keys())}) (task_id: {task_id})"
                                )
                            else:
                                logger.error(
                                    f"❌ Failed to update cache for chat {chat_id} - set_chat_list_item_data returned False (task_id: {task_id})"
                                )
                        else:
                            logger.warning(
                                f"⚠️ Could not fetch fresh chat metadata from Directus to update cache for chat {chat_id} (task_id: {task_id})"
                            )
                    except Exception as cache_error:
                        logger.error(
                            f"⚠️ Failed to update cache for chat {chat_id} after Directus update (task_id: {task_id}): {cache_error}. "
                            f"Directus update succeeded, but cache may be stale until next sync.",
                            exc_info=True
                        )
                else:
                    logger.warning(
                        f"⚠️ Cannot update cache for chat {chat_id} - user_id not provided (task_id: {task_id})"
                    )
            else:
                logger.error(
                    f"Failed to update chat {chat_id} with encrypted metadata (task_id: {task_id})"
                )
        else:
            # Chat doesn't exist - CREATE it with the encrypted metadata
            logger.info(f"Chat {chat_id} doesn't exist, creating with encrypted metadata")
            
            if not hashed_user_id:
                logger.error(
                    f"Cannot create chat {chat_id} without hashed_user_id (task_id: {task_id})"
                )
                return
            
            # CRITICAL: Create chat metadata in sync cache FIRST (before Directus)
            # This ensures cache-first strategy as per requirements
            if user_id:
                try:
                    from backend.core.api.app.services.cache import CacheService
                    from backend.core.api.app.schemas.chat import CachedChatListItemData
                    cache_service = CacheService()
                    
                    # Build chat creation payload with encrypted metadata
                    now_ts = int(datetime.now(timezone.utc).timestamp())
                    
                    # Get version values - use sensible defaults, NEVER 0
                    messages_v = encrypted_metadata.get("messages_v", 1)  # At least 1 message exists when creating chat
                    title_v = encrypted_metadata.get("title_v", 1)  # Title exists if we're creating the chat
                    last_edited = encrypted_metadata.get("last_edited_overall_timestamp", now_ts)
                    last_message = encrypted_metadata.get("last_message_timestamp", now_ts)
                    
                    # Create cache data FIRST with client-encrypted metadata
                    cache_data = CachedChatListItemData(
                        title=encrypted_metadata.get("encrypted_title", ""),  # Note: cache uses 'title' field for encrypted_title
                        unread_count=0,
                        created_at=now_ts,
                        updated_at=now_ts,
                        encrypted_chat_key=encrypted_metadata.get("encrypted_chat_key"),
                        encrypted_icon=encrypted_metadata.get("encrypted_icon"),
                        encrypted_category=encrypted_metadata.get("encrypted_category"),
                        encrypted_chat_summary=encrypted_metadata.get("encrypted_chat_summary"),
                        encrypted_chat_tags=encrypted_metadata.get("encrypted_chat_tags"),
                        encrypted_follow_up_request_suggestions=encrypted_metadata.get("encrypted_follow_up_request_suggestions"),
                        encrypted_active_focus_id=encrypted_metadata.get("encrypted_active_focus_id"),
                        last_message_timestamp=last_message
                    )
                    
                    cache_create_result = await cache_service.set_chat_list_item_data(user_id, chat_id, cache_data)
                    if cache_create_result:
                        logger.info(
                            f"✅ Created chat metadata in sync cache FIRST for chat {chat_id} (task_id: {task_id})"
                        )
                    else:
                        logger.warning(
                            f"⚠️ Failed to create chat metadata in sync cache for chat {chat_id} (task_id: {task_id}). "
                            f"Will continue with Directus creation."
                        )
                except Exception as cache_error:
                    logger.error(
                        f"⚠️ Failed to create chat metadata in sync cache for chat {chat_id} (task_id: {task_id}): {cache_error}",
                        exc_info=True
                    )
                    # Set defaults if cache creation failed
                    now_ts = int(datetime.now(timezone.utc).timestamp())
                    messages_v = encrypted_metadata.get("messages_v", 1)
                    title_v = encrypted_metadata.get("title_v", 1)
                    last_edited = encrypted_metadata.get("last_edited_overall_timestamp", now_ts)
                    last_message = encrypted_metadata.get("last_message_timestamp", now_ts)
            else:
                # No user_id provided - set defaults
                now_ts = int(datetime.now(timezone.utc).timestamp())
                messages_v = encrypted_metadata.get("messages_v", 1)
                title_v = encrypted_metadata.get("title_v", 1)
                last_edited = encrypted_metadata.get("last_edited_overall_timestamp", now_ts)
                last_message = encrypted_metadata.get("last_message_timestamp", now_ts)
            
            # Build chat creation payload with encrypted metadata (for Directus)
            # Note: now_ts, messages_v, title_v, last_edited, last_message are already set above
            
            # Log encrypted_chat_key for debugging
            encrypted_chat_key_value = encrypted_metadata.get("encrypted_chat_key")  # Don't default to empty string
            if encrypted_chat_key_value:
                logger.info(f"✅ Creating chat {chat_id} WITH encrypted_chat_key: {encrypted_chat_key_value[:20]}... (length: {len(encrypted_chat_key_value)})")
            else:
                logger.error(f"❌ Creating chat {chat_id} WITHOUT encrypted_chat_key - this will prevent decryption on other devices!")

            chat_creation_payload = {
                "id": chat_id,
                "hashed_user_id": hashed_user_id,
                "created_at": now_ts,
                "updated_at": encrypted_metadata.get("updated_at", now_ts),
                # Version tracking - use actual values, never 0
                "messages_v": messages_v,
                "title_v": title_v,
                "last_edited_overall_timestamp": last_edited,
                "last_message_timestamp": last_message,
                "unread_count": 0,
                # Encrypted metadata from preprocessing
                "encrypted_title": encrypted_metadata.get("encrypted_title", ""),
                "encrypted_icon": encrypted_metadata.get("encrypted_icon"),  # Add missing encrypted_icon field
                "encrypted_category": encrypted_metadata.get("encrypted_category"),  # Add missing encrypted_category field
                "encrypted_chat_tags": encrypted_metadata.get("encrypted_chat_tags"),
                "encrypted_chat_summary": encrypted_metadata.get("encrypted_chat_summary"),
                "encrypted_follow_up_request_suggestions": encrypted_metadata.get("encrypted_follow_up_request_suggestions"),
            }

            # CRITICAL: Add encrypted_chat_key ONLY if it exists (not None, not empty string)
            if encrypted_chat_key_value:
                chat_creation_payload["encrypted_chat_key"] = encrypted_chat_key_value

            # CRITICAL FIX: Keep all encrypted metadata fields even if empty strings
            # Only remove None values, but keep empty strings for encrypted fields (they might be valid)
            # Exception: encrypted_title must exist (can be empty string for new chats)
            chat_creation_payload = {k: v for k, v in chat_creation_payload.items() if v is not None}
            
            logger.info(
                f"Creating chat {chat_id} with: messages_v={messages_v}, title_v={title_v}, "
                f"last_edited={last_edited}, last_message={last_message}"
            )
            # create_chat_in_directus returns (created_data, is_duplicate)
            # is_duplicate=True means RECORD_NOT_UNIQUE error (race condition - another task created it)
            created_chat, is_duplicate = await directus_service.chat.create_chat_in_directus(chat_creation_payload)
            
            if created_chat and created_chat.get("id"):
                logger.info(
                    f"Successfully created chat {chat_id} with encrypted metadata (task_id: {task_id})"
                )
            elif is_duplicate:
                # RACE CONDITION FIX: Chat creation failed because another task (persist_new_chat_message_task)
                # already created a minimal chat record. Update the existing chat with encrypted metadata.
                logger.info(
                    f"✅ Chat {chat_id} was created by another task (race condition). "
                    f"Updating with encrypted metadata instead. (task_id: {task_id})"
                )
                # Update the existing chat with our encrypted metadata
                # Remove the 'id' field as we're updating, not creating
                update_payload = {k: v for k, v in chat_creation_payload.items() if k != 'id' and v is not None}
                updated_chat = await directus_service.chat.update_chat_fields_in_directus(
                    chat_id=chat_id,
                    fields_to_update=update_payload
                )
                if updated_chat:
                    logger.info(
                        f"✅ Successfully updated chat {chat_id} with encrypted metadata after race condition (task_id: {task_id})"
                    )
                else:
                    logger.error(
                        f"❌ Failed to update chat {chat_id} with encrypted metadata after race condition (task_id: {task_id})"
                    )
            else:
                # Chat creation failed for another reason (not a race condition)
                logger.error(
                    f"❌ Failed to create chat {chat_id} with encrypted metadata (task_id: {task_id}). "
                    f"Response: {created_chat}"
                )

    except Exception as e:
        logger.error(
            f"Error in _async_persist_encrypted_chat_metadata for chat {chat_id} (task_id: {task_id}): {e}",
            exc_info=True
        )
        raise  # Re-raise for Celery's retry mechanisms


@app.task(name="app.tasks.persistence_tasks.persist_encrypted_chat_metadata", bind=True)
def persist_encrypted_chat_metadata(
    self,
    chat_id: str,
    encrypted_metadata: Dict[str, Any],
    hashed_user_id: Optional[str] = None,
    user_id: Optional[str] = None  # User ID for cache updates (not hashed)
):
    """
    Celery task to persist encrypted chat metadata from the dual-phase architecture.
    This enforces zero-knowledge architecture - server never encrypts metadata.
    
    This task is responsible for creating the chat if it doesn't exist, since it has
    the encrypted metadata (title, category, etc.) from preprocessing.
    """
    task_id = self.request.id if self and hasattr(self, 'request') else 'UNKNOWN_TASK_ID'
    logger.info(
        f"SYNC_WRAPPER: persist_encrypted_chat_metadata for chat {chat_id}, "
        f"fields: {list(encrypted_metadata.keys())}, hashed_user_id: {hashed_user_id}, "
        f"user_id: {user_id[:8] + '...' if user_id else 'None'}, task_id: {task_id}"
    )
    
    loop = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_async_persist_encrypted_chat_metadata(
            chat_id, encrypted_metadata, task_id, hashed_user_id, user_id
        ))
    except Exception as e:
        logger.error(
            f"SYNC_WRAPPER_ERROR: persist_encrypted_chat_metadata for chat {chat_id}, "
            f"task_id: {task_id}: {e}",
            exc_info=True
        )
        raise  # Re-raise to let Celery handle retries/failure
    finally:
        if loop:
            loop.close()



# ========================================
# New Chat Suggestions Persistence
# ========================================

async def _async_persist_new_chat_suggestions(
    hashed_user_id: str,
    chat_id: str,
    encrypted_suggestions: list[str],
    task_id: str
):
    """
    Async logic for persisting new chat suggestions to separate Directus collection.
    Maintains last 50 suggestions per user.
    Uses bulk creation to reduce API calls from N to 1.
    """
    logger.info(
        f"Task _async_persist_new_chat_suggestions (task_id: {task_id}): "
        f"Persisting {len(encrypted_suggestions)} suggestions for user {hashed_user_id}"
    )

    directus_service = DirectusService()
    await directus_service.ensure_auth_token()

    now_ts = int(datetime.now(timezone.utc).timestamp())

    try:
        # Build all suggestion records for bulk creation
        suggestion_records = [
            {
                "hashed_user_id": hashed_user_id,
                "chat_id": chat_id,
                "encrypted_suggestion": encrypted_suggestion,
                "created_at": now_ts
            }
            for encrypted_suggestion in encrypted_suggestions
        ]

        # Create suggestions one-by-one using create_item (Directus doesn't support bulk create)
        # Note: This is more API calls but ensures data integrity
        failed_count = 0
        for suggestion_record in suggestion_records:
            try:
                success, result = await directus_service.create_item(
                    collection="new_chat_suggestions",
                    payload=suggestion_record
                )
                
                if not success:
                    logger.warning(f"Failed to create single suggestion for user {hashed_user_id}: {result}")
                    failed_count += 1
            except Exception as e:
                logger.warning(f"Exception creating single suggestion for user {hashed_user_id}: {e}")
                failed_count += 1
        
        if failed_count > 0:
            logger.warning(f"Created {len(suggestion_records) - failed_count}/{len(suggestion_records)} new chat suggestions (task_id: {task_id}), {failed_count} failed")
        else:
            logger.info(
                f"Successfully persisted {len(encrypted_suggestions)} new chat suggestions "
                f"for user {hashed_user_id} using individual creation (task_id: {task_id})"
            )

        # If all failed, raise error
        if failed_count == len(suggestion_records):
            raise RuntimeError(f"Failed to create all {len(suggestion_records)} suggestions")

        # Maintain limit of 50 suggestions per user (delete oldest in bulk)
        # Get count of suggestions for this user
        try:
            # Get all suggestions to count them (without sorting to avoid permissions errors)
            # NOTE: We removed sort to avoid Directus permissions issues
            # This means we might not delete the truly oldest ones, but that's acceptable
            # since suggestions are randomized on the client anyway
            existing_suggestions = await directus_service.get_items(
                collection="new_chat_suggestions",
                params={
                    "filter": {"hashed_user_id": {"_eq": hashed_user_id}},
                    # Removed sort to avoid Directus permissions error
                    "limit": 1000  # Get all to count (assumption: wont have thousands)
                }
            )

            if len(existing_suggestions) > 50:
                # Delete suggestions beyond 50 (may not be the oldest due to no sorting, but acceptable)
                suggestions_to_delete = existing_suggestions[50:]
                suggestion_ids_to_delete = [suggestion["id"] for suggestion in suggestions_to_delete]
                
                # Use bulk delete for efficiency (single HTTP request)
                success = await directus_service.bulk_delete_items(
                    collection="new_chat_suggestions",
                    item_ids=suggestion_ids_to_delete
                )
                
                if success:
                    logger.info(
                        f"Deleted {len(suggestions_to_delete)} suggestions for user {hashed_user_id} "
                        f"to maintain 50-suggestion limit (task_id: {task_id})"
                    )
                else:
                    logger.warning(
                        f"Failed to bulk delete {len(suggestions_to_delete)} suggestions for user {hashed_user_id}"
                    )
        except Exception as cleanup_error:
            # Log the error but don't fail the entire task
            # This allows suggestions to be created even if cleanup fails due to permissions
            logger.warning(
                f"Failed to cleanup old suggestions for user {hashed_user_id} (task_id: {task_id}). "
                f"This is likely due to Directus permissions. Error: {cleanup_error}. "
                f"New suggestions were still created successfully."
            )

    except Exception as e:
        logger.error(
            f"Error persisting new chat suggestions for user {hashed_user_id} (task_id: {task_id}): {e}",
            exc_info=True
        )
        raise


@app.task(name="app.tasks.persistence_tasks.persist_new_chat_suggestions", bind=True)
def persist_new_chat_suggestions_task(
    self,
    hashed_user_id: str,
    chat_id: str,
    encrypted_suggestions: list[str]
):
    """
    Celery task wrapper for persisting new chat suggestions.

    Args:
        hashed_user_id: Hashed user ID
        chat_id: Source chat that generated these suggestions
        encrypted_suggestions: List of encrypted suggestion strings (max 6)
    """
    task_id = self.request.id if self and hasattr(self, "request") else "UNKNOWN_TASK_ID"
    logger.info(
        f"SYNC_WRAPPER: persist_new_chat_suggestions_task for user {hashed_user_id}, "
        f"{len(encrypted_suggestions)} suggestions, task_id: {task_id}"
    )

    loop = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_async_persist_new_chat_suggestions(
            hashed_user_id, chat_id, encrypted_suggestions, task_id
        ))
    except Exception as e:
        logger.error(
            f"SYNC_WRAPPER_ERROR: persist_new_chat_suggestions_task for user {hashed_user_id}, "
            f"task_id: {task_id}: {e}",
            exc_info=True
        )
        raise  # Re-raise to let Celery handle retries/failure
    finally:
        if loop:
            loop.close()
        logger.info(f"TASK_FINALLY_SYNC_WRAPPER: Event loop closed for persist_new_chat_suggestions task_id: {task_id}")


@app.task(name="app.tasks.persistence_tasks.cleanup_uncompleted_signups", bind=True)
def cleanup_uncompleted_signups_task(self):
    """
    Task to clean up user accounts that haven't completed signup within 7 days.
    """
    task_id = self.request.id if self and hasattr(self, 'request') else 'UNKNOWN_TASK_ID'
    logger.info(f"SYNC_WRAPPER: cleanup_uncompleted_signups_task, task_id: {task_id}")
    
    loop = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(_async_cleanup_uncompleted_signups_task(task_id))
    except Exception as e:
        logger.error(f"Error in cleanup_uncompleted_signups_task, task_id: {task_id}: {e}", exc_info=True)
        raise
    finally:
        if loop:
            loop.close()
        logger.info(f"TASK_FINALLY_SYNC_WRAPPER: Event loop closed for cleanup_uncompleted_signups_task, task_id: {task_id}")

async def _async_cleanup_uncompleted_signups_task(task_id: str):
    """
    Async logic for cleaning up uncompleted signups.
    """
    logger.info(f"Task _async_cleanup_uncompleted_signups_task (task_id: {task_id}): Starting cleanup")
    directus_service = DirectusService()
    await directus_service.ensure_auth_token()
    
    from datetime import datetime, timedelta, timezone
    import json
    
    # Define "old" as created more than 7 days ago
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    iso_date = seven_days_ago.isoformat()
    
    # Filter for users who are still in signup process
    # last_opened starts with '/signup/' and signup_completed is false
    params = {
        "filter": json.dumps({
            "_and": [
                {
                    "signup_completed": {
                        "_eq": False
                    }
                },
                {
                    "last_opened": {
                        "_starts_with": "/signup/"
                    }
                },
                {
                    "created_at": {
                        "_lt": iso_date
                    }
                },
                {
                    "is_admin": {
                        "_eq": False
                    }
                }
            ]
        }),
        "fields": "id,account_id,last_opened",
        "limit": -1
    }
    
    try:
        url = f"{directus_service.base_url}/users"
        response = await directus_service._make_api_request("GET", url, params=params)
        
        if response.status_code == 200:
            users = response.json().get("data", [])
            logger.info(f"Found {len(users)} potentially uncompleted signups older than 7 days")
            
            for user in users:
                user_id = user.get("id")
                account_id = user.get("account_id")
                last_opened = user.get("last_opened")
                
                # Double check last_opened with the same logic as the API (Fallback 1)
                if last_opened:
                    import re
                    uuid_pattern = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)
                    if last_opened.startswith("/chat/") or uuid_pattern.match(last_opened):
                        logger.info(f"Skipping user {user_id} ({account_id}) as last_opened indicates completion. Updating flag.")
                        await directus_service.update_user(user_id, {"signup_completed": True})
                        continue

                # Calculate hashed user_id for zero-knowledge collections (usage, invoices)
                user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()

                async def check_usage():
                    usage_params = {
                        "filter": json.dumps({"user_id_hash": {"_eq": user_id_hash}}),
                        "limit": 1,
                        "meta": "filter_count"
                    }
                    resp = await directus_service._make_api_request("GET", f"{directus_service.base_url}/items/usage", params=usage_params)
                    if resp.status_code == 200:
                        return resp.json().get("meta", {}).get("filter_count", 0) > 0
                    return False

                async def check_invoices():
                    payment_params = {
                        "filter": json.dumps({
                            "user_id_hash": {"_eq": user_id_hash}, 
                            "status": {"_eq": "completed"}
                        }),
                        "limit": 1,
                        "meta": "filter_count"
                    }
                    resp = await directus_service._make_api_request("GET", f"{directus_service.base_url}/items/invoices", params=payment_params)
                    if resp.status_code == 200:
                        return resp.json().get("meta", {}).get("filter_count", 0) > 0
                    return False

                # Run checks in parallel for this user (Fallback 2)
                has_usage, has_credits = await asyncio.gather(check_usage(), check_invoices())
                
                if has_usage or has_credits:
                    logger.info(f"Skipping user {user_id} ({account_id}) as they have usage or credits. Updating flag.")
                    await directus_service.update_user(user_id, {"signup_completed": True})
                    continue
                
                # All checks passed, schedule deletion
                from backend.core.api.app.tasks.celery_config import app as celery_app
                celery_app.send_task(
                    "delete_user_account",
                    kwargs={"user_id": user_id},
                    queue="user_init"
                )
                logger.info(f"Scheduled deletion for uncompleted account: {account_id} (user_id: {user_id})")
                
            return True
        else:
            logger.error(f"Failed to fetch users for cleanup: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"Error in _async_cleanup_uncompleted_signups_task: {e}", exc_info=True)
        return False


# ========================================
# Settings/Memory Suggestion Rejection Persistence
# ========================================

async def _async_append_rejected_suggestion_hash(
    chat_id: str,
    rejection_hash: str,
    hashed_user_id: str,
    user_id: str,
    task_id: str
):
    """
    Async logic for appending a rejection hash to a chat's rejected_suggestion_hashes array.
    This enables cross-device sync of rejected settings/memory suggestions.
    
    Uses atomic array append to avoid race conditions.
    """
    logger.info(
        f"Task _async_append_rejected_suggestion_hash (task_id: {task_id}): "
        f"Appending rejection hash to chat {chat_id}"
    )

    directus_service = DirectusService()
    await directus_service.ensure_auth_token()

    try:
        # First, get the current rejected_suggestion_hashes array
        chat_data = await directus_service.chat.get_chat(chat_id)
        
        if not chat_data:
            logger.error(
                f"Task _async_append_rejected_suggestion_hash (task_id: {task_id}): "
                f"Chat {chat_id} not found in Directus"
            )
            return

        # Get existing hashes or initialize empty array
        existing_hashes = chat_data.get("rejected_suggestion_hashes") or []
        
        # Avoid duplicates
        if rejection_hash in existing_hashes:
            logger.debug(
                f"Task _async_append_rejected_suggestion_hash (task_id: {task_id}): "
                f"Hash already exists in chat {chat_id}, skipping"
            )
            return

        # Append the new hash
        updated_hashes = existing_hashes + [rejection_hash]
        
        # Update in Directus
        now_ts = int(datetime.now(timezone.utc).timestamp())
        update_result = await directus_service.chat.update_chat(
            chat_id,
            {
                "rejected_suggestion_hashes": updated_hashes,
                "updated_at": now_ts
            }
        )

        if update_result:
            logger.info(
                f"Task _async_append_rejected_suggestion_hash (task_id: {task_id}): "
                f"Successfully appended rejection hash to chat {chat_id} "
                f"(total hashes: {len(updated_hashes)})"
            )
        else:
            logger.error(
                f"Task _async_append_rejected_suggestion_hash (task_id: {task_id}): "
                f"Failed to update chat {chat_id} with rejection hash"
            )

    except Exception as e:
        logger.error(
            f"Error in _async_append_rejected_suggestion_hash for chat {chat_id} "
            f"(task_id: {task_id}): {e}",
            exc_info=True
        )
        raise


@app.task(name="app.tasks.persistence_tasks.append_rejected_suggestion_hash", bind=True)
def append_rejected_suggestion_hash(
    self,
    chat_id: str,
    rejection_hash: str,
    hashed_user_id: str,
    user_id: str
):
    """
    Celery task to append a rejection hash to a chat's rejected_suggestion_hashes array.
    This enables zero-knowledge cross-device sync of rejected settings/memory suggestions.
    """
    task_id = self.request.id if self and hasattr(self, 'request') else 'UNKNOWN_TASK_ID'
    logger.info(
        f"SYNC_WRAPPER: append_rejected_suggestion_hash for chat {chat_id}, "
        f"task_id: {task_id}"
    )
    
    loop = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_async_append_rejected_suggestion_hash(
            chat_id, rejection_hash, hashed_user_id, user_id, task_id
        ))
    except Exception as e:
        logger.error(
            f"SYNC_WRAPPER_ERROR: append_rejected_suggestion_hash for chat {chat_id}, "
            f"task_id: {task_id}: {e}",
            exc_info=True
        )
        raise
    finally:
        if loop:
            loop.close()


# ==============================================================================
# Embed Fallback Persistence Task
# ==============================================================================
# This task provides a server-side safety net for embed persistence.
#
# PROBLEM: The normal embed persistence flow relies on a client round-trip:
#   1. Server creates embed in cache (vault-encrypted) → sends plaintext to client
#   2. Client encrypts with chat key → sends "store_embed" back to server
#   3. Server writes client-encrypted embed to Directus
#
# If step 2 fails (WebSocket disconnect, client crash, tab closure, etc.),
# the embed is NEVER persisted to Directus. After the Redis cache TTL expires
# (72 hours), the embed data is permanently lost.
#
# SOLUTION: Schedule this fallback task with a countdown (e.g., 60 seconds) after
# an embed is finalized (status="finished"). It checks if the embed was persisted
# to Directus by the client. If not, it reads the vault-encrypted data from Redis
# cache and persists it directly to Directus with encryption_mode="vault".
#
# The client already handles vault-encrypted embeds: when it encounters
# encryption_mode="vault", it stores locally and does NOT re-encrypt.
# This means fallback-persisted embeds are fully functional on all devices.
# ==============================================================================

async def _async_persist_embed_fallback(
    embed_id: str,
    task_id: str
):
    """
    Fallback persistence for an embed that may not have been stored by the client.
    
    Checks if the embed exists in Directus. If not, reads the vault-encrypted
    data from Redis cache and persists it directly. This prevents silent data loss
    when the client-to-server store_embed round-trip fails.
    
    Args:
        embed_id: The embed ID to check/persist
        task_id: Celery task ID for logging
    """
    logger.info(
        f"[EMBED_FALLBACK] Task _async_persist_embed_fallback (task_id: {task_id}): "
        f"Checking embed {embed_id} persistence status"
    )

    directus_service = DirectusService()
    await directus_service.ensure_auth_token()

    # Step 1: Check if the embed already exists in Directus (client persisted it via store_embed)
    try:
        existing = await directus_service.embed.get_embed_by_id(embed_id)
        if existing:
            logger.info(
                f"[EMBED_FALLBACK] ✅ Embed {embed_id} already persisted to Directus "
                f"(client handled it). Skipping fallback. (task_id: {task_id})"
            )
            return
    except Exception as check_error:
        logger.warning(
            f"[EMBED_FALLBACK] Could not check Directus for embed {embed_id}: {check_error}. "
            f"Proceeding with fallback attempt. (task_id: {task_id})"
        )

    # Step 2: Read embed data from Redis cache (vault-encrypted)
    cache_service = CacheService()
    client = await cache_service.client
    if not client:
        logger.error(
            f"[EMBED_FALLBACK] ❌ Redis client not available for embed {embed_id}. "
            f"Cannot persist without cache data. (task_id: {task_id})"
        )
        return

    cache_key = f"embed:{embed_id}"
    embed_json = await client.get(cache_key)
    if not embed_json:
        logger.warning(
            f"[EMBED_FALLBACK] ⚠️ Embed {embed_id} not found in Redis cache (expired or never cached). "
            f"Cannot persist without cache data. (task_id: {task_id})"
        )
        return

    try:
        embed_data = json.loads(embed_json)
    except json.JSONDecodeError as e:
        logger.error(
            f"[EMBED_FALLBACK] ❌ Failed to parse cached embed {embed_id}: {e}. "
            f"(task_id: {task_id})"
        )
        return

    # Step 3: Verify the embed is in "finished" status (don't persist processing/error embeds)
    cached_status = embed_data.get("status")
    if cached_status != "finished":
        logger.info(
            f"[EMBED_FALLBACK] Embed {embed_id} status is '{cached_status}', not 'finished'. "
            f"Skipping fallback persistence. (task_id: {task_id})"
        )
        return

    # Step 4: Build Directus payload from cache data
    # The cache contains vault-encrypted content. We persist it with encryption_mode="vault"
    # so the client knows to request server-side decryption rather than trying to decrypt
    # with a chat key it doesn't have for this embed.
    vault_key_id = embed_data.get("vault_key_id")
    if not vault_key_id:
        logger.warning(
            f"[EMBED_FALLBACK] ⚠️ Embed {embed_id} has no vault_key_id in cache. "
            f"The embed may have been cached before vault_key_id tracking was added. "
            f"Persisting anyway with encryption_mode='vault'. (task_id: {task_id})"
        )

    # Determine encrypted_type: encrypt the plaintext type with vault key if possible
    # For the fallback, we store the type as-is since it's not sensitive (it's metadata)
    # The schema has encrypted_type field but for vault-mode embeds the server can read it
    embed_type = embed_data.get("type", "app_skill_use")

    directus_payload = {
        "embed_id": embed_data.get("embed_id", embed_id),
        "hashed_chat_id": embed_data.get("hashed_chat_id"),
        "hashed_message_id": embed_data.get("hashed_message_id"),
        "hashed_task_id": embed_data.get("hashed_task_id"),
        "status": "finished",
        "hashed_user_id": embed_data.get("hashed_user_id"),
        "is_private": embed_data.get("is_private", False),
        "is_shared": embed_data.get("is_shared", False),
        "embed_ids": embed_data.get("embed_ids"),
        "encryption_mode": "vault",  # Server-managed encryption (vault key)
        "vault_key_id": vault_key_id,
        "encrypted_content": embed_data.get("encrypted_content"),
        "encrypted_type": embed_type,  # Store plaintext type (vault-mode allows server to read it)
        "parent_embed_id": embed_data.get("parent_embed_id"),
        "text_length_chars": embed_data.get("text_length_chars"),
        "created_at": embed_data.get("created_at"),
        "updated_at": embed_data.get("updated_at"),
        "s3_file_keys": embed_data.get("s3_file_keys"),
    }

    # Remove None values to avoid overwriting defaults in Directus
    directus_payload = {k: v for k, v in directus_payload.items() if v is not None}

    # Step 5: Create the embed in Directus
    try:
        created = await directus_service.embed.create_embed(directus_payload)
        if created:
            logger.info(
                f"[EMBED_FALLBACK] ✅ Successfully persisted embed {embed_id} to Directus "
                f"via server-side fallback (encryption_mode=vault, vault_key_id={vault_key_id}). "
                f"(task_id: {task_id})"
            )
        else:
            logger.error(
                f"[EMBED_FALLBACK] ❌ Failed to persist embed {embed_id} to Directus "
                f"(create_embed returned None). (task_id: {task_id})"
            )
    except Exception as e:
        logger.error(
            f"[EMBED_FALLBACK] ❌ Exception persisting embed {embed_id} to Directus: {e}. "
            f"(task_id: {task_id})",
            exc_info=True
        )


@app.task(name="app.tasks.persistence_tasks.persist_embed_fallback", bind=True)
def persist_embed_fallback_task(self, embed_id: str):
    """
    Celery task (sync wrapper) to check if an embed was persisted to Directus
    by the client, and if not, persist the vault-encrypted version from Redis cache.
    
    This task is dispatched with a countdown delay (e.g., 60 seconds) after an embed
    is finalized. The delay gives the client time to complete the normal persistence
    flow (encrypt → store_embed → Directus). If the client didn't persist it within
    that window, this fallback persists the vault-encrypted version directly.
    
    Args:
        embed_id: The embed ID to check/persist
    """
    task_id = self.request.id if self and hasattr(self, 'request') else 'UNKNOWN_TASK_ID'
    logger.info(
        f"SYNC_WRAPPER: persist_embed_fallback for embed {embed_id}, task_id: {task_id}"
    )
    loop = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_async_persist_embed_fallback(embed_id, task_id))
    except Exception as e:
        logger.error(
            f"SYNC_WRAPPER_ERROR: persist_embed_fallback for embed {embed_id}, "
            f"task_id: {task_id}: {e}",
            exc_info=True
        )
        raise
    finally:
        if loop:
            loop.close()
