# backend/core/api/app/routes/handlers/websocket_handlers/app_settings_memories_confirmed_handler.py
"""
Handler for app settings/memories confirmation from client.

When user confirms app settings/memories request:
1. Client sends decrypted app settings/memories data (like embeds)
2. Server encrypts with vault key and stores in cache
3. Cache key: app_settings_memories:{user_id}:{app_id}:{item_key}
4. Server can retrieve from cache for AI processing (similar to embeds)

This replaces the old YAML extraction approach for better efficiency.
"""

import logging
import time
from typing import Dict, Any
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService

logger = logging.getLogger(__name__)


async def handle_app_settings_memories_confirmed(
    websocket,
    manager,
    cache_service: CacheService,
    directus_service: DirectusService,
    encryption_service: EncryptionService,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any]
):
    """
    Handles app settings/memories confirmation from client.
    
    Client sends decrypted app settings/memories data when user confirms.
    Server encrypts with vault key and stores in cache for AI processing.
    
    Cache is chat-specific, so app settings/memories are automatically evicted
    when the chat is evicted from cache.
    
    Args:
        websocket: WebSocket connection
        manager: ConnectionManager instance
        cache_service: CacheService instance
        encryption_service: EncryptionService instance
        user_id: User ID
        device_fingerprint_hash: Device fingerprint hash
        payload: Payload containing chat_id and app_settings_memories array
    """
    try:
        chat_id = payload.get("chat_id")
        app_settings_memories = payload.get("app_settings_memories", [])
        
        if not chat_id:
            logger.warning(f"Invalid app_settings_memories payload from user {user_id}: missing chat_id")
            return
        
        if not app_settings_memories or not isinstance(app_settings_memories, list):
            logger.warning(f"Invalid app_settings_memories payload from user {user_id}: expected array")
            return
        
        # Get user's vault_key_id (try cache first, fallback to Directus)
        user_vault_key_id = await cache_service.get_user_vault_key_id(user_id)
        if not user_vault_key_id:
            logger.debug(f"vault_key_id not in cache for user {user_id}, fetching from Directus")
            try:
                user_profile_result = await directus_service.get_user_profile(user_id)
                if not user_profile_result or not user_profile_result[0]:
                    logger.error(f"Failed to fetch user profile for encryption: {user_id}")
                    await manager.send_personal_message(
                        {"type": "error", "payload": {"message": "Failed to encrypt app settings/memories: user profile not found"}},
                        user_id,
                        device_fingerprint_hash
                    )
                    return
                
                user_vault_key_id = user_profile_result[1].get("vault_key_id")
                if not user_vault_key_id:
                    logger.error(f"User {user_id} missing vault_key_id in Directus profile")
                    await manager.send_personal_message(
                        {"type": "error", "payload": {"message": "Failed to encrypt app settings/memories: encryption key not found"}},
                        user_id,
                        device_fingerprint_hash
                    )
                    return
                
                # Cache the vault_key_id for future use
                await cache_service.update_user(user_id, {"vault_key_id": user_vault_key_id})
                logger.debug(f"Cached vault_key_id for user {user_id}")
            except Exception as e_profile:
                logger.error(f"Error fetching user profile for encryption: {e_profile}", exc_info=True)
                await manager.send_personal_message(
                    {"type": "error", "payload": {"message": "Failed to encrypt app settings/memories: profile error"}},
                    user_id,
                    device_fingerprint_hash
                )
                return
        
        logger.info(f"Processing {len(app_settings_memories)} app settings/memories confirmations for chat {chat_id} from user {user_id}")
        
        cached_count = 0
        for item in app_settings_memories:
            try:
                app_id = item.get("app_id")
                item_key = item.get("item_key")
                content = item.get("content")  # Decrypted content from client
                
                if not app_id or not item_key or content is None:
                    logger.warning(f"Invalid app settings/memories item: missing required fields")
                    continue
                
                # Encrypt content with vault key for server cache
                # Server can decrypt for AI context building
                encrypted_content = encryption_service.encrypt_with_vault_key(
                    user_vault_key_id=user_vault_key_id,
                    plaintext=content if isinstance(content, str) else str(content)
                )
                
                # Prepare cache data (vault-encrypted)
                cache_data = {
                    "app_id": app_id,
                    "item_key": item_key,
                    "content": encrypted_content,  # Vault-encrypted content
                    "cached_at": int(time.time())
                }
                
                # Store in cache (chat-specific, similar to embeds)
                success = await cache_service.set_app_settings_memories_in_cache(
                    user_id=user_id,
                    chat_id=chat_id,
                    app_id=app_id,
                    item_key=item_key,
                    data=cache_data,
                    ttl=86400  # 24 hours, same as message cache
                )
                
                if success:
                    cached_count += 1
                    logger.debug(f"Cached app settings/memories {app_id}:{item_key} for chat {chat_id}")
                else:
                    logger.warning(f"Failed to cache app settings/memories {app_id}:{item_key} for chat {chat_id}")
                    
            except Exception as e:
                logger.error(f"Error processing app settings/memories item: {e}", exc_info=True)
                continue
        
        logger.info(f"Successfully cached {cached_count}/{len(app_settings_memories)} app settings/memories entries for chat {chat_id}")
        
    except Exception as e:
        logger.error(f"Error handling app settings/memories confirmation for user {user_id}: {e}", exc_info=True)

