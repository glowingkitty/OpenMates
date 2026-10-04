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

from fastapi import APIRouter, Depends, HTTPException, Request
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
from backend.core.api.app.routes.handlers.websocket_handlers.sync_sidecar_hydration import (
    load_sync_sidecar_window,
    load_sync_sidecars_for_chats,
)
from backend.core.api.app.routes.handlers.websocket_handlers.sync_message_hydration import (
    load_bounded_sync_message_window,
)
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.chat_message_archive_service import ChatMessageArchiveService
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
    message_chat_id: str | None = Field(
        default=None,
        description="Request the next encrypted message page for this owned chat.",
    )
    before_timestamp: int | None = Field(default=None, ge=0)
    before_message_id: str | None = None
    embed_chat_id: str | None = Field(default=None, description="Request older encrypted embeds for this owned chat.")
    before_embed_created_at: int | None = Field(default=None, ge=0)
    before_embed_id: str | None = None
    sidecar_chat_id: str | None = None
    sidecar_kind: str | None = None
    before_sidecar_updated_at: int | None = Field(default=None, ge=0)
    before_sidecar_id: str | None = None
    wrapper_chat_id: str | None = None
    before_wrapper_id: str | None = None
    wrapper_id: str | None = None


class OfflinePrefetchResponse(BaseModel):
    """Encrypted offline prefetch response for native/desktop clients."""

    chats: list[dict[str, Any]] = Field(default_factory=list)
    messages_by_chat_id: dict[str, list[str]] = Field(default_factory=dict)
    versions_by_chat_id: dict[str, dict[str, int]] = Field(default_factory=dict)
    message_windows_by_chat_id: dict[str, dict[str, Any]] = Field(default_factory=dict)
    embed_windows_by_chat_id: dict[str, dict[str, Any]] = Field(default_factory=dict)
    embed_key_windows_by_chat_id: dict[str, dict[str, Any]] = Field(default_factory=dict)
    compression_checkpoints_by_chat_id: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    embeds: list[dict[str, Any]] = Field(default_factory=list)
    embed_keys: list[dict[str, Any]] = Field(default_factory=list)
    chat_key_wrappers: list[dict[str, Any]] = Field(default_factory=list)
    code_run_outputs: list[dict[str, Any]] = Field(default_factory=list)
    notebook_run_outputs: list[dict[str, Any]] = Field(default_factory=list)
    code_run_output_windows_by_chat_id: dict[str, dict[str, Any]] = Field(default_factory=dict)
    notebook_run_output_windows_by_chat_id: dict[str, dict[str, Any]] = Field(default_factory=dict)
    chat_key_wrapper_windows_by_chat_id: dict[str, dict[str, Any]] = Field(default_factory=dict)
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
    message_chat_id: str | None = None,
    before_timestamp: int | None = None,
    before_message_id: str | None = None,
    embed_chat_id: str | None = None,
    before_embed_created_at: int | None = None,
    before_embed_id: str | None = None,
    archive_service: ChatMessageArchiveService | None = None,
    sidecar_chat_id: str | None = None,
    sidecar_kind: str | None = None,
    before_sidecar_updated_at: int | None = None,
    before_sidecar_id: str | None = None,
    wrapper_chat_id: str | None = None,
    before_wrapper_id: str | None = None,
    wrapper_id: str | None = None,
) -> OfflinePrefetchResponse:
    """Build one encrypted parent-chat offline chunk without touching startup sync."""

    if sum(bool(value) for value in (message_chat_id, embed_chat_id, sidecar_chat_id, wrapper_chat_id)) > 1:
        raise HTTPException(status_code=422, detail="Request one continuation type at a time")

    if wrapper_chat_id is not None:
        if bool(before_wrapper_id) == bool(wrapper_id):
            raise HTTPException(status_code=422, detail="Specify a wrapper cursor or one wrapper id")
        if not await directus_service.chat.check_chat_ownership(wrapper_chat_id, user_id):
            raise HTTPException(status_code=404, detail="Chat not found")
        if wrapper_id:
            wrapper = await directus_service.chat_key_wrapper.get_sync_wrapper_by_id(
                hashlib.sha256(wrapper_chat_id.encode()).hexdigest(), wrapper_id,
                hashed_user_id=hashlib.sha256(user_id.encode()).hexdigest(),
            )
            if wrapper is None:
                raise HTTPException(status_code=404, detail="Wrapper not found")
            return OfflinePrefetchResponse(chat_key_wrappers=[wrapper], done=True)
        page = await directus_service.chat_key_wrapper.get_sync_wrapper_window_for_chat(
            hashlib.sha256(wrapper_chat_id.encode()).hexdigest(),
            hashed_user_id=hashlib.sha256(user_id.encode()).hexdigest(),
            before_id=before_wrapper_id,
        )
        return OfflinePrefetchResponse(
            chat_key_wrappers=page["wrappers"],
            chat_key_wrapper_windows_by_chat_id={wrapper_chat_id: {
                "has_more_before": page["has_more_before"],
                "start_cursor": page["start_cursor"],
                "oversized_wrapper_id": page["oversized_wrapper_id"],
            }},
            done=True,
        )

    if sidecar_chat_id is not None:
        if sidecar_kind not in {"code_run_outputs", "notebook_run_outputs"}:
            raise HTTPException(status_code=422, detail="Unsupported sidecar kind")
        if before_sidecar_updated_at is None or not before_sidecar_id:
            raise HTTPException(status_code=422, detail="Sidecar continuation requires a complete before cursor")
        if not await directus_service.chat.check_chat_ownership(sidecar_chat_id, user_id):
            raise HTTPException(status_code=404, detail="Chat not found")
        page = await load_sync_sidecar_window(
            directus_service,
            collection=sidecar_kind,
            chat_id=sidecar_chat_id,
            user_id=user_id,
            before_updated_at=before_sidecar_updated_at,
            before_id=before_sidecar_id,
        )
        window = {
            "has_more_before": page["has_more_before"],
            "start_cursor": page["start_cursor"],
            "oversized_output": page["oversized_output"],
        }
        if sidecar_kind == "code_run_outputs":
            return OfflinePrefetchResponse(
                code_run_outputs=page["outputs"],
                code_run_output_windows_by_chat_id={sidecar_chat_id: window}, done=True,
            )
        return OfflinePrefetchResponse(
            notebook_run_outputs=page["outputs"],
            notebook_run_output_windows_by_chat_id={sidecar_chat_id: window}, done=True,
        )

    if message_chat_id is not None:
        if before_timestamp is None or not before_message_id:
            raise HTTPException(status_code=422, detail="Message continuation requires a complete before cursor")
        if not await directus_service.chat.check_chat_ownership(message_chat_id, user_id):
            raise HTTPException(status_code=404, detail="Chat not found")
        window = await load_bounded_sync_message_window(
            cache_service=cache_service,
            directus_service=directus_service,
            user_id=user_id,
            chat_id=message_chat_id,
            log_prefix="[OFFLINE_PREFETCH_CONTINUATION]",
            before_timestamp=before_timestamp,
            before_message_id=before_message_id,
            archive_service=archive_service,
        )
        return OfflinePrefetchResponse(
            messages_by_chat_id={message_chat_id: window["messages"]},
            versions_by_chat_id={message_chat_id: {
                "messages_v": window["server_message_count"],
                "server_message_count": window["server_message_count"],
            }},
            message_windows_by_chat_id={message_chat_id: {
                "has_more_before": window["has_more_before"],
                "start_cursor": window["start_cursor"],
                "oversized_message": window["oversized_message"],
                "oversized_message_cursor": window.get("oversized_message_cursor"),
            }},
            done=True,
        )

    if embed_chat_id is not None:
        if before_embed_created_at is None or not before_embed_id:
            raise HTTPException(status_code=422, detail="Embed continuation requires a complete before cursor")
        if not await directus_service.chat.check_chat_ownership(embed_chat_id, user_id):
            raise HTTPException(status_code=404, detail="Chat not found")
        hashed_chat_id = hashlib.sha256(embed_chat_id.encode()).hexdigest()
        hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
        embed_window = await directus_service.embed.get_embed_window_by_hashed_chat_id(
            hashed_chat_id,
            before_created_at=before_embed_created_at,
            before_id=before_embed_id,
        )
        rows = embed_window["embeds"]
        hashed_embed_ids = [
            row.get("hashed_embed_id") or hashlib.sha256(row["embed_id"].encode()).hexdigest()
            for row in rows if row.get("embed_id")
        ]
        key_window = await directus_service.embed.get_sync_embed_key_window_for_page(
            hashed_chat_id, hashed_user_id, hashed_embed_ids,
        )
        keys = key_window["embed_keys"]
        key_metadata = {**key_window, "embed_ids": [row["embed_id"] for row in rows if row.get("embed_id")]}
        key_metadata.pop("embed_keys")
        return OfflinePrefetchResponse(
            embeds=rows,
            embed_keys=keys,
            embed_key_windows_by_chat_id={embed_chat_id: key_metadata},
            embed_windows_by_chat_id={embed_chat_id: {
                "has_more_before": embed_window["has_more_before"],
                "start_cursor": embed_window["start_cursor"],
                "oversized_embed_id": embed_window["oversized_embed_id"],
                "oversized_embed_cursor": embed_window.get("oversized_embed_cursor"),
            }},
            done=True,
        )

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
    message_windows_by_chat_id: dict[str, dict[str, Any]] = {}
    versions_by_chat_id: dict[str, dict[str, int]] = {}
    compression_checkpoints_by_chat_id: dict[str, list[dict[str, Any]]] = {}
    hashed_chat_ids: list[str] = []
    user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()

    for chat_id in selected_chat_ids:
        window = await load_bounded_sync_message_window(
            cache_service=cache_service,
            directus_service=directus_service,
            user_id=user_id,
            chat_id=chat_id,
            log_prefix="[OFFLINE_PREFETCH]",
            archive_service=archive_service,
        )
        messages_by_chat_id[chat_id] = window["messages"]
        server_message_count = window["server_message_count"]
        message_windows_by_chat_id[chat_id] = {
            "has_more_before": window["has_more_before"],
            "start_cursor": window["start_cursor"],
            "oversized_message": window["oversized_message"],
            "oversized_message_cursor": window.get("oversized_message_cursor"),
        }

        server_versions = await cache_service.get_chat_versions(user_id, chat_id)
        messages_v = server_versions.messages_v if server_versions and server_versions.messages_v is not None else 0
        effective_messages_v = max(messages_v, server_message_count)
        versions_by_chat_id[chat_id] = {
            "messages_v": effective_messages_v,
            "server_message_count": server_message_count,
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
    embed_windows_by_chat_id: dict[str, dict[str, Any]] = {}
    embed_key_windows_by_chat_id: dict[str, dict[str, Any]] = {}
    chat_key_wrappers: list[dict[str, Any]] = []
    if include_embeds and selected_chat_ids:
        seen_embed_ids: set[str] = set()
        seen_key_ids: set[str] = set()
        for chat_id, hashed_chat_id in zip(selected_chat_ids, hashed_chat_ids):
            embed_window = await directus_service.embed.get_embed_window_by_hashed_chat_id(hashed_chat_id)
            raw_embeds = embed_window["embeds"]
            embed_windows_by_chat_id[chat_id] = {
                "has_more_before": embed_window["has_more_before"],
                "start_cursor": embed_window["start_cursor"],
                "oversized_embed_id": embed_window["oversized_embed_id"],
                "oversized_embed_cursor": embed_window.get("oversized_embed_cursor"),
            }
            hashed_embed_ids = [
                embed.get("hashed_embed_id") or hashlib.sha256(embed["embed_id"].encode()).hexdigest()
                for embed in raw_embeds if embed.get("embed_id")
            ]
            key_window = await directus_service.embed.get_sync_embed_key_window_for_page(
                hashed_chat_id, user_id_hash, hashed_embed_ids,
            )
            page_keys = key_window["embed_keys"]
            embed_key_windows_by_chat_id[chat_id] = {**key_window, "embed_ids": [row["embed_id"] for row in raw_embeds if row.get("embed_id")]}
            embed_key_windows_by_chat_id[chat_id].pop("embed_keys")
            for embed in raw_embeds:
                embed_id = embed.get("embed_id")
                embed_status = embed.get("status")
                if embed_id and embed_id not in seen_embed_ids and embed_status not in ("error", "cancelled"):
                    embeds.append(embed)
                    seen_embed_ids.add(embed_id)
            for key_entry in page_keys:
                key_id = key_entry.get("id")
                if key_id and key_id not in seen_key_ids:
                    embed_keys.append(key_entry)
                    seen_key_ids.add(key_id)

    wrapper_windows: dict[str, dict[str, Any]] = {}
    for chat_id, hashed_chat_id in zip(selected_chat_ids, hashed_chat_ids):
        page = await directus_service.chat_key_wrapper.get_sync_wrapper_window_for_chat(
            hashed_chat_id, hashed_user_id=user_id_hash,
        )
        chat_key_wrappers.extend(page["wrappers"])
        wrapper_windows[chat_id] = {
            "has_more_before": page["has_more_before"],
            "start_cursor": page["start_cursor"],
            "oversized_wrapper_id": page["oversized_wrapper_id"],
        }

    code_run_outputs, code_windows = await load_sync_sidecars_for_chats(
        directus_service, collection="code_run_outputs", chat_ids=selected_chat_ids, user_id=user_id,
    )
    notebook_run_outputs, notebook_windows = await load_sync_sidecars_for_chats(
        directus_service, collection="notebook_run_outputs", chat_ids=selected_chat_ids, user_id=user_id,
    )

    done = next_cursor_candidate > OFFLINE_PREFETCH_END_OFFSET or not selected_chat_ids
    return OfflinePrefetchResponse(
        chats=selected_chats,
        messages_by_chat_id=messages_by_chat_id,
        message_windows_by_chat_id=message_windows_by_chat_id,
        embed_windows_by_chat_id=embed_windows_by_chat_id,
        embed_key_windows_by_chat_id=embed_key_windows_by_chat_id,
        versions_by_chat_id=versions_by_chat_id,
        compression_checkpoints_by_chat_id=compression_checkpoints_by_chat_id,
        embeds=embeds,
        embed_keys=embed_keys,
        chat_key_wrappers=chat_key_wrappers,
        chat_key_wrapper_windows_by_chat_id=wrapper_windows,
        code_run_outputs=code_run_outputs,
        notebook_run_outputs=notebook_run_outputs,
        code_run_output_windows_by_chat_id=code_windows,
        notebook_run_output_windows_by_chat_id=notebook_windows,
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
        message_chat_id=payload.message_chat_id,
        before_timestamp=payload.before_timestamp,
        before_message_id=payload.before_message_id,
        embed_chat_id=payload.embed_chat_id,
        before_embed_created_at=payload.before_embed_created_at,
        before_embed_id=payload.before_embed_id,
        archive_service=ChatMessageArchiveService(
            directus_service=directus_service,
            s3_service=getattr(request.app.state, "s3_service", None),
        ),
        sidecar_chat_id=payload.sidecar_chat_id,
        sidecar_kind=payload.sidecar_kind,
        before_sidecar_updated_at=payload.before_sidecar_updated_at,
        before_sidecar_id=payload.before_sidecar_id,
        wrapper_chat_id=payload.wrapper_chat_id,
        before_wrapper_id=payload.before_wrapper_id,
        wrapper_id=payload.wrapper_id,
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
