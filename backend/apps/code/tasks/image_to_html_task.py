# backend/apps/code/tasks/image_to_html_task.py
#
# Worker task for Code image-to-HTML generation. The app skill only dispatches
# this task; this worker performs provider calls, bounded credit preflight,
# actual-cost billing, encrypted E2B screenshot storage, and final encrypted
# code-embed delivery. Generated HTML remains untrusted and is only rendered in
# E2B before being saved as source text.

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import math
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.apps.code.skills.image_to_html_skill import (
    DEFAULT_CACHE_READ_USD_PER_MILLION,
    DEFAULT_CACHE_WRITE_USD_PER_MILLION,
    DEFAULT_E2B_CREDITS_PER_STARTED_MINUTE,
    DEFAULT_INPUT_USD_PER_MILLION,
    DEFAULT_MINIMUM_CREDITS,
    DEFAULT_OUTPUT_USD_PER_MILLION,
    ImageToHtmlGenerationResult,
    ImageToHtmlUsage,
    calculate_image_to_html_credits,
    image_to_html_model_pricing,
    reserved_credits_for_correction_passes,
    validate_image_input,
)
from backend.shared.providers.image_to_html_generator import ImageToHtmlGenerator
from backend.shared.python_utils.encrypted_embed_images import resolve_encrypted_image_embed
from backend.shared.python_utils.billing_utils import ensure_credit_headroom, get_usd_per_credit
from backend.shared.python_utils.generated_assets import (
    build_download_url,
    cache_s3_file_keys,
    create_download_token,
    index_generated_asset,
)

try:  # pragma: no cover - local unit tests may not install Celery.
    from backend.core.api.app.services.s3.config import get_bucket_name
    from backend.core.api.app.tasks.base_task import BaseServiceTask
    from backend.core.api.app.tasks.celery_config import app
except (ImportError, ModuleNotFoundError):  # pragma: no cover - exercised by lightweight unit imports.
    def get_bucket_name(bucket_key: str, environment: str | None = None) -> str:
        del environment
        return bucket_key

    class BaseServiceTask:  # type: ignore[no-redef]
        pass

    class _NoopCeleryApp:
        def task(self, *args: Any, **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
            del args, kwargs

            def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
                return func

            return decorator

    app = _NoopCeleryApp()

logger = logging.getLogger(__name__)

PUBLIC_API_BASE_URL = os.getenv("PUBLIC_API_BASE_URL", "https://api.dev.openmates.org")
INTERNAL_API_BASE_URL = os.getenv("INTERNAL_API_BASE_URL", "http://api:8000")
INTERNAL_API_SHARED_TOKEN = os.getenv("INTERNAL_API_SHARED_TOKEN")
SCREENSHOT_VARIANT = "preview"

GeneratorFactory = Callable[[Any], ImageToHtmlGenerator]
ChargeCallable = Callable[..., Awaitable[int]]


@app.task(
    bind=True,
    name="apps.code.tasks.skill_image_to_html",
    base=BaseServiceTask,
    queue="app_code",
    soft_time_limit=900,
    time_limit=960,
)
def image_to_html_task(self, app_id: str, skill_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(_async_image_to_html(self, app_id, skill_id, arguments))


async def _async_image_to_html(
    task: BaseServiceTask,
    app_id: str,
    skill_id: str,
    arguments: dict[str, Any],
    *,
    generator_factory: GeneratorFactory | None = None,
    charge_func: ChargeCallable | None = None,
) -> dict[str, Any]:
    task_id = getattr(getattr(task, "request", None), "id", None) or str(uuid.uuid4())
    log_prefix = f"[code.image_to_html task:{task_id}]"
    user_id = str(arguments.get("user_id") or "")
    user_vault_key_id = str(arguments.get("user_vault_key_id") or "")
    chat_id = arguments.get("chat_id")
    message_id = arguments.get("message_id")
    embed_id = str(arguments.get("embed_id") or uuid.uuid4())
    max_correction_passes = int(arguments.get("max_correction_passes") or 0)

    if not user_id:
        raise ValueError("code.image_to_html requires a user_id")

    await task.initialize_services()
    try:
        await ensure_credit_headroom(
            user_id=user_id,
            estimated_credits=int(arguments.get("reserved_credits") or reserved_credits_for_correction_passes(max_correction_passes)),
            log_prefix=log_prefix,
            operation_name="image-to-HTML generation",
        )

        resolved_arguments = await _resolve_image_input_arguments(
            task,
            arguments,
            user_id=user_id,
            user_vault_key_id=user_vault_key_id,
        )
        parsed = validate_image_input(resolved_arguments)
        generator = generator_factory(task) if generator_factory else ImageToHtmlGenerator(secrets_manager=task._secrets_manager)
        generated = await generator.generate(
            image_bytes=parsed.image_bytes,
            mime_type=parsed.mime_type,
            filename=parsed.filename,
            max_correction_passes=parsed.max_correction_passes,
        )

        usage = _usage_payload_with_charge(
            ImageToHtmlGenerationResult(
                html=generated.html,
                screenshot_bytes=generated.screenshot_bytes,
                screenshot_mime_type=generated.screenshot_mime_type,
                correction_passes_used=generated.correction_passes_used,
                validation_warnings=generated.validation_warnings,
                usage=generated.usage,
            ),
            parsed.max_correction_passes,
        )
        user_id_hash = _hash_value(user_id)
        charged_credits = await (charge_func or charge_image_to_html_credits)(
            user_id=user_id,
            user_id_hash=user_id_hash,
            app_id=app_id,
            skill_id=skill_id,
            credits=int(usage["credits_charged"]),
            usage_details={
                "chat_id": chat_id,
                "message_id": message_id,
                "embed_id": embed_id,
                "source_filename": parsed.filename,
                "unit_name": "image_to_html_generation",
                "model_used": usage.get("model"),
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "duration_second": usage.get("duration_second"),
                "server_provider": "Google AI Studio + E2B",
                **{f"image_to_html_{key}": value for key, value in usage.items()},
            },
            api_key_hash=arguments.get("api_key_hash"),
            device_hash=arguments.get("device_hash"),
            log_prefix=log_prefix,
        )

        resolved_vault_key_id = user_vault_key_id
        if not resolved_vault_key_id and (generated.screenshot_bytes or (chat_id and message_id)):
            resolved_vault_key_id = await _resolve_user_vault_key_id(task, user_id)

        screenshot_metadata = await _store_latest_screenshot(
            task,
            user_id=user_id,
            user_vault_key_id=resolved_vault_key_id,
            embed_id=embed_id,
            screenshot_bytes=generated.screenshot_bytes,
            screenshot_mime_type=generated.screenshot_mime_type,
            log_prefix=log_prefix,
        )

        await _finalize_code_embed(
            task,
            embed_id=embed_id,
            html=generated.html,
            chat_id=str(chat_id or ""),
            message_id=str(message_id or ""),
            user_id=user_id,
            user_id_hash=user_id_hash,
            user_vault_key_id=resolved_vault_key_id,
            usage=usage,
            validation_warnings=generated.validation_warnings,
            correction_passes_used=generated.correction_passes_used,
            latest_screenshot=screenshot_metadata,
            log_prefix=log_prefix,
        )

        return {
            "status": "finished",
            "embed_id": embed_id,
            "user_id_hash": user_id_hash,
            "html": generated.html,
            "latest_screenshot": screenshot_metadata,
            "usage": {**usage, "credits_charged": charged_credits},
        }
    except Exception as exc:
        logger.error("%s Image-to-HTML generation failed: %s", log_prefix, exc, exc_info=True)
        await _mark_code_embed_failed(
            task,
            embed_id=embed_id,
            chat_id=str(chat_id or ""),
            user_id=user_id,
            user_id_hash=_hash_value(user_id),
            user_vault_key_id=user_vault_key_id,
            log_prefix=log_prefix,
        )
        raise
    finally:
        cleanup = getattr(task, "cleanup_services", None)
        if cleanup:
            await cleanup()


def _usage_payload_with_charge(generation: ImageToHtmlGenerationResult, max_correction_passes: int) -> dict[str, Any]:
    usage_payload = dict(generation.usage or {})
    usage = ImageToHtmlUsage(
        model=str(usage_payload.get("model") or "unknown"),
        input_tokens=int(usage_payload.get("input_tokens") or 0),
        output_tokens=int(usage_payload.get("output_tokens") or 0),
        cache_read_tokens=int(usage_payload.get("cache_read_tokens") or 0),
        cache_write_tokens=int(usage_payload.get("cache_write_tokens") or 0),
        e2b_render_seconds=float(usage_payload.get("e2b_render_seconds") or 0.0),
        correction_passes_used=int(usage_payload.get("correction_passes_used") or generation.correction_passes_used),
    )
    charge = calculate_image_to_html_credits(
        usage,
        pricing_details=image_to_html_model_pricing(usage.model),
        input_usd_per_million=DEFAULT_INPUT_USD_PER_MILLION,
        output_usd_per_million=DEFAULT_OUTPUT_USD_PER_MILLION,
        cache_read_usd_per_million=DEFAULT_CACHE_READ_USD_PER_MILLION,
        cache_write_usd_per_million=DEFAULT_CACHE_WRITE_USD_PER_MILLION,
        e2b_credits_per_started_minute=DEFAULT_E2B_CREDITS_PER_STARTED_MINUTE,
        minimum_credits=DEFAULT_MINIMUM_CREDITS,
    )
    reserved_credits = reserved_credits_for_correction_passes(max_correction_passes)
    estimated_cost_credits = math.ceil(charge.provider_cost_usd / get_usd_per_credit()) if charge.provider_cost_usd > 0 else 0
    usage_payload.update(
        {
            "model": usage.model,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_read_tokens": usage.cache_read_tokens,
            "cache_write_tokens": usage.cache_write_tokens,
            "e2b_render_seconds": usage.e2b_render_seconds,
            "duration_second": usage.e2b_render_seconds,
            "correction_passes_used": usage.correction_passes_used,
            "provider_cost_usd": charge.provider_cost_usd,
            "provider_cost_credits": estimated_cost_credits,
            "model_credits": charge.model_credits,
            "e2b_credits": charge.e2b_credits,
            "e2b_started_minutes": charge.e2b_started_minutes,
            "reserved_credits": reserved_credits,
            "credits_charged": charge.credits_charged,
            "credits_refunded": max(0, reserved_credits - charge.credits_charged),
        }
    )
    return usage_payload


async def charge_image_to_html_credits(
    *,
    user_id: str,
    user_id_hash: str,
    app_id: str,
    skill_id: str,
    credits: int,
    usage_details: dict[str, Any],
    api_key_hash: str | None,
    device_hash: str | None,
    log_prefix: str,
) -> int:
    if credits <= 0:
        return 0
    headers = {"Content-Type": "application/json"}
    if INTERNAL_API_SHARED_TOKEN:
        headers["X-Internal-Service-Token"] = INTERNAL_API_SHARED_TOKEN
    payload = {
        "user_id": user_id,
        "user_id_hash": user_id_hash,
        "credits": credits,
        "skill_id": skill_id,
        "app_id": app_id,
        "usage_details": usage_details,
        "api_key_hash": api_key_hash,
        "device_hash": device_hash,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(f"{INTERNAL_API_BASE_URL}/internal/billing/charge", json=payload, headers=headers)
            response.raise_for_status()
        return credits
    except Exception as exc:
        logger.error("%s Failed to charge image-to-HTML credits: %s", log_prefix, exc, exc_info=True)
        return 0


async def _store_latest_screenshot(
    task: BaseServiceTask,
    *,
    user_id: str,
    user_vault_key_id: str,
    embed_id: str,
    screenshot_bytes: bytes | None,
    screenshot_mime_type: str | None,
    log_prefix: str,
) -> dict[str, Any] | None:
    if not screenshot_bytes or not user_vault_key_id:
        return None
    mime_type = screenshot_mime_type or "image/png"
    extension = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}.get(mime_type, "png")
    aes_key = os.urandom(32)
    nonce = os.urandom(12)
    aes_key_b64 = base64.b64encode(aes_key).decode("ascii")
    nonce_b64 = base64.b64encode(nonce).decode("ascii")
    wrapped_key, _ = await task._encryption_service.encrypt_with_user_key(aes_key_b64, user_vault_key_id)
    if not wrapped_key:
        raise RuntimeError("Failed to wrap image-to-HTML screenshot encryption key")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    s3_key = f"{user_id}/{timestamp}_{embed_id[:8]}_image_to_html_preview.{extension}.enc"
    await task._s3_service.upload_file(
        bucket_key="chatfiles",
        file_key=s3_key,
        content=AESGCM(aes_key).encrypt(nonce, screenshot_bytes, None),
        content_type="application/octet-stream",
    )
    files_metadata = {
        SCREENSHOT_VARIANT: {
            "s3_key": s3_key,
            "size_bytes": len(screenshot_bytes),
            "format": extension,
            "mime_type": mime_type,
            "aes_nonce": nonce_b64,
        }
    }
    bucket_name = get_bucket_name("chatfiles", getattr(task._s3_service, "environment", None))
    s3_base_url = f"https://{bucket_name}.{task._s3_service.base_domain}"
    now_ts = int(time.time())
    indexed = await index_generated_asset(
        task,
        user_id=user_id,
        embed_id=embed_id,
        media_type="code_image_to_html",
        files_metadata=files_metadata,
        s3_base_url=s3_base_url,
        aes_key_b64=aes_key_b64,
        nonce_b64=nonce_b64,
        vault_wrapped_aes_key=wrapped_key,
        created_at=now_ts,
        content_hash_source=screenshot_bytes,
        original_filename=f"openmates_image_to_html_{embed_id[:8]}.{extension}",
        content_type=mime_type,
        log_prefix=log_prefix,
        provenance_metadata={"provider": "E2B", "variant": SCREENSHOT_VARIANT},
    )
    if not indexed:
        raise RuntimeError("Failed to index image-to-HTML screenshot")
    await cache_s3_file_keys(task, embed_id=embed_id, files_metadata=files_metadata, log_prefix=log_prefix)
    download_url = build_download_url(
        base_url=PUBLIC_API_BASE_URL,
        asset_id=embed_id,
        variant=SCREENSHOT_VARIANT,
        token=create_download_token(asset_id=embed_id, user_id=user_id, variant=SCREENSHOT_VARIANT),
    )
    return {**files_metadata[SCREENSHOT_VARIANT], "download_url": download_url}


async def _finalize_code_embed(
    task: BaseServiceTask,
    *,
    embed_id: str,
    html: str,
    chat_id: str,
    message_id: str,
    user_id: str,
    user_id_hash: str,
    user_vault_key_id: str,
    usage: dict[str, Any],
    validation_warnings: list[str],
    correction_passes_used: int,
    latest_screenshot: dict[str, Any] | None,
    log_prefix: str,
) -> None:
    if not chat_id or not message_id or not user_vault_key_id:
        return
    from backend.core.api.app.services.embed_service import EmbedService

    embed_service = EmbedService(task._cache_service, task._directus_service, task._encryption_service)
    updated = await embed_service.update_code_embed_content(
        embed_id=embed_id,
        code_content=html,
        chat_id=chat_id,
        user_id=user_id,
        user_id_hash=user_id_hash,
        user_vault_key_id=user_vault_key_id,
        status="finished",
        learning_mode_metadata={
            "app_id": "code",
            "skill_id": "image_to_html",
            "language": "html",
            "filename": "index.html",
            "latest_screenshot": latest_screenshot,
            "latest_screenshot_url": latest_screenshot.get("download_url") if latest_screenshot else None,
            "latest_screenshot_mime_type": latest_screenshot.get("mime_type") if latest_screenshot else None,
            "image_to_html_metadata": {
                "correction_passes_used": correction_passes_used,
                "validation_warnings": validation_warnings,
                "usage": usage,
            },
        },
        log_prefix=log_prefix,
    )
    if not updated:
        logger.warning("%s Code embed %s was not found for image-to-HTML finalization", log_prefix, embed_id)


async def _mark_code_embed_failed(
    task: BaseServiceTask,
    *,
    embed_id: str,
    chat_id: str,
    user_id: str,
    user_id_hash: str,
    user_vault_key_id: str,
    log_prefix: str,
) -> None:
    if not chat_id or not user_vault_key_id:
        return
    try:
        from backend.core.api.app.services.embed_service import EmbedService

        embed_service = EmbedService(task._cache_service, task._directus_service, task._encryption_service)
        await embed_service.update_code_embed_content(
            embed_id=embed_id,
            code_content="",
            chat_id=chat_id,
            user_id=user_id,
            user_id_hash=user_id_hash,
            user_vault_key_id=user_vault_key_id,
            status="error",
            learning_mode_metadata={"app_id": "code", "skill_id": "image_to_html"},
            log_prefix=log_prefix,
        )
    except Exception:
        logger.exception("%s Failed to mark image-to-HTML embed as error", log_prefix)


async def _resolve_user_vault_key_id(task: BaseServiceTask, user_id: str) -> str:
    if not user_id:
        return ""
    success, user_profile, _ = await task._directus_service.get_user_profile(user_id)
    if success and isinstance(user_profile, dict):
        return str(user_profile.get("vault_key_id") or "")
    return ""


async def _resolve_image_input_arguments(
    task: BaseServiceTask,
    arguments: dict[str, Any],
    *,
    user_id: str,
    user_vault_key_id: str,
) -> dict[str, Any]:
    if arguments.get("image_base64"):
        return arguments

    source_embed_id = str(arguments.get("source_image_embed_id") or "")
    if not source_embed_id:
        return arguments

    resolved_vault_key_id = user_vault_key_id or await _resolve_user_vault_key_id(task, user_id)
    resolved = await resolve_encrypted_image_embed(
        embed_id=source_embed_id,
        user_vault_key_id=resolved_vault_key_id,
        cache_client=task._cache_service,
        directus_service=task._directus_service,
        encryption_service=task._encryption_service,
        s3_service=task._s3_service,
        bucket_name=get_bucket_name("chatfiles"),
    )
    return {
        **arguments,
        "image_base64": base64.b64encode(resolved.content).decode("ascii"),
        "mime_type": resolved.mime_type,
    }


def _hash_value(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else ""
