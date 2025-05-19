import logging
import json
from typing import List, Dict, Any, Optional, Tuple

from app.schemas.chat import CachedChatVersions, CachedChatListItemData, ChatSyncData, InitialSyncResponsePayloadSchema, ClientChatComponentVersions # Added ClientChatComponentVersions
from app.services.cache import CacheService
from app.services.directus import DirectusService, chat_methods # Import chat_methods
from app.utils.encryption import EncryptionService
# Assuming manager is ConnectionManager instance from websockets.py
# from app.routes.websockets import manager as websocket_manager
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

async def handle_initial_sync(
    cache_service: CacheService,
    directus_service: DirectusService,
    encryption_service: EncryptionService,
    manager: Any, # Should be ConnectionManager type
    user_id: str,
    device_fingerprint_hash: str, # For sending response to specific device
    websocket: Any, # For sending response
    client_chat_versions: Dict[str, Dict[str, int]], # e.g. {"chat_id1": {"messages_v": 1, "draft_v": 2, "title_v": 1}}
    immediate_view_chat_id: Optional[str] = None # Optional: chat_id client is trying to view immediately
):
    logger.info(f"Handling initial_sync_request for user {user_id}, device {device_fingerprint_hash}. Client has {len(client_chat_versions)} chats.")

    chats_to_add_or_update_data: List[ChatSyncData] = [] # Changed to List[ChatSyncData]
    chat_ids_to_delete_on_client: List[str] = []
    
    # For prioritizing immediate_view_chat_id data
    priority_chat_data_dict: Optional[Dict[str, Any]] = None # Keep as dict for now, convert to ChatSyncData later

    try:
        # 1. Fetch Server's Master Chat List (sorted by last_edited_overall_timestamp desc)
        # Returns list of tuples: (chat_id_str, score_float)
        server_master_list_tuples: List[Tuple[str, float]] = await cache_service.get_chat_ids_versions(user_id, with_scores=True)
        server_master_chat_ids_set = {chat_id for chat_id, score in server_master_list_tuples}
        server_chat_order = [chat_id for chat_id, score in server_master_list_tuples] # Already sorted by recency

        logger.info(f"User {user_id}: Server master list has {len(server_master_chat_ids_set)} chats.")

        # 2. Determine Chats to Delete on Client
        for client_chat_id in client_chat_versions.keys():
            if client_chat_id not in server_master_chat_ids_set:
                chat_ids_to_delete_on_client.append(client_chat_id)
        
        if chat_ids_to_delete_on_client:
            logger.info(f"User {user_id}: Suggesting deletion of {len(chat_ids_to_delete_on_client)} chats on client: {chat_ids_to_delete_on_client}")

        # 3. Process Server's Chats for Deltas
        for server_chat_id, server_last_edited_ts_score in server_master_list_tuples:
            logger.info(f"User {user_id}: Processing chat_id {server_chat_id} from server master list for initial sync.")
            current_chat_payload_dict: Dict[str, Any] = {"chat_id": server_chat_id} # Start payload for this chat as a dict
            needs_update_on_client = False

            # Fetch server's versions for this chat
            logger.info(f"User {user_id}: Attempting to fetch versions for chat {server_chat_id} from cache.")
            server_versions: Optional[CachedChatVersions] = await cache_service.get_chat_versions(user_id, server_chat_id)
            
            if not server_versions:
                logger.error(f"User {user_id}: Cache inconsistency! Versions *NOT FOUND* in cache for chat {server_chat_id} which is in master list. Marking for client deletion and skipping this chat for sync.")
                # Log details about the master list entry for this chat
                logger.info(f"User {user_id}: Chat {server_chat_id} (versions not found) had score {server_last_edited_ts_score} in master list.")
                # If this chat was in the server's master list but its versions are gone,
                # it's a ghost. Tell the client to delete it.
                if server_chat_id not in chat_ids_to_delete_on_client:
                    chat_ids_to_delete_on_client.append(server_chat_id)
                continue
            
            logger.info(f"User {user_id}: Successfully fetched versions for chat {server_chat_id}: {server_versions.model_dump_json(exclude_none=True)}")

            # Fetch user-specific draft content and version *before* constructing client_versions
            draft_cache_result = await cache_service.get_user_draft_from_cache(user_id, server_chat_id)
            if draft_cache_result:
                user_draft_content_encrypted, user_draft_version_cache = draft_cache_result
            else:
                user_draft_content_encrypted = None
                user_draft_version_cache = 0 # Default to 0 if no draft exists
            decrypted_draft_json = None # Initialize before potential assignment

            # Construct the client-facing versions object
            client_versions = ClientChatComponentVersions(
                messages_v=server_versions.messages_v,
                title_v=server_versions.title_v,
                draft_v=user_draft_version_cache if user_draft_version_cache is not None else 0
            )
            current_chat_payload_dict["versions"] = client_versions
            current_chat_payload_dict["last_edited_overall_timestamp"] = int(server_last_edited_ts_score)

            client_versions_for_chat = client_chat_versions.get(server_chat_id)

            # Fetch list_item_data (title, draft, unread_count) - will be needed if new or any component changed
            # This data is encrypted in cache.
            cached_list_item_data: Optional[CachedChatListItemData] = await cache_service.get_chat_list_item_data(user_id, server_chat_id, refresh_ttl=True)
            
            decrypted_title = "" # Default title should be empty
            unread_count = 0 # Default unread count

            if not cached_list_item_data:
                logger.warning(f"User {user_id}: List item data not found in cache for chat {server_chat_id}. Attempting to reconstruct from Directus.")
                chat_metadata_from_db = await chat_methods.get_chat_metadata(directus_service, server_chat_id)
                if chat_metadata_from_db and chat_metadata_from_db.get("encrypted_title"):
                    try:
                        # Use the new decrypt_with_chat_key method
                        dec_title = await encryption_service.decrypt_with_chat_key(
                            ciphertext=chat_metadata_from_db["encrypted_title"],
                            key_id=server_chat_id
                        )
                        if dec_title: decrypted_title = dec_title
                    except Exception as e_dec:
                        logger.error(f"Failed to decrypt title from DB for chat {server_chat_id} using decrypt_with_chat_key: {e_dec}", exc_info=True)
                    
                    # Reconstruct and cache list item data (title is encrypted in cache)
                    # Unread count defaults to 0 as it's not in basic chat metadata.
                    # This part is crucial: we need the *encrypted* title for the cache.
                    # For simplicity, if we had to fetch from DB, we'll use the decrypted title for the current sync,
                    # but ideally, we'd re-encrypt it for the cache or ensure the cache is populated correctly elsewhere.
                    # For now, we'll proceed with the decrypted_title for the current_chat_payload,
                    # and acknowledge that the list_item_data in cache might still be missing or become stale.
                    # A better fix would be to ensure list_item_data is always populated when a chat is created/title changes.
                    # For this immediate fix, we'll use the fetched decrypted title.
                    # The unread_count will be the default 0.
                    
                    # Let's create a temporary CachedChatListItemData for processing if fetched from DB
                    # We will use the encrypted title from DB for caching.
                    reconstructed_list_item_data = CachedChatListItemData(
                        title=chat_metadata_from_db["encrypted_title"], # Store encrypted title in cache
                        unread_count=0 # Default unread count
                    )
                    await cache_service.set_chat_list_item_data(user_id, server_chat_id, reconstructed_list_item_data)
                    logger.info(f"User {user_id}: Reconstructed and cached list_item_data for chat {server_chat_id} from Directus metadata.")
                    # Use the freshly decrypted title for the current payload
                    # unread_count remains the default 0 from above
                else: # This block means: (list_item_data not in cache) AND ( (chat_metadata_from_db is None) OR (chat_metadata_from_db.get("encrypted_title") is None/empty) )
                    # We have server_versions (from line 59) and user_draft_version_cache (from lines 74-79).
                    
                    if server_versions and server_versions.messages_v > 0:
                        logger.warning(f"User {user_id}: Chat {server_chat_id} has messages (messages_v: {server_versions.messages_v}) but its list item data (title) is missing from cache and Directus. Syncing with an empty title.")
                        decrypted_title = "" # Default title
                        unread_count = 0     # Default unread count
                        # No list_item_data to cache here as it's based on missing DB title.
                        # The chat will be synced based on its messages_v and draft_v.
                    elif user_draft_version_cache > 0: # server_versions.messages_v is 0 or server_versions is None
                        logger.info(f"User {user_id}: Chat {server_chat_id} has no messages and no persistent list_item_data, but has a draft (version {user_draft_version_cache}). Syncing as draft-only chat.")
                        decrypted_title = "" # Default title for draft-only chats
                        unread_count = 0     # Default unread count
                    else: # No messages_v (or server_versions is None), no draft_v, and no reconstructible title/list_item_data
                        logger.error(f"User {user_id}: Cache inconsistency! Chat {server_chat_id} has no messages, no draft, and its list item data could not be found/reconstructed. Marking for client deletion and skipping.")
                        if server_chat_id not in chat_ids_to_delete_on_client:
                            chat_ids_to_delete_on_client.append(server_chat_id)
                        continue # Skip further processing for this chat
            else: # cached_list_item_data was found
                unread_count = cached_list_item_data.unread_count
                if cached_list_item_data.title:
                    try:
                        # Use the new decrypt_with_chat_key method
                        dec_title = await encryption_service.decrypt_with_chat_key(
                            ciphertext=cached_list_item_data.title,
                            key_id=server_chat_id
                        )
                        if dec_title: decrypted_title = dec_title
                    except Exception as e:
                        logger.error(f"Failed to decrypt title for chat {server_chat_id} using decrypt_with_chat_key during initial sync. Error: {e}", exc_info=True)

            # Decrypt draft_json (user_draft_content_encrypted was fetched earlier)
            if user_draft_content_encrypted and user_draft_content_encrypted != "null":
                raw_user_aes_key_for_draft = await encryption_service.get_user_draft_aes_key(user_id)
                if raw_user_aes_key_for_draft:
                    try:
                        dec_draft_str = encryption_service.decrypt_locally_with_aes(user_draft_content_encrypted, raw_user_aes_key_for_draft)
                        if dec_draft_str:
                            try:
                                decrypted_draft_json = json.loads(dec_draft_str)
                            except json.JSONDecodeError:
                                logger.error(f"Failed to parse decrypted draft JSON for user {user_id}, chat {server_chat_id} from user-specific cache after local AES decryption.")
                        else:
                            logger.warning(f"Local AES decryption of user-specific draft for user {user_id}, chat {server_chat_id} returned None/empty string.")
                    except Exception as e:
                        logger.error(f"Failed to decrypt user-specific draft for user {user_id}, chat {server_chat_id} using local AES. Error: {e}", exc_info=True)
                else:
                    logger.error(f"Failed to get user draft AES key for user {user_id} (chat {server_chat_id}) during initial sync for user-specific draft decryption.")
            
            current_chat_payload_dict["unread_count"] = unread_count # Use the determined unread_count

            if not client_versions_for_chat: # Scenario 1: Chat is New to Client
                needs_update_on_client = True
                current_chat_payload_dict["type"] = "new_chat"
                current_chat_payload_dict["title"] = decrypted_title
                current_chat_payload_dict["draft_json"] = decrypted_draft_json
                
                # If this new chat is the one the client wants to view immediately, fetch its messages.
                if server_chat_id == immediate_view_chat_id:
                    try:
                        messages_data = await chat_methods.get_all_messages_for_chat( # Renamed to messages_data
                            directus_service=directus_service,
                            encryption_service=encryption_service,
                            server_chat_id=server_chat_id,
                            decrypt_content=True # Assuming this returns list of MessageResponse compatible dicts or models
                        )
                        current_chat_payload_dict["messages"] = messages_data if messages_data else []
                        logger.info(f"User {user_id}: New chat {server_chat_id} is immediate_view. Fetched {len(current_chat_payload_dict['messages'])} decrypted messages.")
                    except Exception as e_msg:
                        logger.error(f"User {user_id}: Failed to fetch/decrypt messages for new immediate_view chat {server_chat_id}: {e_msg}", exc_info=True)
                        current_chat_payload_dict["messages"] = [] # Send empty list on error
                else:
                    # For other new chats, client will request messages if needed.
                    current_chat_payload_dict["messages"] = [] # Or omit messages key
                    logger.info(f"User {user_id}: Chat {server_chat_id} is new to client. Sending metadata and draft. Messages can be requested.")
                
                logger.info(f"User {user_id}: Chat {server_chat_id} is new to client. Payload prepared.")

            else: # Scenario 2: Chat Exists on Client - Compare Versions
                component_updates = {}
                # Compare title version
                if server_versions.title_v > client_versions_for_chat.get("title_v", -1):
                    component_updates["title"] = decrypted_title
                    needs_update_on_client = True
                
                # Compare user-specific draft version.
                # `user_draft_version_cache` is the specific draft version for this user and chat, fetched from `user:{user_id}:chat:{chat_id}:draft`
                # `client_versions_for_chat` should send "draft_v" as per frontend changes.
                client_user_draft_v = client_versions_for_chat.get("draft_v", -1) # Client sends its draft_v

                # server_user_draft_v_from_cache is user_draft_version_cache
                server_user_draft_v_from_cache = user_draft_version_cache if user_draft_version_cache is not None else 0

                if server_user_draft_v_from_cache > client_user_draft_v:
                    component_updates["draft_json"] = decrypted_draft_json
                    # The top-level current_chat_payload["draft_v"] is already set with server_user_draft_v_from_cache.
                    # The current_chat_payload["versions"] contains the raw versions from cache, which might have the user_id specific key.
                    needs_update_on_client = True
                    logger.info(f"User {user_id}, Chat {server_chat_id}: Draft update needed. Server draft_v: {server_user_draft_v_from_cache}, Client draft_v: {client_user_draft_v}")


                if server_versions.messages_v > client_versions_for_chat.get("messages_v", -1):
                    needs_update_on_client = True
                    # If this updated chat is the one the client wants to view immediately, fetch its messages.
                    if server_chat_id == immediate_view_chat_id:
                        try:
                            messages_data = await chat_methods.get_all_messages_for_chat( # Renamed to messages_data
                                directus_service=directus_service,
                                encryption_service=encryption_service,
                                server_chat_id=server_chat_id,
                                decrypt_content=True # Assuming this returns list of MessageResponse compatible dicts or models
                            )
                            component_updates["messages"] = messages_data if messages_data else []
                            logger.info(f"User {user_id}: Updated chat {server_chat_id} is immediate_view. Fetched {len(component_updates['messages'])} decrypted messages.")
                        except Exception as e_msg:
                            logger.error(f"User {user_id}: Failed to fetch/decrypt messages for updated immediate_view chat {server_chat_id}: {e_msg}", exc_info=True)
                            component_updates["messages"] = [] # Send empty list on error
                    else:
                        # For other updated chats, client will request messages if needed based on new messages_v.
                        # component_updates["messages_hint"] = "new_messages_available" # Or similar
                        pass # Just sending the new messages_v is enough to signal client
                
                if needs_update_on_client:
                    current_chat_payload_dict["type"] = "updated_chat"
                    current_chat_payload_dict.update(component_updates)
                    logger.info(f"User {user_id}: Chat {server_chat_id} has updates for client. Payload: {component_updates.keys()}")

            if needs_update_on_client:
                # Convert dict to ChatSyncData model instance before appending or setting as priority
                # Ensure all required fields for ChatSyncData are present in current_chat_payload_dict
                # For example, 'messages' might be None if not fetched, which is fine if Optional in ChatSyncData
                chat_sync_data_item = ChatSyncData(**current_chat_payload_dict)
                if server_chat_id == immediate_view_chat_id:
                    priority_chat_data_dict = current_chat_payload_dict # Keep as dict for now, or convert to model
                else:
                    chats_to_add_or_update_data.append(chat_sync_data_item)
        
        # If priority chat data was identified, convert it and add to the beginning of the list
        if priority_chat_data_dict:
            priority_chat_sync_data_item = ChatSyncData(**priority_chat_data_dict)
            chats_to_add_or_update_data.insert(0, priority_chat_sync_data_item)

        # 4. Construct and Send Response using Pydantic Model
        response_payload_model = InitialSyncResponsePayloadSchema(
            chat_ids_to_delete=chat_ids_to_delete_on_client,
            chats_to_add_or_update=chats_to_add_or_update_data,
            server_chat_order=server_chat_order,
            sync_completed_at=datetime.now(timezone.utc).isoformat()
        )
        
        logger.info(f"User {user_id}: Sending initial_sync_response. Deletes: {len(response_payload_model.chat_ids_to_delete)}, Add/Updates: {len(response_payload_model.chats_to_add_or_update)}, Order: {len(response_payload_model.server_chat_order)}.")
        await manager.send_personal_message( # Use the specific device hash
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