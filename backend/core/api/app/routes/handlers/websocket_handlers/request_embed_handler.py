import logging
from datetime import datetime
from typing import Dict, Any, Optional
from fastapi import WebSocket

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.routes.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)


async def _decrypt_embed_content(
    encryption_service: EncryptionService,
    encrypted_content: str,
    user_vault_key_id: Optional[str],
    log_prefix: str = ""
) -> Optional[str]:
    """Decrypt vault-encrypted embed content with the user's vault key."""
    if not encrypted_content or not user_vault_key_id:
        logger.warning(f"{log_prefix} Missing encrypted_content or user_vault_key_id for embed decrypt")
        return None

    try:
        return await encryption_service.decrypt_with_user_key(encrypted_content, user_vault_key_id)
    except Exception as e:
        logger.error(f"{log_prefix} Failed to decrypt embed content: {e}", exc_info=True)
        return None


async def handle_request_embed(
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
    Handles 'request_embed' from client:
    - Loads embed from cache (embed:{embed_id})
    - Decrypts with the user's vault key
    - Sends 'send_embed_data' back to the requesting device with plaintext TOON content

    NOTE: This is a fallback path. The normal path streams send_embed_data proactively.
    """
    embed_id = payload.get("embed_id")
    log_prefix = f"[request_embed:{embed_id}] "

    if not embed_id:
        logger.error(f"{log_prefix}Missing embed_id in request from user {user_id}")
        return

    try:
        cached = await cache_service.get(f"embed:{embed_id}")
        if not cached:
            logger.warning(f"{log_prefix}Embed not found in cache")
            return

        # Retrieve user's vault key id from cache (authoritative)
        user_vault_key_id = await cache_service.get_user_vault_key_id(user_id)
        if not user_vault_key_id:
            # Try Directus as a fallback
            user_profile = await directus_service.user.get_user_profile(user_id)
            user_vault_key_id = user_profile.get("vault_key_id") if user_profile else None

        plaintext_content = await _decrypt_embed_content(
            encryption_service,
            cached.get("encrypted_content"),
            user_vault_key_id,
            log_prefix=log_prefix
        )

        if not plaintext_content:
            logger.warning(f"{log_prefix}Could not decrypt embed content")
            return

        embed_type = cached.get("type") or "app_skill_use"

        # Reconstruct payload expected by the frontend handler
        send_payload = {
            "event": "send_embed_data",
            "type": "send_embed_data",
            "event_for_client": "send_embed_data",
            "payload": {
                "embed_id": embed_id,
                "type": embed_type,
                "content": plaintext_content,
                "status": cached.get("status", "finished"),
                # Plaintext IDs may be missing in cache; fall back to hashed if needed
                "chat_id": cached.get("chat_id") or cached.get("hashed_chat_id"),
                "message_id": cached.get("message_id") or cached.get("hashed_message_id"),
                "user_id": user_id,
                "share_mode": cached.get("share_mode", "private"),
                "text_length_chars": cached.get("text_length_chars"),
                # Provide fallback timestamps if missing from cache (prevents null values in IndexedDB)
                "createdAt": cached.get("created_at") or int(datetime.now().timestamp()),
                "updatedAt": cached.get("updated_at") or int(datetime.now().timestamp()),
                "embed_ids": cached.get("embed_ids"),
                "task_id": cached.get("hashed_task_id"),  # hashed if that's all we have
                "parent_embed_id": cached.get("parent_embed_id"),
                "version_number": cached.get("version_number"),
                "file_path": cached.get("file_path"),
                "content_hash": cached.get("content_hash"),
            }
        }

        await manager.send_personal_message(send_payload, user_id, device_fingerprint_hash)
        logger.debug(f"{log_prefix}Sent embed data to user {user_id} device {device_fingerprint_hash}")

    except Exception as e:
        logger.error(f"{log_prefix}Error handling request_embed: {e}", exc_info=True)
        await manager.send_personal_message(
            {"type": "error", "payload": {"message": "Failed to load embed"}},
            user_id,
            device_fingerprint_hash
        )
