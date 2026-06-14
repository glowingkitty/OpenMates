# backend/apps/videos/tasks/render_remotion_task.py
#
# Celery task for code-backed Remotion video rendering. Generated MP4 and
# thumbnail files are rendered inside E2B, encrypted for chat-file storage, and
# attached back to the source-backed videos.create embed.

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.apps.videos.remotion_billing import calculate_remotion_render_credits
from backend.core.api.app.services.s3.config import get_bucket_name
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app
from backend.shared.providers.e2b_code_runner import get_e2b_api_key_async
from backend.shared.providers.e2b_remotion_renderer import render_remotion_in_e2b
from backend.shared.python_utils.generated_assets import (
    cache_s3_file_keys,
    index_generated_asset,
)


logger = logging.getLogger(__name__)

INTERNAL_API_BASE_URL = os.getenv("INTERNAL_API_BASE_URL", "http://api:8000")
INTERNAL_API_SHARED_TOKEN = os.getenv("INTERNAL_API_SHARED_TOKEN")


def _hash_value(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def _e2b_api_key(task: BaseServiceTask) -> str:
    secrets_manager = getattr(task, "_secrets_manager", None)
    return await get_e2b_api_key_async(secrets_manager)


async def _resolve_user_vault_key_id(task: BaseServiceTask, *, user_id: str, vault_key_id: str) -> str:
    if vault_key_id:
        return vault_key_id
    if not user_id:
        return ""
    cached_vault_key_id = await task._cache_service.get_user_vault_key_id(user_id)
    if cached_vault_key_id:
        return str(cached_vault_key_id)
    user_data = await task._directus_service.get_user_fields_direct(user_id, ["vault_key_id"])
    if isinstance(user_data, dict) and user_data.get("vault_key_id"):
        return str(user_data["vault_key_id"])
    return ""


async def _ensure_remotion_video_embed(
    *,
    task: BaseServiceTask,
    embed_service: Any,
    embed_id: str,
    source: str,
    chat_id: str | None,
    message_id: str | None,
    user_id: str,
    user_id_hash: str,
    vault_key_id: str,
    filename: str,
    source_version: int,
    log_prefix: str,
) -> str:
    if not chat_id or not message_id:
        return embed_id
    cached_embed = await embed_service._get_cached_embed(embed_id, vault_key_id, log_prefix) if embed_id else None
    if not cached_embed:
        placeholder = await embed_service.create_remotion_video_embed_placeholder(
            chat_id=chat_id,
            message_id=message_id,
            user_id=user_id,
            user_id_hash=user_id_hash,
            user_vault_key_id=vault_key_id,
            embed_id=embed_id or str(uuid.uuid4()),
            task_id=getattr(task.request, "id", None),
            filename=filename,
            log_prefix=log_prefix,
        )
        if placeholder and placeholder.get("embed_id"):
            embed_id = str(placeholder["embed_id"])
    await embed_service.update_remotion_video_embed_content(
        embed_id=embed_id,
        remotion_source=source,
        chat_id=str(chat_id),
        message_id=str(message_id),
        user_id=user_id,
        user_id_hash=user_id_hash,
        user_vault_key_id=vault_key_id,
        filename=filename,
        status="rendering",
        source_version=source_version,
        log_prefix=log_prefix,
    )
    return embed_id


async def _charge_remotion_render_credits(
    *,
    user_id: str,
    user_id_hash: str,
    credits: int,
    runtime_seconds: int,
    auto_started: bool,
    chat_id: str | None,
    message_id: str | None,
    source_version: int,
    log_prefix: str,
) -> None:
    if credits <= 0:
        return
    try:
        headers = {"Content-Type": "application/json"}
        if INTERNAL_API_SHARED_TOKEN:
            headers["X-Internal-Service-Token"] = INTERNAL_API_SHARED_TOKEN
        payload = {
            "user_id": user_id,
            "user_id_hash": user_id_hash,
            "credits": credits,
            "skill_id": "create",
            "app_id": "videos",
            "usage_details": {
                "chat_id": chat_id,
                "message_id": message_id,
                "units_processed": runtime_seconds,
                "duration_seconds": runtime_seconds,
                "unit_name": "remotion_e2b_render_second",
                "server_provider": "E2B",
                "auto_started": auto_started,
                "source_version": source_version,
            },
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(f"{INTERNAL_API_BASE_URL}/internal/billing/charge", json=payload, headers=headers)
            response.raise_for_status()
    except Exception as exc:
        logger.error("%s Failed to charge Remotion render credits: %s", log_prefix, exc, exc_info=True)


@app.task(bind=True, name="apps.videos.tasks.render_remotion", base=BaseServiceTask, queue="app_videos", soft_time_limit=1200, time_limit=1260)
def render_remotion_task(self, arguments: dict[str, Any]):
    return asyncio.run(_async_render_remotion(self, arguments))


async def _async_render_remotion(task: BaseServiceTask, arguments: dict[str, Any]) -> dict[str, Any]:
    task_id = task.request.id
    log_prefix = f"[Task ID: {task_id}]"
    started_at = time.monotonic()
    await task.initialize_services()
    try:
        embed_id = str(arguments.get("embed_id") or "")
        user_id = str(arguments.get("user_id") or "")
        user_id_hash = str(arguments.get("user_id_hash") or _hash_value(user_id))
        chat_id = arguments.get("chat_id")
        message_id = arguments.get("message_id")
        vault_key_id = await _resolve_user_vault_key_id(
            task,
            user_id=user_id,
            vault_key_id=str(arguments.get("vault_key_id") or ""),
        )
        source = str(arguments.get("remotion_source") or "")
        filename = arguments.get("filename")
        source_version = int(arguments.get("source_version") or 1)
        auto_started = bool(arguments.get("auto_started"))
        if not embed_id or not user_id or not vault_key_id or not source.strip():
            raise ValueError("Missing required Remotion render arguments")

        from backend.core.api.app.services.embed_service import EmbedService

        embed_service = EmbedService(task._cache_service, task._directus_service, task._encryption_service)
        filename = str(filename or "Composition.tsx")
        embed_id = await _ensure_remotion_video_embed(
            task=task,
            embed_service=embed_service,
            embed_id=embed_id,
            source=source,
            chat_id=chat_id,
            message_id=message_id,
            user_id=user_id,
            user_id_hash=user_id_hash,
            vault_key_id=vault_key_id,
            filename=filename,
            source_version=source_version,
            log_prefix=log_prefix,
        )

        rendered = render_remotion_in_e2b(
            source=source,
            filename=filename,
            api_key=await _e2b_api_key(task),
            enable_internet=True,
        )
        runtime_seconds = max(1, int(time.monotonic() - started_at))
        credits = calculate_remotion_render_credits(runtime_seconds=runtime_seconds, auto_started=auto_started)
        await _charge_remotion_render_credits(
            user_id=user_id,
            user_id_hash=user_id_hash,
            credits=credits,
            runtime_seconds=runtime_seconds,
            auto_started=auto_started,
            chat_id=chat_id,
            message_id=message_id,
            source_version=source_version,
            log_prefix=log_prefix,
        )

        aes_key = os.urandom(32)
        nonce = os.urandom(12)
        aes_key_b64 = base64.b64encode(aes_key).decode("utf-8")
        nonce_b64 = base64.b64encode(nonce).decode("utf-8")
        vault_wrapped_aes_key, _ = await task._encryption_service.encrypt_with_user_key(aes_key_b64, vault_key_id)
        if not vault_wrapped_aes_key:
            raise RuntimeError("Failed to wrap Remotion video AES key with Vault")

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        video_key = f"{user_id}/{timestamp}_{uuid.uuid4().hex[:8]}_remotion.mp4"
        thumbnail_key = f"{user_id}/{timestamp}_{uuid.uuid4().hex[:8]}_remotion_thumbnail.png"
        encrypted_video = AESGCM(aes_key).encrypt(nonce, rendered.video_bytes, None)
        encrypted_thumbnail = AESGCM(aes_key).encrypt(nonce, rendered.thumbnail_bytes, None)
        await task._s3_service.upload_file("chatfiles", video_key, encrypted_video, "application/octet-stream")
        await task._s3_service.upload_file("chatfiles", thumbnail_key, encrypted_thumbnail, "application/octet-stream")
        files_metadata = {
            "original": {
                "s3_key": video_key,
                "size_bytes": len(rendered.video_bytes),
                "format": "mp4",
                "mime_type": "video/mp4",
                "source_version": source_version,
            },
            "thumbnail": {
                "s3_key": thumbnail_key,
                "size_bytes": len(rendered.thumbnail_bytes),
                "format": "png",
                "mime_type": "image/png",
                "source_version": source_version,
            },
        }
        s3_base_url = f"https://{get_bucket_name('chatfiles')}.{task._s3_service.base_domain}"
        now_ts = int(datetime.now(timezone.utc).timestamp())
        stored = await index_generated_asset(
            task,
            user_id=user_id,
            embed_id=embed_id,
            media_type="video",
            files_metadata=files_metadata,
            s3_base_url=s3_base_url,
            aes_key_b64=aes_key_b64,
            nonce_b64=nonce_b64,
            vault_wrapped_aes_key=vault_wrapped_aes_key,
            created_at=now_ts,
            content_hash_source=rendered.video_bytes,
            original_filename=f"openmates_remotion_{embed_id[:8]}.mp4",
            content_type="video/mp4",
            log_prefix=log_prefix,
            provenance_metadata={"provider": "E2B", "renderer": "Remotion", "source_version": source_version},
        )
        if not stored:
            raise RuntimeError("Failed to index Remotion video in account storage")
        await cache_s3_file_keys(task, embed_id=embed_id, files_metadata=files_metadata, log_prefix=log_prefix)

        await embed_service.update_remotion_video_embed_content(
            embed_id=embed_id,
            remotion_source=source,
            chat_id=str(chat_id or ""),
            message_id=str(message_id or ""),
            user_id=user_id,
            user_id_hash=user_id_hash,
            user_vault_key_id=vault_key_id,
            filename=filename,
            status="finished",
            source_version=source_version,
            render_metadata={
                "provider": "E2B",
                "renderer": "Remotion",
                "sandbox_id_hash": _hash_value(rendered.sandbox_id) if rendered.sandbox_id else None,
                "runtime_seconds": runtime_seconds,
                "charged_credits": credits,
                "auto_started": auto_started,
            },
            files=files_metadata,
            thumbnail=files_metadata["thumbnail"],
            log_prefix=log_prefix,
        )
        return {"status": "finished", "embed_id": embed_id, "runtime_seconds": runtime_seconds, "charged_credits": credits}
    except Exception as exc:
        logger.error("%s Remotion render failed: %s", log_prefix, exc, exc_info=True)
        try:
            from backend.core.api.app.services.embed_service import EmbedService

            embed_service = EmbedService(task._cache_service, task._directus_service, task._encryption_service)
            await embed_service.update_remotion_video_embed_content(
                embed_id=str(arguments.get("embed_id") or ""),
                remotion_source=str(arguments.get("remotion_source") or ""),
                chat_id=str(arguments.get("chat_id") or ""),
                message_id=str(arguments.get("message_id") or ""),
                user_id=str(arguments.get("user_id") or ""),
                user_id_hash=str(arguments.get("user_id_hash") or ""),
                user_vault_key_id=str(arguments.get("vault_key_id") or ""),
                filename=str(arguments.get("filename") or "Composition.tsx"),
                status="error",
                source_version=int(arguments.get("source_version") or 1),
                render_metadata={"safe_error": "Remotion render failed. Inspect the source and try again."},
                log_prefix=log_prefix,
            )
        except Exception:
            logger.exception("%s Failed to mark Remotion embed as error", log_prefix)
        raise
    finally:
        await task.cleanup_services()
