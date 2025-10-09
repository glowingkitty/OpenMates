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
    This implements the 3-phase sync architecture:
    - Phase 1: Last opened chat (immediate priority)
    - Phase 2: Last 10 updated chats (quick access)
    - Phase 3: Last 100 updated chats (full sync)
    """
    try:
        sync_phase = payload.get("phase", "all")
        logger.info(f"Handling phased sync request for user {user_id}, phase: {sync_phase}")
        
        if sync_phase == "phase1" or sync_phase == "all":
            await _handle_phase1_sync(
                manager, cache_service, directus_service, user_id, device_fingerprint_hash
            )
        
        if sync_phase == "phase2" or sync_phase == "all":
            await _handle_phase2_sync(
                manager, cache_service, directus_service, user_id, device_fingerprint_hash
            )
        
        if sync_phase == "phase3" or sync_phase == "all":
            await _handle_phase3_sync(
                manager, cache_service, directus_service, user_id, device_fingerprint_hash
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
    device_fingerprint_hash: str
):
    """Handle Phase 1: Last opened chat (immediate priority)"""
    logger.info(f"Processing Phase 1 sync for user {user_id}")
    
    try:
        # Get last opened chat from user profile
        user_profile = await directus_service.get_user_profile(user_id)
        if not user_profile[1]:  # user_profile returns (success, data, error)
            logger.warning(f"Could not fetch user profile for Phase 1 sync: {user_id}")
            return
        
        last_opened_path = user_profile[1].get("last_opened")
        if not last_opened_path:
            logger.info(f"No last opened path for user {user_id}, skipping Phase 1")
            return
        
        # Extract chat ID from path (assuming format like "/chat/chat-id")
        chat_id = last_opened_path.split("/")[-1] if "/" in last_opened_path else last_opened_path
        
        # Skip fetching metadata for special chat IDs that don't exist in the database
        if chat_id == "new":
            logger.info(f"Skipping Phase 1 sync since no chat ID is provided ('New chat' is selected)")
            return
        
        # Get chat details and messages
        chat_details = await directus_service.chat.get_chat_metadata(chat_id)
        if not chat_details:
            logger.warning(f"Could not fetch chat details for Phase 1: {chat_id}")
            return
        
        # Get messages for the chat
        messages_data = await directus_service.chat.get_all_messages_for_chat(
            chat_id=chat_id, decrypt_content=True
        )
        
        # Send Phase 1 data to client
        await manager.send_personal_message(
            {
                "type": "priorityChatReady",
                "payload": {
                    "chat_id": chat_id,
                    "chat_details": chat_details,
                    "messages": messages_data or [],
                    "phase": "phase1"
                }
            },
            user_id,
            device_fingerprint_hash
        )
        
        logger.info(f"Phase 1 sync complete for user {user_id}, chat: {chat_id}")
        
    except Exception as e:
        logger.error(f"Error in Phase 1 sync for user {user_id}: {e}", exc_info=True)


async def _handle_phase2_sync(
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    user_id: str,
    device_fingerprint_hash: str
):
    """Handle Phase 2: Last 10 updated chats (quick access)"""
    logger.info(f"Processing Phase 2 sync for user {user_id}")
    
    try:
        # Get last 10 updated chats
        recent_chats = await directus_service.chat.get_core_chats_and_user_drafts_for_cache_warming(
            user_id, limit=10
        )
        
        if not recent_chats:
            logger.info(f"No recent chats found for Phase 2 sync: {user_id}")
            return
        
        # Ensure encrypted_chat_key is included in chat_details for each chat
        for chat_wrapper in recent_chats:
            chat_details = chat_wrapper.get("chat_details", {})
            if not chat_details.get("encrypted_chat_key"):
                logger.warning(f"Missing encrypted_chat_key for chat {chat_details.get('id')} in Phase 2")
        
        # Send Phase 2 data to client
        await manager.send_personal_message(
            {
                "type": "phase_2_last_10_chats_ready",
                "payload": {
                    "chats": recent_chats,
                    "chat_count": len(recent_chats),
                    "phase": "phase2"
                }
            },
            user_id,
            device_fingerprint_hash
        )
        
        logger.info(f"Phase 2 sync complete for user {user_id}, chats: {len(recent_chats)}")
        
    except Exception as e:
        logger.error(f"Error in Phase 2 sync for user {user_id}: {e}", exc_info=True)


async def _handle_phase3_sync(
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    user_id: str,
    device_fingerprint_hash: str
):
    """Handle Phase 3: Last 100 updated chats (full sync)"""
    logger.info(f"Processing Phase 3 sync for user {user_id}")
    
    try:
        # Get last 100 updated chats
        all_chats = await directus_service.chat.get_core_chats_and_user_drafts_for_cache_warming(
            user_id, limit=100
        )
        
        if not all_chats:
            logger.info(f"No chats found for Phase 3 sync: {user_id}")
            return
        
        # Get messages for chats that have them cached (top N chats)
        top_n_chat_ids = await cache_service.get_chat_ids_versions(
            user_id, start=0, end=cache_service.TOP_N_MESSAGES_COUNT - 1, with_scores=False
        )
        
        logger.info(f"Phase 3: Found {len(top_n_chat_ids)} chat IDs in 'Hot' cache for user {user_id}: {top_n_chat_ids}")
        
        # Fetch messages for top N chats from cache
        messages_added_count = 0
        for chat_data_wrapper in all_chats:
            chat_id = chat_data_wrapper["chat_details"]["id"]
            logger.debug(f"Phase 3: Processing chat {chat_id}, in top_n: {chat_id in top_n_chat_ids}")
            if chat_id in top_n_chat_ids:
                # Try to get messages from cache
                messages = await cache_service.get_chat_messages_history(user_id, chat_id)
                if messages:
                    chat_data_wrapper["messages"] = messages
                    messages_added_count += 1
                    logger.info(f"Phase 3: Added {len(messages)} messages for chat {chat_id} from cache")
                else:
                    logger.warning(f"Phase 3: No messages found in cache for chat {chat_id}, even though it's in top_n")
        
        logger.info(f"Phase 3: Total chats with messages added: {messages_added_count}/{len(all_chats)}")
        
        # Send Phase 3 data to client
        await manager.send_personal_message(
            {
                "type": "phase_3_last_100_chats_ready",
                "payload": {
                    "chats": all_chats,
                    "chat_count": len(all_chats),
                    "phase": "phase3"
                }
            },
            user_id,
            device_fingerprint_hash
        )
        
        logger.info(f"Phase 3 sync complete for user {user_id}, chats: {len(all_chats)}")
        
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
