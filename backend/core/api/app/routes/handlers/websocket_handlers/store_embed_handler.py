import json
import logging
import hashlib
import re
from typing import Dict, Any
from fastapi import WebSocket

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.routes.connection_manager import ConnectionManager
from backend.core.api.app.services.embed_version_transaction_service import (
    EmbedVersionTransactionError,
    EmbedVersionTransactionService,
    requires_atomic_project_embed_write,
)
from backend.core.api.app.services.chat_recovery_service import ChatRecoveryService

logger = logging.getLogger(__name__)


async def _reject_store_embed_write(
    manager: ConnectionManager,
    user_id: str,
    device_fingerprint_hash: str,
    embed_id: str,
    reason: str,
    request_id: object,
) -> None:
    logger.warning(
        "Rejected unauthorized store_embed write for embed %s from user %s: %s",
        embed_id,
        user_id,
        reason,
    )
    await manager.send_personal_message(
        {"type": "error", "payload": {
            "code": "embed_write_denied",
            "request_id": request_id if isinstance(request_id, str) and 0 < len(request_id) <= 128 else None,
            "message": "Not authorized to store embed",
        }},
        user_id,
        device_fingerprint_hash,
    )


def _user_hash(user_id: str) -> str:
    return hashlib.sha256(user_id.encode()).hexdigest()


async def _complete_direct_intent(
    directus_service: DirectusService,
    *,
    actor_hash: str,
    canonical_embed: Dict[str, Any],
    target_chat_id: str | None = None,
) -> Dict[str, Any]:
    """Close only a direct-skill intent after its canonical head and keys exist."""
    embed_id = canonical_embed.get("embed_id")
    version = canonical_embed.get("version_number")
    hashed_chat_id = canonical_embed.get("hashed_chat_id")
    if not isinstance(embed_id, str) or not embed_id:
        raise RuntimeError("Canonical embed identity is unavailable for direct completion")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise RuntimeError("Canonical embed version is unavailable for direct completion")

    if hashed_chat_id is None:
        if target_chat_id is not None:
            raise RuntimeError("Standalone canonical embed cannot name a target chat")
    elif target_chat_id is not None:
        if (not isinstance(target_chat_id, str)
                or hashlib.sha256(target_chat_id.encode()).hexdigest() != hashed_chat_id):
            raise RuntimeError("Canonical embed chat identity mismatch")
    else:
        from .store_embed_keys_handler import _require_chat_write_scope

        chat = await _require_chat_write_scope(directus_service, hashed_chat_id, actor_hash)
        target_chat_id = chat.get("id")
        if not isinstance(target_chat_id, str) or not target_chat_id:
            raise RuntimeError("Canonical embed chat identity is unavailable for direct completion")

    return await ChatRecoveryService(directus_service).execute(
        "complete_authorized_direct_by_embed",
        {
            "protocol_version": 1,
            "intent_kind": "direct_skill",
            "hashed_user_id": actor_hash,
            "primary_embed_id": embed_id,
            "target_chat_id": target_chat_id,
            "canonical_version": version,
        },
    )


async def _attempt_direct_intent_completion(
    directus_service: DirectusService,
    *,
    actor_hash: str,
    canonical_embed: Dict[str, Any],
    target_chat_id: str | None = None,
) -> None:
    """Keep a durable canonical write successful while closure stays retryable."""
    try:
        result = await _complete_direct_intent(
            directus_service,
            actor_hash=actor_hash,
            canonical_embed=canonical_embed,
            target_chat_id=target_chat_id,
        )
        if result.get("completed"):
            logger.info(
                "Completed authorized direct intent for embed %s%s",
                canonical_embed.get("embed_id"),
                " (idempotent)" if result.get("idempotent") else "",
            )
        elif result.get("reason_code") not in {"pending_wrappers", "no_pending_intent"}:
            logger.error(
                "Direct intent completion returned an invalid result for embed %s",
                canonical_embed.get("embed_id"),
            )
    except Exception:
        # The canonical write remains valid. Durable reconciliation retries the
        # closure; protocol ambiguity also remains fail closed in Directus.
        logger.exception(
            "Direct intent remains pending after canonical write for embed %s",
            canonical_embed.get("embed_id"),
        )

async def handle_store_embed(
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any],
    user_otel_attrs: dict = None,):
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
    _otel_span, _otel_token = None, None
    try:
        from backend.shared.python_utils.tracing.ws_span_helper import start_ws_handler_span
        _otel_span, _otel_token = start_ws_handler_span("store_embed", user_id, payload, user_otel_attrs)
    except Exception:
        pass
    request_id = None
    try:
        try:
            embed_id = payload.get("embed_id")
            if not embed_id:
                logger.error(f"Missing embed_id in store_embed payload from user {user_id}")
                return
            request_id = payload.pop("request_id", None)
            # Recovery correlation is a WebSocket protocol field, not an embeds
            # column. The capability gate has already consumed it before this
            # handler forwards the encrypted head to the legacy transaction.
            payload.pop("recovery_record_id", None)
            # Public app/skill IDs may be projected for paginated discovery. The
            # chat and Team IDs are authorization inputs only, never Directus embed
            # fields or plaintext content.
            chat_id = payload.pop("chat_id", None)
            team_id = payload.pop("team_id", None)
            app_id = payload.pop("app_id", None)
            skill_id = payload.pop("skill_id", None)
            # Catalog and scope fields are server-derived. In particular, a
            # Personal chat must never acquire a client-supplied Team hash.
            for field in ("hashed_team_id", "workspace_origin", "root_embed_id", "apps_workspace_root_id"):
                payload.pop(field, None)
            if app_id is not None or skill_id is not None:
                catalog_id = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
                if not (isinstance(app_id, str) and catalog_id.fullmatch(app_id)
                        and isinstance(skill_id, str) and catalog_id.fullmatch(skill_id)
                        and isinstance(chat_id, str)
                        and payload.get("hashed_chat_id") == hashlib.sha256(chat_id.encode()).hexdigest()):
                    await _reject_store_embed_write(manager, user_id, device_fingerprint_hash, embed_id, "invalid app catalog context", request_id)
                    return
                chats = await directus_service.get_items(
                    "chats", params={"filter[id][_eq]": chat_id,
                                      "fields": "id,hashed_user_id,hashed_team_id", "limit": 1},
                    no_cache=True, admin_required=True, raise_on_error=True,
                )
                if not chats:
                    # Chat metadata may not have synced yet. Persist encrypted
                    # content without a catalog projection; later writes can add it.
                    pass
                else:
                    chat = chats[0]
                    chat_team_hash = chat.get("hashed_team_id")
                    if chat_team_hash:
                        if not isinstance(team_id, str) or hashlib.sha256(team_id.encode()).hexdigest() != chat_team_hash:
                            await _reject_store_embed_write(manager, user_id, device_fingerprint_hash, embed_id, "Team chat context mismatch", request_id)
                            return
                        await directus_service.team.require_team_role(team_id, user_id, {"owner", "admin", "member"})
                        payload["hashed_team_id"] = chat_team_hash
                    elif chat.get("hashed_user_id") != _user_hash(user_id) or team_id:
                        await _reject_store_embed_write(manager, user_id, device_fingerprint_hash, embed_id, "Personal chat context mismatch", request_id)
                        return
                    payload["app_id"] = app_id
                    payload["skill_id"] = skill_id
                    if payload.get("parent_embed_id"):
                        payload["root_embed_id"] = payload["parent_embed_id"]
                    else:
                        payload["root_embed_id"] = embed_id
                        payload["workspace_origin"] = "chat"

            if await requires_atomic_project_embed_write(directus_service, embed_id):
                await _reject_store_embed_write(
                    manager,
                    user_id,
                    device_fingerprint_hash,
                    embed_id,
                    "Project file writes require commit_embed_revision",
                    request_id,
                )
                return

            logger.info(f"Processing store_embed for embed {embed_id} from user {user_id}")

            # CRITICAL FIX: Convert camelCase timestamp fields to snake_case for Directus
            # Frontend sends createdAt/updatedAt (camelCase) but Directus expects created_at/updated_at (snake_case)
            # Without this conversion, timestamps are never stored and embeds show Jan 1970 dates
            if "createdAt" in payload and "created_at" not in payload:
                payload["created_at"] = payload.pop("createdAt")
            if "updatedAt" in payload and "updated_at" not in payload:
                payload["updated_at"] = payload.pop("updatedAt")
            # Compression metadata is carried by client/runtime embed objects,
            # but it is not a column in the permanent Directus embeds schema.
            payload.pop("text_length_chars", None)

            # Merge server-side S3 file keys if cached (set by image generation tasks).
            # Since embed content is client-encrypted, S3 file keys are stored as server-accessible
            # metadata to enable S3 cleanup when the embed or its parent chat is deleted.
            try:
                client = await cache_service.client
                if client:
                    s3_keys_cache_key = f"embed:{embed_id}:s3_file_keys"
                    s3_keys_json = await client.get(s3_keys_cache_key)
                    if s3_keys_json:
                        payload["s3_file_keys"] = json.loads(s3_keys_json)
                        # Clean up the cache key after merging
                        await client.delete(s3_keys_cache_key)
                        logger.info(f"Merged cached s3_file_keys into embed {embed_id} payload")
            except Exception as e:
                logger.warning(f"Failed to check/merge cached s3_file_keys for embed {embed_id}: {e}")

            from backend.core.api.app.services.directus.embed_methods import (
                _validate_client_encrypted_embed_content,
            )
            _validate_client_encrypted_embed_content(embed_id, payload)
            try:
                write_result = await EmbedVersionTransactionService(
                    directus_service,
                ).write_legacy_embed(embed_id, payload, user_id=user_id)
            except EmbedVersionTransactionError as exc:
                if exc.status_code in (403, 409):
                    await _reject_store_embed_write(
                        manager, user_id, device_fingerprint_hash, embed_id, exc.code, request_id,
                    )
                    return
                raise
            logger.info("Stored client-encrypted embed %s (%s)", embed_id, write_result.get("status"))
            try:
                await cache_service.remove_pending_embed(user_id, embed_id)
            except Exception as e:
                logger.warning(f"Failed to remove embed {embed_id} from pending tracking: {e}")
            try:
                client = await cache_service.client
                if client:
                    cache_key = f"embed:{embed_id}"
                    existing = await client.get(cache_key)
                    if existing:
                        await client.expire(cache_key, 259200)
            except Exception as e:
                logger.warning(f"Failed to reset cache TTL for embed {embed_id}: {e}")

            canonical_embed = None
            canonical_digest = None
            if request_id:
                canonical_embed = await directus_service.embed.get_embed_by_id(embed_id)
                if not isinstance(canonical_embed, dict):
                    raise RuntimeError("Canonical embed was unavailable after confirmed write")
                encrypted_content = canonical_embed.get("encrypted_content")
                if not isinstance(encrypted_content, str) or encrypted_content != payload.get("encrypted_content"):
                    raise RuntimeError("Canonical embed ciphertext did not match the confirmed write")
                canonical_digest = hashlib.sha256(encrypted_content.encode("utf-8")).hexdigest()

            # Update the operational cache (embed:{embed_id}) with the client-encrypted data.
            # This prevents stale "processing" entries from being served to other devices
            # via request_embed. The cache entry is updated with the embed's current status
            # so subsequent request_embed calls return the correct data without hitting Directus.
            try:
                embed_status = payload.get("status")
                if embed_status and embed_status != "processing":
                    client = await cache_service.client
                    if client:
                        cache_key = f"embed:{embed_id}"
                        existing_cache = await client.get(cache_key)
                        if existing_cache:
                            cached_data = json.loads(
                                existing_cache.decode('utf-8') if isinstance(existing_cache, bytes) else existing_cache
                            )
                            # Update the status in the cached entry
                            cached_data["status"] = embed_status
                            await client.set(cache_key, json.dumps(cached_data), ex=259200)  # 72 hours
                            logger.info(f"Updated operational cache for embed {embed_id} status to '{embed_status}'")
                        else:
                            logger.debug(f"No operational cache entry to update for embed {embed_id}")
            except Exception as cache_err:
                logger.warning(f"Failed to update operational cache for embed {embed_id}: {cache_err}")

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

            if request_id:
                await manager.send_personal_message(
                    {
                        "type": "store_embed_confirmed",
                        "payload": {"request_id": request_id, "embed_id": embed_id,
                                    "canonical_digest": canonical_digest,
                                    "canonical_source": "head"},
                    },
                    user_id,
                    device_fingerprint_hash,
                )

                # Clients dispatch wrappers only after accepting the exact head
                # receipt, so closure must run after that normal-success response.
                await _attempt_direct_intent_completion(
                    directus_service,
                    actor_hash=_user_hash(user_id),
                    canonical_embed=canonical_embed,
                    target_chat_id=chat_id,
                )

        except Exception as e:
            logger.error(f"Error handling store_embed for user {user_id}: {e}", exc_info=True)
            await manager.send_personal_message(
                {"type": "error", "payload": {
                    "code": "embed_storage_failed",
                    "request_id": request_id if isinstance(request_id, str) else None,
                    "message": "Failed to store embed",
                }},
                user_id,
                device_fingerprint_hash
            )
    finally:
        if _otel_span is not None:
            try:
                from backend.shared.python_utils.tracing.ws_span_helper import end_ws_handler_span as _end_span
                _end_span(_otel_span, _otel_token)
            except Exception:
                pass
