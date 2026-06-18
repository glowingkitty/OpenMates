# backend/apps/code/tasks/run_application_preview_task.py
#
# Worker lifecycle for generated application previews.
# The public API creates viewer-owned session records; this worker resolves a
# prepared payload into E2B planning/provider calls and updates the same Redis
# session with sandbox metadata consumed by the preview gateway.

from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
import os
import time
import uuid
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Awaitable, Callable

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import httpx

from backend.core.api.app.routes.application_preview import (
    APPLICATION_PREVIEW_AUTO_START_TIMEOUT_SECONDS,
    APPLICATION_PREVIEW_CREDITS_PER_STARTED_MINUTE,
    APPLICATION_PREVIEW_SESSION_TTL_SECONDS,
    application_preview_session_key,
)
from backend.shared.providers.e2b_application_preview import (
    ApplicationPreviewEntrypoint,
    ApplicationPreviewFile,
    ApplicationPreviewRuntime,
    kill_application_preview_sandbox_in_e2b,
    plan_application_preview_startup,
    start_application_preview_in_e2b,
)


logger = logging.getLogger(__name__)
APPLICATION_PREVIEW_SCREENSHOT_VARIANT = "preview"
APPLICATION_PREVIEW_SCREENSHOT_WIDTH = 960
APPLICATION_PREVIEW_SCREENSHOT_HEIGHT = 540
INTERNAL_API_BASE_URL = os.getenv("INTERNAL_API_BASE_URL", "http://api:8000")
INTERNAL_API_SHARED_TOKEN = os.getenv("INTERNAL_API_SHARED_TOKEN", "")

try:  # pragma: no cover - local unit tests do not install Celery.
    from backend.core.api.app.tasks.celery_config import app, get_worker_cache_service
    from backend.core.api.app.services.directus import DirectusService
    from backend.core.api.app.services.s3.config import get_bucket_name
    from backend.core.api.app.services.s3.service import S3UploadService
    from backend.core.api.app.utils.encryption import EncryptionService
    from backend.core.api.app.utils.secrets_manager import SecretsManager
    from backend.shared.providers.e2b_code_runner import get_e2b_api_key_async, redact_execution_output
    from backend.shared.python_utils.generated_assets import build_download_url, create_download_token
    from backend.shared.python_utils.generated_assets.service import cache_s3_file_keys, index_generated_asset
except (ImportError, ModuleNotFoundError):  # pragma: no cover - exercised by lightweight unit imports.
    app = None
    get_worker_cache_service = None
    DirectusService = None
    get_bucket_name = None
    S3UploadService = None
    EncryptionService = None
    SecretsManager = None
    get_e2b_api_key_async = None
    build_download_url = None
    create_download_token = None
    cache_s3_file_keys = None
    index_generated_asset = None

    def redact_execution_output(value: str) -> str:
        return value


ProviderStart = Callable[..., ApplicationPreviewRuntime | Awaitable[ApplicationPreviewRuntime]]
ProviderStop = Callable[..., bool | Awaitable[bool]]
ThumbnailStore = Callable[..., dict[str, Any] | Awaitable[dict[str, Any] | None] | None]


async def run_application_preview_session(
    *,
    cache_service: Any,
    session_id: str,
    payload: dict[str, Any],
    provider_start: ProviderStart | None = None,
    provider_stop: ProviderStop | None = None,
    thumbnail_store: ThumbnailStore | None = None,
    now: float | None = None,
) -> None:
    started_at = now if now is not None else time.time()
    await _patch_session(
        cache_service,
        session_id,
        {
            "status": "starting",
            "updated_at": started_at,
            "events+": [{"kind": "status", "text": "Starting application preview sandbox...", "timestamp": started_at}],
        },
    )

    try:
        files = [_file_from_payload(item) for item in payload.get("files", []) if isinstance(item, dict)]
        entrypoints = [_entrypoint_from_payload(item) for item in payload.get("entrypoints", []) if isinstance(item, dict)]
        plan_application_preview_startup(files=files, entrypoints=entrypoints)
        runtime = await _start_runtime(
            provider_start,
            files=files,
            entrypoints=entrypoints,
            api_key=str(payload.get("api_key") or ""),
            enable_internet=bool(payload.get("enable_internet", True)),
        )
        running_at = now if now is not None else time.time()
        thumbnail = await _store_thumbnail(
            thumbnail_store,
            cache_service=cache_service,
            session_id=session_id,
            payload=payload,
            runtime=runtime,
            now=running_at,
        )
        screenshot_url = (
            thumbnail.get("download_url")
            if isinstance(thumbnail, dict) and isinstance(thumbnail.get("download_url"), str)
            else runtime.latest_screenshot_url
        )
        await _patch_session(
            cache_service,
            session_id,
            {
                "status": "running",
                "sandbox_id": runtime.sandbox_id,
                "upstream_base_url": runtime.upstream_base_url,
                "upstream_base_urls": runtime.upstream_base_urls or {},
                "ports": runtime.ports,
                "latest_screenshot_url": screenshot_url,
                "latest_screenshot": thumbnail.get("metadata") if isinstance(thumbnail, dict) else None,
                "latest_screenshot_captured_at": running_at if screenshot_url else None,
                "updated_at": running_at,
                "billing_state.billable_started_at": running_at,
                "events+": [{"kind": "status", "text": "Application preview is running.", "timestamp": running_at}],
            },
        )
        if now is None:
            await _stop_unopened_auto_started_session_after_deadline(
                cache_service=cache_service,
                session_id=session_id,
                sandbox_id=runtime.sandbox_id,
                api_key=str(payload.get("api_key") or ""),
                provider_stop=provider_stop,
            )
    except Exception as exc:
        safe_error = redact_execution_output(str(exc))
        logger.error("Application preview session %s failed: %s", session_id, safe_error, exc_info=True)
        await _patch_session(
            cache_service,
            session_id,
            {
                "status": "failed",
                "error": safe_error,
                "updated_at": time.time() if now is None else now,
                "events+": [{"kind": "error", "text": safe_error, "timestamp": time.time() if now is None else now}],
            },
        )


async def stop_application_preview_sandbox(
    *,
    cache_service: Any,
    session_id: str,
    sandbox_id: str,
    api_key: str,
    provider_stop: ProviderStop | None = None,
    now: float | None = None,
) -> None:
    stopped_at = now if now is not None else time.time()
    try:
        stopped = await _stop_runtime(provider_stop, sandbox_id=sandbox_id, api_key=api_key)
        text = "Application preview sandbox stopped." if stopped else "Application preview sandbox stop was requested."
        charge_patch = await _charge_preview_if_needed(
            cache_service=cache_service,
            session_id=session_id,
            stopped_at=stopped_at,
            billing_phase="stopped",
        )
        await _patch_session(
            cache_service,
            session_id,
            {
                "sandbox_stopped_at": stopped_at,
                "updated_at": stopped_at,
                **charge_patch,
                "events+": [{"kind": "status", "text": text, "timestamp": stopped_at}],
            },
        )
    except Exception as exc:
        safe_error = redact_execution_output(str(exc))
        logger.error("Application preview sandbox stop %s failed: %s", session_id, safe_error, exc_info=True)
        await _patch_session(
            cache_service,
            session_id,
            {
                "sandbox_stop_error": safe_error,
                "updated_at": stopped_at,
                "events+": [{"kind": "error", "text": safe_error, "timestamp": stopped_at}],
            },
        )


def _file_from_payload(item: dict[str, Any]) -> ApplicationPreviewFile:
    return ApplicationPreviewFile(
        path=str(item.get("path") or ""),
        content=str(item.get("content") or ""),
        content_base64=item.get("content_base64") if isinstance(item.get("content_base64"), str) else None,
        mime_type=item.get("mime_type") if isinstance(item.get("mime_type"), str) else None,
        source_embed_id=item.get("source_embed_id") if isinstance(item.get("source_embed_id"), str) else None,
    )


def _entrypoint_from_payload(item: dict[str, Any]) -> ApplicationPreviewEntrypoint:
    return ApplicationPreviewEntrypoint(
        name=str(item.get("name") or ""),
        command=str(item.get("command") or ""),
        port=int(item.get("port") or 0),
    )


async def _start_runtime(
    provider_start: ProviderStart | None,
    **kwargs: Any,
) -> ApplicationPreviewRuntime:
    starter = provider_start or start_application_preview_in_e2b
    result = starter(**kwargs)
    if asyncio.iscoroutine(result):
        return await result
    return result


async def _store_thumbnail(
    thumbnail_store: ThumbnailStore | None,
    **kwargs: Any,
) -> dict[str, Any] | None:
    if thumbnail_store is None:
        return None
    result = thumbnail_store(**kwargs)
    if asyncio.iscoroutine(result):
        return await result
    return result


async def _stop_runtime(
    provider_stop: ProviderStop | None,
    **kwargs: Any,
) -> bool:
    stopper = provider_stop or kill_application_preview_sandbox_in_e2b
    result = stopper(**kwargs)
    if asyncio.iscoroutine(result):
        return bool(await result)
    return bool(result)


async def _patch_session(cache_service: Any, session_id: str, patch: dict[str, Any]) -> None:
    client = await cache_service.client
    key = application_preview_session_key(session_id)
    raw = await client.get(key)
    data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw) if raw else {}
    events = patch.pop("events+", [])
    for key_path, value in patch.items():
        if "." in key_path:
            parent, child = key_path.split(".", 1)
            container = data.setdefault(parent, {})
            if isinstance(container, dict):
                container[child] = value
        else:
            data[key_path] = value
    if events:
        data.setdefault("events", []).extend(events)
    await client.set(application_preview_session_key(session_id), json.dumps(data), ex=APPLICATION_PREVIEW_SESSION_TTL_SECONDS)


async def _stop_unopened_auto_started_session_after_deadline(
    *,
    cache_service: Any,
    session_id: str,
    sandbox_id: str,
    api_key: str,
    provider_stop: ProviderStop | None,
) -> None:
    client = await cache_service.client
    raw = await client.get(application_preview_session_key(session_id))
    if not raw:
        return

    data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    if data.get("auto_started") is not True:
        return

    await asyncio.sleep(APPLICATION_PREVIEW_AUTO_START_TIMEOUT_SECONDS)
    raw = await client.get(application_preview_session_key(session_id))
    if not raw:
        return

    data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    if data.get("auto_started") is not True or data.get("auto_opened_at") is not None:
        return
    if data.get("status") not in {"queued", "starting", "running"}:
        return

    stopped_at = time.time()
    await _patch_session(
        cache_service,
        session_id,
        {
            "status": "timeout",
            "stop_reason": "auto_unopened_timeout",
            "sandbox_stop_requested_at": stopped_at,
            "updated_at": stopped_at,
            "events+": [{"kind": "status", "text": "Auto-started preview timed out before it was opened.", "timestamp": stopped_at}],
        },
    )
    await stop_application_preview_sandbox(
        cache_service=cache_service,
        session_id=session_id,
        sandbox_id=sandbox_id,
        api_key=api_key,
        provider_stop=provider_stop,
        now=stopped_at,
    )


async def _charge_preview_if_needed(
    *,
    cache_service: Any,
    session_id: str,
    stopped_at: float,
    billing_phase: str,
) -> dict[str, Any]:
    client = await cache_service.client
    raw = await client.get(application_preview_session_key(session_id))
    data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw) if raw else {}
    billing_state = data.get("billing_state") if isinstance(data.get("billing_state"), dict) else {}
    if billing_state.get("charged_credits"):
        return {}

    billable_started_at = float(billing_state.get("billable_started_at") or 0)
    duration_seconds = max(0.0, stopped_at - billable_started_at) if billable_started_at else 0.0
    if duration_seconds <= 0:
        return {}

    charged_minutes = max(1, math.ceil(duration_seconds / 60))
    charged_credits = charged_minutes * APPLICATION_PREVIEW_CREDITS_PER_STARTED_MINUTE
    await _charge_preview_credits(
        session=data,
        session_id=session_id,
        credits=charged_credits,
        usage_details={
            "billing_phase": billing_phase,
            "duration_seconds": round(duration_seconds, 3),
            "charged_minutes": charged_minutes,
            "total_charged_minutes": charged_minutes,
        },
    )
    return {
        "billing_state.charged_credits": charged_credits,
        "billing_state.charged_minutes": charged_minutes,
        "billing_state.duration_seconds": round(duration_seconds, 3),
    }


async def _charge_preview_credits(
    *,
    session: dict[str, Any],
    session_id: str,
    credits: int,
    usage_details: dict[str, Any],
) -> None:
    usage_context = session.get("usage_context") if isinstance(session.get("usage_context"), dict) else {}
    charge_payload = {
        "user_id": session["viewer_user_id"],
        "user_id_hash": session["viewer_user_id_hash"],
        "credits": credits,
        "skill_id": "application_preview",
        "app_id": "code",
        "usage_details": {
            "preview_session_id": session_id,
            "application_embed_id": session.get("application_embed_id"),
            "chat_id": usage_context.get("chat_id"),
            "credits_per_minute": APPLICATION_PREVIEW_CREDITS_PER_STARTED_MINUTE,
            **usage_details,
        },
        "api_key_hash": None,
        "device_hash": None,
    }
    headers = {"Content-Type": "application/json"}
    if INTERNAL_API_SHARED_TOKEN:
        headers["X-Internal-Service-Token"] = INTERNAL_API_SHARED_TOKEN
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{INTERNAL_API_BASE_URL}/internal/billing/charge",
            json=charge_payload,
            headers=headers,
        )
        response.raise_for_status()


async def store_application_preview_thumbnail(
    *,
    cache_service: Any,
    session_id: str,
    payload: dict[str, Any],
    runtime: ApplicationPreviewRuntime,
    now: float,
    secrets_manager: Any,
) -> dict[str, Any] | None:
    """Encrypt and store a lightweight preview thumbnail for a successful app run."""
    if any(
        dependency is None
        for dependency in (
            DirectusService,
            EncryptionService,
            S3UploadService,
            get_bucket_name,
            build_download_url,
            create_download_token,
            cache_s3_file_keys,
            index_generated_asset,
        )
    ):
        return None

    try:
        client = await cache_service.client
        raw = await client.get(application_preview_session_key(session_id))
        session = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw) if raw else {}
        viewer_user_id = str(session.get("viewer_user_id") or "")
        application_embed_id = str(session.get("application_embed_id") or payload.get("application_embed_id") or "")
        if not viewer_user_id or not application_embed_id:
            return None
        if session.get("uses_client_shared_context") is True:
            return None

        encryption_service = EncryptionService(cache_service=cache_service)
        await encryption_service.initialize()
        directus_service = DirectusService(cache_service=cache_service, encryption_service=encryption_service)
        s3_service = S3UploadService(secrets_manager=secrets_manager)
        await s3_service.initialize()

        user_profile = await directus_service.get_user_fields_direct(viewer_user_id, ["vault_key_id", "storage_used_bytes"])
        vault_key_id = (user_profile or {}).get("vault_key_id")
        if not vault_key_id:
            return None

        png_bytes = _build_application_preview_thumbnail_png(payload=payload, runtime=runtime)
        aes_key = os.urandom(32)
        nonce = os.urandom(12)
        encrypted_payload = AESGCM(aes_key).encrypt(nonce, png_bytes, None)
        aes_key_b64 = base64.b64encode(aes_key).decode("utf-8")
        nonce_b64 = base64.b64encode(nonce).decode("utf-8")
        vault_wrapped_aes_key, _ = await encryption_service.encrypt_with_user_key(aes_key_b64, vault_key_id)
        if not vault_wrapped_aes_key:
            return None

        timestamp = datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
        file_key = f"{viewer_user_id}/{timestamp}_{uuid.uuid4().hex[:8]}_application_preview.png"
        upload = await s3_service.upload_file(
            bucket_key="chatfiles",
            file_key=file_key,
            content=encrypted_payload,
            content_type="application/octet-stream",
            metadata={"openmates-purpose": "application-preview-thumbnail"},
        )
        if not upload.get("url"):
            return None

        chatfiles_bucket = get_bucket_name("chatfiles", s3_service.environment)
        s3_base_url = f"https://{chatfiles_bucket}.{s3_service.base_domain}"
        files_metadata = {
            APPLICATION_PREVIEW_SCREENSHOT_VARIANT: {
                "s3_key": file_key,
                "width": APPLICATION_PREVIEW_SCREENSHOT_WIDTH,
                "height": APPLICATION_PREVIEW_SCREENSHOT_HEIGHT,
                "size_bytes": len(png_bytes),
                "format": "png",
                "mime_type": "image/png",
            }
        }

        shim = type("ApplicationPreviewAssetTask", (), {})()
        shim._directus_service = directus_service
        shim._s3_service = s3_service
        shim._cache_service = cache_service
        indexed = await index_generated_asset(
            shim,
            user_id=viewer_user_id,
            embed_id=application_embed_id,
            media_type="application_preview",
            files_metadata=files_metadata,
            s3_base_url=s3_base_url,
            aes_key_b64=aes_key_b64,
            nonce_b64=nonce_b64,
            vault_wrapped_aes_key=vault_wrapped_aes_key,
            created_at=int(now),
            content_hash_source=png_bytes,
            original_filename=f"openmates_application_preview_{application_embed_id[:8]}.png",
            content_type="image/png",
            log_prefix=f"[ApplicationPreviewScreenshot] [session:{session_id[:8]}]",
            provenance_metadata={"source": "application_preview_runtime", "application_embed_id": application_embed_id},
        )
        if not indexed:
            await s3_service.delete_file(bucket_key="chatfiles", file_key=file_key)
            return None
        await cache_s3_file_keys(
            shim,
            embed_id=application_embed_id,
            files_metadata=files_metadata,
            log_prefix=f"[ApplicationPreviewScreenshot] [session:{session_id[:8]}]",
        )

        metadata = {
            "asset_id": application_embed_id,
            "variant": APPLICATION_PREVIEW_SCREENSHOT_VARIANT,
            "files": files_metadata,
            "s3_base_url": s3_base_url,
            "aes_key": aes_key_b64,
            "aes_nonce": nonce_b64,
            "vault_wrapped_aes_key": vault_wrapped_aes_key,
            "captured_at": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        }
        token = create_download_token(
            asset_id=application_embed_id,
            user_id=viewer_user_id,
            variant=APPLICATION_PREVIEW_SCREENSHOT_VARIANT,
        )
        return {
            "download_url": build_download_url(
                base_url=_public_api_base_url(),
                asset_id=application_embed_id,
                variant=APPLICATION_PREVIEW_SCREENSHOT_VARIANT,
                token=token,
            ),
            "metadata": metadata,
        }
    except Exception as exc:
        logger.warning("Application preview thumbnail storage failed for %s: %s", session_id, exc, exc_info=True)
        return None


def _build_application_preview_thumbnail_png(*, payload: dict[str, Any], runtime: ApplicationPreviewRuntime) -> bytes:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:  # pragma: no cover - worker image includes Pillow.
        raise RuntimeError("Pillow is required for application preview thumbnails") from exc

    image = Image.new("RGB", (APPLICATION_PREVIEW_SCREENSHOT_WIDTH, APPLICATION_PREVIEW_SCREENSHOT_HEIGHT), "#f6f8fb")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    draw.rounded_rectangle((48, 40, 912, 500), radius=24, fill="#ffffff", outline="#d7dee8", width=2)
    draw.rounded_rectangle((48, 40, 912, 92), radius=24, fill="#edf2f7")
    for index, color in enumerate(("#ff5f57", "#ffbd2e", "#28c840")):
        draw.ellipse((76 + index * 28, 58, 92 + index * 28, 74), fill=color)

    files = [str(file.get("path") or "") for file in payload.get("files", []) if isinstance(file, dict)]
    title = str(payload.get("framework") or "Generated application").title()
    draw.text((80, 132), title, fill="#111827", font=font)
    draw.text((80, 164), "Preview is running in an isolated E2B sandbox", fill="#4b5563", font=font)
    draw.text((80, 206), f"Sandbox: {runtime.sandbox_id[:12] or 'active'}", fill="#6b7280", font=font)
    y = 254
    for path in files[:7]:
        draw.rounded_rectangle((80, y, 560, y + 28), radius=8, fill="#eef6ff")
        draw.text((96, y + 8), path[:72], fill="#1f4e79", font=font)
        y += 40
    draw.rounded_rectangle((620, 250, 840, 390), radius=18, fill="#e8fff3", outline="#b9f6d3")
    draw.polygon([(705, 292), (705, 348), (756, 320)], fill="#10b981")
    draw.text((646, 418), "Live preview ready", fill="#047857", font=font)

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _public_api_base_url() -> str:
    configured = (
        os.getenv("OPENMATES_API_URL")
        or os.getenv("PUBLIC_API_BASE_URL")
        or os.getenv("API_BASE_URL")
        or "https://api.dev.openmates.org"
    )
    return configured.rstrip("/")


def _run_application_preview_session_sync(session_id: str, payload: dict[str, Any]) -> None:
    if get_worker_cache_service is None or SecretsManager is None or get_e2b_api_key_async is None:
        raise RuntimeError("Application preview worker dependencies are not available")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    secrets_manager = SecretsManager()
    try:
        cache_service = loop.run_until_complete(get_worker_cache_service())
        loop.run_until_complete(secrets_manager.initialize())
        api_key = loop.run_until_complete(get_e2b_api_key_async(secrets_manager))
        loop.run_until_complete(run_application_preview_session(
            cache_service=cache_service,
            session_id=session_id,
            payload={**payload, "api_key": api_key},
            thumbnail_store=lambda **kwargs: store_application_preview_thumbnail(
                **kwargs,
                secrets_manager=secrets_manager,
            ),
        ))
    finally:
        loop.run_until_complete(secrets_manager.aclose())
        loop.close()


def _stop_application_preview_sandbox_sync(session_id: str, sandbox_id: str) -> None:
    if get_worker_cache_service is None or SecretsManager is None or get_e2b_api_key_async is None:
        raise RuntimeError("Application preview worker dependencies are not available")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    secrets_manager = SecretsManager()
    try:
        cache_service = loop.run_until_complete(get_worker_cache_service())
        loop.run_until_complete(secrets_manager.initialize())
        api_key = loop.run_until_complete(get_e2b_api_key_async(secrets_manager))
        loop.run_until_complete(stop_application_preview_sandbox(
            cache_service=cache_service,
            session_id=session_id,
            sandbox_id=sandbox_id,
            api_key=api_key,
        ))
    finally:
        loop.run_until_complete(secrets_manager.aclose())
        loop.close()


if app is not None:  # pragma: no cover - registration path runs in worker image.
    @app.task(name="code.run_application_preview", queue="app_code")
    def run_application_preview_task(session_id: str, payload: dict[str, Any]) -> None:
        _run_application_preview_session_sync(session_id, payload)


    @app.task(name="code.stop_application_preview", queue="app_code")
    def stop_application_preview_task(session_id: str, sandbox_id: str) -> None:
        _stop_application_preview_sandbox_sync(session_id, sandbox_id)
