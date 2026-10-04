import hashlib
import logging
from typing import Dict, Any
from fastapi import WebSocket

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.routes.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)


async def _canonical_embed_for_key(directus_service, hashed_embed_id, actor_hash):
    """Resolve one current owner head; never trust the wrapper's owner field."""
    rows = await directus_service.get_items(
        "embeds",
        params={
            "filter": {"hashed_embed_id": {"_eq": hashed_embed_id}},
            "fields": "embed_id,hashed_embed_id,hashed_user_id,hashed_chat_id,version_number",
            "limit": 2,
        },
        no_cache=True,
        admin_required=True,
        raise_on_error=True,
    )
    if not isinstance(rows, list) or len(rows) != 1:
        raise ValueError("Canonical embed unavailable")
    embed = rows[0]
    embed_id = embed.get("embed_id")
    if (not isinstance(embed_id, str)
            or hashlib.sha256(embed_id.encode()).hexdigest() != hashed_embed_id
            or embed.get("hashed_user_id") != actor_hash):
        raise ValueError("Embed owner or identity mismatch")
    links = await directus_service.get_items(
        "project_items",
        params={
            "filter": {
                "target_id_hash": {"_eq": hashed_embed_id},
                "item_type": {"_in": ["embed", "upload"]},
            },
            "fields": "id",
            "limit": 1,
        },
        no_cache=True,
        admin_required=True,
        raise_on_error=True,
    )
    if not isinstance(links, list) or links:
        raise ValueError("Project embed keys require atomic revision commit")
    return embed


async def _existing_wrapper(directus_service, hashed_embed_id, key_type, hashed_chat_id, actor_hash):
    key_filter = {
        "hashed_embed_id": {"_eq": hashed_embed_id},
        "key_type": {"_eq": key_type},
        "hashed_chat_id": {"_eq": hashed_chat_id} if hashed_chat_id else {"_null": True},
    }
    rows = await directus_service.get_items(
        "embed_keys",
        params={
            "filter": key_filter,
            "fields": "id,hashed_user_id,encrypted_embed_key",
            "limit": 2,
        },
        no_cache=True,
        admin_required=True,
        raise_on_error=True,
    )
    if not isinstance(rows, list) or len(rows) > 1:
        raise ValueError("Embed key lookup ambiguous")
    if rows and (rows[0].get("hashed_user_id") != actor_hash or not rows[0].get("id")):
        raise ValueError("Embed key owner mismatch")
    return rows[0] if rows else None


async def _require_chat_write_scope(directus_service, hashed_chat_id, actor_hash):
    """Resolve an opaque chat hash against current authoritative chat ownership."""
    from backend.core.api.app.services.chat_message_archive_service import ChatMessageArchiveService

    response = await ChatMessageArchiveService(
        directus_service=directus_service, s3_service=None,
    ).transaction("resolve_chat_hashes", {"hashes": [hashed_chat_id]})
    chats = response.get("chats")
    if not isinstance(chats, list) or len(chats) != 1:
        raise ValueError("Chat hash could not be resolved")
    chat = chats[0]
    if (not isinstance(chat, dict) or chat.get("hashed_chat_id") != hashed_chat_id
            or "storage_state" not in chat
            or chat.get("storage_state") == "deleting"):
        raise ValueError("Chat is unavailable for key writes")
    team_hash = chat.get("hashed_team_id")
    if not team_hash:
        if chat.get("hashed_user_id") != actor_hash:
            raise ValueError("Chat owner mismatch")
        return chat
    membership = await directus_service.get_items(
        "team_memberships",
        params={
            "filter": {
                "hashed_team_id": {"_eq": team_hash},
                "hashed_user_id": {"_eq": actor_hash},
                "status": {"_eq": "active"},
            },
            "fields": "role,status",
            "limit": 2,
        },
        no_cache=True, admin_required=True, raise_on_error=True,
    )
    if (not isinstance(membership, list) or len(membership) != 1
            or membership[0].get("role") not in {"owner", "admin", "member"}):
        raise ValueError("Team chat write denied")
    teams = await directus_service.get_items(
        "teams",
        params={
            "filter": {"hashed_team_id": {"_eq": team_hash}, "status": {"_eq": "active"}},
            "fields": "id,status",
            "limit": 2,
        },
        no_cache=True, admin_required=True, raise_on_error=True,
    )
    if not isinstance(teams, list) or len(teams) != 1:
        raise ValueError("Team chat is unavailable")
    return chat


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
        from backend.shared.python_utils.tracing.ws_span_helper import start_ws_handler_span
        _otel_span, _otel_token = start_ws_handler_span("store_embed_keys", user_id, payload, user_otel_attrs)
    except Exception:
        pass
    try:
        try:
            keys = payload.get("keys")
            request_id = payload.pop("request_id", None)
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
            actor_hash = hashlib.sha256(user_id.encode()).hexdigest()
            completion_candidates = {}

            for key_data in keys:
                try:
                    # Validate required fields
                    if not isinstance(key_data, dict):
                        raise ValueError("Invalid embed key entry")
                    hashed_embed_id = key_data.get("hashed_embed_id")
                    key_type = key_data.get("key_type")
                    encrypted_embed_key = key_data.get("encrypted_embed_key")
                    hashed_user_id = key_data.get("hashed_user_id")
                    created_at = key_data.get("created_at")

                    if (not isinstance(hashed_embed_id, str) or len(hashed_embed_id) != 64
                            or any(c not in "0123456789abcdef" for c in hashed_embed_id)
                            or not isinstance(encrypted_embed_key, str) or not encrypted_embed_key
                            or hashed_user_id != actor_hash):
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
                        if not isinstance(hashed_chat_id, str) or len(hashed_chat_id) != 64:
                            logger.warning("Missing hashed_chat_id for key_type='chat' in store_embed_keys payload")
                            failed_count += 1
                            continue
                    else:
                        # For master key type, hashed_chat_id should be null
                        hashed_chat_id = None

                    canonical_embed = await _canonical_embed_for_key(
                        directus_service, hashed_embed_id, actor_hash,
                    )
                    if key_type == "chat":
                        await _require_chat_write_scope(
                            directus_service, hashed_chat_id, actor_hash,
                        )

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
                    existing_key = await _existing_wrapper(
                        directus_service, hashed_embed_id, key_type, hashed_chat_id, actor_hash,
                    )
                
                    if existing_key:
                        existing_key_id = existing_key.get("id")
                        existing_encrypted_key = existing_key.get("encrypted_embed_key")

                        if existing_encrypted_key == encrypted_embed_key:
                            # Exact same key wrapper — true duplicate, nothing to do.
                            logger.debug(
                                f"Skipping identical embed_key (no change): key_type={key_type}, "
                                f"hashed_embed_id={hashed_embed_id[:16]}..."
                            )
                            created_count += 1
                            completion_candidates[canonical_embed["embed_id"]] = canonical_embed
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
                            completion_candidates[canonical_embed["embed_id"]] = canonical_embed
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
                        "hashed_user_id": actor_hash,
                        "created_at": created_at
                    }

                    created_key = await directus_service.embed.create_embed_key(embed_key_data)
                    if created_key:
                        created_count += 1
                        completion_candidates[canonical_embed["embed_id"]] = canonical_embed
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

            if request_id:
                await manager.send_personal_message(
                    {
                        "type": "store_embed_keys_confirmed",
                        "payload": {"request_id": request_id, "created_count": created_count,
                                    "failed_count": failed_count, "requested_count": len(keys)},
                    },
                    user_id,
                    device_fingerprint_hash,
                )

            # Wrapper success retriggers closure after its own normal-success
            # receipt. The transaction still verifies the complete wrapper set.
            if completion_candidates:
                from .store_embed_handler import _attempt_direct_intent_completion

                for canonical_embed in completion_candidates.values():
                    await _attempt_direct_intent_completion(
                        directus_service,
                        actor_hash=actor_hash,
                        canonical_embed=canonical_embed,
                    )

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
