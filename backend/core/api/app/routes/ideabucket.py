"""
IdeaBucket encrypted bucket routes.

Purpose: let paired clients and SDKs add ideas to the active bucket without
accepting private cleartext on the server. The server stores normal encrypted
draft ciphertext and cache-only encrypted processing payloads.
Architecture: docs/specs/ideabucket-mvp/spec.yml.
Security: cleartext idea, prompt, transcript, markdown, and content fields are
rejected at the route boundary.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_cache_service, get_current_user
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.ideabucket_scheduled_send_service import IdeaBucketScheduledSendService


router = APIRouter(prefix="/v1/ideabucket", tags=["IdeaBucket"])

FORBIDDEN_IDEABUCKET_CLEARTEXT_KEYS = {
    "text",
    "markdown",
    "prompt",
    "content",
    "ideas",
    "transcript",
    "transcript_original",
    "transcript_corrected",
    "block_markdown_or_embed_reference",
    "server_processable_payload",
}


class IdeaBucketEncryptedAddRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chat_id: str = Field(min_length=1)
    encrypted_draft_md: str = Field(min_length=1)
    encrypted_draft_preview: str | None = None
    ideabucket: bool = True
    ideabucket_processing_window_id: str = Field(min_length=1)
    ideabucket_processing_version: int = Field(gt=0)
    scheduled_send_at: int = Field(gt=0)
    server_vault_encrypted_processing_payload: str = Field(min_length=1)
    client_encrypted_future_user_message: str = Field(min_length=1)
    client_encrypted_ideabucket_system_event: str = Field(min_length=1)
    payload_hash: str = Field(min_length=1)


class IdeaBucketProcessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    now: bool = False
    confirmation_token: str | None = None


def default_bucket_id() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def reject_ideabucket_cleartext_payload(payload: dict[str, Any]) -> None:
    """Reject fields that would carry raw private idea content."""
    present = sorted(FORBIDDEN_IDEABUCKET_CLEARTEXT_KEYS.intersection(payload.keys()))
    if present:
        raise HTTPException(
            status_code=422,
            detail={"error": "ideabucket_cleartext_rejected", "fields": present},
        )


async def store_ideabucket_encrypted_add(
    *,
    user_id: str,
    body: IdeaBucketEncryptedAddRequest,
    cache_service: CacheService,
    directus_service: DirectusService,
) -> dict[str, Any]:
    chat_id = body.chat_id
    bucket_id = body.ideabucket_processing_window_id

    try:
        is_owner = await directus_service.chat.check_chat_ownership(chat_id, user_id)
        if not is_owner and await directus_service.chat.get_chat_metadata(chat_id):
            raise HTTPException(status_code=404, detail="Chat not found")
    except HTTPException:
        raise
    except Exception as exc:
        try:
            if await directus_service.chat.get_chat_metadata(chat_id):
                raise HTTPException(status_code=404, detail="Chat not found") from exc
        except HTTPException:
            raise

    draft_v = await cache_service.increment_user_draft_version(user_id, chat_id)
    if draft_v is None:
        raise HTTPException(status_code=507, detail={"error": "draft_version_failed"})

    draft_ok = await cache_service.update_user_draft_in_cache(
        user_id,
        chat_id,
        body.encrypted_draft_md,
        draft_v,
        encrypted_draft_preview=body.encrypted_draft_preview,
    )
    metadata_ok = await cache_service.update_user_draft_metadata_in_cache(
        user_id,
        chat_id,
        ideabucket=body.ideabucket,
        ideabucket_processing_window_id=bucket_id,
    )
    processing_ok = await cache_service.replace_ideabucket_processing_window_in_cache(
        user_id,
        bucket_id,
        version=body.ideabucket_processing_version,
        chat_id=chat_id,
        scheduled_send_at=body.scheduled_send_at,
        server_vault_encrypted_processing_payload=body.server_vault_encrypted_processing_payload,
        client_encrypted_future_user_message=body.client_encrypted_future_user_message,
        client_encrypted_ideabucket_system_event=body.client_encrypted_ideabucket_system_event,
        payload_hash=body.payload_hash,
    )
    if not draft_ok or not metadata_ok or not processing_ok:
        raise HTTPException(status_code=507, detail={"error": "ideabucket_cache_write_failed"})

    now_ts = int(time.time())
    if not await cache_service.check_chat_exists_for_user(user_id, chat_id):
        await cache_service.add_chat_to_ids_versions(user_id, chat_id, now_ts)

    return {
        "success": True,
        "chat_id": chat_id,
        "bucket_id": bucket_id,
        "processing_window_id": bucket_id,
        "draft_v": draft_v,
        "ideabucket": True,
        "processing_payload_synced": True,
        "payload_hash": body.payload_hash,
    }


async def get_ideabucket_bucket_status(
    *,
    user_id: str,
    bucket_id: str,
    cache_service: CacheService,
) -> dict[str, Any]:
    window = await cache_service.get_ideabucket_processing_window_from_cache(user_id, bucket_id)
    if not window:
        return {"bucket_id": bucket_id, "processing_window_id": bucket_id, "status": "empty"}
    return {
        "bucket_id": bucket_id,
        "processing_window_id": bucket_id,
        "status": window.get("status", "active"),
        "chat_id": window.get("chat_id"),
        "scheduled_send_at": window.get("scheduled_send_at"),
        "version": window.get("version"),
        "payload_hash": window.get("payload_hash"),
        "error_code": window.get("error_code"),
    }


async def process_ideabucket_bucket(
    *,
    user_id: str,
    bucket_id: str,
    now: bool,
    cache_service: CacheService,
    directus_service: DirectusService,
) -> dict[str, Any]:
    timestamp = int(time.time()) if now else None

    async def persist_message(payload: dict[str, Any]) -> Any:
        return await directus_service.chat.create_message_in_directus(payload)

    async def persist_chat_metadata(payload: dict[str, Any]) -> bool:
        created_chat, is_duplicate = await directus_service.chat.create_chat_in_directus(payload)
        return bool(created_chat or is_duplicate)

    async def delete_processed_draft(payload: dict[str, Any]) -> bool:
        return await directus_service.chat.delete_all_drafts_for_chat(str(payload["chat_id"]))

    service = IdeaBucketScheduledSendService(
        cache_service=cache_service,
        persist_user_message=persist_message,
        persist_system_event=persist_message,
        persist_chat_metadata=persist_chat_metadata,
        delete_processed_draft=delete_processed_draft,
    )
    result = await service.process_due_window(user_id=user_id, processing_window_id=bucket_id, now=timestamp)
    result["bucket_id"] = result.get("processing_window_id", bucket_id)
    return result


@router.post("/buckets/{bucket_id}/add")
async def add_to_ideabucket_bucket(
    bucket_id: str,
    body: IdeaBucketEncryptedAddRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    cache_service: CacheService = Depends(get_cache_service),
) -> dict[str, Any]:
    raw_payload = await request.json()
    reject_ideabucket_cleartext_payload(raw_payload if isinstance(raw_payload, dict) else {})
    if body.ideabucket_processing_window_id != bucket_id:
        raise HTTPException(status_code=400, detail={"error": "bucket_id_mismatch"})
    return await store_ideabucket_encrypted_add(
        user_id=str(current_user.id),
        body=body,
        cache_service=cache_service,
        directus_service=request.app.state.directus_service,
    )


@router.get("/buckets")
async def get_default_ideabucket_bucket(
    current_user: User = Depends(get_current_user),
    cache_service: CacheService = Depends(get_cache_service),
) -> dict[str, Any]:
    return await get_ideabucket_bucket_status(user_id=str(current_user.id), bucket_id=default_bucket_id(), cache_service=cache_service)


@router.get("/buckets/{bucket_id}")
async def get_ideabucket_bucket(
    bucket_id: str,
    current_user: User = Depends(get_current_user),
    cache_service: CacheService = Depends(get_cache_service),
) -> dict[str, Any]:
    return await get_ideabucket_bucket_status(user_id=str(current_user.id), bucket_id=bucket_id, cache_service=cache_service)


@router.post("/buckets/{bucket_id}/process")
async def process_ideabucket_bucket_route(
    bucket_id: str,
    body: IdeaBucketProcessRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    cache_service: CacheService = Depends(get_cache_service),
) -> dict[str, Any]:
    return await process_ideabucket_bucket(
        user_id=str(current_user.id),
        bucket_id=bucket_id,
        now=body.now,
        cache_service=cache_service,
        directus_service=request.app.state.directus_service,
    )
