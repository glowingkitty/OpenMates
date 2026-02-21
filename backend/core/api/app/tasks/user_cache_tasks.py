import logging
import asyncio
import hashlib
from typing import Optional, List, Dict, Any

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.schemas.chat import CachedChatVersions, CachedChatListItemData

logger = logging.getLogger(__name__)

async def _load_and_cache_embeds_for_chats(
    chat_ids: List[str],
    directus_service: DirectusService,
    cache_service: CacheService,
    user_id: str,
    phase_name: str
) -> int:
    """
    Load and cache embeds for multiple chats by hashed_chat_id.
    
    Args:
        chat_ids: List of chat IDs to load embeds for
        directus_service: Directus service instance
        cache_service: Cache service instance
        user_id: User ID for logging
        phase_name: Phase name for logging (e.g., "Phase 1", "Phase 2")
        
    Returns:
        Total number of embeds cached
    """
    total_embeds = 0
    
    if not chat_ids:
        return 0
        
    try:
        # Create a map of hashed_chat_id -> chat_id for reverse lookup
        hashed_chat_id_map = {}
        hashed_chat_ids = []
        
        for chat_id in chat_ids:
            hashed = hashlib.sha256(chat_id.encode()).hexdigest()
            hashed_chat_id_map[hashed] = chat_id
            hashed_chat_ids.append(hashed)
            
        # Batch fetch all embeds for these chats
        all_embeds = await directus_service.embed.get_embeds_by_hashed_chat_ids(hashed_chat_ids)
        
        if all_embeds:
            client = await cache_service.client
            if client:
                import json
                
                # Group embeds by chat for logging
                embeds_by_chat = {}
                
                for embed in all_embeds:
                    embed_id = embed.get("embed_id")
                    hashed_chat_id = embed.get("hashed_chat_id")
                    embed_status = embed.get("status")
                    
                    # Skip error/cancelled embeds — these are not stored or
                    # displayed by the client. Caching them wastes memory.
                    if embed_status in ("error", "cancelled"):
                        continue
                    
                    if embed_id and hashed_chat_id:
                        # Get original chat_id
                        chat_id = hashed_chat_id_map.get(hashed_chat_id)
                        
                        if chat_id:
                            # Store in sync cache: embed:{embed_id}:sync (client-encrypted)
                            sync_cache_key = f"embed:{embed_id}:sync"
                            embed_json = json.dumps(embed)
                            await client.set(sync_cache_key, embed_json, ex=3600)  # 1 hour TTL for sync cache
                            
                            # Add to chat embed index
                            await cache_service.add_embed_id_to_chat_index(chat_id, embed_id)
                            total_embeds += 1
                            
                            # Count for logging
                            embeds_by_chat[chat_id] = embeds_by_chat.get(chat_id, 0) + 1
                
                logger.debug(f"User {user_id}: Cached {total_embeds} total embeds for {len(embeds_by_chat)} chats in {phase_name}")
                
    except Exception as e:
        logger.error(f"Error loading embeds for chats in {phase_name}: {e}", exc_info=True)
        # Non-critical error
    
    return total_embeds

def _parse_chat_id_from_path(path: Optional[str]) -> Optional[str]:
    """
    Parse chat ID from last_opened field.
    Supports both formats:
    - Legacy: '/chat/CHAT_ID' (path format)
    - Current: 'CHAT_ID' (direct UUID format)
    """
    if not path or path == '/chat/new' or path == 'new':
        return None
    
    # Skip demo/legal/public chats — these are client-side-only static content
    if path.startswith('demo-') or path.startswith('legal-'):
        logger.debug(f"Skipping public/demo chat ID from last_opened: {path}")
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
    """Handles Phase 1 of cache warming: Immediate Needs (last opened chat AND new chat suggestions).
    
    OPTIMIZATION: New chat suggestions and chat details are fetched in parallel to reduce latency.
    """
    target_immediate_chat_id = _parse_chat_id_from_path(last_opened_path_from_user_model)
    logger.info(f"warm_user_cache Phase 1 for user {user_id}. Target immediate chat: {target_immediate_chat_id}")

    hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
    
    # OPTIMIZATION: Fetch new chat suggestions AND chat details in parallel
    # This reduces Phase 1 latency by running both Directus queries concurrently
    async def fetch_suggestions():
        """Fetch and cache new chat suggestions."""
        try:
            suggestions = await directus_service.chat.get_new_chat_suggestions_for_user(
                hashed_user_id, limit=50
            )
            if suggestions:
                # Cache suggestions with 10-minute TTL
                await cache_service.set_new_chat_suggestions(hashed_user_id, suggestions, ttl=600)
                logger.info(f"User {user_id}: Cached {len(suggestions)} new chat suggestions in Phase 1")
            else:
                logger.info(f"User {user_id}: No new chat suggestions found to cache in Phase 1")
            return suggestions
        except Exception as e:
            logger.error(f"Error caching new chat suggestions in Phase 1 for user {user_id}: {e}", exc_info=True)
            return None
    
    async def fetch_chat_details():
        """Fetch chat details for the target chat."""
        if not target_immediate_chat_id:
            return None
        try:
            return await directus_service.chat.get_full_chat_and_user_draft_details_for_cache_warming(
                user_id, target_immediate_chat_id
            )
        except Exception as e:
            logger.error(f"Error fetching chat details for {target_immediate_chat_id}: {e}", exc_info=True)
            return None
    
    # Run both queries in parallel using asyncio.gather
    suggestions_result, full_data = await asyncio.gather(
        fetch_suggestions(),
        fetch_chat_details()
    )
    
    # If no target chat, we're done (suggestions already cached above)
    if not target_immediate_chat_id:
        logger.info(f"User {user_id}: No specific target_immediate_chat_id found from path '{last_opened_path_from_user_model}'. Skipping Phase 1 specific chat load.")
        return None

    # Process the chat details if we got them
    try:
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
            encrypted_category=chat_details.get("encrypted_category"),
            encrypted_chat_summary=chat_details.get("encrypted_chat_summary"),
            encrypted_chat_tags=chat_details.get("encrypted_chat_tags"),
            encrypted_follow_up_request_suggestions=chat_details.get("encrypted_follow_up_request_suggestions"),
            encrypted_active_focus_id=chat_details.get("encrypted_active_focus_id"),
            last_message_timestamp=chat_details.get("last_message_timestamp"),
            is_shared=chat_details.get("is_shared"),
            is_private=chat_details.get("is_private"),
            user_id=user_id  # Cache the owner ID
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

        # Store client-encrypted messages to SYNC cache (for Phase 1/2/3 client sync)
        if chat_details.get("messages"):
            await cache_service.set_sync_messages_history(user_id, target_immediate_chat_id, chat_details["messages"], ttl=3600)
            logger.debug(f"Stored {len(chat_details['messages'])} client-encrypted messages to sync cache for chat {target_immediate_chat_id}")
        
        # Load and cache embeds for this chat (by hashed_chat_id)
        embed_count = await _load_and_cache_embeds_for_chats(
            [target_immediate_chat_id],
            directus_service,
            cache_service,
            user_id,
            "Phase 1"
        )
        if embed_count > 0:
            logger.info(f"User {user_id}: Cached {embed_count} embed(s) for chat {target_immediate_chat_id} in Phase 1")
        
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

async def _warm_cache_phase_two_optimized(
    user_id: str,
    cache_service: CacheService,
    directus_service: DirectusService,
    encryption_service: EncryptionService,
    target_immediate_chat_id: Optional[str],
    core_chats_with_user_drafts: List[Dict[str, Any]]
):
    """Optimized Phase 2: Process pre-fetched chat data for last 20 chats."""
    logger.info(f"warm_user_cache Phase 2 for user {user_id}: Processing {len(core_chats_with_user_drafts)} pre-fetched chats for quick access.")

    try:
        if not core_chats_with_user_drafts:
            logger.info(f"User {user_id}: No core chats provided for 'Warm' cache.")
        else:
            logger.info(f"User {user_id}: Processing {len(core_chats_with_user_drafts)} chats to populate 'Warm' cache.")

        # OPTIMIZATION: Use Redis pipelining to batch cache operations
        # Instead of individual awaits, collect all operations and execute them together
        pipeline_operations = []

        for item in core_chats_with_user_drafts:
            chat_data = item["chat_details"]
            chat_id = chat_data["id"]

            effective_timestamp = max(chat_data.get("updated_at", 0), item.get("draft_updated_at", 0), chat_data.get("created_at", 0))
            versions = CachedChatVersions(messages_v=chat_data["messages_v"], title_v=chat_data["title_v"])

            list_item = CachedChatListItemData(
                title=chat_data["encrypted_title"],
                unread_count=chat_data["unread_count"],
                created_at=chat_data['created_at'],
                updated_at=chat_data['updated_at'],
                encrypted_chat_key=chat_data.get("encrypted_chat_key"),
                encrypted_icon=chat_data.get("encrypted_icon"),
                encrypted_category=chat_data.get("encrypted_category"),
                encrypted_chat_summary=chat_data.get("encrypted_chat_summary"),
                encrypted_chat_tags=chat_data.get("encrypted_chat_tags"),
                encrypted_follow_up_request_suggestions=chat_data.get("encrypted_follow_up_request_suggestions"),
                encrypted_active_focus_id=chat_data.get("encrypted_active_focus_id"),
                last_message_timestamp=chat_data.get("last_message_timestamp"),
                is_shared=chat_data.get("is_shared"),
                is_private=chat_data.get("is_private"),
                user_id=user_id  # Cache the owner ID
            )

            # Prepare pipeline operations for this chat
            pipeline_operations.extend([
                ('add_chat_to_ids_versions', user_id, chat_id, effective_timestamp),
                ('set_chat_versions', user_id, chat_id, versions),
                ('set_chat_version_component', user_id, chat_id, f"user_draft_v:{user_id}", item.get("user_draft_version_db", 0)),
                ('set_chat_list_item_data', user_id, chat_id, list_item),
                ('update_user_draft_in_cache', user_id, chat_id, item.get("user_encrypted_draft_content"), item.get("user_draft_version_db", 0))
            ])

        # Execute all operations in a single pipeline
        if pipeline_operations:
            pipeline_success = await cache_service.execute_pipeline_operations(pipeline_operations)
            if pipeline_success:
                logger.info(f"User {user_id}: Successfully executed {len(pipeline_operations)} cache operations via pipeline for {len(core_chats_with_user_drafts)} chats")
            else:
                logger.warning(f"User {user_id}: Pipeline execution had some failures, falling back to individual operations")
                # Fallback to individual operations if pipeline fails
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
                        encrypted_category=chat_data.get("encrypted_category"),
                        encrypted_chat_summary=chat_data.get("encrypted_chat_summary"),
                        encrypted_chat_tags=chat_data.get("encrypted_chat_tags"),
                        encrypted_follow_up_request_suggestions=chat_data.get("encrypted_follow_up_request_suggestions"),
                        encrypted_active_focus_id=chat_data.get("encrypted_active_focus_id"),
                        last_message_timestamp=chat_data.get("last_message_timestamp"),
                        is_shared=chat_data.get("is_shared"),
                        is_private=chat_data.get("is_private"),
                        user_id=user_id  # Cache the owner ID
                    )
                    await cache_service.set_chat_list_item_data(user_id, chat_id, list_item)

                    await cache_service.update_user_draft_in_cache(user_id, chat_id, item.get("user_encrypted_draft_content"), item.get("user_draft_version_db", 0))
        
        # Load and cache embeds for all Phase 2 chats
        phase2_chat_ids = [item["chat_details"]["id"] for item in core_chats_with_user_drafts]
        embed_count = await _load_and_cache_embeds_for_chats(
            phase2_chat_ids,
            directus_service,
            cache_service,
            user_id,
            "Phase 2"
        )
        if embed_count > 0:
            logger.info(f"User {user_id}: Cached {embed_count} embed(s) for {len(phase2_chat_ids)} chats in Phase 2")
        
        logger.info(f"User {user_id}: Phase 2 cache populated with metadata for {len(core_chats_with_user_drafts)} chats.")
        
        # Send Phase 2 completion event
        priority_channel = f"user_cache_events:{user_id}"
        phase2_event_data = {"event_type": "phase_2_last_20_chats_ready", "payload": {"chat_count": len(core_chats_with_user_drafts)}}
        await cache_service.publish_event(priority_channel, phase2_event_data)
        
        logger.info(f"User {user_id}: Phase 2 complete - sent phase_2_last_20_chats_ready event")

    except Exception as e:
        logger.error(f"Error in _warm_cache_phase_two for user {user_id}: {e}", exc_info=True)

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
                encrypted_category=chat_data.get("encrypted_category"),
                encrypted_chat_summary=chat_data.get("encrypted_chat_summary"),
                encrypted_chat_tags=chat_data.get("encrypted_chat_tags"),
            )

            await cache_service.set_chat_list_item(user_id, chat_id, list_item)
            logger.debug(f"User {user_id}: Cached list data for chat {chat_id}")

        chat_ids = [item["chat_details"]["id"] for item in core_chats_with_user_drafts]
        total_embeds = await _load_and_cache_embeds_for_chats(chat_ids, directus_service, cache_service, user_id, "Phase 2")
        logger.info(f"User {user_id}: Phase 2 cached {len(core_chats_with_user_drafts)} chats and {total_embeds} embeds for 'Warm' cache")

    except Exception as e:
        logger.error(f"Error in _warm_cache_phase_two for user {user_id}: {e}", exc_info=True)

async def _warm_cache_phase_three_optimized(
    user_id: str,
    cache_service: CacheService,
    directus_service: DirectusService,
    encryption_service: EncryptionService,
    target_immediate_chat_id: Optional[str],
    core_chats_with_user_drafts: List[Dict[str, Any]]
):
    """Optimized Phase 3: Process pre-fetched chat data for all 100 chats."""
    logger.info(f"warm_user_cache Phase 3 for user {user_id}: Processing {len(core_chats_with_user_drafts)} pre-fetched chats for full sync.")

    try:
        if not core_chats_with_user_drafts:
            logger.info(f"User {user_id}: No core chats provided for Phase 3 cache.")
        else:
            logger.info(f"User {user_id}: Processing {len(core_chats_with_user_drafts)} chats to populate Phase 3 cache.")

        # OPTIMIZATION: Use Redis pipelining to batch cache operations
        # Instead of individual awaits, collect all operations and execute them together
        pipeline_operations = []

        for item in core_chats_with_user_drafts:
            chat_data = item["chat_details"]
            chat_id = chat_data["id"]

            effective_timestamp = max(chat_data.get("updated_at", 0), item.get("draft_updated_at", 0), chat_data.get("created_at", 0))
            versions = CachedChatVersions(messages_v=chat_data["messages_v"], title_v=chat_data["title_v"])

            list_item = CachedChatListItemData(
                title=chat_data["encrypted_title"],
                unread_count=chat_data["unread_count"],
                created_at=chat_data['created_at'],
                updated_at=chat_data['updated_at'],
                encrypted_chat_key=chat_data.get("encrypted_chat_key"),
                encrypted_icon=chat_data.get("encrypted_icon"),
                encrypted_category=chat_data.get("encrypted_category"),
                encrypted_chat_summary=chat_data.get("encrypted_chat_summary"),
                encrypted_chat_tags=chat_data.get("encrypted_chat_tags"),
                encrypted_follow_up_request_suggestions=chat_data.get("encrypted_follow_up_request_suggestions"),
                encrypted_active_focus_id=chat_data.get("encrypted_active_focus_id"),
                last_message_timestamp=chat_data.get("last_message_timestamp"),
                is_shared=chat_data.get("is_shared"),
                is_private=chat_data.get("is_private"),
                user_id=user_id  # Cache the owner ID
            )

            # Prepare pipeline operations for this chat
            pipeline_operations.extend([
                ('add_chat_to_ids_versions', user_id, chat_id, effective_timestamp),
                ('set_chat_versions', user_id, chat_id, versions),
                ('set_chat_version_component', user_id, chat_id, f"user_draft_v:{user_id}", item.get("user_draft_version_db", 0)),
                ('set_chat_list_item_data', user_id, chat_id, list_item),
                ('update_user_draft_in_cache', user_id, chat_id, item.get("user_encrypted_draft_content"), item.get("user_draft_version_db", 0))
            ])

        # Execute all operations in a single pipeline
        if pipeline_operations:
            pipeline_success = await cache_service.execute_pipeline_operations(pipeline_operations)
            if pipeline_success:
                logger.info(f"User {user_id}: Successfully executed {len(pipeline_operations)} cache operations via pipeline for {len(core_chats_with_user_drafts)} chats")
            else:
                logger.warning(f"User {user_id}: Pipeline execution had some failures, falling back to individual operations")
                # Fallback to individual operations if pipeline fails
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
                        encrypted_category=chat_data.get("encrypted_category"),
                        encrypted_chat_summary=chat_data.get("encrypted_chat_summary"),
                        encrypted_chat_tags=chat_data.get("encrypted_chat_tags"),
                        encrypted_follow_up_request_suggestions=chat_data.get("encrypted_follow_up_request_suggestions"),
                        encrypted_active_focus_id=chat_data.get("encrypted_active_focus_id"),
                        last_message_timestamp=chat_data.get("last_message_timestamp"),
                        is_shared=chat_data.get("is_shared"),
                        is_private=chat_data.get("is_private"),
                        user_id=user_id  # Cache the owner ID
                    )
                    await cache_service.set_chat_list_item_data(user_id, chat_id, list_item)

                    await cache_service.update_user_draft_in_cache(user_id, chat_id, item.get("user_encrypted_draft_content"), item.get("user_draft_version_db", 0))
        
        # Load and cache embeds for all Phase 3 chats
        phase3_chat_ids = [item["chat_details"]["id"] for item in core_chats_with_user_drafts]
        embed_count = await _load_and_cache_embeds_for_chats(
            phase3_chat_ids,
            directus_service,
            cache_service,
            user_id,
            "Phase 3"
        )
        if embed_count > 0:
            logger.info(f"User {user_id}: Cached {embed_count} embed(s) for {len(phase3_chat_ids)} chats in Phase 3")
        
        logger.info(f"User {user_id}: Phase 3 cache populated with metadata for {len(core_chats_with_user_drafts)} chats.")

        # Get top N chats for message fetching (excluding immediate chat from Phase 1)
        top_n_chat_ids = await cache_service.get_chat_ids_versions(user_id, start=0, end=cache_service.TOP_N_MESSAGES_COUNT - 1, with_scores=False)
        
        chat_ids_to_fetch_messages_for = [cid for cid in top_n_chat_ids if cid != target_immediate_chat_id]

        if chat_ids_to_fetch_messages_for:
            logger.info(f"User {user_id}: Identified {len(chat_ids_to_fetch_messages_for)} chat IDs for 'Hot' cache message batch fetch: {chat_ids_to_fetch_messages_for}")
            
            messages_map = await directus_service.chat.get_messages_for_chats(chat_ids=chat_ids_to_fetch_messages_for, decrypt_content=False)

            # Store client-encrypted messages to SYNC cache (for Phase 2/3 client sync)
            for chat_id, messages in messages_map.items():
                if messages:
                    await cache_service.set_sync_messages_history(user_id, chat_id, messages, ttl=3600)
                    logger.info(f"User {user_id}: Added {len(messages)} client-encrypted messages for chat {chat_id} to sync cache.")
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
        logger.error(f"Error in _warm_cache_phase_three_optimized for user {user_id}: {e}", exc_info=True)

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
                encrypted_category=chat_data.get("encrypted_category"),
                encrypted_chat_summary=chat_data.get("encrypted_chat_summary"),
                encrypted_chat_tags=chat_data.get("encrypted_chat_tags"),
                encrypted_follow_up_request_suggestions=chat_data.get("encrypted_follow_up_request_suggestions"),
                encrypted_active_focus_id=chat_data.get("encrypted_active_focus_id"),
                last_message_timestamp=chat_data.get("last_message_timestamp"),
                is_shared=chat_data.get("is_shared"),
                is_private=chat_data.get("is_private"),
                user_id=user_id  # Cache the owner ID
            )
            await cache_service.set_chat_list_item_data(user_id, chat_id, list_item)

            await cache_service.update_user_draft_in_cache(user_id, chat_id, item.get("user_encrypted_draft_content"), item.get("user_draft_version_db", 0))

        # Load and cache embeds for all Phase 3 chats
        phase3_chat_ids = [item["chat_details"]["id"] for item in core_chats_with_user_drafts]
        embed_count = await _load_and_cache_embeds_for_chats(
            phase3_chat_ids,
            directus_service,
            cache_service,
            user_id,
            "Phase 3"
        )
        if embed_count > 0:
            logger.info(f"User {user_id}: Cached {embed_count} embed(s) for {len(phase3_chat_ids)} chats in Phase 3")

        logger.info(f"User {user_id}: Phase 3 cache populated with metadata for {len(core_chats_with_user_drafts)} chats.")

        # Get top N chats for message fetching (excluding immediate chat from Phase 1)
        top_n_chat_ids = await cache_service.get_chat_ids_versions(user_id, start=0, end=cache_service.TOP_N_MESSAGES_COUNT - 1, with_scores=False)

        chat_ids_to_fetch_messages_for = [cid for cid in top_n_chat_ids if cid != target_immediate_chat_id]

        if chat_ids_to_fetch_messages_for:
            logger.info(f"User {user_id}: Identified {len(chat_ids_to_fetch_messages_for)} chat IDs for 'Hot' cache message batch fetch: {chat_ids_to_fetch_messages_for}")

            messages_map = await directus_service.chat.get_messages_for_chats(chat_ids=chat_ids_to_fetch_messages_for, decrypt_content=False)

            # Store client-encrypted messages to SYNC cache (for Phase 2/3 client sync)
            for chat_id, messages in messages_map.items():
                if messages:
                    await cache_service.set_sync_messages_history(user_id, chat_id, messages, ttl=3600)
                    logger.info(f"User {user_id}: Added {len(messages)} client-encrypted messages for chat {chat_id} to sync cache.")
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
    """Warms the cache with all user-specific app settings and memories.
    
    Note: This function is called during cache warming to pre-populate the cache
    with app settings/memories data. The Directus service method get_all_user_app_data_raw
    handles user_id hashing internally, so we pass the raw user_id.
    
    However, the cache methods expect a hashed user_id, so we hash it here for caching.
    """
    import hashlib
    log_prefix = f"TASK_LOGIC_APP_DATA ({task_id}): User {user_id[:8]}...:"
    logger.info(f"{log_prefix} Starting to warm app settings and memories cache.")
    
    try:
        # get_all_user_app_data_raw handles hashing internally when querying Directus
        all_user_app_data = await directus_service.app_settings_and_memories.get_all_user_app_data_raw(user_id)

        if not all_user_app_data:
            logger.info(f"{log_prefix} No app settings or memories found in Directus to cache.")
            return

        # Hash user_id for cache key (cache methods expect hashed user_id)
        hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
        
        for item_data in all_user_app_data:
            app_id = item_data.get("app_id")
            item_key = item_data.get("item_key")
            # Field name is encrypted_item_json (consistent with schema and other code)
            encrypted_value = item_data.get("encrypted_item_json")

            if app_id and item_key and encrypted_value is not None:
                await cache_service.set_user_app_settings_and_memories_item(
                    user_id_hash=hashed_user_id,
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
    # Ensure Redis client is properly connected before proceeding
    client = await cache_service.client
    if not client:
        logger.error(f"Failed to connect to Redis cache. Cache warming cannot proceed for user {user_id}")
        return
    try:
        pong = await client.ping()
        logger.debug(f"Cache service connected successfully (PING={pong})")
    except Exception as e:
        logger.error(f"Failed to ping Redis cache: {e}. Cache warming cannot proceed for user {user_id}")
        return
    
    directus_service = DirectusService()
    await directus_service.ensure_auth_token()
    encryption_service = EncryptionService()

    # Ensure the user profile in Redis cache has the latest last_opened value.
    # The /lookup endpoint caches the user profile from Directus, but if the user
    # changed chats after that (via set_active_chat), the cached value may already
    # be updated. However, if cache was evicted or this is a fresh warm, we ensure
    # the value passed from the login flow is reflected in the cache.
    if last_opened_path_from_user_model:
        try:
            await cache_service.update_user(user_id, {"last_opened": last_opened_path_from_user_model})
            logger.debug(f"User {user_id}: Ensured last_opened='{last_opened_path_from_user_model}' in user cache during warming")
        except Exception as e:
            logger.warning(f"User {user_id}: Failed to update last_opened in cache during warming: {e}")
            # Non-critical: Phase 1 will still use the parameter value directly

    target_immediate_chat_id = await _warm_cache_phase_one(
        user_id, last_opened_path_from_user_model, cache_service, directus_service, encryption_service
    )

    # OPTIMIZATION: Fetch all chats once and use for both Phase 2 and 3
    # This reduces database queries from 2 separate calls to 1 combined call
    try:
        logger.info(f"User {user_id}: Fetching all chats for Phase 2 and 3 optimization")
        all_core_chats_with_user_drafts = await directus_service.chat.get_core_chats_and_user_drafts_for_cache_warming(user_id, limit=100)

        # Phase 2: Process first 20 chats
        phase_2_chats = all_core_chats_with_user_drafts[:20] if all_core_chats_with_user_drafts else []
        await _warm_cache_phase_two_optimized(
            user_id, cache_service, directus_service, encryption_service, target_immediate_chat_id, phase_2_chats
        )

        # Phase 3: Process all 100 chats
        await _warm_cache_phase_three_optimized(
            user_id, cache_service, directus_service, encryption_service, target_immediate_chat_id, all_core_chats_with_user_drafts
        )
    except Exception as e:
        logger.error(f"Error in optimized Phase 2/3 cache warming for user {user_id}: {e}", exc_info=True)
        # Fall back to original methods if optimization fails
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


@app.task(name="delete_user_account", bind=True)
def delete_user_account_task(
    self,
    user_id: str,
    deletion_type: str = "user_requested",
    reason: str = "User requested account deletion",
    ip_address: str = None,
    device_fingerprint: str = None,
    refund_invoices: bool = True,
    email_encryption_key: str = None,
):
    """
    Asynchronously delete user account and all associated data.
    
    Processes deletion in priority order:
    1. Authentication data (prevents re-login) - CRITICAL
    2. Payment/subscription data (with auto-refunds)
    3. User content (chats, messages, embeds)
    4. Cache cleanup
    5. User record deletion
    
    Args:
        user_id: ID of user to delete
        deletion_type: Type of deletion (user_requested, policy_violation, admin_action)
        reason: Reason for deletion
        ip_address: IP address of deletion request
        device_fingerprint: Device fingerprint of deletion request
        refund_invoices: Whether to auto-refund eligible purchases from last 14 days
        email_encryption_key: Client-side email encryption key for sending refund confirmation emails
    """
    task_id = self.request.id
    logger.info(f"[TASK] delete_user_account started for user {user_id}, task_id={task_id}")
    
    loop = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(_async_delete_user_account(
            user_id=user_id,
            deletion_type=deletion_type,
            reason=reason,
            ip_address=ip_address,
            device_fingerprint=device_fingerprint,
            refund_invoices=refund_invoices,
            task_id=task_id,
            email_encryption_key=email_encryption_key,
        ))
        return result
    except Exception as e:
        logger.error(f"[TASK] delete_user_account failed for user {user_id}, task_id={task_id}: {e}", exc_info=True)
        return False
    finally:
        if loop:
            loop.close()
        logger.info(f"[TASK] delete_user_account completed for user {user_id}, task_id={task_id}")


async def _async_delete_user_account(
    user_id: str,
    deletion_type: str,
    reason: str,
    ip_address: Optional[str],
    device_fingerprint: Optional[str],
    refund_invoices: bool,
    task_id: str,
    email_encryption_key: Optional[str] = None,
) -> bool:
    """
    Async implementation of account deletion following priority order from architecture.
    """
    from backend.core.api.app.services.compliance import ComplianceService
    from datetime import datetime, timezone, timedelta
    
    # Initialize services
    cache_service = CacheService()
    encryption_service = EncryptionService()
    directus_service = DirectusService(
        cache_service=cache_service,
        encryption_service=encryption_service
    )
    compliance_service = ComplianceService()
    
    user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()
    
    try:
        logger.info(f"[DELETE_ACCOUNT] Starting deletion for user {user_id}, task_id={task_id}")
        
        # ===== PHASE 1: Authentication Data (Highest Priority) =====
        logger.info(f"[DELETE_ACCOUNT] Phase 1: Deleting authentication data for user {user_id}")
        
        # 1. Delete passkeys (using bulk delete for efficiency)
        try:
            passkeys = await directus_service.get_user_passkeys_by_user_id(user_id)
            passkey_ids = [p.get("id") for p in passkeys if p.get("id")]
            if passkey_ids:
                await directus_service.bulk_delete_items("user_passkeys", passkey_ids)
            logger.info(f"[DELETE_ACCOUNT] Deleted {len(passkey_ids)} passkeys for user {user_id}")
        except Exception as e:
            logger.error(f"[DELETE_ACCOUNT] Error deleting passkeys for user {user_id}: {e}", exc_info=True)
            # Critical - retry logic could be added here
        
        # 2. Delete API keys and associated devices (using bulk delete for efficiency)
        try:
            api_keys = await directus_service.get_user_api_keys_by_user_id(user_id)
            api_key_ids = [k.get("id") for k in api_keys if k.get("id")]
            
            # Collect all device IDs for all API keys in one batch
            all_device_ids = []
            for api_key_id in api_key_ids:
                api_key_devices = await directus_service.get_items(
                    "api_key_devices",
                    params={"filter": {"api_key_id": {"_eq": api_key_id}}}
                )
                device_ids = [d.get("id") for d in (api_key_devices or []) if d.get("id")]
                all_device_ids.extend(device_ids)
            
            # Bulk delete all devices first, then all API keys
            if all_device_ids:
                await directus_service.bulk_delete_items("api_key_devices", all_device_ids)
            if api_key_ids:
                await directus_service.bulk_delete_items("api_keys", api_key_ids)
            logger.info(f"[DELETE_ACCOUNT] Deleted {len(api_key_ids)} API keys and {len(all_device_ids)} devices for user {user_id}")
        except Exception as e:
            logger.error(f"[DELETE_ACCOUNT] Error deleting API keys for user {user_id}: {e}", exc_info=True)
        
        # 3. Clear 2FA data from user record
        try:
            await directus_service.update_user(user_id, {
                "encrypted_tfa_secret": None,
                "tfa_backup_codes_hashes": None,
                "encrypted_tfa_app_name": None,
                "tfa_last_used": None,
                "consent_tfa_safely_stored_timestamp": None
            })
            logger.info(f"[DELETE_ACCOUNT] Cleared 2FA data for user {user_id}")
        except Exception as e:
            logger.error(f"[DELETE_ACCOUNT] Error clearing 2FA data for user {user_id}: {e}", exc_info=True)
        
        # 4. Clear lookup hashes
        try:
            await directus_service.update_user(user_id, {"lookup_hashes": None})
            logger.info(f"[DELETE_ACCOUNT] Cleared lookup hashes for user {user_id}")
        except Exception as e:
            logger.error(f"[DELETE_ACCOUNT] Error clearing lookup hashes for user {user_id}: {e}", exc_info=True)
        
        # 5. Clear email authentication data
        try:
            await directus_service.update_user(user_id, {
                "hashed_email": None,
                "user_email_salt": None,
                "encrypted_email_address": None,
                "encrypted_email_with_master_key": None
            })
            logger.info(f"[DELETE_ACCOUNT] Cleared email authentication data for user {user_id}")
        except Exception as e:
            logger.error(f"[DELETE_ACCOUNT] Error clearing email auth data for user {user_id}: {e}", exc_info=True)
        
        # 6. Delete encryption keys (master keys encrypted with different login methods) - using bulk delete
        try:
            encryption_keys = await directus_service.get_items(
                "encryption_keys",
                params={"filter": {"hashed_user_id": {"_eq": user_id_hash}}}
            )
            key_ids = [k.get("id") for k in (encryption_keys or []) if k.get("id")]
            if key_ids:
                await directus_service.bulk_delete_items("encryption_keys", key_ids)
            logger.info(f"[DELETE_ACCOUNT] Deleted {len(key_ids)} encryption keys for user {user_id}")
        except Exception as e:
            logger.error(f"[DELETE_ACCOUNT] Error deleting encryption keys for user {user_id}: {e}", exc_info=True)
        
        # 7. Vault keys - Note: Vault deletion may require additional service methods
        # This is marked as TODO in the architecture - implementation depends on Vault service
        
        # 8. Sessions & Tokens - already handled in endpoint (logout_all_sessions called)
        logger.info(f"[DELETE_ACCOUNT] Phase 1 complete for user {user_id}")
        
        # ===== PHASE 2: Payment & Subscription Data =====
        logger.info(f"[DELETE_ACCOUNT] Phase 2: Processing payment/subscription data for user {user_id}")
        
        # 8. Stripe cleanup - Note: Requires PaymentService integration
        # This would cancel subscription and delete customer - marked as TODO
        
        # 9. Auto-refund processing (if enabled)
        # Calls the actual payment provider API (Stripe/Polar) to return money,
        # deducts credits, updates Directus, and optionally dispatches the credit
        # note email task (only when email_encryption_key is available).
        if refund_invoices:
            try:
                import os
                from backend.core.api.app.services.payment.payment_service import PaymentService
                from backend.core.api.app.utils.secrets_manager import SecretsManager

                # Get invoices from last 14 days that are eligible for refund
                now = datetime.now(timezone.utc)
                fourteen_days_ago = now - timedelta(days=14)

                invoices = await directus_service.get_items(
                    "invoices",
                    params={
                        "filter": {
                            "user_id_hash": {"_eq": user_id_hash},
                            "date": {"_gte": fourteen_days_ago.isoformat()},
                            "refunded_at": {"_null": True},
                            "is_gift_card": {"_eq": False}
                        },
                        "fields": "*"
                    }
                )

                if not invoices:
                    invoices = []

                logger.info(f"[DELETE_ACCOUNT] Found {len(invoices)} eligible invoices for refund for user {user_id}")

                if invoices:
                    # Initialize PaymentService for making actual refund API calls
                    secrets_manager = SecretsManager()
                    await secrets_manager.initialize()
                    payment_service = PaymentService(secrets_manager=secrets_manager)
                    is_dev = os.getenv("SERVER_ENVIRONMENT", "development").lower() == "development"
                    await payment_service.initialize(is_production=not is_dev)

                    refund_success_count = 0
                    refund_fail_count = 0

                    for invoice in invoices:
                        invoice_id = invoice.get("id", "unknown")
                        order_id = invoice.get("order_id", "")
                        invoice_provider = invoice.get("provider")  # "stripe", "polar", or None (legacy)
                        provider_order_id = invoice.get("provider_order_id")  # Polar Order UUID
                        encrypted_amount = invoice.get("encrypted_amount")
                        encrypted_credits = invoice.get("encrypted_credits_purchased")
                        vault_key_id = None

                        # Resolve vault_key_id for decryption
                        user_data = await cache_service.get_user_by_id(user_id)
                        if user_data:
                            vault_key_id = user_data.get("vault_key_id")

                        if not encrypted_amount or not vault_key_id:
                            logger.warning(
                                f"[DELETE_ACCOUNT] Skipping refund for invoice {invoice_id}: "
                                f"missing encrypted_amount or vault_key_id"
                            )
                            refund_fail_count += 1
                            continue

                        try:
                            refund_amount_cents = int(
                                await encryption_service.decrypt_with_user_key(encrypted_amount, vault_key_id)
                            )
                        except Exception as decrypt_err:
                            logger.error(
                                f"[DELETE_ACCOUNT] Cannot decrypt amount for invoice {invoice_id}: {decrypt_err}"
                            )
                            refund_fail_count += 1
                            continue

                        # Determine the provider-specific order ID to refund against
                        # For Polar: use provider_order_id (the Polar Order UUID)
                        # For Stripe: use order_id (the PaymentIntent ID like 'pi_...')
                        if invoice_provider == "polar":
                            refund_order_id = provider_order_id
                            if not refund_order_id:
                                logger.error(
                                    f"[DELETE_ACCOUNT] Polar invoice {invoice_id} missing provider_order_id, cannot refund"
                                )
                                refund_fail_count += 1
                                continue
                        else:
                            refund_order_id = order_id

                        if not refund_order_id:
                            logger.warning(
                                f"[DELETE_ACCOUNT] Invoice {invoice_id} has no order ID, cannot refund"
                            )
                            refund_fail_count += 1
                            continue

                        # Call the payment provider API to actually return money
                        logger.info(
                            f"[DELETE_ACCOUNT] Refunding invoice {invoice_id}: "
                            f"{refund_amount_cents} cents via {invoice_provider or 'auto-detect'} "
                            f"(order: {refund_order_id})"
                        )
                        try:
                            refund_result = await payment_service.refund_payment(
                                payment_intent_id=refund_order_id,
                                amount=refund_amount_cents,
                                provider=invoice_provider,
                                reason="customer_request",
                            )
                        except Exception as refund_api_err:
                            logger.error(
                                f"[DELETE_ACCOUNT] Refund API call failed for invoice {invoice_id}: {refund_api_err}",
                                exc_info=True
                            )
                            refund_fail_count += 1
                            continue

                        if not refund_result:
                            logger.error(f"[DELETE_ACCOUNT] Refund returned None for invoice {invoice_id}")
                            refund_fail_count += 1
                            continue

                        # Mark invoice as refunded in Directus
                        try:
                            await directus_service.update_item("invoices", invoice_id, {
                                "refund_status": "completed",
                                "refunded_at": now.isoformat(),
                            })
                        except Exception as update_err:
                            logger.error(
                                f"[DELETE_ACCOUNT] Failed to update Directus refund status for "
                                f"invoice {invoice_id}: {update_err}"
                            )

                        # Deduct credits proportionally
                        credits_to_deduct = 0
                        credits_purchased_for_invoice = 0
                        try:
                            credits_purchased_for_invoice = int(
                                await encryption_service.decrypt_with_user_key(encrypted_credits, vault_key_id)
                            )
                            current_credits = int((await cache_service.get_user_by_id(user_id) or {}).get("credits", 0))
                            credits_to_deduct = min(credits_purchased_for_invoice, current_credits)
                            if credits_to_deduct > 0:
                                await cache_service.update_user_credits(user_id, -credits_to_deduct)
                                logger.info(
                                    f"[DELETE_ACCOUNT] Deducted {credits_to_deduct} credits for "
                                    f"refunded invoice {invoice_id}"
                                )
                        except Exception as credit_err:
                            logger.error(
                                f"[DELETE_ACCOUNT] Failed to deduct credits for invoice {invoice_id}: {credit_err}"
                            )

                        # Record in Invoice Ninja — only for Stripe/Revolut (not Polar MoR)
                        if invoice_provider != "polar":
                            try:
                                from backend.core.api.app.services.invoiceninja.invoiceninja import InvoiceNinjaService
                                ninja_service = InvoiceNinjaService()
                                refund_amount_decimal = refund_amount_cents / 100.0
                                ninja_service.process_refund_transaction(
                                    user_hash=user_id_hash,
                                    external_order_id=order_id,
                                    invoice_id=invoice_id,
                                    customer_firstname="User",
                                    customer_lastname=user_id_hash[:8],
                                    customer_account_id=user_id_hash[:12],
                                    customer_country_code="XX",
                                    refund_amount_value=refund_amount_decimal,
                                    currency_code=invoice.get("currency", "eur"),
                                    refund_date=now.strftime("%Y-%m-%d"),
                                    payment_processor=invoice_provider or "stripe",
                                    custom_credit_note_number=f"CN-DELETE-{invoice_id[:8]}",
                                )
                                logger.info(
                                    f"[DELETE_ACCOUNT] Recorded refund in Invoice Ninja for invoice {invoice_id}"
                                )
                            except Exception as ninja_err:
                                logger.error(
                                    f"[DELETE_ACCOUNT] Invoice Ninja recording failed for "
                                    f"invoice {invoice_id}: {ninja_err}",
                                    exc_info=True
                                )
                        else:
                            logger.info(
                                f"[DELETE_ACCOUNT] Skipping Invoice Ninja for Polar refund "
                                f"(invoice {invoice_id}): Polar is MoR."
                            )

                        # Dispatch credit note email task if encryption key is available
                        # (email_encryption_key is zero-knowledge and only available when
                        # the user is present in the browser during deletion)
                        if email_encryption_key:
                            try:
                                from backend.core.api.app.tasks.celery_config import app as celery_app
                                from backend.core.api.app.services.email.config_loader import load_email_config

                                email_config = load_email_config()
                                invoice_number = invoice.get("invoice_number", "")
                                currency = invoice.get("currency", "eur")

                                celery_app.send_task(
                                    name="app.tasks.email_tasks.credit_note_email_task.process_credit_note_and_send_email",
                                    kwargs={
                                        "invoice_id": invoice_id,
                                        "user_id": user_id,
                                        "order_id": order_id,
                                        "refund_amount_cents": refund_amount_cents,
                                        "unused_credits": credits_to_deduct,
                                        "total_credits": credits_purchased_for_invoice,
                                        "currency": currency,
                                        "referenced_invoice_number": invoice_number,
                                        "sender_addressline1": email_config.get("sender_addressline1", ""),
                                        "sender_addressline2": email_config.get("sender_addressline2", ""),
                                        "sender_addressline3": email_config.get("sender_addressline3", ""),
                                        "sender_country": email_config.get("sender_country", ""),
                                        "sender_email": email_config.get("sender_email", ""),
                                        "sender_vat": email_config.get("sender_vat", ""),
                                        "email_encryption_key": email_encryption_key,
                                        "provider": invoice_provider,
                                    },
                                    queue="email"
                                )
                                logger.info(
                                    f"[DELETE_ACCOUNT] Dispatched credit note email task for invoice {invoice_id}"
                                )
                            except Exception as email_task_err:
                                logger.error(
                                    f"[DELETE_ACCOUNT] Failed to dispatch credit note email task for "
                                    f"invoice {invoice_id}: {email_task_err}",
                                    exc_info=True
                                )
                        else:
                            logger.info(
                                f"[DELETE_ACCOUNT] No email_encryption_key provided, "
                                f"skipping credit note email for invoice {invoice_id}"
                            )

                        refund_success_count += 1

                    # Clean up payment service connections
                    try:
                        await payment_service.close()
                    except Exception:
                        pass

                    logger.info(
                        f"[DELETE_ACCOUNT] Refund processing complete for user {user_id}: "
                        f"{refund_success_count} succeeded, {refund_fail_count} failed"
                    )

            except Exception as e:
                logger.error(f"[DELETE_ACCOUNT] Error processing refunds for user {user_id}: {e}", exc_info=True)
        
        # 10. Delete gift cards (using bulk delete for efficiency)
        try:
            gift_cards = await directus_service.get_items(
                "gift_cards",
                params={"filter": {"purchaser_user_id_hash": {"_eq": user_id_hash}}}
            )
            gift_card_ids = [g.get("id") for g in (gift_cards or []) if g.get("id")]
            if gift_card_ids:
                await directus_service.bulk_delete_items("gift_cards", gift_card_ids)
            
            # Delete redemption records
            redeemed_gift_cards = await directus_service.get_items(
                "redeemed_gift_cards",
                params={"filter": {"user_id_hash": {"_eq": user_id_hash}}}
            )
            redeemed_ids = [r.get("id") for r in (redeemed_gift_cards or []) if r.get("id")]
            if redeemed_ids:
                await directus_service.bulk_delete_items("redeemed_gift_cards", redeemed_ids)
            logger.info(f"[DELETE_ACCOUNT] Deleted {len(gift_card_ids)} gift cards and {len(redeemed_ids)} redemption records for user {user_id}")
        except Exception as e:
            logger.error(f"[DELETE_ACCOUNT] Error deleting gift cards for user {user_id}: {e}", exc_info=True)
        
        # 11. Delete invoices (using bulk delete for efficiency)
        try:
            invoices = await directus_service.get_items(
                "invoices",
                params={"filter": {"user_id_hash": {"_eq": user_id_hash}}}
            )
            # TODO: Delete invoice PDFs from S3 using encrypted_s3_object_key for each invoice
            invoice_ids = [i.get("id") for i in (invoices or []) if i.get("id")]
            if invoice_ids:
                await directus_service.bulk_delete_items("invoices", invoice_ids)
            logger.info(f"[DELETE_ACCOUNT] Deleted {len(invoice_ids)} invoices for user {user_id}")
        except Exception as e:
            logger.error(f"[DELETE_ACCOUNT] Error deleting invoices for user {user_id}: {e}", exc_info=True)
        
        logger.info(f"[DELETE_ACCOUNT] Phase 2 complete for user {user_id}")
        
        # ===== PHASE 3: User Content & Data =====
        logger.info(f"[DELETE_ACCOUNT] Phase 3: Deleting user content for user {user_id}")
        
        # 12. Delete chats, messages, embeds (using bulk delete for efficiency)
        # Note: chats uses hashed_user_id, not user_id
        try:
            # Get all chats for this user (using hashed_user_id)
            chats = await directus_service.get_items(
                "chats",
                params={"filter": {"hashed_user_id": {"_eq": user_id_hash}}}
            )
            
            chat_ids = [c.get("id") for c in (chats or []) if c.get("id")]
            all_message_ids = []
            all_embed_ids = []
            
            # Collect all message and embed IDs for all chats
            for chat_id in chat_ids:
                # Collect messages for this chat
                messages = await directus_service.get_items(
                    "messages",
                    params={"filter": {"chat_id": {"_eq": chat_id}}}
                )
                message_ids = [m.get("id") for m in (messages or []) if m.get("id")]
                all_message_ids.extend(message_ids)
                
                # Collect embeds for this chat (using hashed_chat_id)
                hashed_chat_id = hashlib.sha256(chat_id.encode()).hexdigest()
                embeds = await directus_service.get_items(
                    "embeds",
                    params={"filter": {"hashed_chat_id": {"_eq": hashed_chat_id}}}
                )
                embed_ids = [e.get("id") for e in (embeds or []) if e.get("id")]
                all_embed_ids.extend(embed_ids)
            
            # Also collect any orphaned embeds by hashed_user_id (embeds not linked to a chat)
            orphaned_embeds = await directus_service.get_items(
                "embeds",
                params={"filter": {"hashed_user_id": {"_eq": user_id_hash}}}
            )
            orphaned_embed_ids = [e.get("id") for e in (orphaned_embeds or []) if e.get("id")]
            all_embed_ids.extend(orphaned_embed_ids)
            
            # Remove duplicates from embed IDs (in case of overlap between chat embeds and orphaned embeds)
            all_embed_ids = list(set(all_embed_ids))
            
            # Bulk delete: messages first, then embeds, then chats (respecting foreign key constraints)
            if all_message_ids:
                await directus_service.bulk_delete_items("messages", all_message_ids)
            if all_embed_ids:
                await directus_service.bulk_delete_items("embeds", all_embed_ids)
            if chat_ids:
                await directus_service.bulk_delete_items("chats", chat_ids)
            
            logger.info(f"[DELETE_ACCOUNT] Deleted {len(chat_ids)} chats, {len(all_message_ids)} messages, and {len(all_embed_ids)} embeds for user {user_id}")
        except Exception as e:
            logger.error(f"[DELETE_ACCOUNT] Error deleting user content for user {user_id}: {e}", exc_info=True)
        
        # 13. Delete usage data (using bulk delete for efficiency)
        try:
            usage_entries = await directus_service.get_items(
                "usage",
                params={"filter": {"user_id_hash": {"_eq": user_id_hash}}}
            )
            usage_ids = [e.get("id") for e in (usage_entries or []) if e.get("id")]
            if usage_ids:
                await directus_service.bulk_delete_items("usage", usage_ids)
            
            # Delete usage summaries (monthly and daily) - bulk delete each collection
            for collection in [
                "usage_monthly_chat_summaries", "usage_monthly_api_key_summaries", "usage_monthly_app_summaries",
                "usage_daily_chat_summaries", "usage_daily_app_summaries", "usage_daily_api_key_summaries"
            ]:
                summaries = await directus_service.get_items(
                    collection,
                    params={"filter": {"user_id_hash": {"_eq": user_id_hash}}}
                )
                summary_ids = [s.get("id") for s in (summaries or []) if s.get("id")]
                if summary_ids:
                    await directus_service.bulk_delete_items(collection, summary_ids)
            logger.info(f"[DELETE_ACCOUNT] Deleted usage data for user {user_id}")
        except Exception as e:
            logger.error(f"[DELETE_ACCOUNT] Error deleting usage data for user {user_id}: {e}", exc_info=True)
        
        # 14. Delete app settings & memories (using bulk delete for efficiency)
        try:
            app_settings = await directus_service.get_items(
                "user_app_settings_and_memories",
                params={"filter": {"hashed_user_id": {"_eq": user_id_hash}}}
            )
            setting_ids = [s.get("id") for s in (app_settings or []) if s.get("id")]
            if setting_ids:
                await directus_service.bulk_delete_items("user_app_settings_and_memories", setting_ids)
            logger.info(f"[DELETE_ACCOUNT] Deleted app settings/memories for user {user_id}")
        except Exception as e:
            logger.error(f"[DELETE_ACCOUNT] Error deleting app settings for user {user_id}: {e}", exc_info=True)
        
        # 15. Delete drafts (using bulk delete for efficiency)
        try:
            drafts = await directus_service.get_items(
                "drafts",
                params={"filter": {"hashed_user_id": {"_eq": user_id_hash}}}
            )
            draft_ids = [d.get("id") for d in (drafts or []) if d.get("id")]
            if draft_ids:
                await directus_service.bulk_delete_items("drafts", draft_ids)
            logger.info(f"[DELETE_ACCOUNT] Deleted {len(draft_ids)} drafts for user {user_id}")
        except Exception as e:
            logger.error(f"[DELETE_ACCOUNT] Error deleting drafts for user {user_id}: {e}", exc_info=True)
        
        # 16. Delete new chat suggestions (using bulk delete for efficiency)
        try:
            suggestions = await directus_service.get_items(
                "new_chat_suggestions",
                params={"filter": {"hashed_user_id": {"_eq": user_id_hash}}}
            )
            suggestion_ids = [s.get("id") for s in (suggestions or []) if s.get("id")]
            if suggestion_ids:
                await directus_service.bulk_delete_items("new_chat_suggestions", suggestion_ids)
            logger.info(f"[DELETE_ACCOUNT] Deleted {len(suggestion_ids)} new chat suggestions for user {user_id}")
        except Exception as e:
            logger.error(f"[DELETE_ACCOUNT] Error deleting new chat suggestions for user {user_id}: {e}", exc_info=True)
        
        # 17. Delete embed keys (using bulk delete for efficiency)
        try:
            embed_keys = await directus_service.get_items(
                "embed_keys",
                params={"filter": {"hashed_user_id": {"_eq": user_id_hash}}}
            )
            embed_key_ids = [k.get("id") for k in (embed_keys or []) if k.get("id")]
            if embed_key_ids:
                await directus_service.bulk_delete_items("embed_keys", embed_key_ids)
            logger.info(f"[DELETE_ACCOUNT] Deleted {len(embed_key_ids)} embed keys for user {user_id}")
        except Exception as e:
            logger.error(f"[DELETE_ACCOUNT] Error deleting embed keys for user {user_id}: {e}", exc_info=True)
        
        # 18. Delete credit notes (using bulk delete for efficiency)
        try:
            credit_notes = await directus_service.get_items(
                "credit_notes",
                params={"filter": {"user_id_hash": {"_eq": user_id_hash}}}
            )
            # TODO: Delete credit note PDFs from S3 using encrypted_s3_object_key for each credit note
            credit_note_ids = [c.get("id") for c in (credit_notes or []) if c.get("id")]
            if credit_note_ids:
                await directus_service.bulk_delete_items("credit_notes", credit_note_ids)
            logger.info(f"[DELETE_ACCOUNT] Deleted {len(credit_note_ids)} credit notes for user {user_id}")
        except Exception as e:
            logger.error(f"[DELETE_ACCOUNT] Error deleting credit notes for user {user_id}: {e}", exc_info=True)
        
        # 19. Delete creator income records (if user was a creator) - using bulk delete
        try:
            creator_income = await directus_service.get_items(
                "creator_income",
                params={"filter": {"hashed_creator_user_id": {"_eq": user_id_hash}}}
            )
            income_ids = [i.get("id") for i in (creator_income or []) if i.get("id")]
            if income_ids:
                await directus_service.bulk_delete_items("creator_income", income_ids)
            logger.info(f"[DELETE_ACCOUNT] Deleted {len(income_ids)} creator income records for user {user_id}")
        except Exception as e:
            logger.error(f"[DELETE_ACCOUNT] Error deleting creator income for user {user_id}: {e}", exc_info=True)
        
        logger.info(f"[DELETE_ACCOUNT] Phase 3 complete for user {user_id}")
        
        # ===== PHASE 4: Cache Cleanup =====
        logger.info(f"[DELETE_ACCOUNT] Phase 4: Cleaning cache for user {user_id}")
        
        try:
            client = await cache_service.client
            if client:
                # Delete user profile cache
                await client.delete(f"user_profile:{user_id}")
                
                # Delete user device caches
                device_keys = await client.keys(f"user_device:{user_id}:*")
                if device_keys:
                    await client.delete(*device_keys)
                
                # Delete user device list
                await client.delete(f"user_device_list:{user_id}")
                
                # Delete chat-related caches
                await client.delete(f"user:{user_id}:chat_ids_versions")
                await client.delete(f"user:{user_id}:active_chats_lru")
                await client.delete(f"user:{user_id}:chats")
                
                # Delete chat-specific caches
                chat_keys = await client.keys(f"user:{user_id}:chat:*")
                if chat_keys:
                    await client.delete(*chat_keys)
                
                # Delete app settings/memories cache
                app_keys = await client.keys(f"user:{user_id}:chat:*:app:*")
                if app_keys:
                    await client.delete(*app_keys)
                
                # Delete order status cache
                order_keys = await client.keys("order_status:*")
                # Filter by user if possible - simplified for now
                if order_keys:
                    # Note: Would need to check order ownership - simplified
                    pass
            logger.info(f"[DELETE_ACCOUNT] Cache cleanup complete for user {user_id}")
        except Exception as e:
            logger.error(f"[DELETE_ACCOUNT] Error cleaning cache for user {user_id}: {e}", exc_info=True)
        
        logger.info(f"[DELETE_ACCOUNT] Phase 4 complete for user {user_id}")
        
        # ===== PHASE 5: User Record & Compliance =====
        logger.info(f"[DELETE_ACCOUNT] Phase 5: Final deletion and compliance for user {user_id}")
        
        # 17. Compliance logging (already done in endpoint, but log here too)
        try:
            compliance_service.log_account_deletion(
                user_id=user_id,
                deletion_type=deletion_type,
                reason=reason,
                ip_address=ip_address,
                device_fingerprint=device_fingerprint
            )
        except Exception as e:
            logger.warning(f"[DELETE_ACCOUNT] Error logging compliance event: {e}")
        
        # 18. Delete user record (final step)
        try:
            success = await directus_service.delete_user(
                user_id=user_id,
                deletion_type=deletion_type,
                reason=reason,
                ip_address=ip_address,
                device_fingerprint=device_fingerprint
            )
            if success:
                logger.info(f"[DELETE_ACCOUNT] Successfully deleted user record for user {user_id}")
            else:
                logger.error(f"[DELETE_ACCOUNT] Failed to delete user record for user {user_id}")
                return False
        except Exception as e:
            logger.error(f"[DELETE_ACCOUNT] Error deleting user record for user {user_id}: {e}", exc_info=True)
            return False
        
        logger.info(f"[DELETE_ACCOUNT] Account deletion complete for user {user_id}, task_id={task_id}")
        return True
        
    except Exception as e:
        logger.error(f"[DELETE_ACCOUNT] Fatal error during account deletion for user {user_id}: {e}", exc_info=True)
        return False
    finally:
        await directus_service.close()
