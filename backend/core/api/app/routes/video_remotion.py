# backend/core/api/app/routes/video_remotion.py
#
# REST contracts for Remotion videos.create embeds. Rendering is executed by
# Celery/E2B workers; these endpoints provide viewer-owned render dispatch,
# cancellation status updates, and version metadata for web and Apple clients.

from __future__ import annotations

import json
import hashlib
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.core.api.app.routes.auth_routes.auth_dependencies import (
    get_cache_service,
    get_current_user,
    get_directus_service,
    get_encryption_service,
)


router = APIRouter(prefix="/v1/videos/remotion", tags=["Remotion Videos"])


class RemotionRenderRequest(BaseModel):
    chat_id: str = Field(min_length=1)
    source_version: int | None = None


class RemotionStopRequest(BaseModel):
    chat_id: str = Field(min_length=1)


def send_remotion_task(name: str, args: list[Any], queue: str, **options: Any) -> Any:
    from backend.core.api.app.tasks.celery_config import app as celery_app

    return celery_app.send_task(name, args=args, queue=queue, **options)


def _decode_toon_content(plaintext_toon: str) -> dict[str, Any] | None:
    try:
        from toon_format import decode as toon_decode

        decoded = toon_decode(plaintext_toon)
    except Exception:
        try:
            decoded = json.loads(plaintext_toon)
        except json.JSONDecodeError:
            return None
    return decoded if isinstance(decoded, dict) else None


async def _load_remotion_embed_content(embed_id: str, current_user: Any, cache_service: Any, encryption_service: Any) -> dict[str, Any]:
    vault_key_id = getattr(current_user, "vault_key_id", None)
    if not vault_key_id:
        raise HTTPException(status_code=401, detail="Missing vault key")
    cached = await cache_service.get_embed_from_cache(embed_id)
    if not isinstance(cached, dict):
        raise HTTPException(status_code=404, detail="Embed not found")
    encrypted_content = cached.get("encrypted_content")
    if not isinstance(encrypted_content, str) or not encrypted_content:
        raise HTTPException(status_code=409, detail="Embed content is unavailable")
    plaintext = await encryption_service.decrypt_with_user_key(encrypted_content, vault_key_id)
    content = _decode_toon_content(plaintext) if plaintext else None
    if not isinstance(content, dict) or content.get("app_id") != "videos" or content.get("skill_id") != "create":
        raise HTTPException(status_code=400, detail="Target embed is not a Remotion video")
    return content


@router.post("/{embed_id}/render")
async def start_remotion_render(
    embed_id: str,
    body: RemotionRenderRequest,
    request: Request,
    current_user: Any = Depends(get_current_user),
    cache_service: Any = Depends(get_cache_service),
    directus_service: Any = Depends(get_directus_service),
    encryption_service: Any = Depends(get_encryption_service),
):
    content = await _load_remotion_embed_content(embed_id, current_user, cache_service, encryption_service)
    source = str(content.get("remotion_source") or "")
    if not source.strip():
        raise HTTPException(status_code=409, detail="Remotion source is empty")
    source_version = int(body.source_version or content.get("current_source_version") or 1)
    if source_version < 1:
        raise HTTPException(status_code=400, detail="Invalid source version")
    user_id = str(getattr(current_user, "id", "") or "")
    owner_hash = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    canonical = await directus_service.embed.get_sync_embed_by_id(embed_id)
    if not canonical or canonical.get("hashed_user_id") != owner_hash:
        raise HTTPException(status_code=404, detail="Embed not found")
    if canonical.get("hashed_chat_id") != hashlib.sha256(body.chat_id.encode("utf-8")).hexdigest():
        raise HTTPException(status_code=404, detail="Embed not found")
    canonical_ciphertext = canonical.get("encrypted_content")
    if not isinstance(canonical_ciphertext, str) or not canonical_ciphertext:
        raise HTTPException(status_code=409, detail="Embed content is unavailable")
    canonical_plaintext = await encryption_service.decrypt_with_user_key(
        canonical_ciphertext, getattr(current_user, "vault_key_id", ""),
    )
    canonical_content = _decode_toon_content(canonical_plaintext) if canonical_plaintext else None
    if (
        not isinstance(canonical_content, dict)
        or canonical_content.get("app_id") != "videos"
        or canonical_content.get("skill_id") != "create"
        or canonical_content.get("remotion_source") != source
    ):
        raise HTTPException(status_code=409, detail="Embed source changed")
    try:
        canonical_source_version = int(canonical_content.get("current_source_version") or 1)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="Embed source version unavailable") from exc
    if canonical_source_version != source_version:
        raise HTTPException(status_code=409, detail="Embed source version changed")
    expected_embed_version = canonical.get("version_number")
    if not isinstance(expected_embed_version, int) or expected_embed_version < 1:
        raise HTTPException(status_code=409, detail="Embed version unavailable")
    message_id = content.get("message_id")
    if not isinstance(message_id, str) or not message_id:
        raise HTTPException(status_code=409, detail="Embed message unavailable")
    if canonical_content.get("message_id") != message_id:
        raise HTTPException(status_code=409, detail="Embed message changed")
    render_id = str(uuid.uuid4())
    task_uuid = str(uuid.uuid4())
    task_name = "apps.videos.tasks.render_remotion"
    task_args = [{
        "embed_id": embed_id,
        "chat_id": body.chat_id,
        "message_id": message_id,
        "user_id": user_id,
        "user_id_hash": owner_hash,
        "vault_key_id": getattr(current_user, "vault_key_id", ""),
        "remotion_source": source,
        "filename": content.get("filename"),
        "source_version": source_version,
        "auto_started": False,
        "render_id": render_id,
    }]
    from backend.shared.python_utils.embed_producer_dispatch import (
        PRODUCER_HEADER, PRODUCER_VERSION, _transaction, bind_task_invocation,
    )
    registration = await _transaction("register_authorized_rerender", {
        "protocol_version": PRODUCER_VERSION,
        "task_uuid": task_uuid,
        "task_name": task_name,
        "kwargs_binding": bind_task_invocation(
            task_name=task_name, task_uuid=task_uuid, args=task_args, kwargs={},
        ),
        "hashed_user_id": owner_hash,
        "target_chat_id": body.chat_id,
        "primary_embed_id": embed_id,
        "primary_message_id": message_id,
        "source_version": source_version,
        "expected_embed_version": expected_embed_version,
    })
    if registration.get("producer_intent_id") != task_uuid or registration.get("status") != "DIRECT_AUTHORIZED":
        raise HTTPException(status_code=503, detail="Render authorization unavailable")
    task_sender = getattr(request.app.state, "remotion_task_sender", send_remotion_task)
    task_sender(
        task_name,
        args=task_args,
        queue="app_videos",
        task_id=task_uuid,
        headers={PRODUCER_HEADER: {"version": PRODUCER_VERSION, "intent_id": task_uuid}},
    )
    return {"render_id": render_id, "embed_id": embed_id, "source_version": source_version, "status": "rendering"}


@router.get("/{embed_id}")
async def get_remotion_embed(
    embed_id: str,
    current_user: Any = Depends(get_current_user),
    cache_service: Any = Depends(get_cache_service),
    encryption_service: Any = Depends(get_encryption_service),
):
    content = await _load_remotion_embed_content(embed_id, current_user, cache_service, encryption_service)
    return {
        "embed_id": embed_id,
        "status": content.get("status") or "processing",
        "content": content,
    }


@router.post("/{embed_id}/render/{render_id}/stop")
async def stop_remotion_render(
    embed_id: str,
    render_id: str,
    body: RemotionStopRequest,
    current_user: Any = Depends(get_current_user),
    cache_service: Any = Depends(get_cache_service),
    directus_service: Any = Depends(get_directus_service),
    encryption_service: Any = Depends(get_encryption_service),
):
    content = await _load_remotion_embed_content(embed_id, current_user, cache_service, encryption_service)
    from backend.core.api.app.services.embed_service import EmbedService

    embed_service = EmbedService(cache_service, directus_service, encryption_service)
    await embed_service.update_remotion_video_embed_content(
        embed_id=embed_id,
        remotion_source=str(content.get("remotion_source") or ""),
        chat_id=body.chat_id,
        message_id=str(content.get("message_id") or ""),
        user_id=getattr(current_user, "id", ""),
        user_id_hash=getattr(current_user, "id", ""),
        user_vault_key_id=getattr(current_user, "vault_key_id", ""),
        filename=str(content.get("filename") or "Composition.tsx"),
        status="cancelled",
        source_version=int(content.get("current_source_version") or 1),
        render_metadata={"render_id": render_id, "stopped_at": int(time.time())},
        log_prefix="[RemotionRoute]",
    )
    return {"render_id": render_id, "embed_id": embed_id, "status": "cancelled", "charged_credits": None}


@router.get("/{embed_id}/versions")
async def get_remotion_versions(
    embed_id: str,
    current_user: Any = Depends(get_current_user),
    cache_service: Any = Depends(get_cache_service),
    encryption_service: Any = Depends(get_encryption_service),
):
    content = await _load_remotion_embed_content(embed_id, current_user, cache_service, encryption_service)
    current_version = int(content.get("current_source_version") or 1)
    return {
        "versions": [
            {
                "version": current_version,
                "created_at": int(content.get("created_at") or 0),
                "status": content.get("status") or "processing",
                "has_render": bool(content.get("files")),
            }
        ]
    }
