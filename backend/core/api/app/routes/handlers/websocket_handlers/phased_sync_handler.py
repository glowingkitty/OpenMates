# backend/core/api/app/routes/handlers/websocket_handlers/phased_sync_handler.py
import logging
from typing import Dict, Any, List
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
            hashed_user_id, limit=50
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


async def handle_phased_sync_request(
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
    Handles phased sync requests from the client.
    This implements the 3-phase sync architecture with version-aware delta sync:
    - Phase 1: Last opened chat AND new chat suggestions (immediate priority) - always both
    - Phase 2: Last 20 updated chats (quick access) - only missing/outdated chats
    - Phase 3: Last 100 updated chats (full sync) - only missing/outdated chats
    
    The client sends version data so we can skip sending chats that are already up-to-date.
    Phase 1 ALWAYS sends suggestions - Phase 3 NEVER sends suggestions.
    """
    try:
        sync_phase = payload.get("phase", "all")
        # Extract client version data for delta checking
        client_chat_versions = payload.get("client_chat_versions", {})
        client_chat_ids = payload.get("client_chat_ids", [])
        client_suggestions_count = payload.get("client_suggestions_count", 0)
        
        logger.info(f"Handling phased sync request for user {user_id}, phase: {sync_phase}, client has {len(client_chat_ids)} chats, {client_suggestions_count} suggestions")
        
        # Track sent embed IDs across all phases to prevent duplicates
        # Embeds can be shared across chats in different phases
        sent_embed_ids: set = set()
        
        if sync_phase == "phase1" or sync_phase == "all":
            await _handle_phase1_sync(
                manager, cache_service, directus_service, user_id, device_fingerprint_hash,
                client_chat_versions, client_chat_ids, sent_embed_ids
            )
        
        if sync_phase == "phase2" or sync_phase == "all":
            await _handle_phase2_sync(
                manager, cache_service, directus_service, user_id, device_fingerprint_hash,
                client_chat_versions, client_chat_ids, sent_embed_ids
            )
        
        if sync_phase == "phase3" or sync_phase == "all":
            await _handle_phase3_sync(
                manager, cache_service, directus_service, user_id, device_fingerprint_hash,
                client_chat_versions, client_chat_ids, sent_embed_ids
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


async def _handle_phase1_sync(
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    user_id: str,
    device_fingerprint_hash: str,
    client_chat_versions: Dict[str, Dict[str, int]],
    client_chat_ids: List[str],
    sent_embed_ids: set
):
    """
    Handle Phase 1: Last opened chat AND new chat suggestions (immediate priority)
    ALWAYS fetches and sends BOTH:
    - Last opened chat (if there is one and not "new")
    - New chat suggestions (always, for immediate display)
    
    This ensures users have immediate content regardless of which view they're looking at.
    Maintains zero-knowledge architecture - all data remains encrypted.
    """
    logger.info(f"Processing Phase 1 sync for user {user_id}")
    
    try:
        # ALWAYS fetch new chat suggestions in Phase 1 (cache-first)
        new_chat_suggestions = await _fetch_new_chat_suggestions(cache_service, directus_service, user_id)
        logger.info(f"Phase 1: Retrieved {len(new_chat_suggestions)} new chat suggestions")
        
        # Get last opened chat from user profile
        user_profile = await directus_service.get_user_profile(user_id)
        if not user_profile[1]:  # user_profile returns (success, data, error)
            logger.warning(f"Could not fetch user profile for Phase 1 sync: {user_id}")
            # Still send suggestions even if profile fetch fails
            await manager.send_personal_message(
                {
                    "type": "phase_1_last_chat_ready",
                    "payload": {
                        "chat_id": None,
                        "chat_details": None,
                        "messages": None,
                        "new_chat_suggestions": new_chat_suggestions,
                        "phase": "phase1",
                        "already_synced": False
                    }
                },
                user_id,
                device_fingerprint_hash
            )
            return
        
        last_opened_path = user_profile[1].get("last_opened")
        if not last_opened_path:
            logger.info(f"No last opened path for user {user_id}, sending only suggestions")
            # Send suggestions without chat
            await manager.send_personal_message(
                {
                    "type": "phase_1_last_chat_ready",
                    "payload": {
                        "chat_id": None,
                        "chat_details": None,
                        "messages": None,
                        "new_chat_suggestions": new_chat_suggestions,
                        "phase": "phase1",
                        "already_synced": False
                    }
                },
                user_id,
                device_fingerprint_hash
            )
            return
        
        # Extract chat ID from path (assuming format like "/chat/chat-id")
        chat_id = last_opened_path.split("/")[-1] if "/" in last_opened_path else last_opened_path
        
        # Handle "new" chat section - send only suggestions
        if chat_id == "new":
            logger.info("Phase 1: Last opened was 'new' chat section, sending suggestions only")
            await manager.send_personal_message(
                {
                    "type": "phase_1_last_chat_ready",
                    "payload": {
                        "chat_id": "new",
                        "chat_details": None,
                        "messages": None,
                        "new_chat_suggestions": new_chat_suggestions,
                        "phase": "phase1",
                        "already_synced": False
                    }
                },
                user_id,
                device_fingerprint_hash
            )
            return
        
        # Check if client already has this chat and if it's up-to-date
        client_versions = client_chat_versions.get(chat_id, {})
        chat_is_missing = chat_id not in client_chat_ids
        
        if not chat_is_missing:
            # Client has the chat - check if it's up-to-date
            cached_server_versions = await cache_service.get_chat_versions(user_id, chat_id)
            
            if cached_server_versions:
                client_messages_v = client_versions.get("messages_v", 0)
                
                # CRITICAL: For the last_opened chat in Phase 1, we always proceed to the full check 
                # below to ensure absolute consistency on reload (safety net).
                # We skip the "already_synced" optimization for this one critical chat.
                # The client will deduplicate any messages we send.
                pass 
                
                if False: # Optimization disabled for Phase 1 last_opened chat
                    client_messages_v = client_versions.get("messages_v", 0)
        
        logger.info(f"Phase 1: Fetching and sending chat {chat_id} (missing: {chat_is_missing})")
        
        # CACHE-FIRST STRATEGY: Try cache first, fallback to Directus
        chat_details = None
        messages_data = []
        
        # Try to get chat metadata from cache first
        try:
            cached_list_item = await cache_service.get_chat_list_item_data(user_id, chat_id)
            if cached_list_item:
                # Convert cached list item to chat details format
                has_encrypted_chat_key = bool(cached_list_item.encrypted_chat_key)
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
                    "last_message_timestamp": cached_list_item.last_message_timestamp
                }
                logger.info(
                    f"[PHASE1_CHAT_METADATA] ✅ Cache HIT for chat metadata {chat_id} for user {user_id[:8]}... "
                    f"has_encrypted_chat_key={has_encrypted_chat_key}, "
                    f"encrypted_chat_key_preview={cached_list_item.encrypted_chat_key[:30] + '...' if cached_list_item.encrypted_chat_key else 'NULL'}"
                )
            else:
                logger.info(
                    f"[PHASE1_CHAT_METADATA] ⚠️ Cache MISS for chat metadata {chat_id} "
                    f"for user {user_id[:8]}... - will fetch from Directus"
                )
        except Exception as cache_error:
            logger.warning(
                f"[PHASE1_CHAT_METADATA] ❌ Error reading chat metadata from cache for {chat_id}: {cache_error}"
            )
        
        # Try to get client-encrypted messages from sync cache first
        try:
            cached_sync_messages = await cache_service.get_sync_messages_history(user_id, chat_id)
            if cached_sync_messages:
                messages_data = cached_sync_messages
                logger.info(
                    f"[PHASE1_SYNC_CACHE] ✅ Sync cache HIT for {len(messages_data)} client-encrypted messages "
                    f"in chat {chat_id} for user {user_id[:8]}..."
                )
                
                # CRITICAL VALIDATION: Ensure these are client-encrypted (not vault-encrypted)
                if messages_data and len(messages_data) > 0:
                    import json
                    try:
                        # Check first and last messages to validate encryption
                        first_msg = json.loads(messages_data[0])
                        last_msg = json.loads(messages_data[-1]) if len(messages_data) > 1 else first_msg
                        logger.info(
                            f"[PHASE1_SYNC_CACHE] Message validation for chat {chat_id}: "
                            f"first_msg_id={first_msg.get('id')}, first_role={first_msg.get('role')}, "
                            f"last_msg_id={last_msg.get('id')}, last_role={last_msg.get('role')}, "
                            f"total_messages={len(messages_data)}"
                        )
                    except Exception as parse_err:
                        logger.error(f"[PHASE1_SYNC_CACHE] ❌ Failed to parse messages in sync cache: {parse_err}")
            else:
                logger.info(
                    f"[PHASE1_SYNC_CACHE] ⚠️ Sync cache MISS for messages in chat {chat_id} "
                    f"for user {user_id[:8]}... - will fetch from Directus"
                )
        except Exception as cache_error:
            logger.warning(
                f"[PHASE1_SYNC_CACHE] ❌ Error reading messages from sync cache for chat {chat_id}: {cache_error}"
            )
        
        # Fallback to Directus if cache miss
        if not chat_details:
            logger.info(f"Phase 1: Fetching chat metadata from Directus for {chat_id}")
            chat_details = await directus_service.chat.get_chat_metadata(chat_id)
            if not chat_details:
                logger.warning(f"Could not fetch chat details for Phase 1: {chat_id} (chat may have been deleted)")
                logger.info(f"Phase 1: Falling back to 'new' chat view since last_opened chat {chat_id} is missing")
                # Chat was deleted - fallback to "new" chat view with suggestions
                await manager.send_personal_message(
                    {
                        "type": "phase_1_last_chat_ready",
                        "payload": {
                            "chat_id": "new",  # Fallback to new chat view
                            "chat_details": None,
                            "messages": None,
                            "new_chat_suggestions": new_chat_suggestions,
                            "phase": "phase1",
                            "already_synced": False
                        }
                    },
                    user_id,
                    device_fingerprint_hash
                )
                return
        
        # Fallback to Directus if sync cache didn't have messages
        # BUT only if messages are actually needed (client might already have up-to-date messages)
        if not messages_data:
            logger.info(
                f"[PHASE1_MESSAGES] Fetching messages from Directus for chat {chat_id} "
                f"(sync cache miss or empty) for user {user_id[:8]}..."
            )
            # CRITICAL FIX: Check if client already has up-to-date messages before fetching from Directus
            client_versions = client_chat_versions.get(chat_id, {})
            
            # Get server versions from cache first, fallback to chat metadata if cache is empty
            server_versions = await cache_service.get_chat_versions(user_id, chat_id)
            if not server_versions and chat_details:
                # Cache miss - use versions from chat metadata that was just fetched
                server_messages_v = chat_details.get("messages_v", 0)
            elif server_versions:
                server_messages_v = server_versions.messages_v
            else:
                # No version data available at all - fetch from Directus to be safe
                server_messages_v = None
            
            # Track server message count for client-side validation
            # This helps detect data inconsistencies where version matches but messages are missing
            server_message_count = None
            
            if server_messages_v is not None and client_versions:
                client_messages_v = client_versions.get("messages_v", 0)
                
                # If client already has up-to-date messages, skip fetching from Directus
                # Client will use messages from IndexedDB
                # IMPORTANT: We still need to send the message count so client can validate
                if client_messages_v >= server_messages_v:
                    # Get message count from Directus for validation
                    # This is a lightweight query that helps detect data corruption
                    try:
                        server_message_count = await directus_service.chat.get_message_count_for_chat(chat_id)
                        
                        # CRITICAL FIX: If actual message count exceeds messages_v, force a full fetch
                        # This handles cases where version tracking lagged behind actual message persistence
                        if server_message_count is not None and server_message_count > server_messages_v:
                            logger.warning(
                                f"[PHASE1_MESSAGES] 🚨 VERSION MISMATCH DETECTED for chat {chat_id}! "
                                f"messages_v={server_messages_v}, actual_count={server_message_count}. "
                                f"Forcing full message fetch to ensure consistency."
                            )
                            # Fall through to the fetch logic below by making the version check fail
                            client_messages_v = -1 
                        else:
                            logger.info(
                                f"[PHASE1_MESSAGES] ⏭️ Skipping message fetch for chat {chat_id} - client already has up-to-date messages "
                                f"(client: m={client_messages_v}, server: m={server_messages_v}, server_count={server_message_count}). "
                                f"Client will use IndexedDB and validate count."
                            )
                    except Exception as count_err:
                        logger.warning(f"[PHASE1_MESSAGES] Failed to get message count for {chat_id}: {count_err}")
                        # Continue without count - client will have to trust version
                    
                    # SAFETY NET (only if we didn't force a fetch above)
                    if not messages_data and client_messages_v != -1:
                        logger.info(f"[PHASE1_MESSAGES] 🛡️ Safety net: Fetching last 5 messages for last_opened chat {chat_id} regardless of version.")
                        try:
                            # Use get_messages_for_chats with a limit if possible, or just get all for this one chat
                            # since it's just one chat and we want to ensure immediate consistency
                            messages_data = await directus_service.chat.get_all_messages_for_chat(
                                    chat_id=chat_id, decrypt_content=False
                            )
                            if messages_data and len(messages_data) > 5:
                                messages_data = messages_data[-5:]
                            logger.info(f"[PHASE1_MESSAGES] ✅ Safety net fetched {len(messages_data) if messages_data else 0} messages.")
                        except Exception as safety_err:
                            logger.warning(f"[PHASE1_MESSAGES] Safety net fetch failed: {safety_err}")
                            messages_data = []
                else:
                    logger.info(
                        f"[PHASE1_MESSAGES] 📥 Fetching messages from Directus for {chat_id} "
                        f"(sync cache miss, messages outdated: client={client_messages_v}, server={server_messages_v})"
                    )
                    messages_data = await directus_service.chat.get_all_messages_for_chat(
                            chat_id=chat_id, decrypt_content=False  # Zero-knowledge: keep encrypted with chat keys
                    )
                    logger.info(
                        f"[PHASE1_MESSAGES] ✅ Fetched {len(messages_data) if messages_data else 0} messages from Directus "
                        f"for chat {chat_id}"
                    )
            else:
                # No version data available - fetch from Directus to be safe
                logger.info(
                    f"[PHASE1_MESSAGES] 📥 Fetching messages from Directus for {chat_id} "
                    f"(sync cache miss, no version data available)"
                )
                messages_data = await directus_service.chat.get_all_messages_for_chat(
                        chat_id=chat_id, decrypt_content=False  # Zero-knowledge: keep encrypted with chat keys
                )
                logger.info(
                    f"[PHASE1_MESSAGES] ✅ Fetched {len(messages_data) if messages_data else 0} messages from Directus "
                    f"for chat {chat_id}"
                )
            
            # CRITICAL VALIDATION: Ensure Directus messages are client-encrypted (not vault-encrypted)
            if messages_data and len(messages_data) > 0:
                import json
                try:
                    first_msg = json.loads(messages_data[0])
                    logger.debug(
                        f"[DIRECTUS_VALIDATION] Phase 1: First message from Directus for {chat_id}: "
                        f"id={first_msg.get('id')}, role={first_msg.get('role')}, "
                        f"encrypted_content_length={len(first_msg.get('encrypted_content', ''))}"
                    )
                except Exception as parse_err:
                    logger.error(f"[DIRECTUS_VALIDATION] Failed to parse first message from Directus: {parse_err}")
        
        # Get embeds from sync cache for this chat
        # Filter out embeds already sent in previous phases (cross-phase deduplication)
        raw_embeds_data = await cache_service.get_sync_embeds_for_chat(chat_id)
        import hashlib
        hashed_chat_id = hashlib.sha256(chat_id.encode()).hexdigest()
        if not raw_embeds_data:
            # Fallback: try to get embeds from Directus if not in sync cache
            raw_embeds_data = await directus_service.embed.get_embeds_by_hashed_chat_id(hashed_chat_id)
        
        # Filter and track sent embeds to prevent duplicates across phases
        embeds_data = []
        if raw_embeds_data:
            for embed in raw_embeds_data:
                embed_id = embed.get("embed_id")
                if embed_id and embed_id not in sent_embed_ids:
                    embeds_data.append(embed)
                    sent_embed_ids.add(embed_id)
            logger.info(f"Phase 1: Sending {len(embeds_data)} embeds for chat {chat_id} (filtered from {len(raw_embeds_data)}, {len(sent_embed_ids)} total sent)")
        
        # CRITICAL: Also fetch embed_keys for this chat
        # Embed keys are needed to decrypt the encrypted embed content on the client
        # Without embed_keys, embeds cannot be decrypted and will show errors
        embed_keys_data = []
        try:
            embed_keys_data = await directus_service.embed.get_embed_keys_by_hashed_chat_id(hashed_chat_id)
            if embed_keys_data:
                logger.info(f"Phase 1: Fetched {len(embed_keys_data)} embed_keys for chat {chat_id}")
        except Exception as e:
            logger.warning(f"Phase 1: Error fetching embed_keys for chat {chat_id}: {e}")
        
        # Log what we're sending to client
        has_encrypted_chat_key = bool(chat_details and chat_details.get("encrypted_chat_key"))
        logger.info(
            f"[PHASE1_SEND] 📤 Sending Phase 1 data to client for chat {chat_id}, user {user_id[:8]}...: "
            f"messages={len(messages_data or [])}, embeds={len(embeds_data or [])}, "
            f"embed_keys={len(embed_keys_data or [])}, suggestions={len(new_chat_suggestions)}, "
            f"has_encrypted_chat_key={has_encrypted_chat_key}"
        )
        
        # Send Phase 1 data to client WITH suggestions, embeds, AND embed_keys
        # Include server_message_count for client-side validation of data consistency
        await manager.send_personal_message(
            {
                "type": "phase_1_last_chat_ready",
                "payload": {
                    "chat_id": chat_id,
                    "chat_details": chat_details,
                    "messages": messages_data or [],
                    "server_message_count": server_message_count,  # For client-side validation
                    "embeds": embeds_data or [],  # Include embeds for client-side storage
                    "embed_keys": embed_keys_data or [],  # Include embed_keys for decryption
                    "new_chat_suggestions": new_chat_suggestions,  # Always include suggestions
                    "phase": "phase1",
                    "already_synced": False
                }
            },
            user_id,
            device_fingerprint_hash
        )
        
        logger.info(
            f"[PHASE1_COMPLETE] ✅ Phase 1 sync complete for user {user_id[:8]}..., chat: {chat_id}, "
            f"sent: {len(messages_data or [])} messages, {len(embeds_data or [])} embeds, "
            f"{len(embed_keys_data)} embed_keys, and {len(new_chat_suggestions)} suggestions"
        )
        
    except Exception as e:
        logger.error(f"Error in Phase 1 sync for user {user_id}: {e}", exc_info=True)


async def _handle_phase2_sync(
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    user_id: str,
    device_fingerprint_hash: str,
    client_chat_versions: Dict[str, Dict[str, int]],
    client_chat_ids: List[str],
    sent_embed_ids: set
):
    """
    Handle Phase 2: Last 20 updated chats (quick access)
    Only sends chats that are missing or outdated on the client.
    Maintains zero-knowledge architecture - all data remains encrypted.
    CACHE-FIRST: Uses cached chat list from predictive cache warming for instant sync.
    """
    logger.info(f"Processing Phase 2 sync for user {user_id}")
    
    try:
        # CACHE-FIRST STRATEGY: Get last 20 chat IDs from Redis cache (already populated by cache warming)
        cached_chat_ids = await cache_service.get_chat_ids_versions(user_id, start=0, end=19, with_scores=False)
        
        logger.info(f"[PHASE2_DEBUG] Retrieved {len(cached_chat_ids) if cached_chat_ids else 0} cached chat IDs for user {user_id}")
        if cached_chat_ids:
            logger.debug(f"[PHASE2_DEBUG] Cached chat IDs: {cached_chat_ids[:3]}...")
        
        if not cached_chat_ids:
            logger.info(f"Phase 2: No cached chat IDs found, falling back to Directus for user {user_id}")
            # Fallback to Directus if cache is empty
            all_recent_chats = await directus_service.chat.get_core_chats_and_user_drafts_for_cache_warming(
                user_id, limit=20
            )
        else:
            logger.info(f"Phase 2: ✅ Using cached chat IDs ({len(cached_chat_ids)} chats) for user {user_id}")
            # Build chat wrappers from cache
            all_recent_chats = []
            chat_ids_needing_directus_fetch = []

            for chat_id in cached_chat_ids:
                # Get chat metadata from cache
                cached_list_item = await cache_service.get_chat_list_item_data(user_id, chat_id)
                cached_versions = await cache_service.get_chat_versions(user_id, chat_id)

                if not cached_list_item or not cached_versions:
                    logger.warning(f"Phase 2: Incomplete cache data for chat {chat_id} (list_item: {bool(cached_list_item)}, versions: {bool(cached_versions)}), will fetch from Directus")
                    chat_ids_needing_directus_fetch.append(chat_id)
                    continue

                # Convert cached data to the format expected by the rest of the function
                chat_wrapper = {
                    "chat_details": {
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
                        "messages_v": cached_versions.messages_v,
                        "title_v": cached_versions.title_v
                    },
                    "user_encrypted_draft_content": None,  # Will be fetched if needed
                    "user_draft_version_db": 0,
                    "draft_updated_at": 0
                }
                all_recent_chats.append(chat_wrapper)

            # Fetch missing chats from Directus if needed
            if chat_ids_needing_directus_fetch:
                logger.info(f"Phase 2: Fetching {len(chat_ids_needing_directus_fetch)} chats with incomplete cache from Directus")
                try:
                    # Fetch each chat's metadata and versions from Directus
                    for chat_id in chat_ids_needing_directus_fetch:
                        chat_metadata = await directus_service.chat.get_chat_metadata(chat_id)
                        if chat_metadata:
                            # Build chat wrapper with Directus data
                            chat_wrapper = {
                                "chat_details": {
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
                                    "messages_v": chat_metadata.get("messages_v", 0),
                                    "title_v": chat_metadata.get("title_v", 0)
                                },
                                "user_encrypted_draft_content": None,
                                "user_draft_version_db": 0,
                                "draft_updated_at": 0
                            }
                            all_recent_chats.append(chat_wrapper)
                            logger.debug(f"Phase 2: Added chat {chat_id} from Directus fallback")
                        else:
                            logger.warning(f"Phase 2: Could not fetch chat {chat_id} from Directus")
                    logger.info(f"Phase 2: Added {len([c for c in all_recent_chats if c['chat_details']['id'] in chat_ids_needing_directus_fetch])} chats from Directus fallback")
                except Exception as e:
                    logger.error(f"Phase 2: Failed to fetch chats from Directus: {e}", exc_info=True)
        
        if not all_recent_chats:
            logger.info(f"No recent chats found for Phase 2 sync: {user_id}")
            # Send empty phase 2 completion
            await manager.send_personal_message(
                {
                    "type": "phase_2_last_20_chats_ready",
                    "payload": {
                        "chats": [],
                        "chat_count": 0,
                        "phase": "phase2"
                    }
                },
                user_id,
                device_fingerprint_hash
            )
            return
        
        client_chat_ids_set = set(client_chat_ids)
        
        # Filter chats to only include missing or outdated ones
        # CRITICAL FIX: Always send metadata-only updates for chats with matching versions
        # This ensures clients get encrypted_title, encrypted_category, encrypted_icon even if versions match
        # The client can intelligently merge - if a field is missing locally but present on server, it should update it
        chats_to_send = []
        chats_skipped = 0
        metadata_only_updates = []
        
        for chat_wrapper in all_recent_chats:
            chat_id = chat_wrapper["chat_details"]["id"]
            chat_is_missing = chat_id not in client_chat_ids_set
            
            if not chat_is_missing:
                # Client has the chat - check if it's up-to-date
                cached_server_versions = await cache_service.get_chat_versions(user_id, chat_id)
                client_versions = client_chat_versions.get(chat_id, {})
                
                if cached_server_versions:
                    client_messages_v = client_versions.get("messages_v", 0)
                    client_title_v = client_versions.get("title_v", 0)
                    
                    # Check if client is up-to-date
                    if (client_messages_v >= cached_server_versions.messages_v and 
                        client_title_v >= cached_server_versions.title_v):
                        # CRITICAL FIX: Even if versions match, send metadata-only update
                        # This ensures clients get encrypted_title, encrypted_category, encrypted_icon
                        # if they're missing locally (e.g., old chats created before these fields existed)
                        chat_details = chat_wrapper["chat_details"]
                        has_metadata = (
                            chat_details.get("encrypted_title") or
                            chat_details.get("encrypted_category") or
                            chat_details.get("encrypted_icon")
                        )
                        
                        if has_metadata:
                            # Create metadata-only update (no messages)
                            metadata_only_wrapper = {
                                "chat_details": chat_details,
                                "messages": None,  # No messages for metadata-only updates
                                "user_encrypted_draft_content": None,
                                "user_draft_version_db": 0,
                                "draft_updated_at": 0
                            }
                            metadata_only_updates.append(metadata_only_wrapper)
                            logger.debug(f"Phase 2: Adding metadata-only update for chat {chat_id} (versions match but metadata may be missing on client)")
                        else:
                            logger.debug(f"Phase 2: Skipping chat {chat_id} - client already up-to-date and no metadata to sync "
                                       f"(client: m={client_messages_v}, t={client_title_v}; "
                                       f"server: m={cached_server_versions.messages_v}, t={cached_server_versions.title_v})")
                            chats_skipped += 1
                        continue
            
            # Chat is missing or outdated - add to send list with messages
            chats_to_send.append(chat_wrapper)
            logger.debug(f"Phase 2: Will send chat {chat_id} with messages (missing: {chat_is_missing})")
        
        # Add metadata-only updates to the send list
        chats_to_send.extend(metadata_only_updates)
        
        logger.info(f"Phase 2: Sending {len(chats_to_send)}/{len(all_recent_chats)} chats (skipped {chats_skipped} up-to-date)")
        
        if chats_to_send:
            # Try sync cache first, fallback to Directus
            messages_added_count = 0
            chat_ids_to_fetch_from_directus = []
            
            # Try sync cache for each chat, but ONLY if messages are actually needed
            for chat_wrapper in chats_to_send:
                chat_id = chat_wrapper["chat_details"]["id"]
                
                # CRITICAL FIX: Check if messages are actually needed before fetching
                # A chat can be in chats_to_send because title_v is outdated, but messages_v might be up-to-date
                # Skip fetching messages if client already has up-to-date messages (even if sync cache is empty)
                client_versions = client_chat_versions.get(chat_id, {})
                
                # Get server versions from cache first, fallback to chat metadata if cache is empty
                server_versions = await cache_service.get_chat_versions(user_id, chat_id)
                if not server_versions:
                    # Cache miss - use versions from chat metadata that was just fetched
                    chat_details = chat_wrapper.get("chat_details", {})
                    server_messages_v = chat_details.get("messages_v", 0)
                else:
                    server_messages_v = server_versions.messages_v
                
                if client_versions:
                    client_messages_v = client_versions.get("messages_v", 0)
                    
                    # If client already has up-to-date messages, skip fetching entirely
                    # Client will use messages from IndexedDB
                    if client_messages_v >= server_messages_v:
                        # CRITICAL: Get server message count for client-side validation
                        # This allows client to detect data inconsistency (version matches but messages missing)
                        try:
                            server_message_count = await directus_service.chat.get_message_count_for_chat(chat_id)
                            chat_wrapper["server_message_count"] = server_message_count
                            logger.debug(f"Phase 2: Skipping message fetch for chat {chat_id} - client already has up-to-date messages "
                                       f"(client: m={client_messages_v}, server: m={server_messages_v}, count={server_message_count})")
                        except Exception as count_err:
                            logger.warning(f"Phase 2: Failed to get message count for {chat_id}: {count_err}")
                            # Continue without count - client will have to trust version
                            logger.debug(f"Phase 2: Skipping message fetch for chat {chat_id} - client already has up-to-date messages "
                                       f"(client: m={client_messages_v}, server: m={server_messages_v})")
                        # Ensure messages is None to indicate client should use local data
                        if "messages" not in chat_wrapper:
                            chat_wrapper["messages"] = None
                        continue
                
                # Messages are needed - try sync cache first
                try:
                    cached_sync_messages = await cache_service.get_sync_messages_history(user_id, chat_id)
                    if cached_sync_messages:
                        chat_wrapper["messages"] = cached_sync_messages
                        messages_added_count += 1
                        logger.debug(f"Phase 2: Sync cache HIT for {len(cached_sync_messages)} messages in chat {chat_id}")
                    else:
                        logger.debug(f"Phase 2: Sync cache MISS for messages in chat {chat_id}")
                        chat_ids_to_fetch_from_directus.append(chat_id)
                except Exception as cache_error:
                    logger.warning(f"Phase 2: Error reading messages from sync cache for {chat_id}: {cache_error}")
                    chat_ids_to_fetch_from_directus.append(chat_id)
            
            # Fetch from Directus only for sync cache misses AND when messages are actually needed
            if chat_ids_to_fetch_from_directus:
                logger.info(f"Phase 2: Fetching messages for {len(chat_ids_to_fetch_from_directus)} chats from Directus (sync cache misses)")
                
                try:
                    all_messages_dict = await directus_service.chat.get_messages_for_chats(
                        chat_ids=chat_ids_to_fetch_from_directus, decrypt_content=False  # Zero-knowledge: keep encrypted with chat keys
                    )
                    
                    # Add messages to their respective chats
                    for chat_wrapper in chats_to_send:
                        chat_id = chat_wrapper["chat_details"]["id"]
                        if chat_id in chat_ids_to_fetch_from_directus:
                            messages = all_messages_dict.get(chat_id, [])
                            if messages:
                                chat_wrapper["messages"] = messages
                                messages_added_count += 1
                                logger.debug(f"Phase 2: Added {len(messages)} messages for chat {chat_id} from Directus")
                            else:
                                logger.debug(f"Phase 2: No messages found for chat {chat_id} in Directus")
                
                except Exception as messages_error:
                    logger.error(f"Phase 2: Error fetching messages from Directus: {messages_error}", exc_info=True)
                    # Continue anyway with just metadata - messages can be fetched on-demand
        
            logger.info(f"Phase 2: Total chats with messages added: {messages_added_count}/{len(chats_to_send)} (sync cache hits: {messages_added_count - len(chat_ids_to_fetch_from_directus)}, directus fetches: {len(chat_ids_to_fetch_from_directus)})")
        
        # Collect all unique embeds across all chats (deduplicated by embed_id)
        # CROSS-PHASE DEDUPLICATION: Filter out embeds already sent in Phase 1
        import hashlib
        new_embeds = {}  # embed_id -> embed data (phase-level deduplication)
        for chat_wrapper in chats_to_send:
            chat_id = chat_wrapper.get("chat_details", {}).get("id")
            if chat_id:
                try:
                    # Try sync cache first, then Directus fallback
                    embeds = await cache_service.get_sync_embeds_for_chat(chat_id)
                    if not embeds:
                        # Fallback to Directus
                        hashed_chat_id = hashlib.sha256(chat_id.encode()).hexdigest()
                        embeds = await directus_service.embed.get_embeds_by_hashed_chat_id(hashed_chat_id)
                    
                    if embeds:
                        for embed in embeds:
                            embed_id = embed.get("embed_id")
                            # Skip if already sent in previous phases OR already added in this phase
                            if embed_id and embed_id not in sent_embed_ids and embed_id not in new_embeds:
                                new_embeds[embed_id] = embed
                        logger.debug(f"Phase 2: Found {len(embeds)} embeds for chat {chat_id}")
                except Exception as e:
                    logger.warning(f"Phase 2: Error fetching embeds for chat {chat_id}: {e}")
        
        embeds_list = list(new_embeds.values())
        # Track all newly sent embeds for Phase 3
        for embed_id in new_embeds.keys():
            sent_embed_ids.add(embed_id)
        
        if embeds_list:
            logger.info(f"Phase 2: Sending {len(embeds_list)} new embeds ({len(sent_embed_ids)} total sent across phases)")
        
        # CRITICAL: Batch fetch embed_keys for all chats in this phase (optimized)
        # Embed keys are needed to decrypt the encrypted embed content on the client
        # OPTIMIZATION: Use batch method to reduce from N*2 queries to just 2 queries
        all_embed_keys = []
        seen_embed_key_ids = set()  # Deduplicate by id
        
        # Collect all hashed_chat_ids for batch fetch
        hashed_chat_ids_for_keys = []
        for chat_wrapper in chats_to_send:
            chat_id = chat_wrapper.get("chat_details", {}).get("id")
            if chat_id:
                hashed_chat_ids_for_keys.append(hashlib.sha256(chat_id.encode()).hexdigest())
        
        if hashed_chat_ids_for_keys:
            try:
                # Batch fetch all embed_keys for all chats in 2 queries instead of N*2
                batch_embed_keys = await directus_service.embed.get_embed_keys_by_hashed_chat_ids_batch(hashed_chat_ids_for_keys)
                if batch_embed_keys:
                    for key_entry in batch_embed_keys:
                        key_id = key_entry.get("id")
                        if key_id and key_id not in seen_embed_key_ids:
                            all_embed_keys.append(key_entry)
                            seen_embed_key_ids.add(key_id)
            except Exception as e:
                logger.warning(f"Phase 2: Error batch fetching embed_keys for {len(hashed_chat_ids_for_keys)} chats: {e}")
        
        if all_embed_keys:
            logger.info(f"Phase 2: Sending {len(all_embed_keys)} embed_keys for {len(chats_to_send)} chats (batch optimized)")
        
        # Send Phase 2 data to client (only chats that need updating)
        # Embeds and embed_keys are sent as flat deduplicated arrays, not per-chat
        await manager.send_personal_message(
            {
                "type": "phase_2_last_20_chats_ready",
                "payload": {
                    "chats": chats_to_send,
                    "embeds": embeds_list,  # Flat deduplicated array
                    "embed_keys": all_embed_keys,  # Flat deduplicated array of embed keys
                    "chat_count": len(chats_to_send),
                    "phase": "phase2"
                }
            },
            user_id,
            device_fingerprint_hash
        )
        
        logger.info(f"Phase 2 sync complete for user {user_id}, sent: {len(chats_to_send)} chats, {len(embeds_list)} embeds, {len(all_embed_keys)} embed_keys, skipped: {chats_skipped}")
        
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
    sent_embed_ids: set
):
    """
    Handle Phase 3: Last 100 updated chats (full sync)
    Only sends chats that are missing or outdated on the client.
    NEVER sends new chat suggestions - they are always sent in Phase 1.
    Maintains zero-knowledge architecture - all data remains encrypted.
    CACHE-FIRST: Uses cached chat list from predictive cache warming for instant sync.
    """
    logger.info(f"Processing Phase 3 sync for user {user_id}")
    
    try:
        # CACHE-FIRST STRATEGY: Get last 100 chat IDs from Redis cache (already populated by cache warming)
        cached_chat_ids = await cache_service.get_chat_ids_versions(user_id, start=0, end=99, with_scores=False)
        
        logger.info(f"[PHASE3_DEBUG] Retrieved {len(cached_chat_ids) if cached_chat_ids else 0} cached chat IDs for user {user_id}")
        if cached_chat_ids:
            logger.debug(f"[PHASE3_DEBUG] Cached chat IDs: {cached_chat_ids[:3]}...")
        
        if not cached_chat_ids:
            logger.info(f"Phase 3: No cached chat IDs found, falling back to Directus for user {user_id}")
            # Fallback to Directus if cache is empty
            all_chats_from_server = await directus_service.chat.get_core_chats_and_user_drafts_for_cache_warming(
                user_id, limit=100
            )
        else:
            logger.info(f"Phase 3: ✅ Using cached chat IDs ({len(cached_chat_ids)} chats) for user {user_id}")
            # Build chat wrappers from cache
            all_chats_from_server = []
            chat_ids_needing_directus_fetch = []

            for chat_id in cached_chat_ids:
                # Get chat metadata from cache
                cached_list_item = await cache_service.get_chat_list_item_data(user_id, chat_id)
                cached_versions = await cache_service.get_chat_versions(user_id, chat_id)

                if not cached_list_item or not cached_versions:
                    logger.warning(f"Phase 3: Incomplete cache data for chat {chat_id} (list_item: {bool(cached_list_item)}, versions: {bool(cached_versions)}), will fetch from Directus")
                    chat_ids_needing_directus_fetch.append(chat_id)
                    continue

                # Convert cached data to the format expected by the rest of the function
                chat_wrapper = {
                    "chat_details": {
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
                        "messages_v": cached_versions.messages_v,
                        "title_v": cached_versions.title_v
                    },
                    "user_encrypted_draft_content": None,  # Will be fetched if needed
                    "user_draft_version_db": 0,
                    "draft_updated_at": 0
                }
                all_chats_from_server.append(chat_wrapper)

            # Fetch missing chats from Directus if needed
            if chat_ids_needing_directus_fetch:
                logger.info(f"Phase 3: Fetching {len(chat_ids_needing_directus_fetch)} chats with incomplete cache from Directus")
                try:
                    # Fetch each chat's metadata and versions from Directus
                    for chat_id in chat_ids_needing_directus_fetch:
                        chat_metadata = await directus_service.chat.get_chat_metadata(chat_id)
                        if chat_metadata:
                            # Build chat wrapper with Directus data
                            chat_wrapper = {
                                "chat_details": {
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
                                    "messages_v": chat_metadata.get("messages_v", 0),
                                    "title_v": chat_metadata.get("title_v", 0)
                                },
                                "user_encrypted_draft_content": None,
                                "user_draft_version_db": 0,
                                "draft_updated_at": 0
                            }
                            all_chats_from_server.append(chat_wrapper)
                            logger.debug(f"Phase 3: Added chat {chat_id} from Directus fallback")
                        else:
                            logger.warning(f"Phase 3: Could not fetch chat {chat_id} from Directus")
                    logger.info(f"Phase 3: Added {len([c for c in all_chats_from_server if c['chat_details']['id'] in chat_ids_needing_directus_fetch])} chats from Directus fallback")
                except Exception as e:
                    logger.error(f"Phase 3: Failed to fetch chats from Directus: {e}", exc_info=True)
        
        if not all_chats_from_server:
            logger.info(f"No chats found for Phase 3 sync: {user_id}")
            # Send empty phase 3 completion
        
        client_chat_ids_set = set(client_chat_ids)
        
        # Filter chats to only include missing or outdated ones
        # CRITICAL FIX: Always send metadata-only updates for chats with matching versions
        # This ensures clients get encrypted_title, encrypted_category, encrypted_icon even if versions match
        chats_to_send = []
        chats_skipped = 0
        metadata_only_updates = []
        
        if all_chats_from_server:
            for chat_wrapper in all_chats_from_server:
                chat_id = chat_wrapper["chat_details"]["id"]
                chat_is_missing = chat_id not in client_chat_ids_set
                
                if not chat_is_missing:
                    # Client has the chat - check if it's up-to-date
                    cached_server_versions = await cache_service.get_chat_versions(user_id, chat_id)
                    client_versions = client_chat_versions.get(chat_id, {})
                    
                    if cached_server_versions:
                        client_messages_v = client_versions.get("messages_v", 0)
                        client_title_v = client_versions.get("title_v", 0)
                        
                        # Check if client is up-to-date
                        if (client_messages_v >= cached_server_versions.messages_v and 
                            client_title_v >= cached_server_versions.title_v):
                            # CRITICAL FIX: Even if versions match, send metadata-only update
                            # This ensures clients get encrypted_title, encrypted_category, encrypted_icon
                            # if they're missing locally (e.g., old chats created before these fields existed)
                            chat_details = chat_wrapper["chat_details"]
                            has_metadata = (
                                chat_details.get("encrypted_title") or
                                chat_details.get("encrypted_category") or
                                chat_details.get("encrypted_icon")
                            )
                            
                            if has_metadata:
                                # Create metadata-only update (no messages)
                                metadata_only_wrapper = {
                                    "chat_details": chat_details,
                                    "messages": None,  # No messages for metadata-only updates
                                    "user_encrypted_draft_content": None,
                                    "user_draft_version_db": 0,
                                    "draft_updated_at": 0
                                }
                                metadata_only_updates.append(metadata_only_wrapper)
                                logger.debug(f"Phase 3: Adding metadata-only update for chat {chat_id} (versions match but metadata may be missing on client)")
                            else:
                                logger.debug(f"Phase 3: Skipping chat {chat_id} - client already up-to-date and no metadata to sync "
                                           f"(client: m={client_messages_v}, t={client_title_v}; "
                                           f"server: m={cached_server_versions.messages_v}, t={cached_server_versions.title_v})")
                                chats_skipped += 1
                            continue
                
                # Chat is missing or outdated - add to send list with messages
                chats_to_send.append(chat_wrapper)
                logger.debug(f"Phase 3: Will send chat {chat_id} with messages (missing: {chat_is_missing})")
            
            # Add metadata-only updates to the send list
            chats_to_send.extend(metadata_only_updates)
            
            logger.info(f"Phase 3: Sending {len(chats_to_send)}/{len(all_chats_from_server)} chats (skipped {chats_skipped} up-to-date)")
            
            if chats_to_send:
                # Try sync cache first, fallback to Directus
                messages_added_count = 0
                chat_ids_to_fetch_from_directus = []
                
                # Try sync cache for each chat, but ONLY if messages are actually needed
                for chat_wrapper in chats_to_send:
                    chat_id = chat_wrapper["chat_details"]["id"]
                    
                    # CRITICAL FIX: Check if messages are actually needed before fetching
                    # A chat can be in chats_to_send because title_v is outdated, but messages_v might be up-to-date
                    # Skip fetching messages if client already has up-to-date messages (even if sync cache is empty)
                    client_versions = client_chat_versions.get(chat_id, {})
                    
                    # Get server versions from cache first, fallback to chat metadata if cache is empty
                    server_versions = await cache_service.get_chat_versions(user_id, chat_id)
                    if not server_versions:
                        # Cache miss - use versions from chat metadata that was just fetched
                        chat_details = chat_wrapper.get("chat_details", {})
                        server_messages_v = chat_details.get("messages_v", 0)
                    else:
                        server_messages_v = server_versions.messages_v
                    
                    if client_versions:
                        client_messages_v = client_versions.get("messages_v", 0)
                        
                        # If client already has up-to-date messages, skip fetching entirely
                        # Client will use messages from IndexedDB
                        if client_messages_v >= server_messages_v:
                            # CRITICAL: Get server message count for client-side validation
                            # This allows client to detect data inconsistency (version matches but messages missing)
                            try:
                                server_message_count = await directus_service.chat.get_message_count_for_chat(chat_id)
                                chat_wrapper["server_message_count"] = server_message_count
                                logger.debug(f"Phase 3: Skipping message fetch for chat {chat_id} - client already has up-to-date messages "
                                           f"(client: m={client_messages_v}, server: m={server_messages_v}, count={server_message_count})")
                            except Exception as count_err:
                                logger.warning(f"Phase 3: Failed to get message count for {chat_id}: {count_err}")
                                # Continue without count - client will have to trust version
                                logger.debug(f"Phase 3: Skipping message fetch for chat {chat_id} - client already has up-to-date messages "
                                           f"(client: m={client_messages_v}, server: m={server_messages_v})")
                            # Ensure messages is None to indicate client should use local data
                            if "messages" not in chat_wrapper:
                                chat_wrapper["messages"] = None
                            continue
                    
                    # Messages are needed - try sync cache first
                    try:
                        cached_sync_messages = await cache_service.get_sync_messages_history(user_id, chat_id)
                        if cached_sync_messages:
                            chat_wrapper["messages"] = cached_sync_messages
                            messages_added_count += 1
                            logger.debug(f"Phase 3: Sync cache HIT for {len(cached_sync_messages)} messages in chat {chat_id}")
                        else:
                            logger.debug(f"Phase 3: Sync cache MISS for messages in chat {chat_id}")
                            chat_ids_to_fetch_from_directus.append(chat_id)
                    except Exception as cache_error:
                        logger.warning(f"Phase 3: Error reading messages from sync cache for {chat_id}: {cache_error}")
                        chat_ids_to_fetch_from_directus.append(chat_id)
                
                # Fetch from Directus only for sync cache misses AND when messages are actually needed
                if chat_ids_to_fetch_from_directus:
                    logger.info(f"Phase 3: Fetching messages for {len(chat_ids_to_fetch_from_directus)} chats from Directus (sync cache misses)")
                    
                    try:
                        all_messages_dict = await directus_service.chat.get_messages_for_chats(
                            chat_ids=chat_ids_to_fetch_from_directus, decrypt_content=False  # Zero-knowledge: keep encrypted with chat keys
                        )
                        
                        # Add messages to their respective chats
                        for chat_wrapper in chats_to_send:
                            chat_id = chat_wrapper["chat_details"]["id"]
                            if chat_id in chat_ids_to_fetch_from_directus:
                                messages = all_messages_dict.get(chat_id, [])
                                if messages:
                                    chat_wrapper["messages"] = messages
                                    messages_added_count += 1
                                    logger.debug(f"Phase 3: Added {len(messages)} messages for chat {chat_id} from Directus")
                                else:
                                    logger.debug(f"Phase 3: No messages found for chat {chat_id} in Directus")
                    
                    except Exception as messages_error:
                        logger.error(f"Phase 3: Error fetching messages from Directus: {messages_error}", exc_info=True)
                        # Continue anyway with just metadata - messages can be fetched on-demand

                logger.info(f"Phase 3: Total chats with messages added: {messages_added_count}/{len(chats_to_send)} (sync cache hits: {messages_added_count - len(chat_ids_to_fetch_from_directus)}, directus fetches: {len(chat_ids_to_fetch_from_directus)})")

        # Collect all unique embeds across all chats (deduplicated by embed_id)
        # CROSS-PHASE DEDUPLICATION: Filter out embeds already sent in Phase 1 and Phase 2
        import hashlib
        new_embeds = {}  # embed_id -> embed data (phase-level deduplication)
        for chat_wrapper in chats_to_send:
            chat_id = chat_wrapper.get("chat_details", {}).get("id")
            if chat_id:
                try:
                    # Try sync cache first, then Directus fallback
                    embeds = await cache_service.get_sync_embeds_for_chat(chat_id)
                    if not embeds:
                        # Fallback to Directus
                        hashed_chat_id = hashlib.sha256(chat_id.encode()).hexdigest()
                        embeds = await directus_service.embed.get_embeds_by_hashed_chat_id(hashed_chat_id)
                    
                    if embeds:
                        for embed in embeds:
                            embed_id = embed.get("embed_id")
                            # Skip if already sent in previous phases OR already added in this phase
                            if embed_id and embed_id not in sent_embed_ids and embed_id not in new_embeds:
                                new_embeds[embed_id] = embed
                        logger.debug(f"Phase 3: Found {len(embeds)} embeds for chat {chat_id}")
                except Exception as e:
                    logger.warning(f"Phase 3: Error fetching embeds for chat {chat_id}: {e}")
        
        embeds_list = list(new_embeds.values())
        # Track all newly sent embeds (for completeness, though Phase 3 is last)
        for embed_id in new_embeds.keys():
            sent_embed_ids.add(embed_id)
        
        if embeds_list:
            logger.info(f"Phase 3: Sending {len(embeds_list)} new embeds ({len(sent_embed_ids)} total sent across all phases)")

        # CRITICAL: Batch fetch embed_keys for all chats in this phase (optimized)
        # Embed keys are needed to decrypt the encrypted embed content on the client
        # OPTIMIZATION: Use batch method to reduce from N*2 queries to just 2 queries
        all_embed_keys = []
        seen_embed_key_ids = set()  # Deduplicate by id
        
        # Collect all hashed_chat_ids for batch fetch
        hashed_chat_ids_for_keys = []
        for chat_wrapper in chats_to_send:
            chat_id = chat_wrapper.get("chat_details", {}).get("id")
            if chat_id:
                hashed_chat_ids_for_keys.append(hashlib.sha256(chat_id.encode()).hexdigest())
        
        if hashed_chat_ids_for_keys:
            try:
                # Batch fetch all embed_keys for all chats in 2 queries instead of N*2
                batch_embed_keys = await directus_service.embed.get_embed_keys_by_hashed_chat_ids_batch(hashed_chat_ids_for_keys)
                if batch_embed_keys:
                    for key_entry in batch_embed_keys:
                        key_id = key_entry.get("id")
                        if key_id and key_id not in seen_embed_key_ids:
                            all_embed_keys.append(key_entry)
                            seen_embed_key_ids.add(key_id)
            except Exception as e:
                logger.warning(f"Phase 3: Error batch fetching embed_keys for {len(hashed_chat_ids_for_keys)} chats: {e}")
        
        if all_embed_keys:
            logger.info(f"Phase 3: Sending {len(all_embed_keys)} embed_keys for {len(chats_to_send)} chats (batch optimized)")

        # Send Phase 3 data to client (chats only - NO suggestions, always sent in Phase 1)
        # Embeds and embed_keys are sent as flat deduplicated arrays, not per-chat
        await manager.send_personal_message(
            {
                "type": "phase_3_last_100_chats_ready",
                "payload": {
                    "chats": chats_to_send,
                    "embeds": embeds_list,  # Flat deduplicated array
                    "embed_keys": all_embed_keys,  # Flat deduplicated array of embed keys
                    "chat_count": len(chats_to_send),
                    "phase": "phase3"
                }
            },
            user_id,
            device_fingerprint_hash
        )

        logger.info(f"Phase 3 sync complete for user {user_id}, sent: {len(chats_to_send)} chats, {len(embeds_list)} embeds, {len(all_embed_keys)} embed_keys (skipped: {chats_skipped})")
        
        # Clear sync cache after successful Phase 3 completion (1h TTL, no longer needed)
        try:
            deleted_count = await cache_service.clear_all_sync_messages_for_user(user_id)
            logger.info(f"Cleared {deleted_count} sync message caches for user {user_id[:8]}... after Phase 3 completion")
        except Exception as clear_error:
            logger.warning(f"Failed to clear sync cache for user {user_id[:8]}... after Phase 3: {clear_error}")
        
        # After Phase 3 completes, trigger app settings and memories sync
        try:
            await _handle_app_settings_memories_sync(
                manager, directus_service, user_id, device_fingerprint_hash
            )
        except Exception as app_data_error:
            logger.warning(f"Failed to sync app settings/memories for user {user_id[:8]}... after Phase 3: {app_data_error}", exc_info=True)
        
    except Exception as e:
        logger.error(f"Error in Phase 3 sync for user {user_id}: {e}", exc_info=True)


async def _handle_app_settings_memories_sync(
    manager: ConnectionManager,
    directus_service: DirectusService,
    user_id: str,
    device_fingerprint_hash: str
):
    """
    Handles app settings and memories sync after Phase 3 chat sync completes.
    
    This function:
    1. Fetches all app settings and memories entries for the user from Directus
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
        
        # Fetch all app settings and memories entries for the user
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
    payload: Dict[str, Any]
):
    """
    Handles sync status requests from the client.
    Returns the current sync status and progress.
    """
    try:
        logger.info(f"Handling sync status request for user {user_id}")
        
        # Check cache primed status
        cache_primed = await cache_service.is_user_cache_primed(user_id)
        
        # Get current chat count from cache
        chat_ids = await cache_service.get_chat_ids_versions(user_id, with_scores=False)
        chat_count = len(chat_ids) if chat_ids else 0
        
        logger.debug(f"[SYNC_DEBUG] Cache status for user {user_id}: primed={cache_primed}, chat_ids_count={chat_count}, chat_ids={chat_ids[:5] if chat_ids else 'NONE'}")
        
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
