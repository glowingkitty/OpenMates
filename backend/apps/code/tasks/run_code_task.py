# backend/apps/code/tasks/run_code_task.py
#
# Celery task for Code Run executions.
# Reads a pre-normalized file bundle from the API route, executes it in the
# restricted E2B provider, stores terminal output in Redis, and charges credits
# after completion using minute-rounded sandbox duration.

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import math
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

import httpx

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.tasks.celery_config import app, get_worker_cache_service
from backend.shared.providers.e2b_code_runner import (
    CodeRunCancelled,
    CodeRunDependencyInstall,
    CodeRunFile,
    get_e2b_api_key_async,
    redact_execution_output,
    run_code_in_e2b,
)

try:
    from backend.core.api.app.services.directus import DirectusService
    from backend.core.api.app.services.s3.config import get_bucket_name
    from backend.core.api.app.services.s3.service import S3UploadService
    from backend.core.api.app.utils.encryption import EncryptionService
    from backend.shared.python_utils.generated_assets import build_download_url, create_download_token
    from backend.shared.python_utils.generated_assets.service import cache_s3_file_keys, index_generated_asset
    from backend.shared.python_utils.media_encryption import encrypt_media_variants, load_media_write_version
except Exception:  # pragma: no cover - deployment image dependency guard
    DirectusService = None
    EncryptionService = None
    S3UploadService = None
    get_bucket_name = None
    build_download_url = None
    create_download_token = None
    cache_s3_file_keys = None
    index_generated_asset = None
    encrypt_media_variants = None
    load_media_write_version = None


logger = logging.getLogger(__name__)

EXECUTION_TTL_SECONDS = 3600
RUN_CREDITS_PER_MINUTE = 5
INTERNAL_API_BASE_URL = os.getenv("INTERNAL_API_BASE_URL", "http://api:8000")
INTERNAL_API_SHARED_TOKEN = os.getenv("INTERNAL_API_SHARED_TOKEN")
CODE_RUN_CHANNEL_PREFIX = "code_run_stream"
ARTIFACT_DOWNLOAD_TTL_SECONDS = 900
CODE_RUN_BILLING_IDEMPOTENCY_PREFIX = "code-run"
NATIVE_IMAGE_MIME_TYPES = {"image/png", "image/webp"}
ARTIFACT_SENSITIVE_FIELDS = {
    "aes_key",
    "aes_nonce",
    "bytes",
    "content_base64",
    "download_url",
    "native_render_payload",
    "s3_key",
    "sandbox_id",
    "token",
    "vault_wrapped_aes_key",
}


def _execution_key(execution_id: str) -> str:
    return f"code_run_execution:{execution_id}"


def _stream_channel(execution_id: str) -> str:
    return f"{CODE_RUN_CHANNEL_PREFIX}:{execution_id}"


def _event(kind: str, text: str, timestamp: float | None = None) -> dict[str, Any]:
    return {"kind": kind, "text": text, "timestamp": timestamp or time.time()}


def _safe_artifact_metadata(
    artifacts: list[dict[str, Any]] | None,
    *,
    include_download_url: bool = False,
    include_native_render_payload: bool = False,
) -> list[dict[str, Any]]:
    """Strip artifact bytes, keys, tokens, and storage internals from status payloads."""
    allowed_sensitive_fields = set()
    if include_download_url:
        allowed_sensitive_fields.add("download_url")
    if include_native_render_payload:
        allowed_sensitive_fields.add("native_render_payload")
    blocked_fields = ARTIFACT_SENSITIVE_FIELDS - allowed_sensitive_fields
    safe: list[dict[str, Any]] = []
    for artifact in artifacts or []:
        if not isinstance(artifact, dict):
            continue
        item = {
            key: value
            for key, value in artifact.items()
            if key not in blocked_fields
        }
        if item.get("path") and item.get("mime_type") and item.get("size_bytes"):
            item.setdefault("status", "captured")
            safe.append(item)
    return safe


def _artifact_storage_failed_metadata(artifacts: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    safe = _safe_artifact_metadata(artifacts)
    for artifact in safe:
        artifact["status"] = "storage_failed"
    return safe


def _public_api_base_url() -> str:
    configured = (
        os.getenv("OPENMATES_API_URL")
        or os.getenv("PUBLIC_API_BASE_URL")
        or os.getenv("API_BASE_URL")
        or "https://api.dev.openmates.org"
    )
    return configured.rstrip("/")


def _artifact_asset_id(execution_id: str, payload: dict[str, Any]) -> str:
    target_embed_id = payload.get("target_embed_id")
    return target_embed_id if isinstance(target_embed_id, str) and target_embed_id else execution_id


def _artifact_variant_name(normalized_path: str, used_variants: set[str]) -> str:
    path_hash = hashlib.sha256(normalized_path.encode("utf-8")).hexdigest()[:12]
    slug = "".join(character.lower() if character.isalnum() else "-" for character in normalized_path).strip("-")
    slug = "-".join(part for part in slug.split("-") if part)[:48] or "artifact"
    variant = f"{slug}-{path_hash}"
    suffix = 2
    while variant in used_variants:
        variant = f"{slug}-{path_hash}-{suffix}"
        suffix += 1
    used_variants.add(variant)
    return variant


def _artifact_filename(normalized_path: str) -> str:
    filename = PurePosixPath(normalized_path).name or "artifact"
    safe = "".join(character if character.isalnum() or character in {".", "-", "_"} else "_" for character in filename)
    return safe[:96] or "artifact"


async def _persist_code_run_artifacts(
    *,
    execution_id: str,
    payload: dict[str, Any],
    artifacts: list[dict[str, Any]] | None,
    secrets_manager: Any,
    cache_service: Any | None = None,
    now: float | None = None,
) -> list[dict[str, Any]]:
    if not artifacts:
        return []
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
            encrypt_media_variants,
            load_media_write_version,
        )
    ):
        logger.error("Code Run artifact storage dependencies are unavailable")
        return _artifact_storage_failed_metadata(artifacts)

    try:
        cache_service = cache_service or await get_worker_cache_service()
        user_id = str(payload.get("user_id") or "")
        if not user_id:
            raise RuntimeError("Code Run artifact storage requires user_id")

        encryption_service = EncryptionService(cache_service=cache_service)
        await encryption_service.initialize()
        directus_service = DirectusService(cache_service=cache_service, encryption_service=encryption_service)
        s3_service = S3UploadService(
            secrets_manager=secrets_manager,
            directus_service=directus_service,
        )
        await s3_service.initialize(configure_buckets=False)

        user_profile = await directus_service.get_user_fields_direct(user_id, ["vault_key_id", "storage_used_bytes"])
        vault_key_id = (user_profile or {}).get("vault_key_id")
        if not vault_key_id:
            raise RuntimeError("Code Run artifact owner is missing a Vault key")

        used_variants: set[str] = set()
        plaintext_by_variant: dict[str, bytes] = {}
        artifact_by_variant: dict[str, dict[str, Any]] = {}
        for artifact in artifacts:
            normalized_path = str(artifact.get("normalized_path") or artifact.get("path") or "")
            content_base64 = artifact.get("content_base64")
            if not normalized_path or not isinstance(content_base64, str):
                continue
            content = base64.b64decode(content_base64, validate=True)
            variant = _artifact_variant_name(normalized_path, used_variants)
            plaintext_by_variant[variant] = content
            artifact_by_variant[variant] = artifact

        if not plaintext_by_variant:
            return _artifact_storage_failed_metadata(artifacts)

        encrypted = encrypt_media_variants(
            plaintext_by_variant,
            write_version=load_media_write_version(),
        )
        vault_wrapped_aes_key, _ = await encryption_service.encrypt_with_user_key(
            encrypted.aes_key_b64,
            str(vault_key_id),
        )
        if not vault_wrapped_aes_key:
            raise RuntimeError("Failed to wrap Code Run artifact AES key with Vault")

        created_at = int(now if now is not None else time.time())
        timestamp = datetime.fromtimestamp(created_at, tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
        asset_id = _artifact_asset_id(execution_id, payload)
        uploaded_keys: list[str] = []
        files_metadata: dict[str, dict[str, Any]] = {}
        for variant, encrypted_payload in encrypted.payloads.items():
            artifact = artifact_by_variant[variant]
            normalized_path = str(artifact.get("normalized_path") or artifact.get("path"))
            filename = _artifact_filename(normalized_path)
            extension = PurePosixPath(filename).suffix.lstrip(".") or "bin"
            file_key = f"{user_id}/{timestamp}_{uuid.uuid4().hex[:8]}_code_run_{filename}"
            upload = await s3_service.upload_file(
                bucket_key="chatfiles",
                file_key=file_key,
                content=encrypted_payload,
                content_type="application/octet-stream",
                metadata={"openmates-purpose": "code-run-artifact"},
            )
            if not upload.get("url"):
                raise RuntimeError("Code Run artifact upload did not return an object URL")
            uploaded_keys.append(file_key)
            metadata = {
                "s3_key": file_key,
                "size_bytes": int(artifact.get("size_bytes") or len(plaintext_by_variant[variant])),
                "format": extension,
                "mime_type": str(artifact.get("mime_type") or "application/octet-stream"),
                "path": str(artifact.get("path") or normalized_path),
                "normalized_path": normalized_path,
                "kind": str(artifact.get("kind") or "data"),
            }
            metadata.update(encrypted.metadata.get(variant) or {})
            files_metadata[variant] = metadata

        chatfiles_bucket = get_bucket_name("chatfiles", getattr(s3_service, "environment", None))
        s3_base_url = f"https://{chatfiles_bucket}.{s3_service.base_domain}"
        content_hash_source = b"".join(
            variant.encode("utf-8") + b"\0" + hashlib.sha256(plaintext).digest()
            for variant, plaintext in sorted(plaintext_by_variant.items())
        )
        indexed = await index_generated_asset(
            type("CodeRunArtifactTask", (), {
                "_directus_service": directus_service,
                "_s3_service": s3_service,
                "_cache_service": cache_service,
            })(),
            user_id=user_id,
            embed_id=asset_id,
            media_type="code_run",
            files_metadata=files_metadata,
            s3_base_url=s3_base_url,
            aes_key_b64=encrypted.aes_key_b64,
            nonce_b64=encrypted.legacy_nonce_b64 or "",
            vault_wrapped_aes_key=vault_wrapped_aes_key,
            created_at=created_at,
            content_hash_source=content_hash_source,
            original_filename=f"openmates_code_run_{execution_id[:8]}",
            content_type="application/octet-stream",
            log_prefix=f"[CodeRunArtifacts] [execution:{execution_id[:8]}]",
            provenance_metadata={
                "source": "code_run",
                "mode": "chat_bound" if payload.get("chat_id") and payload.get("target_embed_id") else "direct",
                "execution_id": execution_id,
                "chat_id": payload.get("chat_id"),
                "target_embed_id": payload.get("target_embed_id"),
                "target_path": payload.get("target_path"),
                "artifact_paths": [metadata["normalized_path"] for metadata in files_metadata.values()],
            },
        )
        if not indexed:
            for file_key in uploaded_keys:
                try:
                    await s3_service.delete_file(bucket_key="chatfiles", file_key=file_key)
                except Exception as cleanup_exc:
                    logger.warning("Code Run artifact cleanup failed for %s: %s", file_key, cleanup_exc)
            return _artifact_storage_failed_metadata(artifacts)

        await cache_s3_file_keys(
            type("CodeRunArtifactTask", (), {
                "_directus_service": directus_service,
                "_s3_service": s3_service,
                "_cache_service": cache_service,
            })(),
            embed_id=asset_id,
            files_metadata=files_metadata,
            log_prefix=f"[CodeRunArtifacts] [execution:{execution_id[:8]}]",
        )

        download_expires_at = created_at + ARTIFACT_DOWNLOAD_TTL_SECONDS
        stored_artifacts: list[dict[str, Any]] = []
        chat_bound = bool(payload.get("chat_id") and payload.get("target_embed_id"))
        for variant, artifact in artifact_by_variant.items():
            token = create_download_token(
                asset_id=asset_id,
                user_id=user_id,
                variant=variant,
                expires_at=download_expires_at,
            )
            stored_artifact = {
                "path": str(artifact.get("path") or artifact.get("normalized_path") or ""),
                "normalized_path": str(artifact.get("normalized_path") or artifact.get("path") or ""),
                "mime_type": str(artifact.get("mime_type") or "application/octet-stream"),
                "kind": str(artifact.get("kind") or "data"),
                "size_bytes": int(artifact.get("size_bytes") or 0),
                "status": "captured",
                "asset_id": asset_id,
                "variant": variant,
                "download_url": build_download_url(
                    base_url=_public_api_base_url(),
                    asset_id=asset_id,
                    variant=variant,
                    token=token,
                ),
                "download_expires_at": download_expires_at,
            }
            if chat_bound and stored_artifact["mime_type"] in NATIVE_IMAGE_MIME_TYPES:
                file_metadata = dict(files_metadata[variant])
                stored_artifact["native_render_payload"] = {
                    "app_id": "images",
                    "frontend_type": "image",
                    "content": {
                        "filename": _artifact_filename(stored_artifact["normalized_path"]),
                        "s3_base_url": s3_base_url,
                        "files": {"full": file_metadata, "original": file_metadata},
                        "aes_key": encrypted.aes_key_b64,
                        "aes_nonce": encrypted.legacy_nonce_b64 or "",
                        "file_size": stored_artifact["size_bytes"],
                        "file_type": stored_artifact["mime_type"],
                        "is_authenticated": True,
                    },
                }
            stored_artifacts.append(stored_artifact)
        return stored_artifacts
    except Exception as exc:
        logger.warning("Code Run artifact storage failed for %s: %s", execution_id, exc, exc_info=True)
        return _artifact_storage_failed_metadata(artifacts)


def _safe_skipped_artifacts(skipped_artifacts: list[dict[str, str]] | None) -> list[dict[str, str]]:
    safe: list[dict[str, str]] = []
    for skipped in skipped_artifacts or []:
        if not isinstance(skipped, dict):
            continue
        path = skipped.get("path")
        reason = skipped.get("reason")
        if isinstance(path, str) and isinstance(reason, str):
            safe.append({"path": path, "reason": reason})
    return safe


def _build_code_run_completion_result(
    *,
    execution_id: str,
    payload: dict[str, Any],
    final_status: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": execution_id,
        "app_id": "code",
        "skill_id": "run",
        "status": final_status.get("status"),
        "execution_id": execution_id,
        "embed_id": payload.get("target_embed_id"),
        "target_embed_id": payload.get("target_embed_id"),
        "target_filename": payload.get("target_path"),
        "files": [file.get("path") for file in payload.get("files", []) if isinstance(file.get("path"), str)],
        "exit_code": final_status.get("exit_code"),
        "duration_seconds": final_status.get("duration_seconds"),
        "charged_credits": final_status.get("charged_credits"),
        "charged_minutes": final_status.get("charged_minutes"),
        "artifacts": _safe_artifact_metadata(final_status.get("artifacts")),
        "skipped_artifacts": _safe_skipped_artifacts(final_status.get("skipped_artifacts")),
        "error": final_status.get("error"),
    }


async def _dispatch_code_run_async_continuation(
    *,
    cache_service: Any,
    async_task_id: str,
    completed_results: list[dict[str, Any]],
    result_status: str = "finished",
    request_metadata: dict[str, Any] | None = None,
) -> str | None:
    from backend.apps.ai.tasks.async_skill_continuation import dispatch_async_skill_continuation

    return await dispatch_async_skill_continuation(
        cache_service=cache_service,
        async_task_id=async_task_id,
        completed_results=completed_results,
        result_status=result_status,
        request_metadata=request_metadata or {},
    )


async def _store_execution(execution_id: str, patch: dict[str, Any]) -> None:
    cache_service = await get_worker_cache_service()
    client = await cache_service.client
    key = _execution_key(execution_id)
    raw = await client.get(key)
    data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw) if raw else {}
    data.update(patch)
    data["updated_at"] = time.time()
    await client.set(key, json.dumps(data), ex=EXECUTION_TTL_SECONDS)
    await cache_service.publish_event(
        _stream_channel(execution_id),
        {"type": "code_run_update", "payload": {**patch, "updated_at": data["updated_at"]}},
    )


async def _append_output(execution_id: str, kind: str, text: str) -> None:
    cache_service = await get_worker_cache_service()
    client = await cache_service.client
    key = _execution_key(execution_id)
    raw = await client.get(key)
    data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw) if raw else {}
    events = data.setdefault("events", [])
    event = _event(kind, text)
    events.append(event)
    data["updated_at"] = time.time()
    await client.set(key, json.dumps(data), ex=EXECUTION_TTL_SECONDS)
    await cache_service.publish_event(
        _stream_channel(execution_id),
        {"type": "code_run_event", "payload": event},
    )


async def _is_cancel_requested(execution_id: str) -> bool:
    cache_service = await get_worker_cache_service()
    client = await cache_service.client
    raw = await client.get(_execution_key(execution_id))
    data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw) if raw else {}
    return bool(data.get("cancel_requested") or data.get("status") == "cancelled")


async def _charge_run_credits(
    payload: dict[str, Any],
    credits: int,
    execution_id: str,
    usage_details: dict[str, Any],
) -> int:
    file_names = [file.get("path") for file in payload.get("files", []) if isinstance(file.get("path"), str)]
    usage_payload = {
        "execution_id": execution_id,
        "target_embed_id": payload.get("target_embed_id"),
        "target_filename": payload.get("target_path"),
        "chat_id": payload.get("chat_id"),
        "message_id": payload.get("message_id"),
        "credits_per_minute": RUN_CREDITS_PER_MINUTE,
        "files_count": len(payload.get("files", [])),
        "code_run_filenames": file_names,
        **usage_details,
    }
    idempotency_fingerprint = hashlib.sha256(
        json.dumps(
            {
                "user_id_hash": payload["user_id_hash"],
                "credits": credits,
                "usage_details": usage_payload,
            },
            sort_keys=True,
            default=str,
        ).encode("utf-8"),
    ).hexdigest()[:16]
    charge_payload = {
        "user_id": payload["user_id"],
        "user_id_hash": payload["user_id_hash"],
        "credits": credits,
        "skill_id": "run",
        "app_id": "code",
        "idempotency_key": f"{CODE_RUN_BILLING_IDEMPOTENCY_PREFIX}:{execution_id}:{idempotency_fingerprint}",
        "usage_details": usage_payload,
        "api_key_hash": payload.get("api_key_hash"),
        "device_hash": payload.get("device_hash"),
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
    return credits


async def _clear_active_run(payload: dict[str, Any]) -> None:
    active_key = payload.get("active_run_key")
    active_owner = payload.get("active_run_owner")
    provider_active_key = payload.get("provider_active_run_key")
    provider_active_owner = payload.get("provider_active_run_owner")
    if not active_key and not provider_active_key:
        return
    cache_service = await get_worker_cache_service()
    client = await cache_service.client
    if active_key and active_owner:
        await client.srem(active_key, active_owner)
    if provider_active_key and provider_active_owner:
        await client.srem(provider_active_key, provider_active_owner)


def _run_code_execution(execution_id: str, payload: dict[str, Any]) -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    secrets_manager = SecretsManager()

    def run_async(coro: Any) -> Any:
        return loop.run_until_complete(coro)

    started_at = time.time()
    billable_started_at = 0.0
    billing_state = {"charged_credits": 0, "charged_minutes": 0}
    run_async(_store_execution(execution_id, {"status": "preparing_sandbox", "started_at": started_at}))

    def charge_run(duration: float, billing_phase: str) -> None:
        if billing_state["charged_credits"]:
            return
        if duration <= 0:
            return
        charged_minutes = max(1, math.ceil(duration / 60))
        charged_credits = run_async(
            _charge_run_credits(
                payload,
                charged_minutes * RUN_CREDITS_PER_MINUTE,
                execution_id,
                {
                    "billing_phase": billing_phase,
                    "duration_seconds": round(duration, 3),
                    "charged_minutes": charged_minutes,
                    "total_charged_minutes": charged_minutes,
                },
            )
        )
        billing_state["charged_credits"] = charged_credits
        billing_state["charged_minutes"] = charged_minutes
        run_async(_store_execution(
            execution_id,
            {"charged_credits": charged_credits, "charged_minutes": charged_minutes},
        ))

    def on_output(kind: str, text: str) -> None:
        nonlocal billable_started_at
        if kind == "status":
            if text.startswith("Starting sandbox"):
                run_async(_store_execution(execution_id, {"status": "preparing_sandbox"}))
            elif text.startswith("Uploading"):
                billable_started_at = time.time()
                run_async(_store_execution(execution_id, {"status": "uploading_files"}))
            elif text.startswith("Installing"):
                run_async(_store_execution(execution_id, {"status": "installing_dependencies"}))
            elif text.startswith("Running"):
                run_async(_store_execution(execution_id, {"status": "running"}))
        run_async(_append_output(execution_id, kind, text))

    def should_cancel() -> bool:
        return bool(run_async(_is_cancel_requested(execution_id)))

    def billable_duration() -> float:
        return time.time() - billable_started_at if billable_started_at else 0.0

    def dispatch_assistant_completion(final_status: dict[str, Any], cache_service: Any | None = None) -> None:
        if not payload.get("assistant_async_task"):
            return
        cache_service = cache_service or run_async(get_worker_cache_service())
        run_async(_dispatch_code_run_async_continuation(
            cache_service=cache_service,
            async_task_id=execution_id,
            completed_results=[_build_code_run_completion_result(
                execution_id=execution_id,
                payload=payload,
                final_status=final_status,
            )],
            result_status=str(final_status.get("status") or "finished"),
            request_metadata={"target_filename": payload.get("target_path")},
        ))

    def finalize_cancelled() -> None:
        duration = billable_duration()
        charge_run(duration, "cancelled")
        credits = billing_state["charged_credits"]
        run_async(_append_output(
            execution_id,
            "status",
            f"Cancelled at {time.strftime('%H:%M')} after {duration:.1f}s. Charged {credits} credits.\n",
        ))
        final_status = {
            "status": "cancelled",
            "duration_seconds": duration,
            "charged_credits": credits,
            "charged_minutes": billing_state["charged_minutes"],
            "finished_at": time.time(),
        }
        run_async(_store_execution(
            execution_id,
            final_status,
        ))
        dispatch_assistant_completion(final_status)

    try:
        if should_cancel():
            finalize_cancelled()
            return
        run_async(secrets_manager.initialize())
        api_key = run_async(get_e2b_api_key_async(secrets_manager))
        files = [CodeRunFile(**item) for item in payload["files"]]
        dependency_installs = [
            CodeRunDependencyInstall(ecosystem=item["ecosystem"], packages=tuple(item["packages"]))
            for item in payload.get("dependency_installs", [])
            if isinstance(item, dict) and isinstance(item.get("packages"), list)
        ]
        result = run_code_in_e2b(
            files,
            payload["target_path"],
            on_output,
            api_key,
            dependency_installs,
            should_cancel,
            bool(payload.get("enable_internet", True)),
        )
        duration = result.duration_seconds
        status = "finished" if result.exit_code in (None, 0) else "failed"
        charged_minutes = max(1, math.ceil(duration / 60))
        charge_run(duration, "completed")
        credits = billing_state["charged_credits"]
        run_async(_append_output(
            execution_id,
            "status",
            f"Exited at {time.strftime('%H:%M')} with code {result.exit_code if result.exit_code is not None else 0} in {duration:.1f}s. Charged {credits} credits.\n",
        ))
        if result.output_truncated:
            run_async(_append_output(execution_id, "stderr", "Output was truncated after 100 KB.\n"))
        cache_service = run_async(get_worker_cache_service())
        stored_artifacts = run_async(_persist_code_run_artifacts(
            execution_id=execution_id,
            payload=payload,
            artifacts=result.artifacts,
            secrets_manager=secrets_manager,
            cache_service=cache_service,
        ))
        final_status = {
            "status": status,
            "exit_code": result.exit_code if result.exit_code is not None else 0,
            "duration_seconds": duration,
            "charged_credits": credits,
            "charged_minutes": charged_minutes,
            "artifacts": _safe_artifact_metadata(
                stored_artifacts,
                include_download_url=True,
                include_native_render_payload=True,
            ),
            "skipped_artifacts": _safe_skipped_artifacts(result.skipped_artifacts),
            "finished_at": time.time(),
        }
        run_async(_store_execution(
            execution_id,
            final_status,
        ))
        dispatch_assistant_completion(final_status, cache_service)
    except CodeRunCancelled:
        finalize_cancelled()
    except Exception as exc:
        safe_error = redact_execution_output(str(exc))
        logger.error("Code Run execution %s failed: %s", execution_id, safe_error, exc_info=True)
        if billable_started_at and not billing_state["charged_credits"]:
            charge_run(time.time() - billable_started_at, "failed")
        run_async(_append_output(execution_id, "stderr", f"Run failed: {safe_error}\n"))
        final_status = {
            "status": "failed",
            "error": safe_error,
            "duration_seconds": time.time() - started_at,
            "charged_credits": billing_state["charged_credits"],
            "charged_minutes": billing_state["charged_minutes"],
            "finished_at": time.time(),
        }
        run_async(_store_execution(
            execution_id,
            final_status,
        ))
        dispatch_assistant_completion(final_status)
    finally:
        run_async(_clear_active_run(payload))
        run_async(secrets_manager.aclose())
        loop.close()


@app.task(name="code.run_execution", queue="app_code")
def run_code_execution_task(execution_id: str, payload: dict[str, Any]) -> None:
    _run_code_execution(execution_id, payload)
