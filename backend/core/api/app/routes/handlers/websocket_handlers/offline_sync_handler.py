import hashlib
import logging
import time
from typing import Dict, Any, List, Optional

from fastapi import WebSocket

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService # Keep if needed
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.routes.connection_manager import ConnectionManager
from backend.core.api.app.tasks.celery_config import app as celery_app_instance
# Import validation function from draft handler if needed, or redefine

logger = logging.getLogger(__name__)


def _cached_version_component(server_versions: Any, component: str) -> int:
    """Return a cached version component, including dynamic Pydantic extra fields."""
    value = getattr(server_versions, component, None)
    if value is None:
        value = (getattr(server_versions, "model_extra", None) or {}).get(component)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


async def _offline_draft_change_allowed(
    directus_service: DirectusService,
    user_id: str,
    chat_id: str,
) -> bool:
    """Allow replay for owned chats and draft-only local chats; reject foreign existing chats."""
    chat_service = getattr(directus_service, "chat", None)
    if chat_service is None:
        return True

    try:
        if await chat_service.check_chat_ownership(chat_id, user_id):
            return True
        return await chat_service.get_chat_metadata(chat_id) is None
    except Exception as ownership_error:
        try:
            return await chat_service.get_chat_metadata(chat_id) is None
        except Exception:
            logger.error(
                "Unable to verify offline draft replay permissions for chat %s, user %s: %s",
                chat_id,
                user_id,
                ownership_error,
                exc_info=True,
            )
            return False


async def _delete_directus_user_draft_if_present(
    directus_service: DirectusService,
    user_id: str,
    chat_id: str,
) -> None:
    """Best-effort Directus cleanup; Redis tombstone remains authoritative."""
    get_items = getattr(directus_service, "get_items", None)
    delete_item = getattr(directus_service, "delete_item", None)
    if get_items is None or delete_item is None:
        return

    try:
        existing_drafts_data = await get_items(
            collection="drafts",
            params={
                "filter[hashed_user_id][_eq]": hashlib.sha256(user_id.encode()).hexdigest(),
                "filter[chat_id][_eq]": chat_id,
                "fields": "id",
                "limit": 1,
            },
        )
        if not existing_drafts_data:
            logger.info(
                "User %s: No draft found in Directus for chat_id: %s to delete during offline sync.",
                user_id,
                chat_id,
            )
            return

        draft_to_delete_id = existing_drafts_data[0]["id"]
        delete_successful = await delete_item(collection="drafts", item_id=draft_to_delete_id)
        if delete_successful:
            logger.info(
                "User %s: Successfully deleted draft %s from Directus during offline sync for chat %s",
                user_id,
                draft_to_delete_id,
                chat_id,
            )
        else:
            logger.error(
                "User %s: Failed to delete draft %s from Directus during offline sync for chat %s",
                user_id,
                draft_to_delete_id,
                chat_id,
            )
    except Exception as exc:
        logger.error(
            "User %s: Error processing draft deletion from Directus for chat_id %s during offline sync: %s",
            user_id,
            chat_id,
            exc,
            exc_info=True,
        )


async def _chat_exists_for_user(
    cache_service: CacheService,
    user_id: str,
    chat_id: str,
    default: bool,
) -> bool:
    check_chat_exists = getattr(cache_service, "check_chat_exists_for_user", None)
    if check_chat_exists is None:
        return default
    try:
        return await check_chat_exists(user_id, chat_id)
    except Exception as exc:
        logger.error(
            "Failed to check chat_ids_versions membership for user %s, chat %s: %s",
            user_id,
            chat_id,
            exc,
            exc_info=True,
        )
        return default


async def _add_draft_chat_to_ids_versions(
    cache_service: CacheService,
    user_id: str,
    chat_id: str,
    timestamp: int,
) -> None:
    add_chat = getattr(cache_service, "add_chat_to_ids_versions", None)
    if add_chat is not None:
        added = await add_chat(user_id, chat_id, timestamp)
    else:
        added = await cache_service.update_chat_score_in_ids_versions(user_id, chat_id, timestamp)
    if not added:
        logger.error(
            "Failed to add draft-only chat %s to chat_ids_versions for user %s during offline sync",
            chat_id,
            user_id,
        )


async def handle_sync_offline_changes(
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService, # Keep for potential future use
    encryption_service: EncryptionService,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any], # Expected: {"changes": [...]}
    user_otel_attrs: dict = None,
):
    """Handles queued offline changes sent by the client upon reconnection."""
    
    _otel_span, _otel_token = None, None
    try:
        from backend.shared.python_utils.tracing.ws_span_helper import start_ws_handler_span
        _otel_span, _otel_token = start_ws_handler_span("sync_offline_changes", user_id, payload, user_otel_attrs)
    except Exception:
        pass
    try:
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
                    if change_type not in {"draft", "delete_draft"}:
                        logger.warning(f"Cannot process offline change for chat {chat_id}: Server versions not found in cache. Skipping.")
                        error_count += 1
                        continue
                    if not await _offline_draft_change_allowed(directus_service, user_id, chat_id):
                        logger.warning(
                            f"Cannot process offline draft change for chat {chat_id}: chat exists but is not owned by user {user_id}."
                        )
                        error_count += 1
                        continue
                    logger.info(
                        f"Processing offline {change_type} for chat {chat_id} without cached versions; treating as draft-only local chat replay."
                    )

                # 2. Conflict Resolution
                server_current_version = -1
                component_key: Optional[str] = None
                client_version_key: Optional[str] = None
                if change_type == "title":
                    server_current_version = _cached_version_component(server_versions, "title_v")
                    component_key = "title_v"
                    client_version_key = "title_v"
                elif change_type == "draft":
                    server_current_version = _cached_version_component(server_versions, f"user_draft_v:{user_id}")
                    component_key = f"user_draft_v:{user_id}"
                    client_version_key = "draft_v"
                elif change_type == "delete_draft":
                    server_current_version = _cached_version_component(server_versions, f"user_draft_v:{user_id}")
                    component_key = f"user_draft_v:{user_id}"
                    client_version_key = "draft_v"
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
                broadcast_last_edited_timestamp: Optional[int] = None

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
                            "title_v": new_cache_version,
                            "user_id": user_id,
                        },
                        queue='persistence'
                    )

                # --- Apply Draft Change ---
                elif change_type == "draft":
                    encrypted_draft_md = new_value # Can be encrypted string or null
                    broadcast_data_key = "encrypted_draft_md"
                    broadcast_data_value = encrypted_draft_md

                    # Basic validation for encrypted content
                    if encrypted_draft_md and len(encrypted_draft_md) > 100000:  # Limit for encrypted content
                        logger.warning(f"Offline draft change for chat {chat_id} rejected: Content limits exceeded.")
                        error_count += 1
                        continue # Skip this change

                    # Content is already encrypted, use directly
                    encrypted_value_str = encrypted_draft_md

                    # Update user-specific draft version and data. Drafts are no longer
                    # shared chat version components; each user owns an encrypted draft.
                    new_cache_version = await cache_service.increment_user_draft_version(user_id, chat_id)
                    if new_cache_version is None:
                        logger.error(f"Failed to increment draft_v in cache for offline change (chat {chat_id}).")
                        error_count += 1
                        continue
                    update_success = await cache_service.update_user_draft_in_cache(
                        user_id,
                        chat_id,
                        encrypted_value_str,
                        new_cache_version,
                        encrypted_draft_preview=change.get("encrypted_draft_preview"),
                    )
                    if update_success is None:
                        logger.error(f"Failed to update draft cache for offline change (chat {chat_id}).")
                        error_count += 1
                        continue
                    if update_success is False:
                        logger.info(f"Skipped superseded offline draft update for user {user_id}, chat {chat_id}.")
                        processed_count += 1
                        continue

                    # Match update_draft_handler semantics: draft-only new chats are
                    # discoverable cross-device, but drafts do not reorder existing chats.
                    now_ts_for_draft = int(time.time())
                    chat_exists_in_sorted_set = await _chat_exists_for_user(
                        cache_service,
                        user_id,
                        chat_id,
                        default=server_versions is not None,
                    )
                    if not chat_exists_in_sorted_set:
                        await _add_draft_chat_to_ids_versions(cache_service, user_id, chat_id, now_ts_for_draft)
                        broadcast_last_edited_timestamp = now_ts_for_draft
                    else:
                        get_timestamp = getattr(cache_service, "get_chat_last_edited_overall_timestamp", None)
                        if get_timestamp is not None:
                            try:
                                broadcast_last_edited_timestamp = await get_timestamp(user_id, chat_id)
                            except Exception as timestamp_error:
                                logger.warning(
                                    f"Failed to read chat timestamp for offline draft sync chat {chat_id}: {timestamp_error}"
                                )
                        if broadcast_last_edited_timestamp is None:
                            broadcast_last_edited_timestamp = now_ts_for_draft

                    # NO immediate persistence task for drafts

                # --- Apply Draft Deletion ---
                elif change_type == "delete_draft":
                    deleted_draft_v = await cache_service.increment_user_draft_version(user_id, chat_id)
                    if deleted_draft_v is None:
                        logger.error(f"Failed to increment draft_v tombstone in cache for offline delete_draft (chat {chat_id}).")
                        error_count += 1
                        continue

                    tombstone_draft = getattr(cache_service, "tombstone_user_draft_in_cache", None)
                    if tombstone_draft is not None:
                        cache_delete_success = await tombstone_draft(
                            user_id=user_id,
                            chat_id=chat_id,
                            draft_version=deleted_draft_v,
                        )
                    else:
                        cache_delete_success = await cache_service.delete_user_draft_from_cache(
                            user_id=user_id,
                            chat_id=chat_id,
                        )
                    if cache_delete_success:
                        logger.info(f"User {user_id}: Successfully tombstoned draft in cache for chat_id: {chat_id} during offline sync.")
                    else:
                        logger.warning(f"User {user_id}: Draft cache tombstone failed for chat_id: {chat_id} during offline sync.")
                        processed_count += 1
                        continue

                    try:
                        chat_service = getattr(directus_service, "chat", None)
                        chat_metadata = await chat_service.get_chat_metadata(chat_id) if chat_service is not None else None
                        if not chat_metadata:
                            remove_chat = getattr(cache_service, "remove_chat_from_ids_versions", None)
                            if remove_chat is not None:
                                await remove_chat(user_id, chat_id)
                    except Exception as cleanup_error:
                        logger.error(
                            f"User {user_id}: Error during offline draft-only chat cleanup for {chat_id}: {cleanup_error}",
                            exc_info=True,
                        )

                    await _delete_directus_user_draft_if_present(directus_service, user_id, chat_id)

                    await manager.broadcast_to_user(
                        message={
                            "type": "draft_deleted",
                            "payload": {"chat_id": chat_id, "draft_v": deleted_draft_v},
                        },
                        user_id=user_id,
                        exclude_device_hash=None,
                    )
                    processed_count += 1
                    continue

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
                    "versions": {client_version_key or component_key: new_cache_version}
                }
                if change_type == "draft":
                    broadcast_payload["data"]["encrypted_draft_preview"] = change.get("encrypted_draft_preview")
                if broadcast_last_edited_timestamp is not None:
                    broadcast_payload["last_edited_overall_timestamp"] = broadcast_last_edited_timestamp
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
                except Exception:
                    pass  # Ignore send error

        logger.info(f"Finished processing offline changes for user {user_id}. Processed: {processed_count}, Conflicts: {conflict_count}, Errors: {error_count}.")
        # Optionally send a summary confirmation back to the client device
        try:
            await manager.send_personal_message(
                message={"type": "offline_sync_complete", "payload": {"processed": processed_count, "conflicts": conflict_count, "errors": error_count}},
                user_id=user_id, device_fingerprint_hash=device_fingerprint_hash
            )
        except Exception:
            pass
    finally:
        if _otel_span is not None:
            try:
                from backend.shared.python_utils.tracing.ws_span_helper import end_ws_handler_span as _end_span
                _end_span(_otel_span, _otel_token)
            except Exception:
                pass
