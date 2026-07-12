# backend/apps/models3d/tasks/generate_task.py
#
# Hi3D generation worker. It resolves encrypted image references inside the
# worker, stores validated model masters as chunked encrypted S3 objects, and
# sends only compact encrypted metadata to the chat embed pipeline.

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.apps.models3d.billing import charge_model_generation_credits
from backend.apps.models3d.preview import optimize_preview_glb
from backend.apps.models3d.storage import (
    build_master_variant_metadata,
    build_poster_variant_metadata,
    build_preview_variant_metadata,
)
from backend.core.api.app.services.s3.config import get_bucket_name
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app
from backend.shared.providers.hi3d.client import Hi3DClient
from backend.shared.providers.hi3d.models import Hi3DView
from backend.shared.python_utils.encrypted_embed_images import resolve_encrypted_image_embed
from backend.shared.python_utils.generated_assets import (
    build_download_url,
    cache_s3_file_keys,
    create_download_token,
    encrypt_chunked_stream,
    index_generated_asset,
)
from backend.shared.python_utils.billing_utils import ensure_credit_headroom

logger = logging.getLogger(__name__)

PUBLIC_API_BASE_URL = os.getenv("PUBLIC_API_BASE_URL", "https://api.dev.openmates.org")
MASTER_CHUNK_SIZE = 1024 * 1024


async def _bytes_source(content: bytes) -> AsyncIterator[bytes]:
    for offset in range(0, len(content), MASTER_CHUNK_SIZE):
        yield content[offset : offset + MASTER_CHUNK_SIZE]


@app.task(
    bind=True,
    name="apps.models3d.tasks.skill_generate",
    base=BaseServiceTask,
    queue="app_images",
    soft_time_limit=900,
    time_limit=960,
)
def generate_model_task(self, app_id: str, skill_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(_async_generate_model(self, app_id, skill_id, arguments))


async def _async_generate_model(
    task: BaseServiceTask,
    app_id: str,
    skill_id: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Resolve input images, call Hi3D, then persist its result before URL expiry."""
    task_id = task.request.id
    log_prefix = f"[models3d task:{task_id}]"
    user_id = str(arguments.get("user_id") or "")
    user_vault_key_id = str(arguments.get("user_vault_key_id") or "")
    api_key_hash = arguments.get("api_key_hash")
    device_hash = arguments.get("device_hash")
    embed_id = str(arguments.get("embed_id") or uuid.uuid4())
    chat_id = arguments.get("chat_id")
    message_id = arguments.get("message_id")
    estimated_credits = int(arguments.get("estimated_credits") or 25)
    if not user_id or not user_vault_key_id:
        raise ValueError("models3d generation requires user and vault key identifiers")
    if arguments.get("input_mode") == "text":
        raise ValueError("Text-to-3D reference generation is not available until reference artifact retention is implemented")

    await task.initialize_services()
    await ensure_credit_headroom(
        user_id=user_id,
        estimated_credits=estimated_credits,
        log_prefix=log_prefix,
        operation_name="3D model generation",
    )
    cache_client = await task._cache_service.client
    bucket_name = get_bucket_name("chatfiles", task._s3_service.environment)
    ordered_inputs = arguments.get("ordered_views") or [
        {"view": "front", "embed_id": embed_id}
        for embed_id in arguments.get("reference_embed_ids") or []
    ]
    if not ordered_inputs:
        raise ValueError("models3d generation requires one or more image references")

    hi3d_images: list[tuple[Hi3DView, str, bytes, str]] = []
    for item in ordered_inputs:
        view = Hi3DView(str(item.get("view") or "front"))
        source_embed_id = str(item.get("embed_id") or "")
        if not source_embed_id:
            raise ValueError("models3d image input is missing an embed identifier")
        resolved = await resolve_encrypted_image_embed(
            embed_id=source_embed_id,
            user_vault_key_id=user_vault_key_id,
            cache_client=cache_client,
            directus_service=task._directus_service,
            encryption_service=task._encryption_service,
            s3_service=task._s3_service,
            bucket_name=bucket_name,
        )
        extension = "jpg" if resolved.mime_type == "image/jpeg" else resolved.mime_type.split("/")[-1]
        hi3d_images.append((view, f"{view.value}.{extension}", resolved.content, resolved.mime_type))

    access_key = await task._secrets_manager.get_secret("kv/data/providers/hi3d", "access_key")
    secret_key = await task._secrets_manager.get_secret("kv/data/providers/hi3d", "secret_key")
    if not access_key or not secret_key:
        raise RuntimeError("Hi3D credentials are unavailable")
    async with Hi3DClient(access_key, secret_key) as client:
        provider_task_id = await client.submit_task(images=hi3d_images)
        result = await client.wait_for_task(provider_task_id)
        master_glb = await client.download_glb(result.model_url)
        if not result.cover_url:
            raise RuntimeError("Hi3D result did not include a preview cover")
        poster_image, poster_mime_type = await client.download_cover(result.cover_url)
    preview_glb = await asyncio.to_thread(optimize_preview_glb, master_glb)

    aes_key = os.urandom(32)
    poster_nonce = os.urandom(12)
    preview_nonce = os.urandom(12)
    aes_key_b64 = base64.b64encode(aes_key).decode("ascii")
    poster_nonce_b64 = base64.b64encode(poster_nonce).decode("ascii")
    preview_nonce_b64 = base64.b64encode(preview_nonce).decode("ascii")
    wrapped_key, _ = await task._encryption_service.encrypt_with_user_key(aes_key_b64, user_vault_key_id)
    if not wrapped_key:
        raise RuntimeError("Failed to wrap model encryption key")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    master_s3_key = f"{user_id}/{timestamp}_{embed_id[:8]}_model.glb.enc"
    await task._s3_service.upload_file_stream(
        bucket_key="chatfiles",
        file_key=master_s3_key,
        source=encrypt_chunked_stream(_bytes_source(master_glb), key=aes_key),
        content_type="application/octet-stream",
    )
    poster_extension = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[poster_mime_type]
    poster_s3_key = f"{user_id}/{timestamp}_{embed_id[:8]}_poster.{poster_extension}.enc"
    preview_s3_key = f"{user_id}/{timestamp}_{embed_id[:8]}_preview.glb.enc"
    try:
        await task._s3_service.upload_file(
            bucket_key="chatfiles",
            file_key=poster_s3_key,
            content=AESGCM(aes_key).encrypt(poster_nonce, poster_image, None),
            content_type="application/octet-stream",
        )
        await task._s3_service.upload_file(
            bucket_key="chatfiles",
            file_key=preview_s3_key,
            content=AESGCM(aes_key).encrypt(preview_nonce, preview_glb, None),
            content_type="application/octet-stream",
        )
    except Exception:
        await task._s3_service.delete_file(bucket_key="chatfiles", file_key=master_s3_key)
        await task._s3_service.delete_file(bucket_key="chatfiles", file_key=poster_s3_key)
        raise
    files_metadata = {
        "master": build_master_variant_metadata(master_s3_key, len(master_glb)),
        "poster": {
            **build_poster_variant_metadata(poster_s3_key, len(poster_image), poster_mime_type),
            "aes_nonce": poster_nonce_b64,
        },
        "preview": build_preview_variant_metadata(preview_s3_key, len(preview_glb), preview_nonce_b64),
    }
    s3_base_url = f"https://{bucket_name}.{task._s3_service.base_domain}"
    now_ts = int(datetime.now(timezone.utc).timestamp())
    indexed = await index_generated_asset(
        task,
        user_id=user_id,
        embed_id=embed_id,
        media_type="models3d",
        files_metadata=files_metadata,
        s3_base_url=s3_base_url,
        aes_key_b64=aes_key_b64,
        nonce_b64="",
        vault_wrapped_aes_key=wrapped_key,
        created_at=now_ts,
        content_hash_source=master_glb,
        original_filename=f"openmates_model_{embed_id[:8]}.glb",
        content_type="model/gltf-binary",
        log_prefix=log_prefix,
        provenance_metadata={"provider": "hi3d", "provider_task_id": result.task_id},
    )
    if not indexed:
        for metadata in files_metadata.values():
            await task._s3_service.delete_file(bucket_key="chatfiles", file_key=metadata["s3_key"])
        raise RuntimeError("Failed to index generated model")
    await cache_s3_file_keys(task, embed_id=embed_id, files_metadata=files_metadata, log_prefix=log_prefix)
    user_id_hash = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    await charge_model_generation_credits(
        user_id=user_id,
        user_id_hash=user_id_hash,
        app_id=app_id,
        skill_id=skill_id,
        credits=estimated_credits,
        chat_id=chat_id,
        message_id=message_id,
        api_key_hash=str(api_key_hash) if api_key_hash else None,
        device_hash=str(device_hash) if device_hash else None,
        log_prefix=log_prefix,
    )

    content = {
        "type": "model3d",
        "app_id": app_id,
        "skill_id": skill_id,
        "status": "finished",
        "provider": "hi3d",
        "provider_model": "hitem3dv2.1",
        "files": files_metadata,
        "s3_base_url": s3_base_url,
        "aes_key": aes_key_b64,
        "aes_nonce": "",
        "vault_wrapped_aes_key": wrapped_key,
        "input_embed_ids": [str(item.get("embed_id") or "") for item in ordered_inputs],
    }
    from toon_format import encode as toon_encode

    from backend.core.api.app.services.embed_service import EmbedService

    embed_service = EmbedService(task._cache_service, task._directus_service, task._encryption_service)
    await embed_service.send_embed_data_to_client(
        embed_id=embed_id,
        embed_type="app_skill_use",
        content_toon=toon_encode(content),
        chat_id=chat_id,
        message_id=message_id,
        user_id=user_id,
        user_id_hash=user_id_hash,
        status="finished",
        encryption_mode="client",
        created_at=now_ts,
        updated_at=now_ts,
        log_prefix=log_prefix,
        check_cache_status=False,
    )
    return {
        "embed_id": embed_id,
        "status": "finished",
        "files": {
            variant_name: {
                **metadata,
                "download_url": build_download_url(
                    base_url=PUBLIC_API_BASE_URL,
                    asset_id=embed_id,
                    variant=variant_name,
                    token=create_download_token(asset_id=embed_id, user_id=user_id, variant=variant_name),
                ),
            }
            for variant_name, metadata in files_metadata.items()
        },
    }
