import logging
from typing import Dict, Any
from fastapi import WebSocket

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.routes.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)

async def handle_store_embed_keys(
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any],
    user_otel_attrs: dict = None,):
    """
    Handles the 'store_embed_keys' event from the client.
    Receives wrapped embed keys and stores them in Directus embed_keys collection (zero-knowledge).
    
    This implements the wrapped key architecture where each embed's encryption key is stored
    in multiple wrapped forms:
    - key_type='master': AES(embed_key, master_key) for owner cross-chat access
    - key_type='chat': AES(embed_key, chat_key) for shared chat access
    
    Payload structure:
    {
        "keys": [
            {
                "hashed_embed_id": "...",  // SHA256 hash of embed_id
                "key_type": "master" | "chat",
                "hashed_chat_id": "..." | null,  // For key_type='chat': SHA256(chat_id)
                "encrypted_embed_key": "...",  // AES(embed_key, master_key) or AES(embed_key, chat_key)
                "hashed_user_id": "...",  // SHA256 hash of user_id
                "created_at": 1234567890
            },
            ...
        ]
    }
    """
    _otel_span, _otel_token = None, None
    try:
        from backend.shared.python_utils.tracing.ws_span_helper import start_ws_handler_span, end_ws_handler_span
        _otel_span, _otel_token = start_ws_handler_span("store_embed_keys", user_id, payload, user_otel_attrs)
    except Exception:
        pass
    try:
        try:
            keys = payload.get("keys")
            if not keys or not isinstance(keys, list):
                logger.error(f"Invalid store_embed_keys payload from user {user_id}: missing or invalid 'keys' array")
                return

            if len(keys) == 0:
                logger.warning(f"Empty keys array in store_embed_keys payload from user {user_id}")
                return

            logger.info(f"Processing store_embed_keys: {len(keys)} key wrapper(s) from user {user_id}")

            # Process each key wrapper
            created_count = 0
            failed_count = 0

            for key_data in keys:
                try:
                    # Validate required fields
                    hashed_embed_id = key_data.get("hashed_embed_id")
                    key_type = key_data.get("key_type")
                    encrypted_embed_key = key_data.get("encrypted_embed_key")
                    hashed_user_id = key_data.get("hashed_user_id")
                    created_at = key_data.get("created_at")

                    if not hashed_embed_id or not key_type or not encrypted_embed_key or not hashed_user_id:
                        logger.warning("Invalid key entry in store_embed_keys payload: missing required fields")
                        failed_count += 1
                        continue

                    if key_type not in ["master", "chat"]:
                        logger.warning(f"Invalid key_type '{key_type}' in store_embed_keys payload (must be 'master' or 'chat')")
                        failed_count += 1
                        continue

                    # For chat key type, hashed_chat_id is required
                    if key_type == "chat":
                        hashed_chat_id = key_data.get("hashed_chat_id")
                        if not hashed_chat_id:
                            logger.warning("Missing hashed_chat_id for key_type='chat' in store_embed_keys payload")
                            failed_count += 1
                            continue
                    else:
                        # For master key type, hashed_chat_id should be null
                        hashed_chat_id = None

                    # Check for existing key to upsert rather than blindly create.
                    #
                    # WHY UPSERT (not skip): When a decryption failure triggers embed
                    # re-encryption (AppSkillUseRenderer._decryptionFailed recovery), the
                    # client generates a NEW embed key (key B) and re-encrypts the content.
                    # store_embed also upserts the encrypted_content in Directus.
                    # However, the old code here would find the existing key-A wrappers and
                    # skip writing key-B wrappers — leaving Directus with a permanent mismatch
                    # (content encrypted with B, keys wrap A). Every future session would fail
                    # to decrypt. The fix: if wrappers already exist, UPDATE the
                    # encrypted_embed_key field with the new value instead of skipping.
                    existing_keys = await directus_service.embed.get_embed_keys_by_embed_id_and_type(
                        hashed_embed_id, key_type, hashed_chat_id
                    )
                
                    if existing_keys and len(existing_keys) > 0:
                        existing_key = existing_keys[0]
                        existing_key_id = existing_key.get("id")
                        existing_encrypted_key = existing_key.get("encrypted_embed_key")

                        if existing_encrypted_key == encrypted_embed_key:
                            # Exact same key wrapper — true duplicate, nothing to do.
                            logger.debug(
                                f"Skipping identical embed_key (no change): key_type={key_type}, "
                                f"hashed_embed_id={hashed_embed_id[:16]}..."
                            )
                            created_count += 1
                            continue

                        # Different key value → the embed was re-encrypted; update the wrapper.
                        logger.info(
                            f"Upserting embed_key (re-encryption detected): key_type={key_type}, "
                            f"hashed_embed_id={hashed_embed_id[:16]}..., Directus id={existing_key_id}"
                        )
                        updated_key = await directus_service.embed.update_embed_key(
                            existing_key_id, {"encrypted_embed_key": encrypted_embed_key}
                        )
                        if updated_key:
                            created_count += 1
                            logger.debug(
                                f"Successfully upserted embed_key: key_type={key_type}, "
                                f"hashed_embed_id={hashed_embed_id[:16]}..."
                            )
                        else:
                            failed_count += 1
                            logger.error(
                                f"Failed to upsert embed_key: key_type={key_type}, "
                                f"hashed_embed_id={hashed_embed_id[:16]}..."
                            )
                        continue
                
                    # Create embed_key entry in Directus
                    embed_key_data = {
                        "hashed_embed_id": hashed_embed_id,
                        "key_type": key_type,
                        "hashed_chat_id": hashed_chat_id,
                        "encrypted_embed_key": encrypted_embed_key,
                        "hashed_user_id": hashed_user_id,
                        "created_at": created_at
                    }

                    created_key = await directus_service.embed.create_embed_key(embed_key_data)
                    if created_key:
                        created_count += 1
                        logger.debug(f"Successfully created embed_key entry: key_type={key_type}, hashed_embed_id={hashed_embed_id[:16]}...")
                    else:
                        failed_count += 1
                        logger.error(f"Failed to create embed_key entry: key_type={key_type}, hashed_embed_id={hashed_embed_id[:16]}...")

                except Exception as e:
                    logger.error(f"Error processing embed_key entry: {e}", exc_info=True)
                    failed_count += 1

            if created_count > 0:
                logger.info(f"Successfully stored {created_count} embed_key wrapper(s) in Directus")
            if failed_count > 0:
                logger.warning(f"Failed to store {failed_count} embed_key wrapper(s)")

            # Broadcast update to other devices (optional - key storage doesn't affect UI directly)
            # This ensures other open tabs/devices are aware of the new keys
            # Note: Key wrappers are typically only needed when decrypting embeds, so broadcasting
            # is less critical than for embed content updates

        except Exception as e:
            logger.error(f"Error handling store_embed_keys from user {user_id}: {e}", exc_info=True)



    finally:
        if _otel_span is not None:
            try:
                from backend.shared.python_utils.tracing.ws_span_helper import end_ws_handler_span as _end_span
                _end_span(_otel_span, _otel_token)
            except Exception:
                pass
