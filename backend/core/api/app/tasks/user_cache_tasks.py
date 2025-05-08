import logging
import asyncio
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from app.tasks.celery_config import celery_app
from app.services.directus.directus import get_directus_service, DirectusService
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
        # This needs a comprehensive method in chat_methods or direct calls
        chat_details = await chat_methods.get_full_chat_details_for_cache_warming(directus_service, target_immediate_chat_id)

        if not chat_details:
            logger.warning(f"User {user_id}: Could not fetch details for target_immediate_chat_id {target_immediate_chat_id} from Directus.")
            return None

        # chat_details should contain:
        # id (chat_id), encrypted_title, encrypted_draft (draft_content), draft_version_db,
        # title_version, messages_version, unread_count, last_edited_overall_timestamp,
        # messages (list of encrypted message objects)

        # Populate cache for target_immediate_chat_id
        # 1. list_item_data
        list_item_data = CachedChatListItemData(
            title=chat_details["encrypted_title"], # Already encrypted
            unread_count=chat_details["unread_count"],
            draft_json=chat_details["encrypted_draft"] # Already encrypted, from Chats.draft_content
        )
        await cache_service.set_chat_list_item_data(user_id, target_immediate_chat_id, list_item_data)

        # 2. versions
        versions_data = CachedChatVersions(
            messages_v=chat_details["messages_version"],
            draft_v=chat_details["draft_version_db"], # Initial draft_v from DB
            title_v=chat_details["title_version"]
        )
        await cache_service.set_chat_versions(user_id, target_immediate_chat_id, versions_data)

        # 3. messages
        if chat_details.get("messages"):
            # Assuming messages are already JSON strings of encrypted Message objects
            await cache_service.set_chat_messages_history(user_id, target_immediate_chat_id, chat_details["messages"])
        
        # 4. chat_ids_versions (Sorted Set)
        # Ensure last_edited_overall_timestamp is an int/float
        timestamp_for_score = int(chat_details["last_edited_overall_timestamp"].timestamp()) if isinstance(chat_details["last_edited_overall_timestamp"], datetime) else int(chat_details["last_edited_overall_timestamp"])
        await cache_service.add_chat_to_ids_versions(user_id, target_immediate_chat_id, timestamp_for_score)
        
        logger.info(f"User {user_id}: Phase 1 cache warming complete for chat {target_immediate_chat_id}.")
        
        # Send WebSocket notification if user is connected
        if websocket_manager.is_user_connected(user_id):
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
        # Method should return list of dicts, each with:
        # id, messages_version, title_version, draft_version_db, encrypted_title,
        # unread_count, encrypted_draft (draft_content), last_edited_overall_timestamp
        core_chats_data: List[Dict[str, Any]] = await chat_methods.get_core_chats_for_cache_warming(directus_service, user_id, limit=1000)

        if not core_chats_data:
            logger.info(f"User {user_id}: No core chats found in Directus for Phase 2 warming.")
        else:
            logger.info(f"User {user_id}: Fetched {len(core_chats_data)} core chats for Phase 2 warming.")

        # 2. Populate Granular Cache Keys for All Fetched Chats
        for chat_data in core_chats_data:
            chat_id = chat_data["id"]
            
            # a. Add/update in user:{user_id}:chat_ids_versions
            ts_score = int(chat_data["last_edited_overall_timestamp"].timestamp()) if isinstance(chat_data["last_edited_overall_timestamp"], datetime) else int(chat_data["last_edited_overall_timestamp"])
            await cache_service.add_chat_to_ids_versions(user_id, chat_id, ts_score)

            # b. Store in user:{user_id}:chat:{chat_id}:versions
            versions = CachedChatVersions(
                messages_v=chat_data["messages_version"],
                title_v=chat_data["title_version"],
                draft_v=chat_data["draft_version_db"] # Initial draft_v from DB
            )
            await cache_service.set_chat_versions(user_id, chat_id, versions)

            # c. Store in user:{user_id}:chat:{chat_id}:list_item_data
            list_item = CachedChatListItemData(
                title=chat_data["encrypted_title"], # Already encrypted
                unread_count=chat_data["unread_count"],
                draft_json=chat_data["encrypted_draft"] # Already encrypted, from Chats.draft_content
            )
            await cache_service.set_chat_list_item_data(user_id, chat_id, list_item)
        
        logger.info(f"User {user_id}: Populated :versions and :list_item_data for {len(core_chats_data)} chats.")

        # Server Notification (Phase 2 Complete - General Sync Readiness)
        if websocket_manager.is_user_connected(user_id):
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
            messages: Optional[List[str]] = await chat_methods.get_all_messages_for_chat(directus_service, chat_id_for_messages)
            if messages:
                await cache_service.set_chat_messages_history(user_id, chat_id_for_messages, messages)
                logger.info(f"User {user_id}: Cached messages for Top N chat {chat_id_for_messages}.")
            else:
                logger.info(f"User {user_id}: No messages found or error fetching for Top N chat {chat_id_for_messages}.")
        
        logger.info(f"User {user_id}: Phase 2 cache warming complete.")

    except Exception as e:
        logger.error(f"Error in _warm_cache_phase_two for user {user_id}: {e}", exc_info=True)


@celery_app.task(name="app.tasks.user_cache_tasks.warm_user_cache")
async def warm_user_cache(user_id: str, last_opened_path_from_user_model: Optional[str]):
    """
    Asynchronously warms the user's cache upon login.
    """
    logger.info(f"Starting warm_user_cache task for user_id: {user_id}, last_opened_path: {last_opened_path_from_user_model}")

    # It's crucial that these services are instantiated correctly for async context
    # In Celery, tasks run in separate processes. get_directus_service() etc. must handle this.
    # If they are simple instantiations, it's fine. If they rely on FastAPI app state,
    # they might need to be initialized differently or passed pre-initialized if possible (complex for Celery).
    # For now, assuming they can be instantiated directly or their factories handle it.
    
    cache_service = CacheService() # Assuming direct instantiation is okay
    # For services that might need app context (like DB connections from a pool):
    directus_service: DirectusService = await get_directus_service()
    encryption_service = EncryptionService() # Assuming direct instantiation

    # Phase 1
    target_immediate_chat_id = await _warm_cache_phase_one(
        user_id, last_opened_path_from_user_model, cache_service, directus_service, encryption_service
    )

    # Phase 2
    await _warm_cache_phase_two(
        user_id, cache_service, directus_service, encryption_service, target_immediate_chat_id
    )

    logger.info(f"warm_user_cache task finished for user_id: {user_id}")

# Placeholder for chat_methods that need to be implemented/verified:
# - chat_methods.get_full_chat_details_for_cache_warming(directus_service, chat_id) -> Dict
#   (should return id, encrypted_title, encrypted_draft, draft_version_db, title_version, messages_version, unread_count, last_edited_overall_timestamp, messages: List[str_encrypted_message_json])
# - chat_methods.get_core_chats_for_cache_warming(directus_service, user_id, limit) -> List[Dict]
#   (ordered by last_edited_overall_timestamp or updated_at desc, returning fields for list_item_data and versions)
# - chat_methods.get_all_messages_for_chat(directus_service, chat_id) -> List[str_encrypted_message_json]