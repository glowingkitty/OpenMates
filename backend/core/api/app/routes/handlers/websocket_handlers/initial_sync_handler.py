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
    client_chat_ids: List[str],  # REQUIRED: explicit list of chat IDs client has
    client_chat_count: int,  # REQUIRED: number of chats client has
    last_sync_timestamp: Optional[int] = None,
    immediate_view_chat_id: Optional[str] = None,
    pending_message_ids: Optional[Dict[str, List[str]]] = None
):
    logger.info(f"Handling initial_sync_request for user {user_id}, device {device_fingerprint_hash}. Client has {client_chat_count} chats. Last sync timestamp: {last_sync_timestamp}")

    chats_to_add_or_update_data: List[ChatSyncData] = []
    chat_ids_to_delete_on_client: List[str] = []
    
    try:
        # Validate required fields
        if client_chat_ids is None:
            error_msg = f"User {user_id}: Missing required field 'chat_ids' in sync request. Client must send explicit list of chat IDs."
            logger.error(error_msg)
            await manager.send_personal_message(
                message={"type": "initial_sync_error", "payload": {"message": "Missing required field: chat_ids"}},
                user_id=user_id,
                device_fingerprint_hash=device_fingerprint_hash
            )
            return
        
        if client_chat_count is None:
            error_msg = f"User {user_id}: Missing required field 'chat_count' in sync request."
            logger.error(error_msg)
            await manager.send_personal_message(
                message={"type": "initial_sync_error", "payload": {"message": "Missing required field: chat_count"}},
                user_id=user_id,
                device_fingerprint_hash=device_fingerprint_hash
            )
            return
        
        # Validate chat_count matches chat_ids length
        if len(client_chat_ids) != client_chat_count:
            error_msg = f"User {user_id}: chat_count ({client_chat_count}) doesn't match chat_ids length ({len(client_chat_ids)})"
            logger.warning(error_msg)
            # Don't fail, just log warning - use actual length
            client_chat_count = len(client_chat_ids)
        
        # The timestamp at the beginning of the sync process.
        sync_start_timestamp = int(datetime.now(timezone.utc).timestamp())

        # 1. Fetch Server's Master Chat List from Cache
        server_master_list_tuples: List[Tuple[str, float]] = await cache_service.get_chat_ids_versions(user_id, with_scores=True)
        server_master_chat_ids_set = {chat_id for chat_id, score in server_master_list_tuples}
        server_chat_order = [chat_id for chat_id, score in server_master_list_tuples]
        logger.info(f"User {user_id}: Server master list from cache has {len(server_master_chat_ids_set)} chats.")

        # 2. Determine Chats to Delete on Client
        # Use explicit client_chat_ids list (REQUIRED - no fallback)
        client_chat_ids_set = set(client_chat_ids)
        logger.debug(f"User {user_id}: Client has {len(client_chat_ids_set)} chats explicitly listed")
        
        # Calculate missing chats (server has but client doesn't)
        chats_missing_on_client = list(server_master_chat_ids_set - client_chat_ids_set)
        
        # Calculate extra chats (client has but server doesn't)
        chats_to_delete = list(client_chat_ids_set - server_master_chat_ids_set)
        
        if chats_to_delete:
            chat_ids_to_delete_on_client.extend(chats_to_delete)
            logger.info(f"User {user_id}: Suggesting deletion of {len(chat_ids_to_delete_on_client)} chats on client: {chat_ids_to_delete_on_client}")
        
        if chats_missing_on_client:
            logger.info(f"User {user_id}: Client is missing {len(chats_missing_on_client)} chats. Will send them.")

        # 3. Process Server's Chats for Deltas
        for server_chat_id, server_last_edited_ts_score in server_master_list_tuples:
            # Skip timestamp-based filtering if client is missing this chat entirely
            is_missing_on_client = server_chat_id in chats_missing_on_client
            
            # Timestamp-based filtering (but not for missing chats)
            if not is_missing_on_client and last_sync_timestamp and server_last_edited_ts_score <= last_sync_timestamp:
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
                
                # CRITICAL FIX: Fetch real versions from DB instead of using sentinel values (9999)
                # Using 9999 causes the client to preserve those fake versions instead of accepting server updates
                db_list_item_data_for_versions = await directus_service.chat.get_chat_list_item_data_from_db(server_chat_id)
                if db_list_item_data_for_versions:
                    # Use actual versions from DB
                    cached_server_versions = CachedChatVersions(
                        messages_v=db_list_item_data_for_versions.get('messages_v', 1),
                        title_v=db_list_item_data_for_versions.get('title_v', 1)
                    )
                    logger.info(f"User {user_id}: Fetched real versions from DB for chat {server_chat_id}: messages_v={cached_server_versions.messages_v}, title_v={cached_server_versions.title_v}")
                else:
                    # Chat not found in DB either - this is a serious problem
                    logger.error(f"User {user_id}: Chat {server_chat_id} not found in DB. Skipping this chat.")
                    continue
            
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

            # Check if client is missing this chat entirely (reliable detection)
            if is_missing_on_client or not client_versions_for_chat:
                needs_update_on_client = True
                current_chat_payload_dict["type"] = "new_chat"
                logger.debug(f"User {user_id}: Chat {server_chat_id} is new to client (missing: {is_missing_on_client}, no versions: {not client_versions_for_chat})")
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
                encrypted_title = ""  # Will hold encrypted title from cache or default
                unread_count = 0
                db_list_item_data = None  # Initialize to avoid UnboundLocalError
                
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
                            created_at=db_list_item_data.get("created_at", 0),
                            updated_at=db_list_item_data.get("updated_at", 0),
                            encrypted_chat_key=db_list_item_data.get("encrypted_chat_key")  # Include encrypted_chat_key from DB
                        )
                    else:
                        logger.error(f"DB fallback failed for chat {server_chat_id}. Cannot get list item data.")
                        cached_list_item_data = None
                        # If DB fallback fails, we cannot proceed with this chat.
                        continue

                if cached_list_item_data:
                    if cached_list_item_data.title:
                        # Send encrypted title directly - frontend will decrypt with master key
                        encrypted_title = cached_list_item_data.title
                    unread_count = cached_list_item_data.unread_count
                    current_chat_payload_dict["created_at"] = cached_list_item_data.created_at
                    current_chat_payload_dict["updated_at"] = cached_list_item_data.updated_at
                    if cached_server_versions:
                        current_chat_payload_dict["versions"].title_v = cached_server_versions.title_v


                # Send encrypted draft content directly (no need to decrypt since client handles encryption)
                encrypted_draft_md = None
                if user_draft_content_encrypted and user_draft_content_encrypted != "null":
                    encrypted_draft_md = user_draft_content_encrypted

                current_chat_payload_dict["encrypted_title"] = encrypted_title  # This is encrypted content from cache
                current_chat_payload_dict["encrypted_draft_md"] = encrypted_draft_md
                current_chat_payload_dict["unread_count"] = unread_count
                
                # CRITICAL: Add encrypted_chat_key for client-side decryption
                # Try to get it from cached_list_item_data first, then db_list_item_data fallback, then DB fetch
                encrypted_chat_key = None
                if cached_list_item_data:
                    # Pydantic model - access as attribute
                    encrypted_chat_key = cached_list_item_data.encrypted_chat_key
                if not encrypted_chat_key and db_list_item_data:
                    # Dict - access with get()
                    encrypted_chat_key = db_list_item_data.get("encrypted_chat_key")
                
                # If still no key, fetch from DB (cache might be stale/missing this field)
                if not encrypted_chat_key:
                    logger.warning(f"User {user_id}: encrypted_chat_key missing from cache for chat {server_chat_id}, fetching from DB...")
                    if not db_list_item_data:
                        db_list_item_data = await directus_service.chat.get_chat_list_item_data_from_db(server_chat_id)
                    if db_list_item_data:
                        encrypted_chat_key = db_list_item_data.get("encrypted_chat_key")
                
                if encrypted_chat_key:
                    current_chat_payload_dict["encrypted_chat_key"] = encrypted_chat_key
                    logger.debug(f"User {user_id}: Added encrypted_chat_key for chat {server_chat_id}")
                else:
                    logger.error(f"User {user_id}: CRITICAL - No encrypted_chat_key found for chat {server_chat_id} even after DB fetch - client won't be able to decrypt!")
                
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
                            # Parse JSON string back to dictionary if needed
                            if isinstance(msg, str):
                                try:
                                    msg = json.loads(msg)
                                except json.JSONDecodeError as e:
                                    logger.error(f"Failed to parse message JSON for chat {server_chat_id}: {e}")
                                    continue
                            
                            # Map encrypted message fields to EncryptedMessageResponse schema
                            encrypted_msg = {
                                'id': msg.get('id', ''),
                                'chat_id': server_chat_id,
                                'encrypted_content': msg.get('encrypted_content', ''),
                                'role': msg.get('role', 'user'),
                                'encrypted_category': msg.get('encrypted_category'),
                                'encrypted_sender_name': msg.get('encrypted_sender_name'),
                                'status': msg.get('status', 'delivered'),
                                'created_at': msg.get('created_at', int(datetime.now(timezone.utc).timestamp()))
                            }
                            processed_messages.append(encrypted_msg)
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
