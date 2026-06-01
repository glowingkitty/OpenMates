# backend/core/api/app/routes/sync_api.py
#
# Native/desktop sync endpoints for optional offline availability.
#
# Architecture:
#   - Startup sync stays bounded to the 10 most recent parent chats.
#   - This API hydrates older parent chats in small resumable chunks for clients
#     that have explicit offline-storage capability.
#   - Sub-chat content is excluded; sub-chats hydrate on demand when opened.
#
# Security:
#   - Requires the same authenticated session as the web app.
#   - Returns encrypted payloads only; message/embed plaintext is never exposed.
#   - Chat ownership is enforced by fetching only the current user's chat list.

from __future__ import annotations

import hashlib
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import (
    get_cache_service,
    get_current_user,
    get_directus_service,
)
from backend.core.api.app.routes.handlers.websocket_handlers.chat_compression_checkpoint_handler import (
    get_latest_chat_compression_checkpoint,
)
from backend.core.api.app.routes.handlers.websocket_handlers.chat_content_batch_handler import (
    _fetch_code_run_outputs_for_chats,
)
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.limiter import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/sync", tags=["Sync"])

OFFLINE_PREFETCH_START_OFFSET = 10
OFFLINE_PREFETCH_END_OFFSET = 99
OFFLINE_PREFETCH_MAX_LIMIT = 5
OFFLINE_PREFETCH_SCAN_MULTIPLIER = 3


class OfflinePrefetchRequest(BaseModel):
    """Request a resumable encrypted offline-content chunk."""

    cursor: int | None = Field(
        default=None,
        ge=OFFLINE_PREFETCH_START_OFFSET,
        le=OFFLINE_PREFETCH_END_OFFSET + 1,
        description="Absolute parent-chat cursor. Defaults to the first chat after startup sync.",
    )
    limit: int = Field(
        default=3,
        ge=1,
        le=OFFLINE_PREFETCH_MAX_LIMIT,
        description="Maximum parent chats to hydrate in this chunk.",
    )
    include_embeds: bool = Field(
        default=True,
        description="Include encrypted embed records and keys referenced by returned parent chats.",
    )


class OfflinePrefetchResponse(BaseModel):
    """Encrypted offline prefetch response for native/desktop clients."""

    chats: list[dict[str, Any]] = Field(default_factory=list)
    messages_by_chat_id: dict[str, list[str]] = Field(default_factory=dict)
    versions_by_chat_id: dict[str, dict[str, int]] = Field(default_factory=dict)
    compression_checkpoints_by_chat_id: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    embeds: list[dict[str, Any]] = Field(default_factory=list)
    embed_keys: list[dict[str, Any]] = Field(default_factory=list)
    code_run_outputs: list[dict[str, Any]] = Field(default_factory=list)
    next_cursor: int | None = None
    done: bool = False


def _is_parent_chat(chat_details: dict[str, Any]) -> bool:
    return not chat_details.get("is_sub_chat") and not chat_details.get("parent_id")


async def build_offline_prefetch_chunk(
    *,
    user_id: str,
    cursor: int,
    limit: int,
    include_embeds: bool,
    cache_service: CacheService,
    directus_service: DirectusService,
) -> OfflinePrefetchResponse:
    """Build one encrypted parent-chat offline chunk without touching startup sync."""

    cursor = max(cursor, OFFLINE_PREFETCH_START_OFFSET)
    if cursor > OFFLINE_PREFETCH_END_OFFSET:
        return OfflinePrefetchResponse(done=True)

    selected_chats: list[dict[str, Any]] = []
    selected_chat_ids: list[str] = []
    scan_cursor = cursor
    next_cursor_candidate = cursor

    while len(selected_chats) < limit and scan_cursor <= OFFLINE_PREFETCH_END_OFFSET:
        scan_limit = min(
            max(limit * OFFLINE_PREFETCH_SCAN_MULTIPLIER, limit),
            OFFLINE_PREFETCH_END_OFFSET - scan_cursor + 1,
        )
        rows = await directus_service.chat.get_core_chats_and_user_drafts_for_cache_warming(
            user_id,
            limit=scan_limit,
            offset=scan_cursor,
        )
        if not rows:
            break

        for index, wrapper in enumerate(rows):
            next_cursor_candidate = scan_cursor + index + 1
            chat_details = wrapper.get("chat_details") if isinstance(wrapper, dict) else None
            if not isinstance(chat_details, dict) or not _is_parent_chat(chat_details):
                continue
            chat_id = chat_details.get("id")
            if not chat_id:
                continue
            selected_chats.append(chat_details)
            selected_chat_ids.append(str(chat_id))
            if len(selected_chats) >= limit:
                break
        scan_cursor += scan_limit

    messages_by_chat_id: dict[str, list[str]] = {}
    versions_by_chat_id: dict[str, dict[str, int]] = {}
    compression_checkpoints_by_chat_id: dict[str, list[dict[str, Any]]] = {}
    hashed_chat_ids: list[str] = []
    user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()

    for chat_id in selected_chat_ids:
        messages = await cache_service.get_sync_messages_history(user_id, chat_id)
        if not messages:
            messages = await directus_service.chat.get_all_messages_for_chat(
                chat_id=chat_id,
                decrypt_content=False,
            ) or []
        messages_by_chat_id[chat_id] = messages

        server_versions = await cache_service.get_chat_versions(user_id, chat_id)
        messages_v = server_versions.messages_v if server_versions and server_versions.messages_v is not None else 0
        effective_messages_v = max(messages_v, len(messages))
        versions_by_chat_id[chat_id] = {
            "messages_v": effective_messages_v,
            "server_message_count": len(messages),
        }

        checkpoint = await get_latest_chat_compression_checkpoint(
            directus_service,
            chat_id,
            user_id_hash,
        )
        if checkpoint:
            compression_checkpoints_by_chat_id[chat_id] = [checkpoint]
        hashed_chat_ids.append(hashlib.sha256(chat_id.encode()).hexdigest())

    embeds: list[dict[str, Any]] = []
    embed_keys: list[dict[str, Any]] = []
    if include_embeds and selected_chat_ids:
        seen_embed_ids: set[str] = set()
        seen_key_ids: set[str] = set()
        for chat_id, hashed_chat_id in zip(selected_chat_ids, hashed_chat_ids):
            raw_embeds = await cache_service.get_sync_embeds_for_chat(chat_id)
            if not raw_embeds:
                raw_embeds = await directus_service.embed.get_embeds_by_hashed_chat_id(hashed_chat_id)
            for embed in raw_embeds or []:
                embed_id = embed.get("embed_id")
                embed_status = embed.get("status")
                if embed_id and embed_id not in seen_embed_ids and embed_status not in ("error", "cancelled"):
                    embeds.append(embed)
                    seen_embed_ids.add(embed_id)

        batch_keys = await directus_service.embed.get_embed_keys_by_hashed_chat_ids_batch(hashed_chat_ids)
        for key_entry in batch_keys or []:
            key_id = key_entry.get("id")
            if key_id and key_id not in seen_key_ids:
                embed_keys.append(key_entry)
                seen_key_ids.add(key_id)

    code_run_outputs = await _fetch_code_run_outputs_for_chats(
        directus_service,
        selected_chat_ids,
        user_id,
    )

    done = next_cursor_candidate > OFFLINE_PREFETCH_END_OFFSET or not selected_chat_ids
    return OfflinePrefetchResponse(
        chats=selected_chats,
        messages_by_chat_id=messages_by_chat_id,
        versions_by_chat_id=versions_by_chat_id,
        compression_checkpoints_by_chat_id=compression_checkpoints_by_chat_id,
        embeds=embeds,
        embed_keys=embed_keys,
        code_run_outputs=code_run_outputs,
        next_cursor=None if done else next_cursor_candidate,
        done=done,
    )


@router.post("/offline-prefetch", response_model=OfflinePrefetchResponse)
@limiter.limit("30/minute")
async def offline_prefetch(
    payload: OfflinePrefetchRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    cache_service: CacheService = Depends(get_cache_service),
    directus_service: DirectusService = Depends(get_directus_service),
) -> OfflinePrefetchResponse:
    """Return encrypted content chunks for optional native/desktop offline sync."""

    cursor = payload.cursor or OFFLINE_PREFETCH_START_OFFSET
    response = await build_offline_prefetch_chunk(
        user_id=current_user.id,
        cursor=cursor,
        limit=payload.limit,
        include_embeds=payload.include_embeds,
        cache_service=cache_service,
        directus_service=directus_service,
    )
    logger.info(
        "Offline prefetch user=%s cursor=%s next=%s chats=%s messages=%s embeds=%s done=%s",
        current_user.id[:8],
        cursor,
        response.next_cursor,
        len(response.chats),
        sum(len(messages) for messages in response.messages_by_chat_id.values()),
        len(response.embeds),
        response.done,
    )
    return response
