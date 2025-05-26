import logging
import json
import time
from typing import Dict, Any, List, Optional

from fastapi import WebSocket

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService # Keep if needed
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.routes.connection_manager import ConnectionManager
from backend.core.api.app.tasks.celery_config import app as celery_app_instance
# Import validation function from draft handler if needed, or redefine
from .draft_update_handler import _validate_draft_content, MAX_DRAFT_WORDS, MAX_DRAFT_CHARS

logger = logging.getLogger(__name__)

async def handle_sync_offline_changes(
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService, # Keep for potential future use
    encryption_service: EncryptionService,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any] # Expected: {"changes": [...]}
):
    """Handles queued offline changes sent by the client upon reconnection."""
    
    offline_changes: List[Dict[str, Any]] = payload.get("changes", [])
    if not offline_changes:
        logger.info(f"Received sync_offline_changes from {user_id}/{device_fingerprint_hash} with no changes.")
        return

    logger.info(f"Processing {len(offline_changes)} offline changes for user {user_id}/{device_fingerprint_hash}.")

    processed_count = 0
    conflict_count = 0
    error_count = 0

    for change in offline_changes:
        try:
            chat_id = change.get("chat_id")
            change_type = change.get("type") # "title" or "draft"
            new_value = change.get("value") # Plain text title or Tiptap JSON draft object/null
            version_before_edit = change.get("version_before_edit") # Client's version before their offline edit

            if not chat_id or not change_type or version_before_edit is None:
                logger.warning(f"Skipping invalid offline change item: {change}. Missing required fields.")
                error_count += 1
                continue

            # 1. Fetch current server versions for the chat
            server_versions = await cache_service.get_chat_versions(user_id, chat_id)
            if not server_versions:
                logger.warning(f"Cannot process offline change for chat {chat_id}: Server versions not found in cache. Skipping.")
                error_count += 1
                continue

            # 2. Conflict Resolution
            server_current_version = -1
            component_key: Optional[str] = None
            if change_type == "title":
                server_current_version = server_versions.title_v
                component_key = "title_v"
            elif change_type == "draft":
                server_current_version = server_versions.draft_v
                component_key = "draft_v"
            else:
                logger.warning(f"Skipping offline change for chat {chat_id}: Unknown change type '{change_type}'.")
                error_count += 1
                continue

            if server_current_version > version_before_edit:
                logger.info(f"Offline change conflict for chat {chat_id}, type '{change_type}'. Server version ({server_current_version}) > Client version before edit ({version_before_edit}). Discarding client change.")
                conflict_count += 1
                # Optionally notify client of conflict? For now, just log.
                continue

            # 3. Apply Accepted Change
            logger.info(f"Applying offline change for chat {chat_id}, type '{change_type}'. Server version ({server_current_version}) <= Client version before edit ({version_before_edit}).")

            new_cache_version = -1
            encrypted_value_str: Optional[str] = None
            broadcast_data_key: str = ""
            broadcast_data_value: Any = None
            update_timestamp = False

            # --- Apply Title Change ---
            if change_type == "title":
                new_title_plain = new_value if isinstance(new_value, str) else ""
                broadcast_data_key = "title"
                broadcast_data_value = new_title_plain

                # Validate
                if len(new_title_plain) > 255:
                    logger.warning(f"Offline title change for chat {chat_id} rejected: Title too long.")
                    error_count += 1
                    continue # Skip this change

                try:
                    # Encrypt title using the new encrypt_with_chat_key method
                    encrypted_title_tuple = await encryption_service.encrypt_with_chat_key(
                        plaintext=new_title_plain,
                        key_id=chat_id
                    )
                    if not encrypted_title_tuple or not encrypted_title_tuple[0]:
                        logger.error(f"Offline sync: encrypt_with_chat_key failed to return encrypted title for chat {chat_id}.")
                        error_count += 1
                        continue
                    encrypted_value_str = encrypted_title_tuple[0] # (ciphertext, version_identifier)
                except Exception as e:
                    logger.error(f"Offline sync: Failed to encrypt title for chat {chat_id} using encrypt_with_chat_key. Error: {e}", exc_info=True)
                    error_count += 1
                    continue

                # Update Cache Version & Data
                new_cache_version = await cache_service.increment_chat_component_version(user_id, chat_id, "title_v")
                if new_cache_version is None:
                    logger.error(f"Failed to increment title_v in cache for offline change (chat {chat_id}).")
                    error_count += 1
                    continue
                await cache_service.update_chat_list_item_field(user_id, chat_id, "title", encrypted_value_str)

                # Dispatch Persistence Task
                celery_app_instance.send_task(
                    name='app.tasks.persistence_tasks.persist_chat_title',
                    kwargs={
                        "chat_id": chat_id,
                        "encrypted_title": encrypted_value_str,
                        "title_version": new_cache_version
                    },
                    queue='persistence'
                )

            # --- Apply Draft Change ---
            elif change_type == "draft":
                draft_json_plain = new_value # Can be dict or null
                broadcast_data_key = "draft_json"
                broadcast_data_value = draft_json_plain
                update_timestamp = True # Draft changes update timestamp

                # Validate
                if draft_json_plain and not _validate_draft_content(draft_json_plain):
                    logger.warning(f"Offline draft change for chat {chat_id} rejected: Content limits exceeded.")
                    error_count += 1
                    continue # Skip this change

                # Encrypt
                if draft_json_plain:
                    try:
                        draft_json_string = json.dumps(draft_json_plain)
                        # Encrypt draft using local AES with user-specific key
                        raw_user_aes_key = await encryption_service.get_user_draft_aes_key(user_id)
                        if not raw_user_aes_key:
                            logger.error(f"Offline sync: Failed to get user draft AES key for user {user_id}, chat {chat_id}.")
                            error_count += 1
                            continue
                        encrypted_value_str = encryption_service.encrypt_locally_with_aes(draft_json_string, raw_user_aes_key)
                    except Exception as e:
                        logger.error(f"Offline sync: Failed to encrypt draft for user {user_id}, chat {chat_id} using local AES. Error: {e}", exc_info=True)
                        error_count += 1
                        continue
                else:
                    encrypted_value_str = None # Handle null draft

                # Update Cache Version & Data
                new_cache_version = await cache_service.increment_chat_component_version(user_id, chat_id, "draft_v")
                if new_cache_version is None:
                    logger.error(f"Failed to increment draft_v in cache for offline change (chat {chat_id}).")
                    error_count += 1
                    continue
                await cache_service.update_chat_list_item_field(user_id, chat_id, "draft_json", encrypted_value_str)

                # NO immediate persistence task for drafts

            # --- Post-Update Steps (Common for accepted changes) ---
            now_ts = int(time.time())
            if update_timestamp:
                await cache_service.update_chat_score_in_ids_versions(user_id, chat_id, now_ts)

            # Broadcast Update
            broadcast_event = f"chat_{change_type}_updated" # e.g., chat_title_updated, chat_draft_updated
            broadcast_payload = {
                "event": broadcast_event,
                "chat_id": chat_id,
                "data": {broadcast_data_key: broadcast_data_value},
                "versions": {component_key: new_cache_version}
            }
            if update_timestamp:
                broadcast_payload["last_edited_overall_timestamp"] = now_ts

            await manager.broadcast_to_user(
                message_content=broadcast_payload,
                user_id=user_id,
                exclude_device_hash=None # Notify all devices, including the one that sent the offline changes
            )
            processed_count += 1

        except Exception as e:
            logger.error(f"Error processing offline change item {change} for user {user_id}: {e}", exc_info=True)
            error_count += 1
            # Attempt to notify client about the specific error?
            try:
                 await manager.send_personal_message(
                    message={"type": "error", "payload": {"message": f"Error processing an offline change for chat {change.get('chat_id')}", "change": change}},
                    user_id=user_id, device_fingerprint_hash=device_fingerprint_hash
                 )
            except: pass # Ignore send error

    logger.info(f"Finished processing offline changes for user {user_id}. Processed: {processed_count}, Conflicts: {conflict_count}, Errors: {error_count}.")
    # Optionally send a summary confirmation back to the client device
    try:
        await manager.send_personal_message(
            message={"type": "offline_sync_complete", "payload": {"processed": processed_count, "conflicts": conflict_count, "errors": error_count}},
            user_id=user_id, device_fingerprint_hash=device_fingerprint_hash
        )
    except: pass