# backend/core/api/app/routes/handlers/websocket_handlers/phased_sync_handler.py
import logging
import time
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from fastapi import WebSocket

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.routes.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)


async def _fetch_new_chat_suggestions(
    cache_service: CacheService,
    directus_service: DirectusService,
    user_id: str
) -> List[Dict[str, Any]]:
    """
    Helper function to fetch new chat suggestions for a user with cache-first strategy.
    Returns empty list on error to allow sync to continue.
    CACHE-FIRST: Uses cached suggestions from predictive cache warming for instant sync.
    """
    try:
        # Hash user ID for fetching personalized suggestions
        import hashlib
        hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
        
        # CACHE-FIRST STRATEGY: Try cache first
        cached_suggestions = await cache_service.get_new_chat_suggestions(hashed_user_id)
        if cached_suggestions:
            logger.info(f"Phase 1: ✅ Using cached new chat suggestions ({len(cached_suggestions)} suggestions) for user {user_id[:8]}...")
            return cached_suggestions
        
        # Fallback to Directus if cache miss
        logger.info(f"Phase 1: Cache MISS for new chat suggestions, fetching from Directus for user {user_id[:8]}...")
        new_chat_suggestions = await directus_service.chat.get_new_chat_suggestions_for_user(
            hashed_user_id, limit=30
        )
        
        # Cache for future requests
        if new_chat_suggestions:
            await cache_service.set_new_chat_suggestions(hashed_user_id, new_chat_suggestions, ttl=600)
            logger.info(f"Cached {len(new_chat_suggestions)} new chat suggestions for user {user_id[:8]}...")
        
        logger.info(f"Fetched {len(new_chat_suggestions)} new chat suggestions from Directus for user {user_id[:8]}...")
        return new_chat_suggestions
        
    except Exception as e:
        logger.error(f"Error fetching new chat suggestions for user {user_id}: {e}", exc_info=True)
        return []


async def _fetch_daily_inspirations(
    cache_service: CacheService,
    directus_service: DirectusService,
    user_id: str
) -> List[Dict[str, Any]]:
    """
    Fetch daily inspirations for a user with cache-first strategy.

    Mirrors _fetch_new_chat_suggestions in structure. Returns the list of
    encrypted inspiration records for inclusion in the Phase 1 sync payload.

    CACHE-FIRST: Uses the sync cache populated by cache warming (user_cache_tasks).
    Falls back to a direct Directus query on cache miss.

    Returns empty list on error to allow sync to continue.
    """
    try:
        import hashlib
        hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()

        # CACHE-FIRST STRATEGY: Try the sync cache populated during cache warming
        cached_inspirations = await cache_service.get_daily_inspirations_sync(hashed_user_id)
        if cached_inspirations is not None:
            logger.info(
                f"Phase 1: ✅ Using cached daily inspirations "
                f"({len(cached_inspirations)} entries) for user {user_id[:8]}..."
            )
            return cached_inspirations

        # Cache miss — fetch directly from Directus
        logger.info(
            f"Phase 1: Cache MISS for daily inspirations, "
            f"fetching from Directus for user {user_id[:8]}..."
        )
        inspirations = await directus_service.user_daily_inspiration.get_user_inspirations(
            user_id=user_id, limit=10
        )

        # Populate the sync cache for subsequent rapid reconnects
        if inspirations:
            await cache_service.set_daily_inspirations_sync(hashed_user_id, inspirations)
            logger.info(
                f"Cached {len(inspirations)} daily inspirations (sync) for user {user_id[:8]}..."
            )

        logger.info(
            f"Fetched {len(inspirations)} daily inspirations from Directus for user {user_id[:8]}..."
        )
        return inspirations

    except Exception as e:
        logger.error(
            f"Error fetching daily inspirations for user {user_id}: {e}", exc_info=True
        )
        return []


async def handle_phased_sync_request(
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
    Handles phased sync requests from the client.
    This implements the 3-phase sync architecture with version-aware delta sync:
    - Phase 1: Last opened chat AND new chat suggestions (immediate priority) - always both
    - Phase 2: Last 20 updated chats (quick access) - only missing/outdated chats
    - Phase 3: Last 100 updated chats (full sync) - only missing/outdated chats
    
    The client sends version data so we can skip sending chats that are already up-to-date.
    Phase 1 ALWAYS sends suggestions - Phase 3 NEVER sends suggestions.
    """
    _otel_span, _otel_token = None, None
    try:
        from backend.shared.python_utils.tracing.ws_span_helper import start_ws_handler_span
        _otel_span, _otel_token = start_ws_handler_span("phased_sync_request", user_id, payload, user_otel_attrs)
    except Exception:
        pass
    try:
        try:
            sync_phase = payload.get("phase", "all")
            # Extract client version data for delta checking
            client_chat_versions = payload.get("client_chat_versions", {})
            client_chat_ids = payload.get("client_chat_ids", [])
            client_suggestions_count = payload.get("client_suggestions_count", 0)
            # Client sends the embed IDs it already has stored in IndexedDB so the server
            # can skip re-sending those embeds (cross-session deduplication).
            client_embed_ids: set = set(payload.get("client_embed_ids", []))
        
            logger.info(
                f"Handling phased sync request for user {user_id}, phase: {sync_phase}, "
                f"client has {len(client_chat_ids)} chats, {client_suggestions_count} suggestions, "
                f"{len(client_embed_ids)} embed(s) already on device"
            )
        
            # Track sent embed IDs across all phases to prevent duplicates
            # Embeds can be shared across chats in different phases
            sent_embed_ids: set = set()
        
            # Phase 1a: Metadata for last-opened + 10 most recent chats (instant)
            # Returns list of chat IDs so Phase 1b can fetch their content
            phase1_chat_ids: List[str] = []
            if sync_phase == "phase1" or sync_phase == "all":
                phase1_chat_ids = await _handle_phase1_sync(
                    manager, cache_service, directus_service, user_id, device_fingerprint_hash,
                    client_chat_versions, client_chat_ids, sent_embed_ids
                )

            # Phase 1b: Messages + embeds for the Phase 1a chats (separate WS message)
            # Sent after Phase 1a so "continue where you left off" renders without waiting
            if (sync_phase == "phase1" or sync_phase == "all") and phase1_chat_ids:
                await _handle_phase1b_sync(
                    manager, cache_service, directus_service, user_id, device_fingerprint_hash,
                    phase1_chat_ids, client_chat_versions, sent_embed_ids, client_embed_ids
                )

            # Phase 2: Metadata-only for 100 chats (no messages, no embeds)
            if sync_phase == "phase2" or sync_phase == "all":
                await _handle_phase2_sync(
                    manager, cache_service, directus_service, user_id, device_fingerprint_hash,
                    client_chat_versions, client_chat_ids, sent_embed_ids, client_embed_ids
                )

            # Phase 3: Background message sync (chunked batches of 10, no embeds)
            if sync_phase == "phase3" or sync_phase == "all":
                await _handle_phase3_sync(
                    manager, cache_service, directus_service, user_id, device_fingerprint_hash,
                    client_chat_versions, client_chat_ids, sent_embed_ids, client_embed_ids,
                    phase1_chat_ids
                )
        
            # Send sync completion event
            await manager.send_personal_message(
                {
                    "type": "phased_sync_complete",
                    "payload": {
                        "phase": sync_phase,
                        "timestamp": int(datetime.now(timezone.utc).timestamp())
                    }
                },
                user_id,
                device_fingerprint_hash
            )
        
            logger.info(f"Phased sync complete for user {user_id}, phase: {sync_phase}")
        
        except Exception as e:
            logger.error(f"Error handling phased sync for user {user_id}: {e}", exc_info=True)
            try:
                await manager.send_personal_message(
                    {"type": "error", "payload": {"message": "Failed to process phased sync request"}},
                    user_id,
                    device_fingerprint_hash
                )
            except Exception as send_err:
                logger.error(f"Failed to send error message to {user_id}/{device_fingerprint_hash}: {send_err}")



    finally:
        if _otel_span is not None:
            try:
                from backend.shared.python_utils.tracing.ws_span_helper import end_ws_handler_span as _end_span
                _end_span(_otel_span, _otel_token)
            except Exception:
                pass
async def _build_chat_details_from_cache(
    cached_list_item, cached_versions, chat_id: str
) -> Dict[str, Any]:
    """
    Convert cached list item + versions into the chat_details dict format
    used throughout phased sync. Avoids repeating this 20-field mapping everywhere.
    """
    return {
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
        "last_edited_overall_timestamp": cached_list_item.last_message_timestamp,
        "messages_v": cached_versions.messages_v if cached_versions else 0,
        "title_v": cached_versions.title_v if cached_versions else 0,
        "pinned": cached_list_item.pinned,
        "is_shared": cached_list_item.is_shared,
        "is_private": cached_list_item.is_private
    }


def _build_chat_details_from_directus_metadata(
    chat_metadata: Dict[str, Any], chat_id: str
) -> Dict[str, Any]:
    """
    Convert Directus chat metadata into the chat_details dict format.
    """
    return {
        "id": chat_id,
        "encrypted_title": chat_metadata.get("encrypted_title"),
        "unread_count": chat_metadata.get("unread_count", 0),
        "created_at": chat_metadata.get("created_at"),
        "updated_at": chat_metadata.get("updated_at"),
        "encrypted_chat_key": chat_metadata.get("encrypted_chat_key"),
        "encrypted_icon": chat_metadata.get("encrypted_icon"),
        "encrypted_category": chat_metadata.get("encrypted_category"),
        "encrypted_chat_summary": chat_metadata.get("encrypted_chat_summary"),
        "encrypted_chat_tags": chat_metadata.get("encrypted_chat_tags"),
        "encrypted_follow_up_request_suggestions": chat_metadata.get("encrypted_follow_up_request_suggestions"),
        "encrypted_active_focus_id": chat_metadata.get("encrypted_active_focus_id"),
        "last_message_timestamp": chat_metadata.get("last_edited_overall_timestamp"),
        "last_edited_overall_timestamp": chat_metadata.get("last_edited_overall_timestamp"),
        "messages_v": chat_metadata.get("messages_v", 0),
        "title_v": chat_metadata.get("title_v", 0),
        "pinned": chat_metadata.get("pinned"),
        "is_shared": chat_metadata.get("is_shared"),
        "is_private": chat_metadata.get("is_private")
    }


async def _handle_phase1_sync(
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    user_id: str,
    device_fingerprint_hash: str,
    client_chat_versions: Dict[str, Dict[str, int]],
    client_chat_ids: List[str],
    sent_embed_ids: set
) -> List[str]:
    """
    Phase 1a: Metadata-only for last-opened + 10 most recent chats.

    PERFORMANCE OVERHAUL: This phase sends ONLY chat metadata (no messages, no embeds).
    The client decrypts title/icon/category for just these 11 chats (~44 decrypts) and
    renders "continue where you left off" instantly. Messages and embeds arrive in Phase 1b.

    Returns list of chat IDs sent in this phase (used by Phase 1b to fetch content).
    """
    logger.info(f"Processing Phase 1a sync for user {user_id}")

    try:
        import asyncio as _asyncio

        # Run all independent fetches concurrently for minimal latency
        suggestions_task = _fetch_new_chat_suggestions(cache_service, directus_service, user_id)
        inspirations_task = _fetch_daily_inspirations(cache_service, directus_service, user_id)
        recent_ids_task = cache_service.get_chat_ids_versions(user_id, start=0, end=10, with_scores=False)

        new_chat_suggestions, daily_inspirations, recent_chat_ids = await _asyncio.gather(
            suggestions_task, inspirations_task, recent_ids_task
        )
        logger.info(
            f"Phase 1a: Retrieved {len(new_chat_suggestions)} suggestions, "
            f"{len(daily_inspirations)} inspirations, {len(recent_chat_ids) if recent_chat_ids else 0} recent chat IDs"
        )

        # --- Determine last-opened chat ID ---
        last_opened_path = None
        cached_user = await cache_service.get_user_by_id(user_id)
        if cached_user:
            last_opened_path = cached_user.get("last_opened")

        if not last_opened_path:
            user_profile = await directus_service.get_user_profile(user_id)
            if user_profile[1]:
                last_opened_path = user_profile[1].get("last_opened")

        last_opened_id = None
        if last_opened_path:
            raw_id = last_opened_path.split("/")[-1] if "/" in last_opened_path else last_opened_path
            # Skip demo/legal chats and "new" sentinel
            if raw_id and raw_id != "new" and not raw_id.startswith("demo-") and not raw_id.startswith("legal-"):
                last_opened_id = raw_id

        # --- Build list of up to 11 chat IDs (last-opened + 10 most recent) ---
        phase1_chat_ids: List[str] = []
        if last_opened_id:
            phase1_chat_ids.append(last_opened_id)

        if recent_chat_ids:
            for cid in recent_chat_ids:
                if cid not in phase1_chat_ids:
                    phase1_chat_ids.append(cid)
                if len(phase1_chat_ids) >= 11:
                    break

        # If cache returned nothing, try Directus fallback for recent chats
        if not recent_chat_ids and not phase1_chat_ids:
            try:
                fallback_chats = await directus_service.chat.get_core_chats_and_user_drafts_for_cache_warming(
                    user_id, limit=11
                )
                for cw in (fallback_chats or []):
                    cid = cw.get("chat_details", {}).get("id") if isinstance(cw, dict) else None
                    if cid and cid not in phase1_chat_ids:
                        phase1_chat_ids.append(cid)
                    if len(phase1_chat_ids) >= 11:
                        break
            except Exception as e:
                logger.warning(f"Phase 1a: Directus fallback for recent chats failed: {e}")

        # --- No chats at all — send suggestions only ---
        if not phase1_chat_ids:
            logger.info(f"Phase 1a: No chats for user {user_id}, sending suggestions only")
            await manager.send_personal_message(
                {
                    "type": "phase_1_last_chat_ready",
                    "payload": {
                        "chat_id": last_opened_id or ("new" if last_opened_path and "new" in last_opened_path else None),
                        "chat_details": None,
                        "messages": None,
                        "recent_chat_metadata": [],
                        "new_chat_suggestions": new_chat_suggestions,
                        "daily_inspirations": daily_inspirations,
                        "phase": "phase1",
                        "already_synced": False
                    }
                },
                user_id,
                device_fingerprint_hash
            )
            return []

        # --- Batch fetch metadata for all phase1 chats ---
        batch_list_items = await cache_service.get_batch_chat_list_item_data(user_id, phase1_chat_ids)
        batch_versions = await cache_service.get_batch_chat_versions(user_id, phase1_chat_ids)

        # Collect IDs that need Directus fallback
        directus_needed = [
            cid for cid in phase1_chat_ids
            if not batch_list_items.get(cid) or not batch_versions.get(cid)
        ]

        directus_metadata_map: Dict[str, Dict[str, Any]] = {}
        if directus_needed:
            try:
                directus_metadata_map = await directus_service.chat.get_chats_metadata_batch(directus_needed)
            except Exception as e:
                logger.warning(f"Phase 1a: Directus batch metadata fetch failed: {e}")

        # Build chat_details for each chat
        last_chat_details = None
        recent_chat_metadata: List[Dict[str, Any]] = []
        valid_phase1_ids: List[str] = []

        for cid in phase1_chat_ids:
            cached_item = batch_list_items.get(cid)
            cached_ver = batch_versions.get(cid)
            chat_details = None

            if cached_item:
                chat_details = await _build_chat_details_from_cache(cached_item, cached_ver, cid)
            elif cid in directus_metadata_map:
                chat_details = _build_chat_details_from_directus_metadata(directus_metadata_map[cid], cid)
            else:
                # Individual Directus fallback (rare — batch already tried)
                try:
                    single_meta = await directus_service.chat.get_chat_metadata(cid)
                    if single_meta:
                        chat_details = single_meta if isinstance(single_meta, dict) else None
                except Exception:
                    pass

            if not chat_details:
                logger.warning(f"Phase 1a: Could not fetch metadata for chat {cid}, skipping")
                continue

            valid_phase1_ids.append(cid)
            if cid == last_opened_id:
                last_chat_details = chat_details
            else:
                recent_chat_metadata.append(chat_details)

        # If last_opened wasn't found (deleted?), promote first recent to last_chat
        if last_opened_id and not last_chat_details and recent_chat_metadata:
            last_chat_details = recent_chat_metadata.pop(0)
            last_opened_id = last_chat_details["id"]

        # --- Send Phase 1a: metadata only, no messages, no embeds ---
        await manager.send_personal_message(
            {
                "type": "phase_1_last_chat_ready",
                "payload": {
                    "chat_id": last_opened_id or ("new" if last_opened_path and "new" in last_opened_path else None),
                    "chat_details": last_chat_details,
                    "messages": None,
                    "recent_chat_metadata": recent_chat_metadata,
                    "new_chat_suggestions": new_chat_suggestions,
                    "daily_inspirations": daily_inspirations,
                    "phase": "phase1",
                    "already_synced": False
                }
            },
            user_id,
            device_fingerprint_hash
        )

        logger.info(
            f"[PHASE1a_COMPLETE] ✅ Phase 1a sync for user {user_id[:8]}...: "
            f"last_chat={'yes' if last_chat_details else 'no'}, "
            f"recent_metadata={len(recent_chat_metadata)}, "
            f"{len(new_chat_suggestions)} suggestions, {len(daily_inspirations)} inspirations"
        )

        return valid_phase1_ids

    except Exception as e:
        logger.error(f"Error in Phase 1a sync for user {user_id}: {e}", exc_info=True)
        return []


async def _handle_phase1b_sync(
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    user_id: str,
    device_fingerprint_hash: str,
    phase1_chat_ids: List[str],
    client_chat_versions: Dict[str, Dict[str, int]],
    sent_embed_ids: set,
    client_embed_ids: Optional[set] = None
):
    """
    Phase 1b: Messages + embeds for the 11 Phase 1a chats (separate WS message).

    Sent immediately after Phase 1a so the client can render "continue where you left off"
    without waiting for message content. Messages are stored encrypted in IDB — no decryption
    during sync.
    """
    if not phase1_chat_ids:
        return

    logger.info(f"Processing Phase 1b sync for user {user_id}: {len(phase1_chat_ids)} chats")
    phase1b_start = time.perf_counter()

    try:
        import hashlib

        chats_data: List[Dict[str, Any]] = []

        for chat_id in phase1_chat_ids:
            messages_data: List[str] = []

            # Delta sync: skip message fetch if client already has up-to-date messages
            client_versions = client_chat_versions.get(chat_id, {})
            client_messages_v = client_versions.get("messages_v", 0)
            server_versions = await cache_service.get_chat_versions(user_id, chat_id)
            server_messages_v = server_versions.messages_v if server_versions else 0

            should_fetch_messages = True
            server_message_count = None

            if client_messages_v >= server_messages_v and server_messages_v > 0:
                # Validate with actual count to catch version lag
                try:
                    server_message_count = await directus_service.chat.get_message_count_for_chat(chat_id)
                    if server_message_count is not None and server_message_count > server_messages_v:
                        logger.warning(
                            f"[PHASE1b] Version mismatch for {chat_id}: "
                            f"messages_v={server_messages_v}, actual={server_message_count}. Forcing fetch."
                        )
                    else:
                        should_fetch_messages = False
                        logger.debug(f"[PHASE1b] Skipping messages for {chat_id} (up-to-date: v={client_messages_v})")
                except Exception:
                    should_fetch_messages = False

            if should_fetch_messages:
                # Try sync cache first
                try:
                    cached = await cache_service.get_sync_messages_history(user_id, chat_id)
                    if cached:
                        messages_data = cached
                except Exception:
                    pass

                # Fallback to Directus
                if not messages_data:
                    try:
                        messages_data = await directus_service.chat.get_all_messages_for_chat(
                            chat_id=chat_id, decrypt_content=False
                        ) or []
                    except Exception as e:
                        logger.warning(f"[PHASE1b] Failed to fetch messages for {chat_id}: {e}")

                if server_message_count is None:
                    server_message_count = len(messages_data)

            chats_data.append({
                "chat_id": chat_id,
                "messages": messages_data if should_fetch_messages else None,
                "server_message_count": server_message_count or 0
            })

        # Fetch embeds + embed_keys for all Phase 1 chats
        all_embeds: List[Dict[str, Any]] = []
        all_embed_keys: List[Dict[str, Any]] = []
        seen_embed_ids: set = set()
        seen_key_ids: set = set()
        hashed_chat_ids: List[str] = []

        for chat_id in phase1_chat_ids:
            hashed_id = hashlib.sha256(chat_id.encode()).hexdigest()
            hashed_chat_ids.append(hashed_id)

            try:
                raw_embeds = await cache_service.get_sync_embeds_for_chat(chat_id)
                if not raw_embeds:
                    raw_embeds = await directus_service.embed.get_embeds_by_hashed_chat_id(hashed_id)

                if raw_embeds:
                    for embed in raw_embeds:
                        embed_id = embed.get("embed_id")
                        embed_status = embed.get("status")
                        if (embed_id and embed_id not in seen_embed_ids
                                and embed_id not in sent_embed_ids
                                and embed_id not in (client_embed_ids or set())
                                and embed_status not in ("error", "cancelled")):
                            all_embeds.append(embed)
                            seen_embed_ids.add(embed_id)
                            sent_embed_ids.add(embed_id)
            except Exception as e:
                logger.warning(f"[PHASE1b] Error fetching embeds for {chat_id}: {e}")

        # Batch fetch embed_keys
        if hashed_chat_ids:
            try:
                batch_keys = await directus_service.embed.get_embed_keys_by_hashed_chat_ids_batch(hashed_chat_ids)
                if batch_keys:
                    for key_entry in batch_keys:
                        key_id = key_entry.get("id")
                        if key_id and key_id not in seen_key_ids:
                            all_embed_keys.append(key_entry)
                            seen_key_ids.add(key_id)
            except Exception as e:
                logger.warning(f"[PHASE1b] Error batch fetching embed_keys: {e}")

        # Send Phase 1b as separate WS message
        await manager.send_personal_message(
            {
                "type": "phase_1b_chat_content_ready",
                "payload": {
                    "chats": chats_data,
                    "embeds": all_embeds,
                    "embed_keys": all_embed_keys
                }
            },
            user_id,
            device_fingerprint_hash
        )

        phase1b_elapsed = time.perf_counter() - phase1b_start
        messages_total = sum(len(c.get("messages") or []) for c in chats_data)
        logger.info(
            f"[PHASE1b_COMPLETE] ✅ Phase 1b sync for user {user_id[:8]}... in {phase1b_elapsed:.3f}s: "
            f"{len(chats_data)} chats, {messages_total} messages, "
            f"{len(all_embeds)} embeds, {len(all_embed_keys)} embed_keys"
        )

    except Exception as e:
        logger.error(f"Error in Phase 1b sync for user {user_id}: {e}", exc_info=True)


async def _handle_phase2_sync(
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    user_id: str,
    device_fingerprint_hash: str,
    client_chat_versions: Dict[str, Dict[str, int]],
    client_chat_ids: List[str],
    sent_embed_ids: set,
    client_embed_ids: Optional[List[str]] = None
):
    """
    Phase 2: Metadata-only for 100 chats (no messages, no embeds).

    PERFORMANCE OVERHAUL: This phase sends ONLY chat metadata — no messages, no embeds,
    no embed_keys. The client stores encrypted metadata in IDB and decrypts lazily when
    rendering in the sidebar. Messages arrive in Phase 3 (background chunked sync).
    Embeds are fetched on-demand when user opens a chat.

    Includes total_chat_count so the client knows how many chats exist on the server.
    """
    logger.info(f"Processing Phase 2 sync for user {user_id}")
    phase2_start = time.perf_counter()

    try:
        # Expand to 100 chats (was 20)
        cached_chat_ids = await cache_service.get_chat_ids_versions(user_id, start=0, end=99, with_scores=False)

        # Get total chat count — uses Directus as authoritative source since
        # the Redis sorted set only has ~100 entries from cache warming
        from .load_more_chats_handler import _get_total_chat_count
        total_chat_count = await _get_total_chat_count(cache_service, user_id, directus_service)

        logger.info(f"Phase 2: Retrieved {len(cached_chat_ids) if cached_chat_ids else 0} cached chat IDs (total: {total_chat_count})")

        if not cached_chat_ids:
            logger.info("Phase 2: No cached chat IDs, falling back to Directus")
            all_recent_chats = await directus_service.chat.get_core_chats_and_user_drafts_for_cache_warming(
                user_id, limit=100
            )
        else:
            all_recent_chats = []
            chat_ids_needing_directus_fetch = []

            batch_list_items = await cache_service.get_batch_chat_list_item_data(user_id, cached_chat_ids)
            batch_versions = await cache_service.get_batch_chat_versions(user_id, cached_chat_ids)

            for chat_id in cached_chat_ids:
                cached_list_item = batch_list_items.get(chat_id)
                cached_versions = batch_versions.get(chat_id)

                if not cached_list_item or not cached_versions:
                    chat_ids_needing_directus_fetch.append(chat_id)
                    continue

                chat_wrapper = {
                    "chat_details": await _build_chat_details_from_cache(cached_list_item, cached_versions, chat_id)
                }
                all_recent_chats.append(chat_wrapper)

            if chat_ids_needing_directus_fetch:
                logger.info(f"Phase 2: Fetching {len(chat_ids_needing_directus_fetch)} chats from Directus")
                try:
                    batch_metadata = await directus_service.chat.get_chats_metadata_batch(chat_ids_needing_directus_fetch)
                    for chat_id in chat_ids_needing_directus_fetch:
                        chat_metadata = batch_metadata.get(chat_id)
                        if chat_metadata:
                            chat_wrapper = {
                                "chat_details": _build_chat_details_from_directus_metadata(chat_metadata, chat_id)
                            }
                            all_recent_chats.append(chat_wrapper)
                except Exception as e:
                    logger.error(f"Phase 2: Failed to fetch chats from Directus: {e}", exc_info=True)

        if not all_recent_chats:
            logger.info(f"Phase 2: No chats found for user {user_id}")
            await manager.send_personal_message(
                {
                    "type": "phase_2_last_20_chats_ready",
                    "payload": {"chats": [], "chat_count": 0, "total_chat_count": total_chat_count, "phase": "phase2"}
                },
                user_id,
                device_fingerprint_hash
            )
            return

        # Delta sync: skip chats where client already has up-to-date metadata
        client_chat_ids_set = set(client_chat_ids)
        chats_to_send = []
        chats_skipped = 0

        existing_chat_ids = [cw["chat_details"]["id"] for cw in all_recent_chats if cw["chat_details"]["id"] in client_chat_ids_set]
        batch_server_versions = await cache_service.get_batch_chat_versions(user_id, existing_chat_ids) if existing_chat_ids else {}

        for chat_wrapper in all_recent_chats:
            chat_id = chat_wrapper["chat_details"]["id"]

            if chat_id in client_chat_ids_set:
                cached_server_versions = batch_server_versions.get(chat_id)
                client_versions = client_chat_versions.get(chat_id, {})

                if cached_server_versions:
                    client_messages_v = client_versions.get("messages_v", 0)
                    client_title_v = client_versions.get("title_v", 0)
                    chat_details_messages_v = chat_wrapper["chat_details"].get("messages_v", 0)
                    server_messages_v = max(cached_server_versions.messages_v, chat_details_messages_v)
                    server_title_v = cached_server_versions.title_v

                    if client_messages_v >= server_messages_v and client_title_v >= server_title_v:
                        chats_skipped += 1
                        continue

            chats_to_send.append(chat_wrapper)

        logger.info(f"Phase 2: Sending {len(chats_to_send)}/{len(all_recent_chats)} metadata-only chats (skipped {chats_skipped})")

        # Send metadata-only payload (no messages, no embeds, no embed_keys)
        await manager.send_personal_message(
            {
                "type": "phase_2_last_20_chats_ready",
                "payload": {
                    "chats": chats_to_send,
                    "chat_count": len(chats_to_send),
                    "total_chat_count": total_chat_count,
                    "phase": "phase2"
                }
            },
            user_id,
            device_fingerprint_hash
        )

        phase2_elapsed = time.perf_counter() - phase2_start
        logger.info(f"Phase 2 sync complete for user {user_id} in {phase2_elapsed:.3f}s, sent: {len(chats_to_send)} metadata-only chats, skipped: {chats_skipped}")

    except Exception as e:
        logger.error(f"Error in Phase 2 sync for user {user_id}: {e}", exc_info=True)


async def _handle_phase3_sync(
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    user_id: str,
    device_fingerprint_hash: str,
    client_chat_versions: Dict[str, Dict[str, int]],
    client_chat_ids: List[str],
    sent_embed_ids: set,
    client_embed_ids: Optional[List[str]] = None,
    phase1_chat_ids: Optional[List[str]] = None
):
    """
    Phase 3: Background message + embed sync — chunked batches of 10 chats.

    Sends messages AND embeds for up to 100 chats in batches of 10,
    each as a separate WS message to avoid congestion. Skips Phase 1b chats
    (already sent) and chats where client version matches (delta sync).
    Embeds + embed_keys are included per batch so they're available offline in IndexedDB.
    """
    logger.info(f"Processing Phase 3 (background message sync) for user {user_id}")
    phase3_start = time.perf_counter()

    try:
        # Get same 100 chat IDs that Phase 2 used
        cached_chat_ids = await cache_service.get_chat_ids_versions(user_id, start=0, end=99, with_scores=False)

        if not cached_chat_ids:
            # Fallback to Directus
            try:
                fallback = await directus_service.chat.get_core_chats_and_user_drafts_for_cache_warming(user_id, limit=100)
                cached_chat_ids = [
                    cw.get("chat_details", {}).get("id") for cw in (fallback or [])
                    if isinstance(cw, dict) and cw.get("chat_details", {}).get("id")
                ]
            except Exception:
                cached_chat_ids = []

        if not cached_chat_ids:
            logger.info("Phase 3: No chat IDs for background message sync")
            # Still trigger app settings sync
            try:
                await _handle_app_settings_memories_sync(manager, directus_service, user_id, device_fingerprint_hash)
            except Exception:
                pass
            return

        # Skip Phase 1b chats (already have messages)
        phase1_ids_set = set(phase1_chat_ids or [])
        chat_ids_for_messages = [cid for cid in cached_chat_ids if cid not in phase1_ids_set]
        logger.info(f"Phase 3: {len(chat_ids_for_messages)} chats for background message sync (skipped {len(phase1_ids_set)} Phase 1b chats)")

        # Delta sync: filter to only chats needing message updates
        chats_needing_messages: List[str] = []
        batch_versions = await cache_service.get_batch_chat_versions(user_id, chat_ids_for_messages) if chat_ids_for_messages else {}

        for chat_id in chat_ids_for_messages:
            client_versions = client_chat_versions.get(chat_id, {})
            client_messages_v = client_versions.get("messages_v", 0)
            server_ver = batch_versions.get(chat_id)
            server_messages_v = server_ver.messages_v if server_ver else 0

            if client_messages_v < server_messages_v or not client_versions:
                chats_needing_messages.append(chat_id)

        logger.info(f"Phase 3: {len(chats_needing_messages)} chats need message sync (delta-checked)")

        # Send messages + embeds in chunked batches of 10
        import hashlib
        BATCH_SIZE = 10
        total_messages_sent = 0
        total_embeds_sent = 0
        batch_num = 0

        for i in range(0, len(chats_needing_messages), BATCH_SIZE):
            batch_chat_ids = chats_needing_messages[i:i + BATCH_SIZE]
            batch_num += 1
            batch_data: List[Dict[str, Any]] = []

            for chat_id in batch_chat_ids:
                messages_data: List[str] = []

                # Try sync cache first
                try:
                    cached = await cache_service.get_sync_messages_history(user_id, chat_id)
                    if cached:
                        messages_data = cached
                except Exception:
                    pass

                # Fallback to Directus
                if not messages_data:
                    try:
                        messages_data = await directus_service.chat.get_all_messages_for_chat(
                            chat_id=chat_id, decrypt_content=False
                        ) or []
                    except Exception as e:
                        logger.warning(f"Phase 3: Failed to fetch messages for {chat_id}: {e}")

                server_ver = batch_versions.get(chat_id)
                server_messages_v = server_ver.messages_v if server_ver else len(messages_data)

                batch_data.append({
                    "chat_id": chat_id,
                    "messages": messages_data,
                    "server_message_count": len(messages_data),
                    "messages_v": max(server_messages_v, len(messages_data))
                })
                total_messages_sent += len(messages_data)

            # Fetch embeds + embed_keys for this batch so they're available offline
            batch_embeds: List[Dict[str, Any]] = []
            batch_embed_keys: List[Dict[str, Any]] = []
            batch_seen_embed_ids: set = set()
            batch_seen_key_ids: set = set()
            batch_hashed_ids: List[str] = []

            for chat_id in batch_chat_ids:
                hashed_id = hashlib.sha256(chat_id.encode()).hexdigest()
                batch_hashed_ids.append(hashed_id)

                try:
                    raw_embeds = await cache_service.get_sync_embeds_for_chat(chat_id)
                    if not raw_embeds:
                        raw_embeds = await directus_service.embed.get_embeds_by_hashed_chat_id(hashed_id)
                    if raw_embeds:
                        for embed in raw_embeds:
                            embed_id = embed.get("embed_id")
                            embed_status = embed.get("status")
                            if (embed_id and embed_id not in batch_seen_embed_ids
                                    and embed_id not in sent_embed_ids
                                    and embed_id not in (client_embed_ids or set())
                                    and embed_status not in ("error", "cancelled")):
                                batch_embeds.append(embed)
                                batch_seen_embed_ids.add(embed_id)
                                sent_embed_ids.add(embed_id)
                except Exception as e:
                    logger.warning(f"Phase 3: Error fetching embeds for {chat_id}: {e}")

            # Batch fetch embed_keys for this batch's chats
            if batch_hashed_ids:
                try:
                    keys = await directus_service.embed.get_embed_keys_by_hashed_chat_ids_batch(batch_hashed_ids)
                    if keys:
                        for key_entry in keys:
                            key_id = key_entry.get("id")
                            if key_id and key_id not in batch_seen_key_ids:
                                batch_embed_keys.append(key_entry)
                                batch_seen_key_ids.add(key_id)
                except Exception as e:
                    logger.warning(f"Phase 3: Error batch fetching embed_keys: {e}")

            total_embeds_sent += len(batch_embeds)

            # Send each batch as a separate WS message to avoid congestion
            payload_data: Dict[str, Any] = {
                "chats": batch_data,
                "batch_number": batch_num,
                "is_last_batch": (i + BATCH_SIZE >= len(chats_needing_messages))
            }
            # Only include embeds/keys if present (saves bandwidth for chats without embeds)
            if batch_embeds:
                payload_data["embeds"] = batch_embeds
            if batch_embed_keys:
                payload_data["embed_keys"] = batch_embed_keys

            await manager.send_personal_message(
                {
                    "type": "background_message_sync",
                    "payload": payload_data
                },
                user_id,
                device_fingerprint_hash
            )

            logger.debug(
                f"Phase 3: Sent batch {batch_num} ({len(batch_data)} chats, "
                f"{len(batch_embeds)} embeds, {len(batch_embed_keys)} embed_keys)"
            )

        # Clear sync cache after successful completion
        try:
            deleted_count = await cache_service.clear_all_sync_messages_for_user(user_id)
            logger.info(f"Cleared {deleted_count} sync message caches for user {user_id[:8]}...")
        except Exception as clear_error:
            logger.warning(f"Failed to clear sync cache: {clear_error}")

        # Trigger app memories sync
        try:
            await _handle_app_settings_memories_sync(manager, directus_service, user_id, device_fingerprint_hash)
        except Exception as app_data_error:
            logger.warning(f"Failed to sync app settings/memories: {app_data_error}", exc_info=True)

        phase3_elapsed = time.perf_counter() - phase3_start
        logger.info(
            f"Phase 3 complete for user {user_id} in {phase3_elapsed:.3f}s: "
            f"{len(chats_needing_messages)} chats, {total_messages_sent} messages, "
            f"{total_embeds_sent} embeds in {batch_num} batches"
        )

    except Exception as e:
        logger.error(f"Error in Phase 3 sync for user {user_id}: {e}", exc_info=True)


async def _handle_app_settings_memories_sync(
    manager: ConnectionManager,
    directus_service: DirectusService,
    user_id: str,
    device_fingerprint_hash: str
):
    """
    Handles app memories sync after Phase 3 chat sync completes.
    
    This function:
    1. Fetches all app memories entries for the user from Directus
    2. Sends encrypted data via WebSocket "app_settings_memories_sync_ready" event
    3. Client stores encrypted entries in IndexedDB and handles conflict resolution
    
    **Zero-Knowledge Architecture**: Server never decrypts the data - it only forwards
    encrypted entries from Directus to the client. All decryption happens client-side.
    
    **Field Mapping** (Directus -> Client):
    - id: UUID primary key (client-generated)
    - app_id: App identifier (e.g., 'code', 'travel', 'tv')
    - item_key: Entry identifier within a category  
    - item_type: Category/type ID for filtering (e.g., 'preferred_technologies')
    - encrypted_item_json: Client-encrypted JSON data
    - encrypted_app_key: Encrypted app-specific key for device sync
    - created_at, updated_at: Unix timestamps
    - item_version: Version for conflict resolution
    - sequence_number: Optional ordering
    """
    try:
        logger.info(f"[SYNC] Starting app settings/memories sync for user {user_id[:8]}...")
        
        # Fetch all app memories entries for the user
        # Note: This returns encrypted data - server never decrypts it
        # The get_all_user_app_data_raw method now accepts user_id directly and hashes it internally
        all_user_app_data = await directus_service.app_settings_and_memories.get_all_user_app_data_raw(user_id)
        
        if not all_user_app_data:
            logger.info(f"[SYNC] No app settings/memories found for user {user_id[:8]}...")
            # Still send sync event with empty array so client knows sync is complete
            await manager.send_personal_message(
                {
                    "type": "app_settings_memories_sync_ready",
                    "payload": {
                        "entries": [],
                        "entry_count": 0
                    }
                },
                user_id,
                device_fingerprint_hash
            )
            return
        
        # Prepare entries for client (all data is already encrypted)
        # Directus returns fields directly, we just need to forward them to client
        entries = []
        for item_data in all_user_app_data:
            # Include all fields needed for client-side storage and conflict resolution
            # These field names must match what the frontend expects in:
            # - chatSyncServiceHandlersAppSettings.ts (AppSettingsMemoriesSyncReadyPayload interface)
            # - db/appSettingsMemories.ts (AppSettingsMemoriesEntry interface)
            entry = {
                "id": item_data.get("id"),
                "app_id": item_data.get("app_id"),
                "item_key": item_data.get("item_key"),
                "item_type": item_data.get("item_type"),  # Category ID for filtering
                "encrypted_item_json": item_data.get("encrypted_item_json"),
                "encrypted_app_key": item_data.get("encrypted_app_key", ""),
                "created_at": item_data.get("created_at"),
                "updated_at": item_data.get("updated_at"),
                "item_version": item_data.get("item_version", 1),
                "sequence_number": item_data.get("sequence_number")
            }
            entries.append(entry)
        
        # Send encrypted app settings/memories data to client
        await manager.send_personal_message(
            {
                "type": "app_settings_memories_sync_ready",
                "payload": {
                    "entries": entries,
                    "entry_count": len(entries)
                }
            },
            user_id,
            device_fingerprint_hash
        )
        
        logger.info(f"[SYNC] App settings/memories sync complete for user {user_id[:8]}..., sent: {len(entries)} entries")
        
    except Exception as e:
        logger.error(f"[SYNC] Error in app settings/memories sync for user {user_id[:8]}...: {e}", exc_info=True)
        # Don't raise - this is a non-critical sync that shouldn't block Phase 3 completion


async def handle_sync_status_request(
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
    Handles sync status requests from the client.
    Returns the current sync status and progress.
    
    IMPORTANT: If cache is not primed (e.g. TTL expired after device was offline for hours),
    this handler auto-dispatches a cache warming task so the client doesn't get stuck waiting
    forever. The client will receive a cache_primed push event when warming completes.
    """
    _otel_span, _otel_token = None, None
    try:
        from backend.shared.python_utils.tracing.ws_span_helper import start_ws_handler_span
        _otel_span, _otel_token = start_ws_handler_span("sync_status_request", user_id, payload, user_otel_attrs)
    except Exception:
        pass
    try:
        try:
            logger.info(f"Handling sync status request for user {user_id}")
        
            # Check cache primed status
            cache_primed = await cache_service.is_user_cache_primed(user_id)
        
            # Get current chat count from cache
            chat_ids = await cache_service.get_chat_ids_versions(user_id, with_scores=False)
            chat_count = len(chat_ids) if chat_ids else 0
        
            logger.debug(f"[SYNC_DEBUG] Cache status for user {user_id}: primed={cache_primed}, chat_ids_count={chat_count}, chat_ids={chat_ids[:5] if chat_ids else 'NONE'}")
        
            # AUTO-REWARM: If cache is not primed (e.g. primed_flag TTL expired after device was
            # offline for >6 hours), dispatch a new cache warming task. Without this, the client
            # would be stuck forever at "Loading chats..." because:
            # 1. The client only calls /lookup during initial login (not on WebSocket reconnect)
            # 2. /lookup is what normally triggers cache warming
            # 3. The cache_primed push event from the original warming task is long gone
            # This ensures that reconnecting devices always get their cache re-warmed.
            if not cache_primed:
                await _trigger_cache_rewarming_if_needed(cache_service, user_id)
        
            # Send sync status to client
            await manager.send_personal_message(
                {
                    "type": "sync_status_response",
                    "payload": {
                        "is_primed": cache_primed,  # Frontend expects 'is_primed' not 'cache_primed'
                        "chat_count": chat_count,
                        "timestamp": int(datetime.now(timezone.utc).timestamp())
                    }
                },
                user_id,
                device_fingerprint_hash
            )
        
            logger.info(f"Sync status sent for user {user_id}: primed={cache_primed}, chats={chat_count}")
        
        except Exception as e:
            logger.error(f"Error handling sync status for user {user_id}: {e}", exc_info=True)
            try:
                await manager.send_personal_message(
                    {"type": "error", "payload": {"message": "Failed to get sync status"}},
                    user_id,
                    device_fingerprint_hash
                )
            except Exception as send_err:
                logger.error(f"Failed to send error message to {user_id}/{device_fingerprint_hash}: {send_err}")



    finally:
        if _otel_span is not None:
            try:
                from backend.shared.python_utils.tracing.ws_span_helper import end_ws_handler_span as _end_span
                _end_span(_otel_span, _otel_token)
            except Exception:
                pass
async def _trigger_cache_rewarming_if_needed(
    cache_service: CacheService,
    user_id: str
) -> None:
    """
    Dispatches a cache warming Celery task if one isn't already in progress.
    Uses a deduplication flag (5 min TTL) to prevent flooding.
    
    This is the same pattern used by /lookup and login endpoints, but triggered
    from the WebSocket sync status handler for reconnecting devices whose
    cache primed flag has expired.
    """
    try:
        warming_flag = f"cache_warming_in_progress:{user_id}"
        is_warming = await cache_service.get(warming_flag)
        
        if is_warming:
            logger.info(
                f"[SYNC_REWARM] Cache warming already in progress for user {user_id[:8]}... "
                f"(flag exists). Skipping duplicate dispatch."
            )
            return
        
        # Set deduplication flag (5 min TTL, same as /lookup)
        await cache_service.set(warming_flag, "warming", ttl=300)
        
        # Dispatch the Celery task
        from backend.core.api.app.tasks.celery_config import app as celery_app
        
        if celery_app.conf.task_always_eager is False:
            logger.info(
                f"[SYNC_REWARM] Cache not primed for user {user_id[:8]}... "
                f"Dispatching warm_user_cache task (triggered by sync status request on reconnect)."
            )
            celery_app.send_task(
                name='app.tasks.user_cache_tasks.warm_user_cache',
                kwargs={'user_id': user_id, 'last_opened_path_from_user_model': None},
                queue='user_init'
            )
        else:
            # Eager mode (tests) - set primed flag directly
            logger.info(
                f"[SYNC_REWARM] Celery is in eager mode. Setting primed flag directly for user {user_id[:8]}..."
            )
            await cache_service.set_user_cache_primed_flag(user_id)
            
    except Exception as e:
        # Non-blocking: don't let re-warming failure prevent the sync status response
        logger.error(
            f"[SYNC_REWARM] Failed to dispatch cache re-warming for user {user_id[:8]}...: {e}",
            exc_info=True
        )
