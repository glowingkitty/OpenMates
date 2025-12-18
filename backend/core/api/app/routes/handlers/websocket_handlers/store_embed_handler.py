import logging
from typing import Dict, Any
from fastapi import WebSocket

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.routes.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)

async def handle_store_embed(
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any]
):
    """
    Handles the 'store_embed' event from the client.
    Receives an encrypted embed and stores it in Directus (zero-knowledge).
    
    Payload structure:
    {
        "embed_id": "...",
        "encrypted_type": "...",  // Encrypted with embed_key (client-side)
        "encrypted_content": "...",  // Encrypted with embed_key (client-side)
        "encrypted_text_preview": "...",  // Encrypted with embed_key (client-side)
        "status": "...",
        "hashed_chat_id": "...",
        "hashed_message_id": "...",
        "hashed_task_id": "...",
        "hashed_user_id": "...",
        "embed_ids": [...],  // For composite embeds
        "parent_embed_id": "...",
        "version_number": 1,
        "encrypted_diff": "...",
        "file_path": "...",
        "content_hash": "...",
        "text_length_chars": 123,
        "is_private": false,
        "is_shared": false,
        "createdAt": 1234567890,
        "updatedAt": 1234567890
    }
    
    Note: encryption_key_embed is no longer part of this payload.
    Embed keys are stored separately via store_embed_keys event in embed_keys collection.
    """
    try:
        embed_id = payload.get("embed_id")
        if not embed_id:
            logger.error(f"Missing embed_id in store_embed payload from user {user_id}")
            return

        logger.info(f"Processing store_embed for embed {embed_id} from user {user_id}")

        # Check if embed already exists
        existing_embed = await directus_service.embed.get_embed_by_id(embed_id)
        
        if existing_embed:
            # Update existing embed
            logger.debug(f"Embed {embed_id} exists, updating...")
            updated_embed = await directus_service.embed.update_embed(embed_id, payload)
            if updated_embed:
                logger.info(f"Successfully updated embed {embed_id} in Directus")
            else:
                logger.error(f"Failed to update embed {embed_id} in Directus")
        else:
            # Create new embed
            logger.debug(f"Embed {embed_id} does not exist, creating...")
            created_embed = await directus_service.embed.create_embed(payload)
            if created_embed:
                logger.info(f"Successfully created embed {embed_id} in Directus")
            else:
                logger.error(f"Failed to create embed {embed_id} in Directus")

        # Broadcast update to other devices
        # This ensures other open tabs/devices get the updated embed status/content
        broadcast_payload = {
            "type": "embed_update",
            "event_for_client": "embed_update",
            "embed_id": embed_id,
            "chat_id": payload.get("hashed_chat_id"), # Note: Client expects plaintext chat_id usually, but for zero-knowledge sync we might need to adjust. 
                                                      # However, the client handles 'embed_update' by looking up the embed.
                                                      # The 'embed_update' payload in chat.ts expects:
                                                      # embed_id, chat_id, message_id, status, child_embed_ids
                                                      # Since we only have hashed IDs here, we can't send plaintext IDs back.
                                                      # But the client receiving this broadcast likely already has the chat/message context 
                                                      # or can fetch the embed by ID.
            "status": payload.get("status"),
            "child_embed_ids": payload.get("embed_ids")
        }
        
        # We can't easily broadcast plaintext chat_id/message_id because we don't have them (zero-knowledge).
        # But the client handler for 'embed_update' mainly uses 'embed_id' to fetch/update the embed.
        # Let's send what we have.
        
        await manager.broadcast_to_user(
            message=broadcast_payload,
            user_id=user_id,
            exclude_device_hash=device_fingerprint_hash
        )
        logger.debug(f"Broadcasted embed_update for {embed_id} to other devices")

    except Exception as e:
        logger.error(f"Error handling store_embed for user {user_id}: {e}", exc_info=True)
        await manager.send_personal_message(
            {"type": "error", "payload": {"message": "Failed to store embed"}},
            user_id,
            device_fingerprint_hash
        )