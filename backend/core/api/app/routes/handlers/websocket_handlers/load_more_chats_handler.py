# backend/core/api/app/routes/handlers/websocket_handlers/load_more_chats_handler.py
"""
Handler for loading additional older chats beyond the initial 100 synced via Phase 3.

The client requests batches of 20 older chats on demand (via "Show more" button).
These chats are returned as metadata-only (no messages) — messages are fetched
on-demand when the user opens a specific chat. The client stores these in memory
only (not IndexedDB) to prevent storage limit issues.

Architecture:
- Cache-first: Uses Redis sorted set (chat_ids_versions) with offset/limit
- Fallback: Queries Directus with offset/limit if cache is empty
- Returns metadata + encrypted_chat_key per chat (needed for sidebar display)
- Does NOT return messages (loaded on-demand via get_chat_messages)
"""
import logging
from typing import Dict, Any, List

from fastapi import WebSocket

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.routes.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)


async def handle_load_more_chats(
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    encryption_service: EncryptionService,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any]
):
    """
    Handle client request to load more chats beyond the initial 100.
    
    Payload:
        offset (int): Start index in the sorted set (e.g., 100 for chats after initial sync)
        limit (int): Number of chats to fetch (default 20, max 50)
    
    Response:
        type: "load_more_chats_response"
        payload:
            chats: List of chat metadata objects (same format as Phase 2/3 chats, but without messages)
            has_more: Whether there are more chats available beyond this batch
            total_count: Total number of chats for this user
            offset: The offset that was requested (for client-side tracking)
    """
    try:
        offset = payload.get("offset", 100)
        limit = min(payload.get("limit", 20), 50)  # Cap at 50 to prevent abuse
        
        logger.info(f"Loading more chats for user {user_id[:8]}...: offset={offset}, limit={limit}")
        
        # Get total chat count from Redis sorted set
        total_count = await _get_total_chat_count(cache_service, user_id)
        
        if total_count <= offset:
            # No more chats available
            logger.info(f"No more chats for user {user_id[:8]}...: total={total_count}, offset={offset}")
            await manager.send_personal_message(
                {
                    "type": "load_more_chats_response",
                    "payload": {
                        "chats": [],
                        "has_more": False,
                        "total_count": total_count,
                        "offset": offset
                    }
                },
                user_id,
                device_fingerprint_hash
            )
            return
        
        # Fetch chat IDs from cache (sorted by last_edited_overall_timestamp desc)
        end_index = offset + limit - 1  # Redis ZRANGE end is inclusive
        cached_chat_ids = await cache_service.get_chat_ids_versions(
            user_id, start=offset, end=end_index, with_scores=False
        )
        
        chats_to_send = []
        
        if cached_chat_ids:
            logger.info(f"Load more: Using {len(cached_chat_ids)} cached chat IDs for user {user_id[:8]}... (offset={offset})")
            
            # Fetch metadata for each chat from cache
            chat_ids_needing_directus = []
            for chat_id in cached_chat_ids:
                cached_list_item = await cache_service.get_chat_list_item_data(user_id, chat_id)
                cached_versions = await cache_service.get_chat_versions(user_id, chat_id)
                
                if not cached_list_item:
                    chat_ids_needing_directus.append(chat_id)
                    continue
                
                # Build chat wrapper in same format as Phase 2/3 (metadata only, no messages)
                chat_wrapper = _build_chat_wrapper_from_cache(chat_id, cached_list_item, cached_versions)
                chats_to_send.append(chat_wrapper)
            
            # Fetch any missing chats from Directus
            if chat_ids_needing_directus:
                logger.info(f"Load more: Fetching {len(chat_ids_needing_directus)} chats from Directus (cache miss)")
                directus_chats = await _fetch_chats_from_directus(
                    directus_service, user_id, chat_ids_needing_directus
                )
                chats_to_send.extend(directus_chats)
        else:
            # Cache empty — fall back to Directus with offset/limit
            logger.info(f"Load more: No cached chat IDs, falling back to Directus for user {user_id[:8]}...")
            chats_to_send = await _fetch_chats_from_directus_paginated(
                directus_service, user_id, offset, limit
            )
        
        has_more = (offset + len(chats_to_send)) < total_count
        
        logger.info(
            f"Load more complete for user {user_id[:8]}...: "
            f"sent={len(chats_to_send)}, offset={offset}, total={total_count}, has_more={has_more}"
        )
        
        await manager.send_personal_message(
            {
                "type": "load_more_chats_response",
                "payload": {
                    "chats": chats_to_send,
                    "has_more": has_more,
                    "total_count": total_count,
                    "offset": offset
                }
            },
            user_id,
            device_fingerprint_hash
        )
        
    except Exception as e:
        logger.error(f"Error loading more chats for user {user_id}: {e}", exc_info=True)
        # Send error response so client can handle gracefully
        await manager.send_personal_message(
            {
                "type": "load_more_chats_response",
                "payload": {
                    "chats": [],
                    "has_more": False,
                    "total_count": 0,
                    "offset": payload.get("offset", 100),
                    "error": "Failed to load more chats"
                }
            },
            user_id,
            device_fingerprint_hash
        )


async def _get_total_chat_count(cache_service: CacheService, user_id: str) -> int:
    """Get the total number of chats for a user from the Redis sorted set."""
    try:
        client = await cache_service.client
        if not client:
            return 0
        key = cache_service._get_user_chat_ids_versions_key(user_id)
        count = await client.zcard(key)
        return count or 0
    except Exception as e:
        logger.error(f"Error getting total chat count for user {user_id[:8]}...: {e}")
        return 0


def _build_chat_wrapper_from_cache(chat_id: str, cached_list_item, cached_versions) -> Dict[str, Any]:
    """Build a chat metadata wrapper from cached data (same format as Phase 2/3)."""
    chat_details = {
        "id": chat_id,
        "encrypted_title": cached_list_item.title,
        "unread_count": cached_list_item.unread_count,
        "created_at": cached_list_item.created_at,
        "updated_at": cached_list_item.updated_at,
        "encrypted_chat_key": cached_list_item.encrypted_chat_key,
        "encrypted_icon": cached_list_item.encrypted_icon,
        "encrypted_category": cached_list_item.encrypted_category,
        "encrypted_chat_summary": cached_list_item.encrypted_chat_summary,
        "encrypted_chat_tags": cached_list_item.encrypted_chat_tags,
        "encrypted_follow_up_request_suggestions": cached_list_item.encrypted_follow_up_request_suggestions,
        "encrypted_active_focus_id": cached_list_item.encrypted_active_focus_id,
        "last_message_timestamp": cached_list_item.last_message_timestamp,
        "pinned": cached_list_item.pinned,
        "is_shared": cached_list_item.is_shared,
        "is_private": cached_list_item.is_private,
    }
    
    # Add version info if available (helps client determine if it needs to fetch messages)
    if cached_versions:
        chat_details["messages_v"] = cached_versions.get("messages_v", 0)
        chat_details["title_v"] = cached_versions.get("title_v", 0)
    
    return {
        "chat_details": chat_details,
        "messages": None,  # No messages — loaded on-demand when user opens the chat
        "server_message_count": None,
    }


async def _fetch_chats_from_directus(
    directus_service: DirectusService, user_id: str, chat_ids: List[str]
) -> List[Dict[str, Any]]:
    """Fetch specific chats from Directus by their IDs."""
    chats = []
    try:
        for chat_id in chat_ids:
            chat_data = await directus_service.chat.get_chat_metadata(chat_id)
            if chat_data:
                chats.append({
                    "chat_details": chat_data,
                    "messages": None,
                    "server_message_count": None,
                })
    except Exception as e:
        logger.error(f"Error fetching chats from Directus for user {user_id[:8]}...: {e}", exc_info=True)
    return chats


async def _fetch_chats_from_directus_paginated(
    directus_service: DirectusService, user_id: str, offset: int, limit: int
) -> List[Dict[str, Any]]:
    """Fetch chats from Directus with pagination (fallback when cache is empty)."""
    try:
        all_chats = await directus_service.chat.get_core_chats_and_user_drafts_for_cache_warming(
            user_id, limit=limit, offset=offset
        )
        # Convert to the expected format (metadata only, no messages)
        return [
            {
                "chat_details": chat.get("chat_details", {}),
                "messages": None,
                "server_message_count": None,
            }
            for chat in all_chats
        ]
    except Exception as e:
        logger.error(f"Error fetching paginated chats from Directus for user {user_id[:8]}...: {e}", exc_info=True)
        return []
