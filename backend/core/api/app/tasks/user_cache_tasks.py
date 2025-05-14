import logging
import asyncio
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from app.tasks.celery_config import app
from app.services.directus.directus import DirectusService
from app.services.directus import chat_methods
from app.services.cache import CacheService
from app.utils.encryption import EncryptionService
from app.routes.websockets import manager as websocket_manager # Access the global connection manager
from app.schemas.chat import CachedChatVersions, CachedChatListItemData

logger = logging.getLogger(__name__)

# Helper to parse chat_id from last_opened_path
def _parse_chat_id_from_path(path: Optional[str]) -> Optional[str]:
    if path and path.startswith('/chat/') and path != '/chat/new':
        parts = path.split('/')
        if len(parts) >= 3:
            return parts[2]
    return None

async def _warm_cache_phase_one(
    user_id: str,
    last_opened_path_from_user_model: Optional[str],
    cache_service: CacheService,
    directus_service: DirectusService,
    encryption_service: EncryptionService
) -> Optional[str]:
    """Handles Phase 1 of cache warming: Immediate Needs."""
    target_immediate_chat_id = _parse_chat_id_from_path(last_opened_path_from_user_model)
    logger.info(f"warm_user_cache Phase 1 for user {user_id}. Target immediate chat: {target_immediate_chat_id}")

    if not target_immediate_chat_id:
        logger.info(f"User {user_id}: No specific target_immediate_chat_id found from path '{last_opened_path_from_user_model}'. Skipping Phase 1 specific chat load.")
        return None

    try:
        # Fetch complete data for target_immediate_chat_id from Directus
        # This method now needs to fetch chat details AND the current user's draft for that chat.
        # It should return chat data and, separately, user_draft_content and user_draft_version.
        full_data = await chat_methods.get_full_chat_and_user_draft_details_for_cache_warming(
            directus_service, user_id, target_immediate_chat_id
        )

        if not full_data or not full_data.get("chat_details"):
            logger.warning(f"User {user_id}: Could not fetch details for target_immediate_chat_id {target_immediate_chat_id} from Directus.")
            return None
        
        chat_details = full_data["chat_details"] # Contains chat-specific info
        user_draft_content = full_data.get("user_encrypted_draft_content") # Encrypted with user key
        user_draft_version_db = full_data.get("user_draft_version_db", 0) # Version from Drafts table

        # Populate cache for target_immediate_chat_id
        # 1. list_item_data (no draft here anymore)
        list_item_data = CachedChatListItemData(
            title=chat_details["encrypted_title"], # Already encrypted (chat key)
            unread_count=chat_details["unread_count"]
        )
        await cache_service.set_chat_list_item_data(user_id, target_immediate_chat_id, list_item_data)

        # 2. versions (no general draft_v here anymore)
        versions_data = CachedChatVersions(
            messages_v=chat_details["messages_version"],
            title_v=chat_details["title_version"]
            # user_draft_v will be set dynamically below
        )
        logger.info(f"User {user_id}, Chat {target_immediate_chat_id} (Phase 1): Attempting to set versions: {versions_data.model_dump_json()}")
        set_versions_success_ph1 = await cache_service.set_chat_versions(user_id, target_immediate_chat_id, versions_data)
        logger.info(f"User {user_id}, Chat {target_immediate_chat_id} (Phase 1): set_chat_versions success: {set_versions_success_ph1}. Versions data: {versions_data.model_dump_json()}")
        # Set the specific user's draft version in the chat's versions hash
        logger.info(f"User {user_id}, Chat {target_immediate_chat_id} (Phase 1): Attempting to set user_draft_v:{user_id} to {user_draft_version_db}")
        await cache_service.set_chat_version_component( # Use the new HSET method
            user_id, target_immediate_chat_id, f"user_draft_v:{user_id}", user_draft_version_db
        )


        # 3. User-specific draft cache
        await cache_service.update_user_draft_in_cache(
            user_id, target_immediate_chat_id, user_draft_content, user_draft_version_db
        )

        # 4. messages
        if chat_details.get("messages"):
            # Assuming messages are already JSON strings of encrypted Message objects (chat key)
            await cache_service.set_chat_messages_history(user_id, target_immediate_chat_id, chat_details["messages"])
        
        # 5. chat_ids_versions (Sorted Set) - Determine effective timestamp for sorting
        # Timestamps from Directus are now integers.
        # Use chat's 'updated_at' as its own last modification time.
        chat_own_update_ts = chat_details.get("updated_at", 0)
        if not isinstance(chat_own_update_ts, int): # Basic type check
            logger.warning(f"Chat {target_immediate_chat_id} updated_at is not an int: {chat_own_update_ts}. Defaulting to 0.")
            chat_own_update_ts = 0

        user_draft = await chat_methods.get_user_draft_from_directus(
            directus_service, user_id, target_immediate_chat_id
        )
        draft_updated_at_ts = 0
        if user_draft:
            # Use 'updated_at' from draft as it now reflects the last edit time.
            draft_updated_at_ts = user_draft.get("updated_at", 0)
            if not isinstance(draft_updated_at_ts, int): # Basic type check
                logger.warning(f"Draft for chat {target_immediate_chat_id} updated_at is not an int: {draft_updated_at_ts}. Defaulting to 0.")
                draft_updated_at_ts = 0
        
        effective_timestamp = max(chat_own_update_ts, draft_updated_at_ts)

        if effective_timestamp == 0:
            # Fallback to chat's creation timestamp
            created_at_ts = chat_details.get("created_at", 0)
            if not isinstance(created_at_ts, int): # Basic type check
                 logger.warning(f"Chat {target_immediate_chat_id} created_at is not an int: {created_at_ts}. Defaulting to 0.")
                 created_at_ts = 0
            effective_timestamp = created_at_ts
            if effective_timestamp == 0:
                logger.warning(
                    f"Chat {target_immediate_chat_id} for user {user_id} (Phase 1) has no valid timestamps "
                    f"(chat.updated_at, draft.updated_at, chat.created_at), using 0 for score."
                )
        
        timestamp_for_score = effective_timestamp
        await cache_service.add_chat_to_ids_versions(user_id, target_immediate_chat_id, timestamp_for_score)
        
        # Ensure the 'last_edited_overall_timestamp' in chat_details (which might populate metadata cache)
        # reflects this user-specific effective_timestamp for consistency if that field is used by clients.
        chat_details["last_edited_overall_timestamp"] = effective_timestamp

        logger.info(f"User {user_id}: Phase 1 cache warming complete for chat {target_immediate_chat_id}. Score: {timestamp_for_score}")
        
        # Send WebSocket notification if user is connected
        if websocket_manager.is_user_active(user_id):
            await websocket_manager.broadcast_to_user_specific_event(
                user_id=user_id,
                event_name="priority_chat_ready",
                payload={"chat_id": target_immediate_chat_id}
            )
            logger.info(f"User {user_id}: Sent 'priority_chat_ready' event for chat {target_immediate_chat_id}.")
        return target_immediate_chat_id

    except Exception as e:
        logger.error(f"Error in _warm_cache_phase_one for user {user_id}, chat {target_immediate_chat_id}: {e}", exc_info=True)
        return None


async def _warm_cache_phase_two(
    user_id: str,
    cache_service: CacheService,
    directus_service: DirectusService,
    encryption_service: EncryptionService, # May not be needed if data from Directus is already encrypted
    target_immediate_chat_id: Optional[str] # To avoid re-fetching messages for this chat
):
    """Handles Phase 2 of cache warming: Core Chat List & Top N LLM Cache."""
    logger.info(f"warm_user_cache Phase 2 for user {user_id}.")
    
    try:
        # 1. Fetch Core Data for 1000 Chats from Directus
        # Method now needs to return chat data AND the current user's draft for each chat.
        # Expected structure: List[{"chat_details": {...}, "user_encrypted_draft_content": "...", "user_draft_version_db": ...}]
        core_chats_with_user_drafts: List[Dict[str, Any]] = await chat_methods.get_core_chats_and_user_drafts_for_cache_warming(
            directus_service, user_id, limit=1000
        )

        if not core_chats_with_user_drafts:
            logger.info(f"User {user_id}: No core chats found in Directus for Phase 2 warming.")
        else:
            logger.info(f"User {user_id}: Fetched {len(core_chats_with_user_drafts)} core chats with user drafts for Phase 2 warming.")

        # 2. Populate Granular Cache Keys for All Fetched Chats
        for item in core_chats_with_user_drafts:
            chat_data = item["chat_details"]
            user_draft_content = item.get("user_encrypted_draft_content") # Encrypted with user key
            user_draft_version_db = item.get("user_draft_version_db", 0)
            chat_id = chat_data["id"]
            
            # a. Add/update in user:{user_id}:chat_ids_versions - Determine effective timestamp
            # Timestamps from Directus are now integers.
            # Use chat's 'updated_at' as its own last modification time.
            chat_own_update_ts_ph2 = chat_data.get("updated_at", 0)
            if not isinstance(chat_own_update_ts_ph2, int):
                logger.warning(f"Chat {chat_id} updated_at is not an int: {chat_own_update_ts_ph2}. Defaulting to 0.")
                chat_own_update_ts_ph2 = 0

            # Fetch user's draft for this specific chat_id to get its updated_at
            # This is done for each chat in the loop. Consider if get_core_chats_and_user_drafts_for_cache_warming
            # can already provide the user_draft's updated_at to avoid N+1 queries here.
            # For now, assuming it's fetched individually.
            user_draft_ph2 = await chat_methods.get_user_draft_from_directus(
                directus_service, user_id, chat_id
            )
            draft_updated_at_ts_ph2 = 0
            if user_draft_ph2:
                draft_updated_at_ts_ph2 = user_draft_ph2.get("updated_at", 0)
                if not isinstance(draft_updated_at_ts_ph2, int):
                    logger.warning(f"Draft for chat {chat_id} updated_at is not an int: {draft_updated_at_ts_ph2}. Defaulting to 0.")
                    draft_updated_at_ts_ph2 = 0
            
            effective_timestamp_ph2 = max(chat_own_update_ts_ph2, draft_updated_at_ts_ph2)

            if effective_timestamp_ph2 == 0:
                # Fallback to chat's creation timestamp
                created_at_ts_ph2 = chat_data.get("created_at", 0)
                if not isinstance(created_at_ts_ph2, int):
                    logger.warning(f"Chat {chat_id} created_at is not an int: {created_at_ts_ph2}. Defaulting to 0.")
                    created_at_ts_ph2 = 0
                effective_timestamp_ph2 = created_at_ts_ph2
                if effective_timestamp_ph2 == 0:
                    logger.warning(
                        f"Chat {chat_id} for user {user_id} (Phase 2) has no valid timestamps "
                        f"(chat.updated_at, draft.updated_at, chat.created_at), using 0 for score."
                    )
            
            ts_score = effective_timestamp_ph2
            await cache_service.add_chat_to_ids_versions(user_id, chat_id, ts_score)
            
            # Ensure the 'last_edited_overall_timestamp' in chat_data (which might populate metadata cache)
            # reflects this user-specific effective_timestamp.
            chat_data["last_edited_overall_timestamp"] = effective_timestamp_ph2

            logger.debug(f"User {user_id}, Chat {chat_id} (Phase 2): Added to ids_versions with score {ts_score}.")

            # b. Store in user:{user_id}:chat:{chat_id}:versions
            versions = CachedChatVersions( # No general draft_v
                messages_v=chat_data["messages_version"],
                title_v=chat_data["title_version"]
            )
            logger.info(f"User {user_id}, Chat {chat_id} (Phase 2): Attempting to set versions: {versions.model_dump_json()}")
            set_versions_success_ph2 = await cache_service.set_chat_versions(user_id, chat_id, versions)
            logger.info(f"User {user_id}, Chat {chat_id} (Phase 2): set_chat_versions success: {set_versions_success_ph2}. Versions data: {versions.model_dump_json()}")
            # Set the specific user's draft version in the chat's versions hash
            logger.info(f"User {user_id}, Chat {chat_id} (Phase 2): Attempting to set user_draft_v:{user_id} to {user_draft_version_db}")
            await cache_service.set_chat_version_component( # Use the new HSET method
                user_id, chat_id, f"user_draft_v:{user_id}", user_draft_version_db
            )

            # c. Store in user:{user_id}:chat:{chat_id}:list_item_data (no draft here)
            list_item = CachedChatListItemData(
                title=chat_data["encrypted_title"], # Already encrypted (chat key)
                unread_count=chat_data["unread_count"]
            )
            await cache_service.set_chat_list_item_data(user_id, chat_id, list_item)

            # d. Store user-specific draft in user:{user_id}:chat:{chat_id}:draft
            await cache_service.update_user_draft_in_cache(
                user_id, chat_id, user_draft_content, user_draft_version_db
            )
        
        logger.info(f"User {user_id}: Populated :versions, :list_item_data, and user-specific :draft for {len(core_chats_with_user_drafts)} chats.")

        # Server Notification (Phase 2 Complete - General Sync Readiness)
        if websocket_manager.is_user_active(user_id):
            await websocket_manager.broadcast_to_user_specific_event(
                user_id=user_id,
                event_name="cache_primed",
                payload={"status": "full_sync_ready"}
            )
            logger.info(f"User {user_id}: Sent 'cache_primed' (full_sync_ready) event.")

        # 3. Load Messages for Top N (e.g., 3) Most Recently Edited Chats
        # Get top N chat IDs from the sorted set (which should now be populated)
        top_n_chat_ids_with_scores = await cache_service.get_chat_ids_versions(user_id, start=0, end=cache_service.TOP_N_MESSAGES_COUNT - 1, with_scores=False)
        
        logger.info(f"User {user_id}: Identified Top N chat IDs for message caching: {top_n_chat_ids_with_scores}")

        for chat_id_for_messages in top_n_chat_ids_with_scores:
            if chat_id_for_messages == target_immediate_chat_id:
                logger.debug(f"User {user_id}: Messages for chat {chat_id_for_messages} already cached in Phase 1. Skipping.")
                continue
            
            # Check if messages are already cached (e.g., if Top N overlaps with another process)
            # This check might be redundant if we always fetch, but good for optimization.
            # For simplicity here, we'll fetch. A more robust check would be `await cache_service.get_chat_messages_history(...)`
            
            logger.debug(f"User {user_id}: Fetching messages for Top N chat {chat_id_for_messages}.")
            # This method needs to fetch all messages for a given chat_id
            messages: Optional[List[str]] = await chat_methods.get_all_messages_for_chat(
                directus_service=directus_service,
                encryption_service=encryption_service, # Pass encryption service
                chat_id=chat_id_for_messages,
                decrypt_content=False # Explicitly keep content encrypted for cache
            )
            if messages:
                await cache_service.set_chat_messages_history(user_id, chat_id_for_messages, messages)
                logger.info(f"User {user_id}: Cached messages for Top N chat {chat_id_for_messages}.")
            else:
                logger.info(f"User {user_id}: No messages found or error fetching for Top N chat {chat_id_for_messages}.")
        
        logger.info(f"User {user_id}: Phase 2 cache warming complete.")

    except Exception as e:
        logger.error(f"Error in _warm_cache_phase_two for user {user_id}: {e}", exc_info=True)


async def _async_warm_user_cache(user_id: str, last_opened_path_from_user_model: Optional[str], task_id: Optional[str] = "UNKNOWN_TASK_ID"):
    """
    Asynchronously warms the user's cache upon login. (Actual async logic)
    """
    logger.info(f"TASK_LOGIC_ENTRY: Starting _async_warm_user_cache for user_id: {user_id}, last_opened_path: {last_opened_path_from_user_model}, task_id: {task_id}")

    cache_service = CacheService()
    directus_service = DirectusService()
    await directus_service.ensure_auth_token()
    encryption_service = EncryptionService()

    # Phase 1
    target_immediate_chat_id = await _warm_cache_phase_one(
        user_id, last_opened_path_from_user_model, cache_service, directus_service, encryption_service
    )

    # Phase 2
    await _warm_cache_phase_two(
        user_id, cache_service, directus_service, encryption_service, target_immediate_chat_id
    )

    logger.info(f"TASK_LOGIC_FINISH: _async_warm_user_cache task finished for user_id: {user_id}, task_id: {task_id}")


@app.task(name="app.tasks.user_cache_tasks.warm_user_cache", bind=True)
def warm_user_cache(self, user_id: str, last_opened_path_from_user_model: Optional[str]):
    """
    Synchronous Celery task wrapper to warm the user's cache.
    Manages an asyncio event loop to run the async logic.
    """
    task_id = self.request.id if self and hasattr(self, 'request') else 'UNKNOWN_TASK_ID'
    logger.info(f"TASK_ENTRY_SYNC_WRAPPER: Starting warm_user_cache task for user_id: {user_id}, last_opened_path: {last_opened_path_from_user_model}, task_id: {task_id}")
    
    loop = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        loop.run_until_complete(_async_warm_user_cache(
            user_id=user_id,
            last_opened_path_from_user_model=last_opened_path_from_user_model,
            task_id=task_id
        ))
        logger.info(f"TASK_SUCCESS_SYNC_WRAPPER: warm_user_cache task completed for user_id: {user_id}, task_id: {task_id}")
        return True # Indicate success
    except Exception as e:
        logger.error(f"TASK_FAILURE_SYNC_WRAPPER: Failed to run warm_user_cache task for user_id {user_id}, task_id: {task_id}: {str(e)}", exc_info=True)
        return False # Indicate failure
    finally:
        if loop:
            loop.close()
        logger.info(f"TASK_FINALLY_SYNC_WRAPPER: Event loop closed for warm_user_cache task_id: {task_id}")

# Placeholder for chat_methods that need to be implemented/verified:
# - chat_methods.get_full_chat_details_for_cache_warming(directus_service, chat_id) -> Dict
#   (should return id, encrypted_title, encrypted_draft, draft_version_db, title_version, messages_version, unread_count, last_edited_overall_timestamp, messages: List[str_encrypted_message_json])
# - chat_methods.get_core_chats_for_cache_warming(directus_service, user_id, limit) -> List[Dict]
#   (ordered by last_edited_overall_timestamp or updated_at desc, returning fields for list_item_data and versions)
# - chat_methods.get_all_messages_for_chat(directus_service, chat_id) -> List[str_encrypted_message_json]