# backend/core/api/app/routes/handlers/websocket_handlers/phased_sync_handler.py
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from fastapi import WebSocket

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.routes.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)


async def _fetch_new_chat_suggestions(
    directus_service: DirectusService,
    user_id: str
) -> List[Dict[str, Any]]:
    """
    Helper function to fetch new chat suggestions for a user.
    Returns empty list on error to allow sync to continue.
    """
    try:
        # Hash user ID for fetching personalized suggestions
        import hashlib
        hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
        
        # Fetch latest 50 new chat suggestions
        new_chat_suggestions = await directus_service.chat.get_new_chat_suggestions_for_user(
            hashed_user_id, limit=50
        )
        
        logger.info(f"Fetched {len(new_chat_suggestions)} new chat suggestions for user {user_id}")
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
        
        if sync_phase == "phase1" or sync_phase == "all":
            await _handle_phase1_sync(
                manager, cache_service, directus_service, user_id, device_fingerprint_hash,
                client_chat_versions, client_chat_ids
            )
        
        if sync_phase == "phase2" or sync_phase == "all":
            await _handle_phase2_sync(
                manager, cache_service, directus_service, user_id, device_fingerprint_hash,
                client_chat_versions, client_chat_ids
            )
        
        if sync_phase == "phase3" or sync_phase == "all":
            await _handle_phase3_sync(
                manager, cache_service, directus_service, user_id, device_fingerprint_hash,
                client_chat_versions, client_chat_ids
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
    client_chat_ids: List[str]
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
        # ALWAYS fetch new chat suggestions in Phase 1
        new_chat_suggestions = await _fetch_new_chat_suggestions(directus_service, user_id)
        logger.info(f"Phase 1: Fetched {len(new_chat_suggestions)} new chat suggestions")
        
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
            logger.info(f"Phase 1: Last opened was 'new' chat section, sending suggestions only")
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
            from backend.core.api.app.schemas.chat import CachedChatVersions
            cached_server_versions = await cache_service.get_chat_versions(user_id, chat_id)
            
            if cached_server_versions:
                client_messages_v = client_versions.get("messages_v", 0)
                client_title_v = client_versions.get("title_v", 0)
                
                # Check if client version matches or exceeds server version
                if (client_messages_v >= cached_server_versions.messages_v and 
                    client_title_v >= cached_server_versions.title_v):
                    logger.info(f"Phase 1: Client already has up-to-date version of chat {chat_id} "
                               f"(client: m={client_messages_v}, t={client_title_v}; "
                               f"server: m={cached_server_versions.messages_v}, t={cached_server_versions.title_v}). "
                               f"Skipping data transmission.")
                    
                    # Send empty phase 1 completion with suggestions
                    await manager.send_personal_message(
                        {
                            "type": "phase_1_last_chat_ready",
                            "payload": {
                                "chat_id": chat_id,
                                "chat_details": None,  # Client already has it
                                "messages": None,  # Client already has them
                                "new_chat_suggestions": new_chat_suggestions,  # Always send suggestions
                                "phase": "phase1",
                                "already_synced": True
                            }
                        },
                        user_id,
                        device_fingerprint_hash
                    )
                    return
        
        logger.info(f"Phase 1: Fetching and sending chat {chat_id} (missing: {chat_is_missing})")
        
        # CACHE-FIRST STRATEGY: Try cache first, fallback to Directus
        chat_details = None
        messages_data = []
        
        # Try to get chat metadata from cache first
        try:
            cached_list_item = await cache_service.get_chat_list_item_data(user_id, chat_id)
            if cached_list_item:
                # Convert cached list item to chat details format
                chat_details = {
                    "id": chat_id,
                    "encrypted_title": cached_list_item.title,
                    "unread_count": cached_list_item.unread_count,
                    "created_at": cached_list_item.created_at,
                    "updated_at": cached_list_item.updated_at,
                    "encrypted_chat_key": cached_list_item.encrypted_chat_key,
                    "encrypted_icon": cached_list_item.encrypted_icon,
                    "encrypted_category": cached_list_item.encrypted_category
                }
                logger.info(f"Phase 1: Cache HIT for chat metadata {chat_id}")
            else:
                logger.info(f"Phase 1: Cache MISS for chat metadata {chat_id}")
        except Exception as cache_error:
            logger.warning(f"Phase 1: Error reading chat metadata from cache for {chat_id}: {cache_error}")
        
        # Try to get messages from cache first
        try:
            cached_messages = await cache_service.get_chat_messages_history(user_id, chat_id)
            if cached_messages:
                messages_data = cached_messages
                logger.info(f"Phase 1: Cache HIT for {len(messages_data)} messages in chat {chat_id}")
            else:
                logger.info(f"Phase 1: Cache MISS for messages in chat {chat_id}")
        except Exception as cache_error:
            logger.warning(f"Phase 1: Error reading messages from cache for {chat_id}: {cache_error}")
        
        # Fallback to Directus if cache miss
        if not chat_details:
            logger.info(f"Phase 1: Fetching chat metadata from Directus for {chat_id}")
            chat_details = await directus_service.chat.get_chat_metadata(chat_id)
            if not chat_details:
                logger.warning(f"Could not fetch chat details for Phase 1: {chat_id}")
                # Still send suggestions even if chat fetch fails
                await manager.send_personal_message(
                    {
                        "type": "phase_1_last_chat_ready",
                        "payload": {
                            "chat_id": chat_id,
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
        
        if not messages_data:
            logger.info(f"Phase 1: Fetching messages from Directus for {chat_id}")
            messages_data = await directus_service.chat.get_all_messages_for_chat(
                    chat_id=chat_id, decrypt_content=False  # Zero-knowledge: keep encrypted
            )
        
        # Send Phase 1 data to client WITH suggestions (always)
        await manager.send_personal_message(
            {
                "type": "phase_1_last_chat_ready",
                "payload": {
                    "chat_id": chat_id,
                    "chat_details": chat_details,
                    "messages": messages_data or [],
                    "new_chat_suggestions": new_chat_suggestions,  # Always include suggestions
                    "phase": "phase1",
                    "already_synced": False
                }
            },
            user_id,
            device_fingerprint_hash
        )
        
        logger.info(f"Phase 1 sync complete for user {user_id}, chat: {chat_id}, sent: {len(messages_data or [])} messages and {len(new_chat_suggestions)} suggestions")
        
    except Exception as e:
        logger.error(f"Error in Phase 1 sync for user {user_id}: {e}", exc_info=True)


async def _handle_phase2_sync(
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    user_id: str,
    device_fingerprint_hash: str,
    client_chat_versions: Dict[str, Dict[str, int]],
    client_chat_ids: List[str]
):
    """
    Handle Phase 2: Last 20 updated chats (quick access)
    Only sends chats that are missing or outdated on the client.
    Maintains zero-knowledge architecture - all data remains encrypted.
    """
    logger.info(f"Processing Phase 2 sync for user {user_id}")
    
    try:
        # Get last 20 updated chats from server
        all_recent_chats = await directus_service.chat.get_core_chats_and_user_drafts_for_cache_warming(
            user_id, limit=20
        )
        
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
        
        from backend.core.api.app.schemas.chat import CachedChatVersions
        client_chat_ids_set = set(client_chat_ids)
        
        # Filter chats to only include missing or outdated ones
        chats_to_send = []
        chats_skipped = 0
        
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
                        logger.debug(f"Phase 2: Skipping chat {chat_id} - client already up-to-date "
                                   f"(client: m={client_messages_v}, t={client_title_v}; "
                                   f"server: m={cached_server_versions.messages_v}, t={cached_server_versions.title_v})")
                        chats_skipped += 1
                        continue
            
            # Chat is missing or outdated - add to send list
            chats_to_send.append(chat_wrapper)
            logger.debug(f"Phase 2: Will send chat {chat_id} (missing: {chat_is_missing})")
        
        logger.info(f"Phase 2: Sending {len(chats_to_send)}/{len(all_recent_chats)} chats (skipped {chats_skipped} up-to-date)")
        
        if chats_to_send:
            # CACHE-FIRST STRATEGY: Try cache first for each chat, fallback to Directus
            chat_ids_to_fetch_from_directus = []
            messages_added_count = 0
            
            for chat_wrapper in chats_to_send:
                chat_id = chat_wrapper["chat_details"]["id"]
                messages = []
                
                # Try to get messages from cache first
                try:
                    cached_messages = await cache_service.get_chat_messages_history(user_id, chat_id)
                    if cached_messages:
                        messages = cached_messages
                        chat_wrapper["messages"] = messages
                        messages_added_count += 1
                        logger.debug(f"Phase 2: Cache HIT for {len(messages)} messages in chat {chat_id}")
                    else:
                        logger.debug(f"Phase 2: Cache MISS for messages in chat {chat_id}")
                        chat_ids_to_fetch_from_directus.append(chat_id)
                except Exception as cache_error:
                    logger.warning(f"Phase 2: Error reading messages from cache for {chat_id}: {cache_error}")
                    chat_ids_to_fetch_from_directus.append(chat_id)
            
            # Fetch from Directus only for cache misses
            if chat_ids_to_fetch_from_directus:
                logger.info(f"Phase 2: Fetching messages for {len(chat_ids_to_fetch_from_directus)} chats from Directus (cache misses)")
                
                try:
                    all_messages_dict = await directus_service.chat.get_messages_for_chats(
                        chat_ids=chat_ids_to_fetch_from_directus, decrypt_content=False  # Zero-knowledge: keep encrypted
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
        
            logger.info(f"Phase 2: Total chats with messages added: {messages_added_count}/{len(chats_to_send)} (cache hits: {messages_added_count - len(chat_ids_to_fetch_from_directus)}, directus fetches: {len(chat_ids_to_fetch_from_directus)})")
        
        # Send Phase 2 data to client (only chats that need updating)
        await manager.send_personal_message(
            {
                "type": "phase_2_last_20_chats_ready",
                "payload": {
                    "chats": chats_to_send,
                    "chat_count": len(chats_to_send),
                    "phase": "phase2"
                }
            },
            user_id,
            device_fingerprint_hash
        )
        
        logger.info(f"Phase 2 sync complete for user {user_id}, sent: {len(chats_to_send)} chats, skipped: {chats_skipped}")
        
    except Exception as e:
        logger.error(f"Error in Phase 2 sync for user {user_id}: {e}", exc_info=True)


async def _handle_phase3_sync(
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    user_id: str,
    device_fingerprint_hash: str,
    client_chat_versions: Dict[str, Dict[str, int]],
    client_chat_ids: List[str]
):
    """
    Handle Phase 3: Last 100 updated chats (full sync)
    Only sends chats that are missing or outdated on the client.
    NEVER sends new chat suggestions - they are always sent in Phase 1.
    Maintains zero-knowledge architecture - all data remains encrypted.
    """
    logger.info(f"Processing Phase 3 sync for user {user_id}")
    
    try:
        # Get last 100 updated chats from server
        all_chats_from_server = await directus_service.chat.get_core_chats_and_user_drafts_for_cache_warming(
            user_id, limit=100
        )
        
        if not all_chats_from_server:
            logger.info(f"No chats found for Phase 3 sync: {user_id}")
            # Still send suggestions even if no chats
        
        from backend.core.api.app.schemas.chat import CachedChatVersions
        client_chat_ids_set = set(client_chat_ids)
        
        # Filter chats to only include missing or outdated ones
        chats_to_send = []
        chats_skipped = 0
        
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
                            logger.debug(f"Phase 3: Skipping chat {chat_id} - client already up-to-date "
                                       f"(client: m={client_messages_v}, t={client_title_v}; "
                                       f"server: m={cached_server_versions.messages_v}, t={cached_server_versions.title_v})")
                            chats_skipped += 1
                            continue
                
                # Chat is missing or outdated - add to send list
                chats_to_send.append(chat_wrapper)
                logger.debug(f"Phase 3: Will send chat {chat_id} (missing: {chat_is_missing})")
            
            logger.info(f"Phase 3: Sending {len(chats_to_send)}/{len(all_chats_from_server)} chats (skipped {chats_skipped} up-to-date)")
            
            if chats_to_send:
                # CACHE-FIRST STRATEGY: Try cache first for each chat, fallback to Directus
                chat_ids_to_fetch_from_directus = []
                messages_added_count = 0
                
                for chat_wrapper in chats_to_send:
                    chat_id = chat_wrapper["chat_details"]["id"]
                    messages = []
                    
                    # Try to get messages from cache first
                    try:
                        cached_messages = await cache_service.get_chat_messages_history(user_id, chat_id)
                        if cached_messages:
                            messages = cached_messages
                            chat_wrapper["messages"] = messages
                            messages_added_count += 1
                            logger.debug(f"Phase 3: Cache HIT for {len(messages)} messages in chat {chat_id}")
                        else:
                            logger.debug(f"Phase 3: Cache MISS for messages in chat {chat_id}")
                            chat_ids_to_fetch_from_directus.append(chat_id)
                    except Exception as cache_error:
                        logger.warning(f"Phase 3: Error reading messages from cache for {chat_id}: {cache_error}")
                        chat_ids_to_fetch_from_directus.append(chat_id)
                
                # Fetch from Directus only for cache misses
                if chat_ids_to_fetch_from_directus:
                    logger.info(f"Phase 3: Fetching messages for {len(chat_ids_to_fetch_from_directus)} chats from Directus (cache misses)")
                    
                    try:
                        all_messages_dict = await directus_service.chat.get_messages_for_chats(
                            chat_ids=chat_ids_to_fetch_from_directus, decrypt_content=False  # Zero-knowledge: keep encrypted
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

                logger.info(f"Phase 3: Total chats with messages added: {messages_added_count}/{len(chats_to_send)} (cache hits: {messages_added_count - len(chat_ids_to_fetch_from_directus)}, directus fetches: {len(chat_ids_to_fetch_from_directus)})")

        # Send Phase 3 data to client (chats only - NO suggestions, always sent in Phase 1)
        await manager.send_personal_message(
            {
                "type": "phase_3_last_100_chats_ready",
                "payload": {
                    "chats": chats_to_send,
                    "chat_count": len(chats_to_send),
                    "phase": "phase3"
                }
            },
            user_id,
            device_fingerprint_hash
        )

        logger.info(f"Phase 3 sync complete for user {user_id}, sent: {len(chats_to_send)} chats (skipped: {chats_skipped})")
        
    except Exception as e:
        logger.error(f"Error in Phase 3 sync for user {user_id}: {e}", exc_info=True)


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
        
        # Send sync status to client
        await manager.send_personal_message(
            {
                "type": "sync_status_response",
                "payload": {
                    "cache_primed": cache_primed,
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
