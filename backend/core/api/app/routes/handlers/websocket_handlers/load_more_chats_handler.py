# backend/core/api/app/routes/handlers/websocket_handlers/load_more_chats_handler.py
"""
Handler for loading additional older chats beyond the initial 100 synced via Phase 3.

The client requests batches of 20 older chats on demand (via "Show more" button).
These chats are returned as metadata-only (no messages) — messages are fetched
on-demand when the user opens a specific chat. The client stores these in memory
only (not IndexedDB) to prevent storage limit issues.

Architecture:
- Uses authoritative scoped Directus pagination for every offset
- Redis is sparse and must never determine positions in the full chat list
- Returns metadata + encrypted_chat_key per chat (needed for sidebar display)
- Does NOT return messages (loaded on-demand via get_chat_messages)
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import TYPE_CHECKING, Dict, Any, List, Optional

from fastapi import WebSocket

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.routes.connection_manager import ConnectionManager

if TYPE_CHECKING:
    from backend.core.api.app.services.directus import DirectusService

logger = logging.getLogger(__name__)


async def handle_load_more_chats(
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    encryption_service: EncryptionService,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any],
    user_otel_attrs: dict = None,):
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
    _otel_span, _otel_token = None, None
    try:
        from backend.shared.python_utils.tracing.ws_span_helper import start_ws_handler_span
        _otel_span, _otel_token = start_ws_handler_span("load_more_chats", user_id, payload, user_otel_attrs)
    except Exception:
        pass
    try:
        try:
            offset = payload.get("offset", 100)
            limit = min(payload.get("limit", 20), 50)  # Cap at 50 to prevent abuse
            raw_team_id = payload.get("team_id")
            team_id = raw_team_id if isinstance(raw_team_id, str) and raw_team_id else None
            context_epoch = payload.get("context_epoch")
            if team_id:
                await directus_service.team.require_team_role(
                    team_id,
                    user_id,
                    {"owner", "admin", "member", "viewer"},
                )
        
            logger.info(f"Loading more chats for user {user_id[:8]}...: offset={offset}, limit={limit}")
        
            # Get total chat count (Redis + Directus fallback for accuracy)
            total_count = await _get_total_chat_count(
                cache_service,
                user_id,
                directus_service,
                team_id=team_id,
            )
        
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
                            "offset": offset,
                            "team_id": team_id,
                            "context_epoch": context_epoch,
                        }
                    },
                    user_id,
                    device_fingerprint_hash
                )
                return
        
            # The Redis index is a sparse warm cache (and includes draft-only
            # IDs), not a complete ordered account inventory. Its offsets cannot
            # address the authoritative list, even when it contains some rows.
            chats_to_send = await _fetch_chats_from_directus_paginated(
                directus_service, user_id, offset, limit, team_id=team_id, cache_service=cache_service
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
                        "offset": offset,
                        "team_id": team_id,
                        "context_epoch": context_epoch,
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
                        "error": "Failed to load more chats",
                        "team_id": payload.get("team_id"),
                        "context_epoch": payload.get("context_epoch"),
                    }
                },
                user_id,
                device_fingerprint_hash
            )



    finally:
        if _otel_span is not None:
            try:
                from backend.shared.python_utils.tracing.ws_span_helper import end_ws_handler_span as _end_span
                _end_span(_otel_span, _otel_token)
            except Exception:
                pass
async def _get_total_chat_count(
    cache_service: CacheService,
    user_id: str,
    directus_service: Optional[DirectusService] = None,
    team_id: Optional[str] = None,
) -> int:
    """Count the same persisted scope used for offset pagination."""
    if directus_service is None:
        raise ValueError("Authoritative chat pagination requires Directus")
    return await directus_service.chat.get_user_chat_count(user_id, team_id=team_id)


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
        "encrypted_share_cta_text": cached_list_item.encrypted_share_cta_text,
        "encrypted_chat_tags": cached_list_item.encrypted_chat_tags,
        "encrypted_follow_up_request_suggestions": cached_list_item.encrypted_follow_up_request_suggestions,
        "encrypted_top_recommended_apps_for_chat": cached_list_item.encrypted_top_recommended_apps_for_chat,
        "encrypted_quick_tip_slugs": cached_list_item.encrypted_quick_tip_slugs,
        "encrypted_shared_short_url": cached_list_item.encrypted_shared_short_url,
        "encrypted_active_focus_id": cached_list_item.encrypted_active_focus_id,
        "encrypted_auto_speak_response": cached_list_item.encrypted_auto_speak_response,
        "last_message_timestamp": cached_list_item.last_message_timestamp,
        "pinned": cached_list_item.pinned,
        "is_shared": cached_list_item.is_shared,
        "is_private": cached_list_item.is_private,
    }
    
    # Add version info if available (helps client determine if it needs to fetch messages)
    if cached_versions:
        chat_details["messages_v"] = cached_versions.messages_v
        chat_details["title_v"] = cached_versions.title_v
        chat_details["metadata_v"] = (
            cached_versions.metadata_v
            if cached_versions.metadata_v or cached_versions.title_v == 0
            else cached_versions.title_v
        )
    
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
    hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
    try:
        for chat_id in chat_ids:
            chat_data = await directus_service.chat.get_chat_metadata(chat_id)
            if not chat_data:
                continue
            if chat_data.get("hashed_user_id") != hashed_user_id or chat_data.get("hashed_team_id"):
                logger.warning("Skipping Directus chat metadata outside the requesting Personal scope")
                continue
            chats.append({
                "chat_details": chat_data,
                "messages": None,
                "server_message_count": None,
            })
    except Exception as e:
        logger.error(f"Error fetching chats from Directus for user {user_id[:8]}...: {e}", exc_info=True)
    return chats


async def _fetch_chats_from_directus_paginated(
    directus_service: DirectusService,
    user_id: str,
    offset: int,
    limit: int,
    team_id: Optional[str] = None,
    cache_service: Optional[CacheService] = None,
) -> List[Dict[str, Any]]:
    """Fetch an authoritative metadata page in the requested account/team scope."""
    try:
        all_chats = await directus_service.chat.get_core_chats_and_user_drafts_for_cache_warming(
            user_id, limit=limit, offset=offset, team_id=team_id
        )
        # Directus returns user-owned draft ciphertext beside chat_details.
        # Normalize it before discarding that wrapper, exactly as startup sync
        # does. Page size/order remain the authoritative scoped Directus result.
        from .phased_sync_handler import (
            PHASE2_DRAFT_LOOKUP_CONCURRENCY,
            _apply_batched_draft_metadata,
            _apply_cached_draft_override,
        )

        normalized = [
            {**chat, "chat_details": dict(chat.get("chat_details", {}))}
            for chat in all_chats
        ]
        for wrapper in normalized:
            _apply_batched_draft_metadata(wrapper)

        if cache_service is not None:
            # A newer draft or deletion can still be waiting for its Directus
            # write. Reuse the same version/tombstone rule as phased sync, with
            # bounded concurrent Redis reads; no per-chat database reads.
            for start in range(0, len(normalized), PHASE2_DRAFT_LOOKUP_CONCURRENCY):
                await asyncio.gather(*(
                    _apply_cached_draft_override(
                        wrapper["chat_details"], cache_service, user_id,
                        wrapper["chat_details"]["id"],
                    )
                    for wrapper in normalized[start:start + PHASE2_DRAFT_LOOKUP_CONCURRENCY]
                    if wrapper["chat_details"].get("id")
                ))
        return [
            {"chat_details": wrapper["chat_details"], "messages": None, "server_message_count": None}
            for wrapper in normalized
        ]
    except Exception as e:
        logger.error(f"Error fetching paginated chats from Directus for user {user_id[:8]}...: {e}", exc_info=True)
        raise
