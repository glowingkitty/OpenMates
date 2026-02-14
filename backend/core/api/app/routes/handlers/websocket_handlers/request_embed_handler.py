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

        # If the cache shows "processing", the embed may have already finished but the
        # cache was never updated (the client that received the finished result encrypts
        # and stores to Directus, but the operational cache is not refreshed).
        # In this case, check Directus for the authoritative status.
        if cached and cached.get("status") == "processing":
            logger.info(
                f"{log_prefix}Cache has stale 'processing' status, checking Directus for authoritative data"
            )
            directus_embed = await directus_service.embed.get_embed_by_id(embed_id)
            if directus_embed and directus_embed.get("status") == "finished":
                logger.info(
                    f"{log_prefix}Directus confirms embed is 'finished' - serving client-encrypted data from Directus"
                )
                # Directus has the client-encrypted final embed. Send it directly
                # using the send_embed_data event so the client stores it in IndexedDB.
                # The content in Directus is already client-encrypted (stored by the
                # original device via store_embed), so we send it as-is.
                send_payload = {
                    "event": "send_embed_data",
                    "type": "send_embed_data",
                    "event_for_client": "send_embed_data",
                    "payload": {
                        "embed_id": embed_id,
                        "type": directus_embed.get("encrypted_type") or "app_skill_use",
                        "content": directus_embed.get("encrypted_content", ""),
                        "status": "finished",
                        "chat_id": cached.get("chat_id") or cached.get("hashed_chat_id"),
                        "message_id": cached.get("message_id") or cached.get("hashed_message_id"),
                        "user_id": user_id,
                        "is_private": directus_embed.get("is_private", False),
                        "is_shared": directus_embed.get("is_shared", False),
                        "text_length_chars": directus_embed.get("text_length_chars"),
                        "createdAt": directus_embed.get("created_at") or cached.get("created_at") or int(datetime.now().timestamp()),
                        "updatedAt": directus_embed.get("updated_at") or cached.get("updated_at") or int(datetime.now().timestamp()),
                        "embed_ids": directus_embed.get("embed_ids"),
                        "parent_embed_id": directus_embed.get("parent_embed_id"),
                        "version_number": directus_embed.get("version_number"),
                        "file_path": directus_embed.get("file_path"),
                        "content_hash": directus_embed.get("content_hash"),
                        # Signal to the client that this content is already client-encrypted
                        # and should be stored directly without re-encryption
                        "already_encrypted": True,
                        "encryption_mode": directus_embed.get("encryption_mode", "client"),
                    }
                }

                # Also update the operational cache so subsequent requests are fast
                try:
                    import json as json_lib
                    client = await cache_service.client
                    if client:
                        # Update the cached entry's status to "finished" to prevent
                        # repeated Directus lookups
                        cached["status"] = "finished"
                        await client.set(
                            f"embed:{embed_id}",
                            json_lib.dumps(cached),
                            ex=259200  # 72 hours
                        )
                        logger.debug(f"{log_prefix}Updated operational cache status to 'finished'")
                except Exception as cache_err:
                    logger.warning(f"{log_prefix}Failed to update cache after Directus lookup: {cache_err}")

                await manager.send_personal_message(send_payload, user_id, device_fingerprint_hash)
                logger.info(f"{log_prefix}Sent finished embed data from Directus to user {user_id}")
                return

        # Handle error/cancelled embeds from cache: send error status to client
        # without full vault decryption, and remove from cache to prevent repeated lookups.
        # The client's embedResolver will mark this embed as a known error
        # to prevent re-requesting it on every render cycle.
        if cached and cached.get("status") in ("error", "cancelled"):
            logger.info(
                f"{log_prefix}Embed has status='{cached.get('status')}' in cache, "
                f"sending error status to client and removing from cache"
            )
            error_payload = {
                "event": "send_embed_data",
                "type": "send_embed_data",
                "event_for_client": "send_embed_data",
                "payload": {
                    "embed_id": embed_id,
                    "type": cached.get("type") or "app_skill_use",
                    "content": cached.get("encrypted_content", ""),
                    "status": cached.get("status"),
                    "chat_id": cached.get("chat_id") or cached.get("hashed_chat_id"),
                    "message_id": cached.get("message_id") or cached.get("hashed_message_id"),
                    "user_id": user_id,
                    "embed_ids": cached.get("embed_ids"),
                    "parent_embed_id": cached.get("parent_embed_id"),
                    "is_private": cached.get("is_private", False),
                    "is_shared": cached.get("is_shared", False),
                }
            }
            await manager.send_personal_message(error_payload, user_id, device_fingerprint_hash)

            # Remove the error embed from cache so we don't keep sending it
            # on repeated requests. The client-side knownErrorEmbeds set will
            # prevent the client from re-requesting after the first response.
            try:
                client = await cache_service.client
                if client:
                    await client.delete(f"embed:{embed_id}")
                    logger.debug(f"{log_prefix}Removed error embed from cache")
            except Exception as cache_err:
                logger.warning(f"{log_prefix}Failed to remove error embed from cache: {cache_err}")
            return

        if not cached:
            # If not in cache at all, check Directus as a last resort
            logger.warning(f"{log_prefix}Embed not found in cache, checking Directus")
            directus_embed = await directus_service.embed.get_embed_by_id(embed_id)
            if directus_embed and directus_embed.get("status") == "finished":
                logger.info(f"{log_prefix}Found finished embed in Directus (not in cache)")
                send_payload = {
                    "event": "send_embed_data",
                    "type": "send_embed_data",
                    "event_for_client": "send_embed_data",
                    "payload": {
                        "embed_id": embed_id,
                        "type": directus_embed.get("encrypted_type") or "app_skill_use",
                        "content": directus_embed.get("encrypted_content", ""),
                        "status": "finished",
                        "chat_id": directus_embed.get("hashed_chat_id"),
                        "message_id": directus_embed.get("hashed_message_id"),
                        "user_id": user_id,
                        "is_private": directus_embed.get("is_private", False),
                        "is_shared": directus_embed.get("is_shared", False),
                        "text_length_chars": directus_embed.get("text_length_chars"),
                        "createdAt": directus_embed.get("created_at") or int(datetime.now().timestamp()),
                        "updatedAt": directus_embed.get("updated_at") or int(datetime.now().timestamp()),
                        "embed_ids": directus_embed.get("embed_ids"),
                        "parent_embed_id": directus_embed.get("parent_embed_id"),
                        "version_number": directus_embed.get("version_number"),
                        "file_path": directus_embed.get("file_path"),
                        "content_hash": directus_embed.get("content_hash"),
                        "already_encrypted": True,
                        "encryption_mode": directus_embed.get("encryption_mode", "client"),
                    }
                }
                await manager.send_personal_message(send_payload, user_id, device_fingerprint_hash)
                logger.info(f"{log_prefix}Sent finished embed data from Directus to user {user_id}")
                return

            logger.warning(f"{log_prefix}Embed not found in cache or Directus")
            return

        # Cache has non-processing embed data (e.g. vault-encrypted content from
        # active skill execution) - proceed with vault decryption
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
                "is_private": cached.get("is_private", False),
                "is_shared": cached.get("is_shared", False),
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
