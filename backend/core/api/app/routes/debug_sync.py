"""
Debug Sync Status Endpoint

Provides server-side sync status for chats and embeds to any authenticated user,
limited to items owned by the requesting user.

Architecture context: See docs/architecture/ for overall sync design.
Tests: backend/tests/  (no dedicated test file yet)

This endpoint powers window.debug.chat(), window.debug.embed(), and window.debug()
in the frontend debugUtils.ts, enabling immediate comparison of:
  - Client IndexedDB state (messages_v, embed count) vs.
  - Server Directus state (actual message count, messages_v) vs.
  - Server Redis cache state (cached messages_v)

Security:
  - Requires JWT session cookie authentication (same as all other user-facing endpoints)
  - Users can ONLY query items they own (ownership enforced via user_id filter)
  - Returns NO encrypted content — only version numbers, counts, and cache presence booleans
  - Rate limited to 30 req/min

Batch design:
  - Up to MAX_BATCH_SIZE (20) chat_ids or embed_ids per request
  - 100 local chats → 5 requests of 20
"""

import hashlib
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import (
    get_cache_service,
    get_current_user,
    get_directus_service,
)
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.limiter import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/debug", tags=["Debug Sync"])

# Maximum items per batch request.
# 100 chats / 20 per batch = 5 requests.
MAX_BATCH_SIZE = 20


# ============================================================================
# REQUEST / RESPONSE MODELS
# ============================================================================


class SyncStatusRequest(BaseModel):
    """
    Batch request for server sync status.

    Provide either chat_ids or embed_ids (not both in the same request).
    Maximum MAX_BATCH_SIZE items per request.
    """

    chat_ids: Optional[List[str]] = Field(
        None,
        description=f"Chat UUIDs to inspect (max {MAX_BATCH_SIZE})",
        max_length=MAX_BATCH_SIZE,
    )
    embed_ids: Optional[List[str]] = Field(
        None,
        description=f"Embed UUIDs to inspect (max {MAX_BATCH_SIZE})",
        max_length=MAX_BATCH_SIZE,
    )


class ChatSyncStatus(BaseModel):
    """
    Server-side sync status for a single chat.

    Contains only version numbers, counts, and cache presence — NO encrypted content.
    """

    chat_id: str
    # Whether the chat exists on the server at all
    found: bool
    # --- Directus DB state ---
    # Actual number of messages stored in the messages collection
    db_message_count: Optional[int] = None
    # messages_v stored in the chats table (the version counter the client syncs against)
    db_messages_v: Optional[int] = None
    # Actual number of embeds stored in the embeds collection (by hashed_chat_id)
    db_embed_count: Optional[int] = None
    # --- Redis cache state ---
    # True if a Redis cache entry exists for this chat
    cache_present: bool = False
    # messages_v stored in the Redis versions hash (what the cache thinks the version is)
    cache_messages_v: Optional[int] = None
    # --- Consistency flags ---
    # True if db_message_count matches db_messages_v (DB is internally consistent)
    db_consistent: Optional[bool] = None
    # True if db_messages_v matches cache_messages_v (DB and cache agree)
    db_cache_consistent: Optional[bool] = None


class EmbedSyncStatus(BaseModel):
    """
    Server-side sync status for a single embed.

    Contains only embed existence, key counts, and status — NO encrypted content.
    """

    embed_id: str
    # Whether the embed exists on the server at all
    found: bool
    # --- Directus DB state ---
    # Embed status field (e.g. "finished", "processing", "error")
    db_status: Optional[str] = None
    # Number of embed_keys records for this embed (chat-type + master-type)
    db_key_count: Optional[int] = None
    # Number of chat-type keys
    db_chat_key_count: Optional[int] = None
    # Number of master-type keys
    db_master_key_count: Optional[int] = None


class SyncStatusResponse(BaseModel):
    """Response for the batch sync status request."""

    success: bool
    chats: List[ChatSyncStatus] = Field(default_factory=list)
    embeds: List[EmbedSyncStatus] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


# ============================================================================
# HELPERS
# ============================================================================


async def _get_chat_sync_status(
    chat_id: str,
    user_id: str,
    hashed_user_id: str,
    directus_service: DirectusService,
    cache_service: CacheService,
) -> ChatSyncStatus:
    """
    Fetch server-side sync status for a single chat.

    Enforces ownership: only returns data when the chat's hashed_user_id matches
    the requesting user's hashed ID. Returns found=False (no data leakage) when
    not owned.

    Args:
        user_id: Raw Directus user UUID — used for Redis cache key lookups.
        hashed_user_id: SHA-256 hex digest of user_id — used for Directus
            ownership filter (chats table stores hashed_user_id, not raw UUID).
    """
    try:
        # Fetch chat metadata — filter by both id AND hashed_user_id for ownership check.
        # The chats table stores hashed_user_id (SHA-256 of the Directus UUID),
        # not the raw user_id. This is the critical security guard: if the chat
        # exists but belongs to another user, this returns an empty list and we
        # return found=False.
        chat_params = {
            "filter[id][_eq]": chat_id,
            "filter[hashed_user_id][_eq]": hashed_user_id,
            "fields": "id,messages_v",
            "limit": 1,
        }
        chats = await directus_service.get_items("chats", chat_params, no_cache=True)

        if not chats:
            # Chat doesn't exist OR belongs to another user — treat identically.
            return ChatSyncStatus(chat_id=chat_id, found=False)

        chat = chats[0]
        db_messages_v_raw = chat.get("messages_v")
        db_messages_v = int(db_messages_v_raw) if db_messages_v_raw is not None else None

        # Count actual messages for this chat
        message_count_params = {
            "filter[chat_id][_eq]": chat_id,
            "aggregate[count]": "id",
        }
        message_count_result = await directus_service.get_items(
            "messages", message_count_params, no_cache=True
        )
        db_message_count: Optional[int] = None
        if message_count_result and isinstance(message_count_result, list) and len(message_count_result) > 0:
            raw_count = message_count_result[0].get("count", {})
            if isinstance(raw_count, dict):
                # Directus returns {"count": {"id": "42"}} for aggregate
                count_val = raw_count.get("id")
                db_message_count = int(count_val) if count_val is not None else None
            elif raw_count is not None:
                db_message_count = int(raw_count)

        # Count embeds using hashed_chat_id
        hashed_chat_id = hashlib.sha256(chat_id.encode()).hexdigest()
        embed_count_params = {
            "filter[hashed_chat_id][_eq]": hashed_chat_id,
            "aggregate[count]": "id",
        }
        embed_count_result = await directus_service.get_items(
            "embeds", embed_count_params, no_cache=True
        )
        db_embed_count: Optional[int] = None
        if embed_count_result and isinstance(embed_count_result, list) and len(embed_count_result) > 0:
            raw_ecount = embed_count_result[0].get("count", {})
            if isinstance(raw_ecount, dict):
                ecount_val = raw_ecount.get("id")
                db_embed_count = int(ecount_val) if ecount_val is not None else None
            elif raw_ecount is not None:
                db_embed_count = int(raw_ecount)

        # Check Redis cache for this chat
        cache_present = False
        cache_messages_v: Optional[int] = None
        try:
            client = await cache_service.client
            if client:
                # Look up the versions hash — key pattern: user:{user_id}:chat:{chat_id}:versions
                versions_key = f"user:{user_id}:chat:{chat_id}:versions"
                versions_data = await client.hgetall(versions_key)
                if versions_data:
                    cache_present = True
                    raw_v = versions_data.get(b"messages_v") or versions_data.get("messages_v")
                    if raw_v is not None:
                        v_str = raw_v.decode("utf-8") if isinstance(raw_v, bytes) else str(raw_v)
                        cache_messages_v = int(v_str) if v_str.isdigit() else None
        except Exception as cache_err:
            logger.warning(
                f"[debug_sync] Redis cache lookup failed for chat {chat_id}: {cache_err}"
            )

        # Compute consistency flags
        db_consistent: Optional[bool] = None
        if db_message_count is not None and db_messages_v is not None:
            db_consistent = db_message_count == db_messages_v

        db_cache_consistent: Optional[bool] = None
        if cache_present and db_messages_v is not None and cache_messages_v is not None:
            db_cache_consistent = db_messages_v == cache_messages_v

        return ChatSyncStatus(
            chat_id=chat_id,
            found=True,
            db_message_count=db_message_count,
            db_messages_v=db_messages_v,
            db_embed_count=db_embed_count,
            cache_present=cache_present,
            cache_messages_v=cache_messages_v,
            db_consistent=db_consistent,
            db_cache_consistent=db_cache_consistent,
        )

    except Exception as e:
        logger.error(
            f"[debug_sync] Error fetching chat sync status for {chat_id} "
            f"(user={user_id}): {e}",
            exc_info=True,
        )
        raise


async def _get_embed_sync_status(
    embed_id: str,
    hashed_user_id: str,
    directus_service: DirectusService,
) -> EmbedSyncStatus:
    """
    Fetch server-side sync status for a single embed.

    Ownership is verified via the embed's hashed_user_id field.
    Returns only status and key counts — NO encrypted content.

    Args:
        hashed_user_id: SHA-256 hex digest of the Directus user UUID — used for
            the ownership filter (embeds table stores hashed_user_id).
    """
    try:
        # Fetch embed metadata with ownership check.
        # The embeds table stores hashed_user_id (SHA-256 of the Directus UUID),
        # not the raw user_id.
        embed_params = {
            "filter[id][_eq]": embed_id,
            "filter[hashed_user_id][_eq]": hashed_user_id,
            "fields": "id,status",
            "limit": 1,
        }
        embeds = await directus_service.get_items("embeds", embed_params, no_cache=True)

        if not embeds:
            return EmbedSyncStatus(embed_id=embed_id, found=False)

        embed = embeds[0]
        db_status = embed.get("status")

        # Count embed keys (chat-type and master-type)
        hashed_embed_id = hashlib.sha256(embed_id.encode()).hexdigest()

        # Total key count
        key_count_params = {
            "filter[hashed_embed_id][_eq]": hashed_embed_id,
            "aggregate[count]": "id",
        }
        key_count_result = await directus_service.get_items(
            "embed_keys", key_count_params, no_cache=True
        )
        db_key_count: Optional[int] = None
        if key_count_result and isinstance(key_count_result, list) and len(key_count_result) > 0:
            raw_kc = key_count_result[0].get("count", {})
            if isinstance(raw_kc, dict):
                kc_val = raw_kc.get("id")
                db_key_count = int(kc_val) if kc_val is not None else None
            elif raw_kc is not None:
                db_key_count = int(raw_kc)

        # Chat-type key count
        chat_key_params = {
            "filter[hashed_embed_id][_eq]": hashed_embed_id,
            "filter[key_type][_eq]": "chat",
            "aggregate[count]": "id",
        }
        chat_key_result = await directus_service.get_items(
            "embed_keys", chat_key_params, no_cache=True
        )
        db_chat_key_count: Optional[int] = None
        if chat_key_result and isinstance(chat_key_result, list) and len(chat_key_result) > 0:
            raw_ck = chat_key_result[0].get("count", {})
            if isinstance(raw_ck, dict):
                ck_val = raw_ck.get("id")
                db_chat_key_count = int(ck_val) if ck_val is not None else None
            elif raw_ck is not None:
                db_chat_key_count = int(raw_ck)

        # Master-type key count
        master_key_params = {
            "filter[hashed_embed_id][_eq]": hashed_embed_id,
            "filter[key_type][_eq]": "master",
            "aggregate[count]": "id",
        }
        master_key_result = await directus_service.get_items(
            "embed_keys", master_key_params, no_cache=True
        )
        db_master_key_count: Optional[int] = None
        if master_key_result and isinstance(master_key_result, list) and len(master_key_result) > 0:
            raw_mk = master_key_result[0].get("count", {})
            if isinstance(raw_mk, dict):
                mk_val = raw_mk.get("id")
                db_master_key_count = int(mk_val) if mk_val is not None else None
            elif raw_mk is not None:
                db_master_key_count = int(raw_mk)

        return EmbedSyncStatus(
            embed_id=embed_id,
            found=True,
            db_status=db_status,
            db_key_count=db_key_count,
            db_chat_key_count=db_chat_key_count,
            db_master_key_count=db_master_key_count,
        )

    except Exception as e:
        logger.error(
            f"[debug_sync] Error fetching embed sync status for {embed_id} "
            f"(hashed_user={hashed_user_id[:12]}...): {e}",
            exc_info=True,
        )
        raise


# ============================================================================
# ENDPOINT
# ============================================================================


@router.post("/sync", response_model=SyncStatusResponse)
@limiter.limit("30/minute")
async def get_sync_status(
    request: Request,
    body: SyncStatusRequest,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
) -> SyncStatusResponse:
    """
    Batch server-side sync status for chats or embeds.

    Returns version numbers, message/embed counts, and cache presence for each
    requested item — enough to detect sync drift, missing cache entries, and
    missing embed keys WITHOUT returning any encrypted content.

    Security: Only returns data for items owned by the requesting user.
    Items that don't exist or belong to another user are returned with found=False.

    Usage (from browser console / window.debug):
        await fetch('/v1/debug/sync', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ chat_ids: ['uuid-1', 'uuid-2', ...] }),
            credentials: 'include'
        }).then(r => r.json())
    """
    errors: List[str] = []

    # Validate batch sizes
    chat_ids = body.chat_ids or []
    embed_ids = body.embed_ids or []

    if len(chat_ids) > MAX_BATCH_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Too many chat_ids: max {MAX_BATCH_SIZE} per request, got {len(chat_ids)}",
        )
    if len(embed_ids) > MAX_BATCH_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Too many embed_ids: max {MAX_BATCH_SIZE} per request, got {len(embed_ids)}",
        )
    if not chat_ids and not embed_ids:
        raise HTTPException(
            status_code=400,
            detail="Provide at least one chat_id or embed_id",
        )

    user_id = current_user.id
    # The chats and embeds tables store hashed_user_id (SHA-256 of the Directus
    # UUID), not the raw user_id. Hash once here and pass to helper functions.
    hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
    logger.debug(
        f"[debug_sync] User {user_id} requesting sync status: "
        f"{len(chat_ids)} chats, {len(embed_ids)} embeds"
    )

    # Process chats
    chat_statuses: List[ChatSyncStatus] = []
    for chat_id in chat_ids:
        if not chat_id or not isinstance(chat_id, str):
            errors.append(f"Invalid chat_id: {chat_id!r}")
            continue
        try:
            status = await _get_chat_sync_status(
                chat_id=chat_id.strip(),
                user_id=user_id,
                hashed_user_id=hashed_user_id,
                directus_service=directus_service,
                cache_service=cache_service,
            )
            chat_statuses.append(status)
        except Exception as e:
            errors.append(f"chat {chat_id}: {str(e)}")
            chat_statuses.append(ChatSyncStatus(chat_id=chat_id, found=False))

    # Process embeds
    embed_statuses: List[EmbedSyncStatus] = []
    for embed_id in embed_ids:
        if not embed_id or not isinstance(embed_id, str):
            errors.append(f"Invalid embed_id: {embed_id!r}")
            continue
        try:
            status = await _get_embed_sync_status(
                embed_id=embed_id.strip(),
                hashed_user_id=hashed_user_id,
                directus_service=directus_service,
            )
            embed_statuses.append(status)
        except Exception as e:
            errors.append(f"embed {embed_id}: {str(e)}")
            embed_statuses.append(EmbedSyncStatus(embed_id=embed_id, found=False))

    return SyncStatusResponse(
        success=True,
        chats=chat_statuses,
        embeds=embed_statuses,
        errors=errors,
    )
