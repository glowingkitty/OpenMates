import logging
import asyncio
import hashlib
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.directus import chat_methods
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.schemas.chat import CachedChatVersions, CachedChatListItemData

logger = logging.getLogger(__name__)

def _parse_chat_id_from_path(path: Optional[str]) -> Optional[str]:
    """
    Parse chat ID from last_opened field.
    Supports both formats:
    - Legacy: '/chat/CHAT_ID' (path format)
    - Current: 'CHAT_ID' (direct UUID format)
    """
    if not path or path == '/chat/new' or path == 'new':
        return None
    
    # Check if it's a path format
    if path.startswith('/chat/'):
        parts = path.split('/')
        if len(parts) >= 3:
            return parts[2]
    
    # Check if it's already a direct chat ID (UUID format)
    # UUID format: 8-4-4-4-12 hexadecimal digits
    import re
    uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    if re.match(uuid_pattern, path, re.IGNORECASE):
        return path
    
    return None

async def _warm_cache_phase_one(
    user_id: str,
    last_opened_path_from_user_model: Optional[str],
    cache_service: CacheService,
    directus_service: DirectusService,
    encryption_service: EncryptionService
) -> Optional[str]:
    """Handles Phase 1 of cache warming: Immediate Needs (last opened chat AND new chat suggestions)."""
    target_immediate_chat_id = _parse_chat_id_from_path(last_opened_path_from_user_model)
    logger.info(f"warm_user_cache Phase 1 for user {user_id}. Target immediate chat: {target_immediate_chat_id}")

    # ALWAYS fetch and cache new chat suggestions in Phase 1
    try:
        hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
        new_chat_suggestions = await directus_service.chat.get_new_chat_suggestions_for_user(
            hashed_user_id, limit=50
        )
        if new_chat_suggestions:
            # Cache suggestions with 10-minute TTL
            await cache_service.set_new_chat_suggestions(hashed_user_id, new_chat_suggestions, ttl=600)
            logger.info(f"User {user_id}: Cached {len(new_chat_suggestions)} new chat suggestions in Phase 1")
        else:
            logger.info(f"User {user_id}: No new chat suggestions found to cache in Phase 1")
    except Exception as e:
        logger.error(f"Error caching new chat suggestions in Phase 1 for user {user_id}: {e}", exc_info=True)

    if not target_immediate_chat_id:
        logger.info(f"User {user_id}: No specific target_immediate_chat_id found from path '{last_opened_path_from_user_model}'. Skipping Phase 1 specific chat load.")
        return None

    try:
        full_data = await directus_service.chat.get_full_chat_and_user_draft_details_for_cache_warming(
            user_id, target_immediate_chat_id
        )

        if not full_data or not full_data.get("chat_details"):
            logger.warning(f"User {user_id}: Could not fetch details for target_immediate_chat_id {target_immediate_chat_id} from Directus (chat may have been deleted).")
            logger.info(f"User {user_id}: Skipping Phase 1 cache warming - user will see 'new chat' view instead")
            return None
        
        chat_details = full_data["chat_details"]
        user_draft_content = full_data.get("user_encrypted_draft_content")
        user_draft_version_db = full_data.get("user_draft_version_db", 0)

        list_item_data = CachedChatListItemData(
            title=chat_details["encrypted_title"],
            unread_count=chat_details["unread_count"],
            created_at=chat_details['created_at'],
            updated_at=chat_details['updated_at'],
            encrypted_chat_key=chat_details.get("encrypted_chat_key"),
            encrypted_icon=chat_details.get("encrypted_icon"),
            encrypted_category=chat_details.get("encrypted_category")
        )
        await cache_service.set_chat_list_item_data(user_id, target_immediate_chat_id, list_item_data)

        versions_data = CachedChatVersions(
            messages_v=chat_details["messages_v"],
            title_v=chat_details["title_v"]
        )
        await cache_service.set_chat_versions(user_id, target_immediate_chat_id, versions_data)
        await cache_service.set_chat_version_component(
            user_id, target_immediate_chat_id, f"user_draft_v:{user_id}", user_draft_version_db
        )

        await cache_service.update_user_draft_in_cache(
            user_id, target_immediate_chat_id, user_draft_content, user_draft_version_db
        )

        if chat_details.get("messages"):
            await cache_service.set_chat_messages_history(user_id, target_immediate_chat_id, chat_details["messages"])
        
        chat_own_update_ts = chat_details.get("updated_at", 0)
        hashed_user_id_for_draft_ph1 = hashlib.sha256(user_id.encode()).hexdigest()
        user_draft = await directus_service.chat.get_user_draft_from_directus(
            hashed_user_id_for_draft_ph1, target_immediate_chat_id
        )
        draft_updated_at_ts = user_draft.get("updated_at", 0) if user_draft else 0
        
        effective_timestamp = max(chat_own_update_ts, draft_updated_at_ts, chat_details.get("created_at", 0))
        
        await cache_service.add_chat_to_ids_versions(user_id, target_immediate_chat_id, effective_timestamp)
        
        logger.info(f"User {user_id}: Phase 1 cache warming complete for chat {target_immediate_chat_id}. Score: {effective_timestamp}")
        
        priority_channel = f"user_cache_events:{user_id}"
        priority_event_data = {"event_type": "phase_1_last_chat_ready", "payload": {"chat_id": target_immediate_chat_id}}
        await cache_service.publish_event(priority_channel, priority_event_data)
        
        return target_immediate_chat_id

    except Exception as e:
        logger.error(f"Error in _warm_cache_phase_one for user {user_id}, chat {target_immediate_chat_id}: {e}", exc_info=True)
        return None

async def _warm_cache_phase_two(
    user_id: str,
    cache_service: CacheService,
    directus_service: DirectusService,
    encryption_service: EncryptionService,
    target_immediate_chat_id: Optional[str]
):
    """Handles Phase 2 of cache warming: Last 20 updated chats for quick access."""
    logger.info(f"warm_user_cache Phase 2 for user {user_id}: Loading last 20 updated chats for quick access.")
    
    try:
        # Phase 2: Get last 20 updated chats (excluding the immediate chat from Phase 1)
        core_chats_with_user_drafts = await directus_service.chat.get_core_chats_and_user_drafts_for_cache_warming(user_id, limit=20)

        if not core_chats_with_user_drafts:
            logger.info(f"User {user_id}: No core chats found in Directus for 'Warm' cache.")
        else:
            logger.info(f"User {user_id}: Fetched {len(core_chats_with_user_drafts)} chats to populate 'Warm' cache.")

        for item in core_chats_with_user_drafts:
            chat_data = item["chat_details"]
            chat_id = chat_data["id"]
            
            effective_timestamp = max(chat_data.get("updated_at", 0), item.get("draft_updated_at", 0), chat_data.get("created_at", 0))
            await cache_service.add_chat_to_ids_versions(user_id, chat_id, effective_timestamp)
            
            versions = CachedChatVersions(messages_v=chat_data["messages_v"], title_v=chat_data["title_v"])
            await cache_service.set_chat_versions(user_id, chat_id, versions)
            await cache_service.set_chat_version_component(user_id, chat_id, f"user_draft_v:{user_id}", item.get("user_draft_version_db", 0))

            list_item = CachedChatListItemData(
                title=chat_data["encrypted_title"],
                unread_count=chat_data["unread_count"],
                created_at=chat_data['created_at'],
                updated_at=chat_data['updated_at'],
                encrypted_chat_key=chat_data.get("encrypted_chat_key"),
                encrypted_icon=chat_data.get("encrypted_icon"),
                encrypted_category=chat_data.get("encrypted_category")
            )
            await cache_service.set_chat_list_item_data(user_id, chat_id, list_item)

            await cache_service.update_user_draft_in_cache(user_id, chat_id, item.get("user_encrypted_draft_content"), item.get("user_draft_version_db", 0))
        
        logger.info(f"User {user_id}: Phase 2 cache populated with metadata for {len(core_chats_with_user_drafts)} chats.")
        
        # Send Phase 2 completion event
        priority_channel = f"user_cache_events:{user_id}"
        phase2_event_data = {"event_type": "phase_2_last_20_chats_ready", "payload": {"chat_count": len(core_chats_with_user_drafts)}}
        await cache_service.publish_event(priority_channel, phase2_event_data)
        
        logger.info(f"User {user_id}: Phase 2 complete - sent phase_2_last_20_chats_ready event")

    except Exception as e:
        logger.error(f"Error in _warm_cache_phase_two for user {user_id}: {e}", exc_info=True)

async def _warm_cache_phase_three(
    user_id: str,
    cache_service: CacheService,
    directus_service: DirectusService,
    encryption_service: EncryptionService,
    target_immediate_chat_id: Optional[str]
):
    """Handles Phase 3 of cache warming: Last 100 updated chats for full sync."""
    logger.info(f"warm_user_cache Phase 3 for user {user_id}: Loading last 100 updated chats for full sync.")
    
    try:
        # Phase 3: Get last 100 updated chats for full sync
        core_chats_with_user_drafts = await directus_service.chat.get_core_chats_and_user_drafts_for_cache_warming(user_id, limit=100)

        if not core_chats_with_user_drafts:
            logger.info(f"User {user_id}: No core chats found in Directus for Phase 3 cache.")
        else:
            logger.info(f"User {user_id}: Fetched {len(core_chats_with_user_drafts)} chats to populate Phase 3 cache.")

        for item in core_chats_with_user_drafts:
            chat_data = item["chat_details"]
            chat_id = chat_data["id"]
            
            effective_timestamp = max(chat_data.get("updated_at", 0), item.get("draft_updated_at", 0), chat_data.get("created_at", 0))
            await cache_service.add_chat_to_ids_versions(user_id, chat_id, effective_timestamp)
            
            versions = CachedChatVersions(messages_v=chat_data["messages_v"], title_v=chat_data["title_v"])
            await cache_service.set_chat_versions(user_id, chat_id, versions)
            await cache_service.set_chat_version_component(user_id, chat_id, f"user_draft_v:{user_id}", item.get("user_draft_version_db", 0))

            list_item = CachedChatListItemData(
                title=chat_data["encrypted_title"],
                unread_count=chat_data["unread_count"],
                created_at=chat_data['created_at'],
                updated_at=chat_data['updated_at'],
                encrypted_chat_key=chat_data.get("encrypted_chat_key"),
                encrypted_icon=chat_data.get("encrypted_icon"),
                encrypted_category=chat_data.get("encrypted_category")
            )
            await cache_service.set_chat_list_item_data(user_id, chat_id, list_item)

            await cache_service.update_user_draft_in_cache(user_id, chat_id, item.get("user_encrypted_draft_content"), item.get("user_draft_version_db", 0))
        
        logger.info(f"User {user_id}: Phase 3 cache populated with metadata for {len(core_chats_with_user_drafts)} chats.")

        # Get top N chats for message fetching (excluding immediate chat from Phase 1)
        top_n_chat_ids = await cache_service.get_chat_ids_versions(user_id, start=0, end=cache_service.TOP_N_MESSAGES_COUNT - 1, with_scores=False)
        
        chat_ids_to_fetch_messages_for = [cid for cid in top_n_chat_ids if cid != target_immediate_chat_id]

        if chat_ids_to_fetch_messages_for:
            logger.info(f"User {user_id}: Identified {len(chat_ids_to_fetch_messages_for)} chat IDs for 'Hot' cache message batch fetch: {chat_ids_to_fetch_messages_for}")
            
            messages_map = await directus_service.chat.get_messages_for_chats(chat_ids=chat_ids_to_fetch_messages_for, decrypt_content=False)

            for chat_id, messages in messages_map.items():
                if messages:
                    await cache_service.set_chat_messages_history(user_id, chat_id, messages)
                    logger.info(f"User {user_id}: Added {len(messages)} messages for chat {chat_id} to 'Hot' cache.")
        else:
            logger.info(f"User {user_id}: No additional chats required for 'Hot' cache message population.")
        
        logger.info(f"User {user_id}: Phase 3 cache population complete.")
        
        # Send Phase 3 completion event
        priority_channel = f"user_cache_events:{user_id}"
        phase3_event_data = {"event_type": "phase_3_last_100_chats_ready", "payload": {"chat_count": len(core_chats_with_user_drafts)}}
        await cache_service.publish_event(priority_channel, phase3_event_data)
        
        logger.info(f"User {user_id}: Phase 3 complete - sent phase_3_last_100_chats_ready event")

        await cache_service.set_user_cache_primed_flag(user_id)
        logger.info(f"User {user_id}: Successfully set user_cache_primed_flag in Redis.")

        cache_primed_channel = f"user_cache_events:{user_id}"
        cache_primed_event_data = {"event_type": "cache_primed", "payload": {"status": "full_sync_ready"}}
        await cache_service.publish_event(cache_primed_channel, cache_primed_event_data)
        
    except Exception as e:
        logger.error(f"Error in _warm_cache_phase_three for user {user_id}: {e}", exc_info=True)

async def _warm_user_app_settings_and_memories_cache(
    user_id: str,
    directus_service: DirectusService,
    cache_service: CacheService,
    task_id: Optional[str] = "UNKNOWN_TASK_ID"
):
    """Warms the cache with all user-specific app settings and memories."""
    log_prefix = f"TASK_LOGIC_APP_DATA ({task_id}): User {user_id}:"
    logger.info(f"{log_prefix} Starting to warm app settings and memories cache.")
    
    try:
        all_user_app_data = await directus_service.app_settings_and_memories.get_all_user_app_data_raw(user_id)

        if not all_user_app_data:
            logger.info(f"{log_prefix} No app settings or memories found in Directus to cache.")
            return

        for item_data in all_user_app_data:
            app_id = item_data.get("app_id")
            item_key = item_data.get("item_key")
            encrypted_value = item_data.get("encrypted_item_value_json")

            if app_id and item_key and encrypted_value is not None:
                await cache_service.set_user_app_settings_and_memories_item(
                    user_id_hash=user_id,
                    app_id=app_id,
                    item_key=item_key,
                    encrypted_value_json=encrypted_value,
                )
        
        logger.info(f"{log_prefix} Successfully cached {len(all_user_app_data)} app settings and memory items.")

    except AttributeError as ae:
        logger.error(f"{log_prefix} AttributeError during app settings/memories cache warming (method might be missing): {ae}", exc_info=True)
    except Exception as e:
        logger.error(f"{log_prefix} Error during app settings/memories cache warming: {e}", exc_info=True)

async def _async_warm_user_cache(user_id: str, last_opened_path_from_user_model: Optional[str], task_id: Optional[str] = "UNKNOWN_TASK_ID"):
    """Asynchronously warms the user's cache upon login."""
    logger.info(f"TASK_LOGIC_ENTRY: Starting _async_warm_user_cache for user_id: {user_id}, task_id: {task_id}")
    logger.info(f"Entering _async_warm_user_cache for user {user_id}")

    cache_service = CacheService()
    directus_service = DirectusService()
    await directus_service.ensure_auth_token()
    encryption_service = EncryptionService()

    target_immediate_chat_id = await _warm_cache_phase_one(
        user_id, last_opened_path_from_user_model, cache_service, directus_service, encryption_service
    )
    await _warm_cache_phase_two(
        user_id, cache_service, directus_service, encryption_service, target_immediate_chat_id
    )
    await _warm_cache_phase_three(
        user_id, cache_service, directus_service, encryption_service, target_immediate_chat_id
    )
    # TODO implement correctly later once we implement e2ee for chats, app settings and memories 
    # await _warm_user_app_settings_and_memories_cache(
    #     user_id=user_id,
    #     directus_service=directus_service,
    #     cache_service=cache_service,
    #     task_id=task_id
    # )

    logger.info(f"TASK_LOGIC_FINISH: _async_warm_user_cache task finished for user_id: {user_id}, task_id: {task_id}")

@app.task(name="app.tasks.user_cache_tasks.warm_user_cache", bind=True)
def warm_user_cache(self, user_id: str, last_opened_path_from_user_model: Optional[str]):
    """Synchronous Celery task wrapper to warm the user's cache."""
    task_id = self.request.id if self and hasattr(self, 'request') else 'UNKNOWN_TASK_ID'
    logger.info(f"TASK_ENTRY_SYNC_WRAPPER: Starting warm_user_cache task for user_id: {user_id}, task_id: {task_id}, last_opened_path: {last_opened_path_from_user_model}")
    
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
        return True
    except Exception as e:
        logger.error(f"TASK_FAILURE_SYNC_WRAPPER: Failed to run warm_user_cache task for user_id {user_id}, task_id: {task_id}: {str(e)}", exc_info=True)
        return False
    finally:
        if loop:
            loop.close()
        logger.info(f"TASK_FINALLY_SYNC_WRAPPER: Event loop closed for warm_user_cache task_id: {task_id}")
