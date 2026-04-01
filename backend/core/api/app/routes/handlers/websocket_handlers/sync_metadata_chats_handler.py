# backend/core/api/app/routes/handlers/websocket_handlers/sync_metadata_chats_handler.py
"""
Handler for syncing metadata-only chat records for chats beyond the initial 100.

After Phase 3 syncs the 100 most recent chats with full messages + embeds,
this handler syncs metadata (title, summary, tags, icon, category, chat key)
for up to 900 additional chats (positions 101–1000). This metadata is stored
in IndexedDB on the client and enables search by title, summary, and tags
across ~1000 chats — 10× the previous search coverage.

Messages for these metadata-only chats are NOT included. They load on-demand
when the user opens a specific chat.

Architecture:
- Triggered automatically by the client after Phase 3 completes
- Cache-first: Redis sorted set (chat_ids_versions) with offset 100..999
- Fallback: Directus with offset/limit if cache is empty
- Returns same chat_details format as load_more_chats (reuses _build_chat_wrapper_from_cache)
- Large payload (~1-2MB for 900 chats) sent as a single WS message

See also: docs/architecture/sync.md
"""
import logging
from typing import Dict, Any

from fastapi import WebSocket

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.routes.connection_manager import ConnectionManager

# Reuse the shared utilities from load_more_chats_handler
from .load_more_chats_handler import (
    _get_total_chat_count,
    _build_chat_wrapper_from_cache,
    _fetch_chats_from_directus,
    _fetch_chats_from_directus_paginated,
)

logger = logging.getLogger(__name__)

# Maximum number of metadata-only chats to sync (positions 101–1000)
MAX_METADATA_CHATS = 900


async def handle_sync_metadata_chats(
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
    Sync metadata-only chat records for chats 101–1000.

    Triggered automatically after Phase 3 completes when total_chat_count > 100.
    The client passes the chat IDs it already has locally so we can skip unchanged chats.

    Payload:
        existing_chat_ids (list[str], optional): Chat IDs the client already has in IndexedDB.
            If provided, these chats are excluded from the response to save bandwidth.

    Response:
        type: "sync_metadata_chats_response"
        payload:
            chats: List of metadata-only chat wrappers (same format as load_more_chats)
            total_count: Total number of chats for this user
    """
    _otel_span, _otel_token = None, None
    try:
        from backend.shared.python_utils.tracing.ws_span_helper import start_ws_handler_span
        _otel_span, _otel_token = start_ws_handler_span("sync_metadata_chats", user_id, payload, user_otel_attrs)
    except Exception:
        pass
    try:
        try:
            existing_chat_ids = set(payload.get("existing_chat_ids", []))

            total_count = await _get_total_chat_count(cache_service, user_id, directus_service)
            metadata_chat_count = min(total_count - 100, MAX_METADATA_CHATS) if total_count > 100 else 0

            if metadata_chat_count <= 0:
                logger.info(
                    f"No metadata chats to sync for user {user_id[:8]}...: "
                    f"total={total_count} (need >100)"
                )
                await manager.send_personal_message(
                    {
                        "type": "sync_metadata_chats_response",
                        "payload": {
                            "chats": [],
                            "total_count": total_count,
                        }
                    },
                    user_id,
                    device_fingerprint_hash
                )
                return

            logger.info(
                f"Syncing {metadata_chat_count} metadata chats for user {user_id[:8]}... "
                f"(total={total_count}, existing_on_client={len(existing_chat_ids)})"
            )

            # Fetch chat IDs from Redis sorted set (positions 100..100+metadata_chat_count-1)
            end_index = 100 + metadata_chat_count - 1
            cached_chat_ids = await cache_service.get_chat_ids_versions(
                user_id, start=100, end=end_index, with_scores=False
            )

            chats_to_send = []

            if cached_chat_ids:
                # Skip chats the client already has
                new_chat_ids = [
                    cid for cid in cached_chat_ids
                    if cid not in existing_chat_ids
                ]

                logger.info(
                    f"Metadata sync: {len(cached_chat_ids)} from cache, "
                    f"{len(cached_chat_ids) - len(new_chat_ids)} already on client, "
                    f"{len(new_chat_ids)} to send"
                )

                # Fetch metadata for new chats from cache — batch Redis lookups
                chat_ids_needing_directus = []
                batch_list_items = await cache_service.get_batch_chat_list_item_data(user_id, new_chat_ids)
                batch_versions = await cache_service.get_batch_chat_versions(user_id, new_chat_ids)

                for chat_id in new_chat_ids:
                    cached_list_item = batch_list_items.get(chat_id)
                    cached_versions = batch_versions.get(chat_id)

                    if not cached_list_item:
                        chat_ids_needing_directus.append(chat_id)
                        continue

                    chat_wrapper = _build_chat_wrapper_from_cache(chat_id, cached_list_item, cached_versions)
                    chats_to_send.append(chat_wrapper)

                # Fetch any cache misses from Directus
                if chat_ids_needing_directus:
                    logger.info(
                        f"Metadata sync: Fetching {len(chat_ids_needing_directus)} chats from Directus (cache miss)"
                    )
                    directus_chats = await _fetch_chats_from_directus(
                        directus_service, user_id, chat_ids_needing_directus
                    )
                    chats_to_send.extend(directus_chats)
            else:
                # Cache empty — fall back to Directus with offset/limit
                logger.info(
                    f"Metadata sync: No cached chat IDs, falling back to Directus for user {user_id[:8]}..."
                )
                chats_to_send = await _fetch_chats_from_directus_paginated(
                    directus_service, user_id, 100, metadata_chat_count
                )

                # Filter out chats the client already has
                if existing_chat_ids:
                    chats_to_send = [
                        c for c in chats_to_send
                        if c.get("chat_details", {}).get("id") not in existing_chat_ids
                    ]

            logger.info(
                f"Metadata sync complete for user {user_id[:8]}...: "
                f"sending {len(chats_to_send)} chats (total={total_count})"
            )

            await manager.send_personal_message(
                {
                    "type": "sync_metadata_chats_response",
                    "payload": {
                        "chats": chats_to_send,
                        "total_count": total_count,
                    }
                },
                user_id,
                device_fingerprint_hash
            )

        except Exception as e:
            logger.error(f"Error syncing metadata chats for user {user_id}: {e}", exc_info=True)
            await manager.send_personal_message(
                {
                    "type": "sync_metadata_chats_response",
                    "payload": {
                        "chats": [],
                        "total_count": 0,
                        "error": "Failed to sync metadata chats",
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
