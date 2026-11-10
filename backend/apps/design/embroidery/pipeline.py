"""One design.embroidery conversion: source, check, optional rework, convert, store, charge, deliver.

Runs inside the registered generated-media batch (``run_generated_media_batch``)
on the shared media worker. The worker never parses the untrusted SVG geometry
itself; check and conversion run in the embroidery sandbox
(``backend/shared/providers/e2b_embroidery.py``). Expected failures (no vector
source, sandbox errors, a missing sandbox template) publish a failed child with the
reason in plain words and are never charged. Infrastructure errors propagate so
the batch helper records the slot as failed.
"""

from __future__ import annotations

import hashlib
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from backend.apps.design.embroidery.billing import (
    charge_embroidery_credits,
    embroidery_credits,
    estimate_embroidery_credits,
)
from backend.apps.design.embroidery.content import (
    INVALID_SOURCE_MESSAGE,
    assistant_summary,
    build_failed_content,
    build_finished_content,
)
from backend.apps.design.embroidery.request import parse_embroidery_request
from backend.apps.design.embroidery.rework import rework_for_embroidery, rework_result_notes
from backend.apps.design.embroidery.storage import (
    IncompleteEmbroideryFiles,
    require_complete_files,
    result_title,
    store_embroidery_files,
    variant_filename,
)
from backend.apps.images.vector_author import VECTOR_AUTHOR_MODELS
from backend.core.api.app.services.s3.config import get_bucket_name
from backend.shared.providers.e2b_code_runner import get_e2b_api_key_async
from backend.shared.python_utils.billing_utils import ensure_credit_headroom
from backend.shared.python_utils.encrypted_embed_vectors import VectorSourceError, resolve_vector_source_embed
from backend.shared.python_utils.fresh_upload_images import FreshUploadImageUnavailable
from backend.shared.python_utils.generated_assets import (
    build_download_url,
    cache_s3_file_keys,
    create_download_token,
    index_generated_asset,
)
from backend.shared.python_utils.generated_media_graph import generated_media_embed_ref, send_generated_media_child
from backend.shared.python_utils.storage_availability import initialize_task_storage, require_storage_available

logger = logging.getLogger(__name__)

TEMPLATE_ENV = "E2B_EMBROIDERY_TEMPLATE"
PUBLIC_API_BASE_URL = os.getenv("PUBLIC_API_BASE_URL", "https://api.dev.openmates.org")
INTERNAL_API_BASE_URL = os.getenv("INTERNAL_API_BASE_URL", "http://api:8000")
INCOMPLETE_FILES_MESSAGE = "The conversion did not produce every machine file, so no files are offered."


async def request_internal(method: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Call the internal API (owner-scoped upload metadata recovery for the source graphic)."""
    headers = {"X-Internal-Service-Token": os.getenv("INTERNAL_API_SHARED_TOKEN") or ""}
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.request(method, f"{INTERNAL_API_BASE_URL}/{path}", json=payload, headers=headers)
    if response.status_code in {401, 403, 404}:
        raise FreshUploadImageUnavailable("Referenced graphic is not available in the current processing window")
    response.raise_for_status()
    return response.json()


def open_embroidery_session(*, api_key: str, template: str) -> Any:
    """Create the sandbox session that runs check and conversion (Lane A provider)."""
    from backend.shared.providers.e2b_embroidery import EmbroiderySession

    return EmbroiderySession(api_key=api_key, template=template)


def _embed_service(task: Any) -> Any:
    from backend.core.api.app.services.embed_service import EmbedService

    return EmbedService(task._cache_service, task._directus_service, task._encryption_service)


async def _assert_can_generate(task: Any, *, embed_id: str, chat_id: Any, message_id: Any, user_id: str) -> None:
    from backend.core.api.app.services.embed_service import EmbedService

    await EmbedService.assert_registered_output_can_generate(
        task._directus_service, embed_id=embed_id, chat_id=chat_id, message_id=message_id,
        owner_hash=hashlib.sha256(user_id.encode("utf-8")).hexdigest(),
    )


async def run_embroidery(task: Any, app_id: str, skill_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Convert one referenced vector graphic and publish its result child."""
    from backend.shared.providers.e2b_embroidery import EMBROIDERY_TEMPLATE_NAME, EmbroideryError, EmbroideryOptions

    log_prefix = f"[design.embroidery task:{task.request.id}]"
    user_id = str(arguments.get("user_id") or "")
    user_vault_key_id = str(arguments.get("user_vault_key_id") or "")
    embed_id = str(arguments.get("embed_id") or uuid.uuid4())
    parent_embed_id = str(arguments.get("producer_embed_id") or embed_id)
    chat_id, message_id = arguments.get("chat_id"), arguments.get("message_id")
    source_embed_id = str(arguments.get("source_embed_id") or "")
    source_ref = str(arguments.get("source") or "")
    if not user_id or not user_vault_key_id:
        raise ValueError("design.embroidery requires user and vault key identifiers")
    request = parse_embroidery_request(
        width_mm=arguments.get("width_mm"), hoop=arguments.get("hoop"),
        fabric=arguments.get("fabric"), instructions=arguments.get("instructions"),
    )
    user_id_hash = hashlib.sha256(user_id.encode("utf-8")).hexdigest()

    await task.initialize_core_services()
    await _assert_can_generate(task, embed_id=parent_embed_id, chat_id=chat_id, message_id=message_id, user_id=user_id)
    s3_service = await initialize_task_storage(task)
    await require_storage_available(s3_service)
    embed_service = _embed_service(task)

    async def publish(content: dict[str, Any]) -> None:
        await send_generated_media_child(
            embed_service, parent_embed_id=parent_embed_id, child_embed_id=embed_id,
            child_index=int(arguments.get("media_child_index") or 0), content=content,
            chat_id=chat_id, message_id=message_id, user_id=user_id, user_id_hash=user_id_hash,
            created_at=int(datetime.now(timezone.utc).timestamp()), log_prefix=log_prefix,
        )

    async def fail(code: str, message: str, title: str) -> dict[str, Any]:
        await publish(build_failed_content(
            skill_id=skill_id, title=title, hoop=request.hoop, fabric=request.fabric, error_code=code,
            user_message=message, source_embed_ref=source_ref, source_embed_id=source_embed_id,
        ))
        return {
            "embed_id": embed_id, "child_embed_id": embed_id, "status": "failed", "child_published": True,
            "error": message, "error_code": code, "billing_status": "not_charged",
            "input_embed_ids": [source_embed_id] if source_embed_id else [],
        }

    bucket_name = get_bucket_name("chatfiles", s3_service.environment)
    if not source_embed_id:
        return await fail("invalid_source", INVALID_SOURCE_MESSAGE, result_title(source_ref))
    try:
        source = await resolve_vector_source_embed(
            embed_id=source_embed_id, user_id=user_id, user_vault_key_id=user_vault_key_id,
            cache_client=await task._cache_service.client, directus_service=task._directus_service,
            encryption_service=task._encryption_service, s3_service=s3_service,
            request_internal=request_internal, bucket_name=bucket_name,
        )
    except VectorSourceError as exc:
        logger.info("%s Source is not a readable vector graphic: %s", log_prefix, exc)
        return await fail("invalid_source", INVALID_SOURCE_MESSAGE, result_title(source_ref))
    title = result_title(source.label or source_ref)

    template = os.getenv(TEMPLATE_ENV, "").strip() or EMBROIDERY_TEMPLATE_NAME

    await ensure_credit_headroom(
        user_id=user_id, log_prefix=log_prefix, operation_name="embroidery conversion",
        estimated_credits=await estimate_embroidery_credits(
            svg_chars=len(source.svg), rework_possible=True, rework_model=VECTOR_AUTHOR_MODELS[0],
        ),
    )
    options = EmbroideryOptions(width_mm=request.width_mm, hoop=request.hoop, fabric=request.fabric)
    api_key = await get_e2b_api_key_async(task._secrets_manager)
    try:
        async with open_embroidery_session(api_key=api_key, template=template) as session:
            check = await session.check(source.svg, options)
            outcome = await rework_for_embroidery(
                svg=source.svg, findings=check.findings, width_mm=request.width_mm,
                instructions=request.instructions, task_id=str(task.request.id),
                secrets_manager=task._secrets_manager,
            )
            run = await session.convert(outcome.svg, options)
            sandbox_seconds = float(session.sandbox_seconds)
    except EmbroideryError as exc:
        logger.info("%s Conversion failed with %s", log_prefix, exc.code)
        return await fail(exc.code, exc.user_message, title)
    try:
        files = require_complete_files(run.files)
    except IncompleteEmbroideryFiles as exc:
        logger.error("%s %s", log_prefix, exc)
        return await fail("sandbox_failed", INCOMPLETE_FILES_MESSAGE, title)

    stored = await store_embroidery_files(
        s3_service=task._s3_service, user_id=user_id, embed_id=embed_id, title=title, files=files,
    )
    wrapped_key, _ = await task._encryption_service.encrypt_with_user_key(stored.aes_key_b64, user_vault_key_id)
    s3_base_url = f"https://{bucket_name}.{task._s3_service.base_domain}"
    indexed = bool(wrapped_key) and await index_generated_asset(
        task, user_id=user_id, embed_id=embed_id, media_type="design_embroidery",
        files_metadata=stored.files_metadata, s3_base_url=s3_base_url, aes_key_b64=stored.aes_key_b64,
        nonce_b64=stored.nonce_b64, vault_wrapped_aes_key=wrapped_key,
        created_at=int(datetime.now(timezone.utc).timestamp()), content_hash_source=files["dst"],
        original_filename=variant_filename(title, "dst"), content_type="application/octet-stream",
        log_prefix=log_prefix, provenance_metadata={"engine": "inkstitch", "reworked": outcome.reworked},
    )
    if not indexed:
        for s3_key in stored.s3_keys:
            await task._s3_service.delete_file(bucket_key="chatfiles", file_key=s3_key)
        raise RuntimeError("Failed to wrap or index the embroidery result files")
    await cache_s3_file_keys(task, embed_id=embed_id, files_metadata=stored.files_metadata, log_prefix=log_prefix)

    billing_status = "charged"
    try:
        credits, usage_details = await embroidery_credits(sandbox_seconds=sandbox_seconds, usage=outcome.usage)
        await charge_embroidery_credits(
            user_id=user_id, user_id_hash=user_id_hash, app_id=app_id, skill_id=skill_id, credits=credits,
            usage_details=usage_details, chat_id=chat_id, message_id=message_id,
            api_key_hash=str(arguments["api_key_hash"]) if arguments.get("api_key_hash") else None,
            device_hash=str(arguments["device_hash"]) if arguments.get("device_hash") else None,
            event_id=embed_id,
        )
    except (httpx.HTTPError, RuntimeError) as exc:
        billing_status = "failed"
        logger.error("%s Files were stored but billing failed; delivering with billing_status=failed: %s",
                     log_prefix, exc, exc_info=True)

    content = build_finished_content(
        skill_id=skill_id, title=title, summary=run.summary,
        extra_notes=[*outcome.notes, *rework_result_notes(
            original_findings=check.findings, remaining_findings=run.findings,
            reworked=outcome.reworked, instructions=request.instructions,
        )],
        hoop=request.hoop, fabric=request.fabric, reworked=outcome.reworked,
        files_metadata=stored.files_metadata, s3_base_url=s3_base_url, aes_key_b64=stored.aes_key_b64,
        nonce_b64=stored.nonce_b64, vault_wrapped_aes_key=wrapped_key, source_embed_ref=source_ref,
        source_embed_id=source_embed_id, billing_status=billing_status,
    )
    await publish(content)
    return {
        "embed_id": embed_id,
        "child_embed_id": embed_id,
        "child_embed_ids": [embed_id],
        "embed_ref": generated_media_embed_ref("design", embed_id),
        "status": "finished",
        "billing_status": billing_status,
        "input_embed_ids": [source_embed_id],
        **assistant_summary(content),
        "files": {
            variant: {
                "format": metadata["format"], "size_bytes": metadata["size_bytes"],
                "download_url": build_download_url(
                    base_url=PUBLIC_API_BASE_URL, asset_id=embed_id, variant=variant,
                    token=create_download_token(asset_id=embed_id, user_id=user_id, variant=variant),
                ),
            }
            for variant, metadata in stored.files_metadata.items()
        },
    }
