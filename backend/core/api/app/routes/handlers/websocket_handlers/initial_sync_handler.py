import logging
import json
from typing import List, Dict, Any, Optional, Tuple
from pydantic import ValidationError

from backend.core.api.app.schemas.chat import CachedChatVersions, CachedChatListItemData, ChatSyncData, InitialSyncResponsePayloadSchema, ClientChatComponentVersions
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

async def handle_initial_sync(
    cache_service: CacheService,
    directus_service: DirectusService,
    encryption_service: EncryptionService,
    manager: Any, # Should be ConnectionManager type
    user_id: str,
    device_fingerprint_hash: str,
    websocket: Any,
    client_chat_versions: Dict[str, Dict[str, int]],
    last_sync_timestamp: Optional[int] = None,
    immediate_view_chat_id: Optional[str] = None,
    pending_message_ids: Optional[Dict[str, List[str]]] = None
):
    logger.info(f"Handling initial_sync_request for user {user_id}, device {device_fingerprint_hash}. Client has {len(client_chat_versions)} chats. Last sync timestamp: {last_sync_timestamp}")

    chats_to_add_or_update_data: List[ChatSyncData] = []
    chat_ids_to_delete_on_client: List[str] = []
    
    try:
        # The timestamp at the beginning of the sync process.
        sync_start_timestamp = int(datetime.now(timezone.utc).timestamp())

        # 1. Fetch Server's Master Chat List from Cache
        server_master_list_tuples: List[Tuple[str, float]] = await cache_service.get_chat_ids_versions(user_id, with_scores=True)
        server_master_chat_ids_set = {chat_id for chat_id, score in server_master_list_tuples}
        server_chat_order = [chat_id for chat_id, score in server_master_list_tuples]
        logger.info(f"User {user_id}: Server master list from cache has {len(server_master_chat_ids_set)} chats.")

        # 2. Determine Chats to Delete on Client
        client_chat_ids_set = set(client_chat_versions.keys())
        chats_to_delete = list(client_chat_ids_set - server_master_chat_ids_set)
        if chats_to_delete:
            chat_ids_to_delete_on_client.extend(chats_to_delete)
            logger.info(f"User {user_id}: Suggesting deletion of {len(chat_ids_to_delete_on_client)} chats on client: {chat_ids_to_delete_on_client}")

        # 3. Process Server's Chats for Deltas
        for server_chat_id, server_last_edited_ts_score in server_master_list_tuples:
            # Timestamp-based filtering
            if last_sync_timestamp and server_last_edited_ts_score <= last_sync_timestamp:
                logger.debug(f"User {user_id}: Chat {server_chat_id} skipped by timestamp. Server TS: {server_last_edited_ts_score}, Client Last Sync: {last_sync_timestamp}")
                continue

            current_chat_payload_dict: Dict[str, Any] = {"chat_id": server_chat_id}
            needs_update_on_client = False

            cached_server_versions: Optional[CachedChatVersions] = await cache_service.get_chat_versions(user_id, server_chat_id)
            
            if not cached_server_versions:
                logger.warning(f"User {user_id}: Versions not found in cache for chat {server_chat_id}. This indicates a cache inconsistency. Forcing update for this chat.")
                # Force a full update for this chat since we can't trust the cache
                needs_update_on_client = True
                current_chat_payload_dict["type"] = "updated_chat" # Treat as updated to force client to fetch
                # Create a dummy versions object to allow processing to continue
                cached_server_versions = CachedChatVersions(messages_v=9999, title_v=9999) # High versions to ensure update
            
            draft_cache_result = await cache_service.get_user_draft_from_cache(user_id, server_chat_id)
            user_draft_content_encrypted, user_draft_version_cache = draft_cache_result if draft_cache_result else (None, 0)

            server_versions_for_client = ClientChatComponentVersions(
                messages_v=cached_server_versions.messages_v,
                title_v=cached_server_versions.title_v,
                draft_v=user_draft_version_cache
            )
            current_chat_payload_dict["versions"] = server_versions_for_client
            current_chat_payload_dict["last_edited_overall_timestamp"] = int(server_last_edited_ts_score)

            client_versions_for_chat = client_chat_versions.get(server_chat_id)

            if not client_versions_for_chat:
                needs_update_on_client = True
                current_chat_payload_dict["type"] = "new_chat"
            elif not needs_update_on_client: # Don't re-evaluate if already forced
                if server_versions_for_client.title_v > client_versions_for_chat.get("title_v", -1):
                    needs_update_on_client = True
                if server_versions_for_client.draft_v > client_versions_for_chat.get("draft_v", -1):
                    needs_update_on_client = True
                if server_versions_for_client.messages_v > client_versions_for_chat.get("messages_v", -1):
                    needs_update_on_client = True
                
                if needs_update_on_client:
                    current_chat_payload_dict["type"] = "updated_chat"

            if needs_update_on_client:
                decrypted_title = ""
                unread_count = 0
                mates = []
                
                try:
                    cached_list_item_data = await cache_service.get_chat_list_item_data(user_id, server_chat_id, refresh_ttl=True)
                    if not cached_list_item_data:
                        raise ValueError("Cached list item data is None")
                except (ValidationError, ValueError) as e:
                    logger.warning(f"Validation/Value error for cached list item data for chat {server_chat_id}, user {user_id}: {e}. Falling back to DB.")
                    db_list_item_data = await directus_service.chat.get_chat_list_item_data_from_db(server_chat_id)
                    if db_list_item_data:
                        # Re-construct a valid-looking object for the subsequent logic
                        cached_list_item_data = CachedChatListItemData(
                            title=db_list_item_data.get("encrypted_title", ""),
                            unread_count=db_list_item_data.get("unread_count", 0),
                            mates=db_list_item_data.get("mates", []),
                            created_at=db_list_item_data.get("created_at", 0),
                            updated_at=db_list_item_data.get("updated_at", 0)
                        )
                    else:
                        logger.error(f"DB fallback failed for chat {server_chat_id}. Cannot get list item data.")
                        cached_list_item_data = None
                        # If DB fallback fails, we cannot proceed with this chat.
                        continue

                if cached_list_item_data:
                    if cached_list_item_data.title:
                        dec_title = await encryption_service.decrypt_with_chat_key(cached_list_item_data.title, server_chat_id)
                        if dec_title: decrypted_title = dec_title
                    unread_count = cached_list_item_data.unread_count
                    if cached_list_item_data.mates:
                        # Ensure mates is a list of unique strings
                        mates = list(dict.fromkeys(cached_list_item_data.mates))
                    current_chat_payload_dict["created_at"] = cached_list_item_data.created_at
                    current_chat_payload_dict["updated_at"] = cached_list_item_data.updated_at
                    if cached_server_versions:
                        current_chat_payload_dict["versions"].title_v = cached_server_versions.title_v


                decrypted_draft_json = None
                if user_draft_content_encrypted and user_draft_content_encrypted != "null":
                    raw_user_aes_key = await encryption_service.get_user_draft_aes_key(user_id)
                    if raw_user_aes_key:
                        dec_draft_str = encryption_service.decrypt_locally_with_aes(user_draft_content_encrypted, raw_user_aes_key)
                        if dec_draft_str:
                            decrypted_draft_json = json.loads(dec_draft_str)

                current_chat_payload_dict["title"] = decrypted_title
                current_chat_payload_dict["draft_json"] = decrypted_draft_json
                current_chat_payload_dict["unread_count"] = unread_count
                current_chat_payload_dict["mates"] = mates
                
                fetch_messages = False
                if current_chat_payload_dict["type"] == "new_chat":
                    fetch_messages = True
                # Also fetch messages if we forced an update due to missing versions
                elif current_chat_payload_dict.get("type") == "updated_chat":
                    fetch_messages = True

                if fetch_messages:
                    messages_data = await directus_service.chat.get_all_messages_for_chat(chat_id=server_chat_id, decrypt_content=True)
                    processed_messages = []
                    if messages_data:
                        for msg in messages_data:
                            # Ensure every message has a status. 'delivered' is appropriate for persisted messages.
                            if 'status' not in msg:
                                msg['status'] = 'delivered'
                            processed_messages.append(msg)
                    current_chat_payload_dict["messages"] = processed_messages
                
                chat_sync_data_item = ChatSyncData(**current_chat_payload_dict)
                chats_to_add_or_update_data.append(chat_sync_data_item)

        # 4. Construct and Send Response
        response_payload_model = InitialSyncResponsePayloadSchema(
            chat_ids_to_delete=chat_ids_to_delete_on_client,
            chats_to_add_or_update=chats_to_add_or_update_data,
            server_chat_order=server_chat_order,
            server_timestamp=sync_start_timestamp
        )
        
        logger.info(f"User {user_id}: Sending initial_sync_response. Deletes: {len(response_payload_model.chat_ids_to_delete)}, Add/Updates: {len(response_payload_model.chats_to_add_or_update)}, Order: {len(response_payload_model.server_chat_order)}, New Server Timestamp: {response_payload_model.server_timestamp}.")
        await manager.send_personal_message(
            message={"type": "initial_sync_response", "payload": response_payload_model.model_dump(exclude_none=True)},
            user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash
        )

    except Exception as e:
        logger.error(f"Error during handle_initial_sync for user {user_id}, device {device_fingerprint_hash}: {e}", exc_info=True)
        try:
            await manager.send_personal_message(
                message={"type": "initial_sync_error", "payload": {"message": "Failed to perform initial synchronization."}},
                user_id=user_id,
                device_fingerprint_hash=device_fingerprint_hash
            )
        except Exception as send_err:
            logger.error(f"Failed to send error message for initial_sync to user {user_id}: {send_err}")
