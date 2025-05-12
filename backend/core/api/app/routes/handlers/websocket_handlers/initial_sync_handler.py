import logging
import time
import json
import hashlib
from typing import List, Dict, Any, Optional, Tuple

from app.schemas.chat import ChatListItem, CachedChatVersions, CachedChatListItemData
from app.services.cache import CacheService
from app.services.directus import DirectusService, chat_methods # Import chat_methods
from app.utils.encryption import EncryptionService
# Assuming manager is ConnectionManager instance from websockets.py
# from app.routes.websockets import manager as websocket_manager
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Helper function to convert timestamp/datetime string/number to datetime object (can be kept)
def _to_datetime(value: Any) -> Optional[datetime]:
    if value is None: return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    if isinstance(value, (int, float)):
        try: return datetime.fromtimestamp(value, tz=timezone.utc)
        except (ValueError, TypeError, OSError): pass
    if isinstance(value, str):
        try:
            dt_str = value.replace('Z', '+00:00')
            dt = datetime.fromisoformat(dt_str)
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
        except ValueError: pass
    logger.warning(f"Could not convert value to datetime: {value} (type: {type(value)})")
    return None

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

    chats_to_add_or_update: List[Dict[str, Any]] = []
    chat_ids_to_delete_on_client: List[str] = []
    
    # For prioritizing immediate_view_chat_id data
    priority_chat_data: Optional[Dict[str, Any]] = None

    try:
        # 1. Fetch Server's Master Chat List (sorted by last_edited_overall_timestamp desc)
        # Returns list of tuples: (chat_id_str, score_float)
        server_master_list_tuples: List[Tuple[str, float]] = await cache_service.get_chat_ids_versions(user_id, with_scores=True)
        server_master_chat_ids_set = {chat_id for chat_id, score in server_master_list_tuples}
        server_chat_order = [chat_id for chat_id, score in server_master_list_tuples] # Already sorted by recency

        logger.debug(f"User {user_id}: Server master list has {len(server_master_chat_ids_set)} chats.")

        # 2. Determine Chats to Delete on Client
        for client_chat_id in client_chat_versions.keys():
            if client_chat_id not in server_master_chat_ids_set:
                chat_ids_to_delete_on_client.append(client_chat_id)
        
        if chat_ids_to_delete_on_client:
            logger.info(f"User {user_id}: Suggesting deletion of {len(chat_ids_to_delete_on_client)} chats on client: {chat_ids_to_delete_on_client}")

        # 3. Process Server's Chats for Deltas
        for server_chat_id, server_last_edited_ts_score in server_master_list_tuples:
            current_chat_payload = {"chat_id": server_chat_id} # Start payload for this chat
            needs_update_on_client = False

            # Fetch server's versions for this chat
            server_versions: Optional[CachedChatVersions] = await cache_service.get_chat_versions(user_id, server_chat_id)
            if not server_versions:
                logger.error(f"User {user_id}: Cache inconsistency! Versions not found for chat {server_chat_id} which is in master list. Skipping.")
                continue
            
            current_chat_payload["versions"] = server_versions.model_dump()
            current_chat_payload["last_edited_overall_timestamp"] = int(server_last_edited_ts_score)


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
                    raw_chat_aes_key_for_title = await encryption_service.get_chat_aes_key(server_chat_id)
                    if raw_chat_aes_key_for_title:
                        try:
                            dec_title = encryption_service.decrypt_locally_with_aes(chat_metadata_from_db["encrypted_title"], raw_chat_aes_key_for_title)
                            if dec_title: decrypted_title = dec_title
                        except Exception as e_dec:
                            logger.error(f"Failed to decrypt title from DB for chat {server_chat_id}: {e_dec}")
                    else:
                        logger.error(f"Failed to get chat AES key for title decryption (DB fallback) for chat {server_chat_id}")
                    
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
                else:
                    logger.error(f"User {user_id}: Cache inconsistency! List item data not found for chat {server_chat_id} and could not reconstruct from Directus. Skipping.")
                    continue
            else: # cached_list_item_data was found
                unread_count = cached_list_item_data.unread_count
                if cached_list_item_data.title:
                    raw_chat_aes_key = await encryption_service.get_chat_aes_key(server_chat_id)
                    if raw_chat_aes_key:
                        try:
                            dec_title = encryption_service.decrypt_locally_with_aes(cached_list_item_data.title, raw_chat_aes_key)
                            if dec_title: decrypted_title = dec_title
                        except Exception as e:
                            logger.error(f"Failed to decrypt title for chat {server_chat_id} using local AES during initial sync. Error: {e}", exc_info=True)
                    else:
                        logger.error(f"Failed to get chat AES key for chat {server_chat_id} during initial sync for title decryption.")

            # Decrypt draft_json using the user's specific AES key (fetched from its dedicated cache key)
            user_draft_content_encrypted, user_draft_version_cache = await cache_service.get_user_draft_from_cache(user_id, server_chat_id)
            decrypted_draft_json = None
            if user_draft_content_encrypted and user_draft_content_encrypted != "null":
                raw_user_aes_key_for_draft = await encryption_service.get_user_draft_aes_key(user_id) # Use a different variable name
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
            
            current_chat_payload["unread_count"] = unread_count # Use the determined unread_count

            if not client_versions_for_chat: # Scenario 1: Chat is New to Client
                needs_update_on_client = True
                current_chat_payload["type"] = "new_chat"
                current_chat_payload["title"] = decrypted_title
                current_chat_payload["draft_json"] = decrypted_draft_json
                
                # If this new chat is the one the client wants to view immediately, fetch its messages.
                if server_chat_id == immediate_view_chat_id:
                    try:
                        messages = await chat_methods.get_all_messages_for_chat(
                            directus_service=directus_service,
                            encryption_service=encryption_service,
                            server_chat_id=server_chat_id,
                            decrypt_content=True
                        )
                        current_chat_payload["messages"] = messages if messages else []
                        logger.debug(f"User {user_id}: New chat {server_chat_id} is immediate_view. Fetched {len(current_chat_payload['messages'])} decrypted messages.")
                    except Exception as e_msg:
                        logger.error(f"User {user_id}: Failed to fetch/decrypt messages for new immediate_view chat {server_chat_id}: {e_msg}", exc_info=True)
                        current_chat_payload["messages"] = [] # Send empty list on error
                else:
                    # For other new chats, client will request messages if needed.
                    current_chat_payload["messages"] = [] # Or omit messages key
                    logger.debug(f"User {user_id}: Chat {server_chat_id} is new to client. Sending metadata and draft. Messages can be requested.")
                
                logger.debug(f"User {user_id}: Chat {server_chat_id} is new to client. Payload prepared.")

            else: # Scenario 2: Chat Exists on Client - Compare Versions
                component_updates = {}
                if server_versions.title_v > client_versions_for_chat.get("title_v", -1):
                    component_updates["title"] = decrypted_title
                    needs_update_on_client = True
                
                if server_versions.draft_v > client_versions_for_chat.get("draft_v", -1):
                    component_updates["draft_json"] = decrypted_draft_json
                    needs_update_on_client = True

                if server_versions.messages_v > client_versions_for_chat.get("messages_v", -1):
                    needs_update_on_client = True
                    # If this updated chat is the one the client wants to view immediately, fetch its messages.
                    if server_chat_id == immediate_view_chat_id:
                        try:
                            messages = await chat_methods.get_all_messages_for_chat(
                                directus_service=directus_service,
                                encryption_service=encryption_service,
                                server_chat_id=server_chat_id,
                                decrypt_content=True
                            )
                            component_updates["messages"] = messages if messages else []
                            logger.debug(f"User {user_id}: Updated chat {server_chat_id} is immediate_view. Fetched {len(component_updates['messages'])} decrypted messages.")
                        except Exception as e_msg:
                            logger.error(f"User {user_id}: Failed to fetch/decrypt messages for updated immediate_view chat {server_chat_id}: {e_msg}", exc_info=True)
                            component_updates["messages"] = [] # Send empty list on error
                    else:
                        # For other updated chats, client will request messages if needed based on new messages_v.
                        # component_updates["messages_hint"] = "new_messages_available" # Or similar
                        pass # Just sending the new messages_v is enough to signal client
                
                if needs_update_on_client:
                    current_chat_payload["type"] = "updated_chat"
                    current_chat_payload.update(component_updates)
                    logger.debug(f"User {user_id}: Chat {server_chat_id} has updates for client. Payload: {component_updates.keys()}")

            if needs_update_on_client:
                if server_chat_id == immediate_view_chat_id:
                    priority_chat_data = current_chat_payload
                else:
                    chats_to_add_or_update.append(current_chat_payload)
        
        # If priority chat data was identified, add it to the beginning of the list
        if priority_chat_data:
            chats_to_add_or_update.insert(0, priority_chat_data)

        # 4. Construct and Send Response
        response_payload = {
            "chat_ids_to_delete": chat_ids_to_delete_on_client,
            "chats_to_add_or_update": chats_to_add_or_update,
            "server_chat_order": server_chat_order, # Full ordered list of chat_ids from server
            "sync_completed_at": datetime.now(timezone.utc).isoformat()
        }
        
        logger.info(f"User {user_id}: Sending initial_sync_response. Deletes: {len(chat_ids_to_delete_on_client)}, Add/Updates: {len(chats_to_add_or_update)}, Order: {len(server_chat_order)}.")
        await manager.send_personal_message( # Use the specific device hash
            message={"type": "initial_sync_response", "payload": response_payload},
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