"""Image Enhance worker: decrypt, check, re-render at 2K, store, charge once, deliver.

Specification feature.embed-user-edits (embed-user-edits.enhance.faithful-2k,
embed-user-edits.enhance.billed-once-refunded-on-failure); Plan
docs/plans/embed-user-edit-versions (A2). Started by POST /v1/images/enhance
for one pending ``image_enhance_jobs`` row.

Order matters for billing: the source and the result both pass the image
safety pipeline and the result is uploaded before the single charge, so a
provider, safety or storage failure costs nothing. The charge uses
``image_revision.billing_event_id(embed_id, N+1, operation_id)``, so a retried
request is never charged twice. The result (file metadata and its new AES key)
is stored Vault-encrypted for the requester; the client core reads it, builds
the next version's content and commits it through the user revision commit,
which moves the row to ``committed``.

``sweep_enhance_jobs`` (beat, every 10 minutes) deletes the files of a result
that was never committed within 24 hours and refunds it only when the result
never reached the requester (``result_delivered_at`` unset); it reconciles
charges whose outcome was unknown and drops terminal rows after 7 days.

A duplicate task delivery claims the pending row by compare-and-set
(``worker_claim``) before the provider call; a run that cannot claim it exits
without touching the job, its files or billing.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import uuid
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Dict, List, Mapping, Optional

import httpx
from cryptography.exceptions import InvalidTag
from PIL import Image

from backend.apps.images import enhance_jobs as jobs
from backend.core.api.app.services.s3.config import get_bucket_name
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app
from backend.shared.providers.google.gemini_image_enhance import (
    ENHANCE_MODEL_ID,
    ENHANCE_PROMPT,
    ImageEnhanceProviderError,
    enhance_image_google,
)
from backend.shared.python_utils.image_mime import validate_raster_image
from backend.shared.python_utils.image_safety import get_pipeline
from backend.shared.python_utils.media_encryption import (
    MEDIA_ENCRYPTION_V2,
    decrypt_media_payload,
    encrypt_media_variants,
    load_media_write_version,
)
from backend.shared.python_utils.storage_availability import initialize_task_storage, require_storage_available

logger = logging.getLogger(__name__)

MAX_SOURCE_BYTES = 40 * 1024 * 1024
FORMAT_MAPPING = {"original": "original", "full_webp": "full", "preview_webp": "preview"}
SWEEP_BATCH = 100
EVENT_READY = "image_enhance_ready"
EVENT_FAILED = "image_enhance_failed"

ERROR_SOURCE = "source_unavailable"
ERROR_SAFETY = "safety_rejected"
ERROR_PROVIDER = "provider_failed"
ERROR_BILLING = "billing_failed"
ERROR_STORAGE = "storage_failed"
ERROR_INTERNAL = "internal_error"


class EnhanceSourceUnavailable(RuntimeError):
    """The source file could not be read or decrypted; the request fails without a charge."""


async def _publish(task: Any, *, user_id: str, event: str, payload: Mapping[str, Any]) -> None:
    """Server-to-client event through the existing ``user_updates::*`` listener."""
    await task._cache_service.publish_event(f"user_updates::{jobs.hash_id(user_id)}", {
        "event_for_client": event, "user_id_uuid": user_id, "payload": dict(payload),
    })


async def _load_source(task: Any, *, s3_service: Any, source: Mapping[str, Any], vault_key_id: str) -> tuple[bytes, str]:
    aes_key_b64 = await task._encryption_service.decrypt_with_user_key(source["wrapped_aes_key"], vault_key_id)
    try:
        aes_key = base64.b64decode(aes_key_b64 or "", validate=True)
    except (TypeError, ValueError, binascii.Error) as exc:
        raise EnhanceSourceUnavailable("The source key could not be unwrapped") from exc
    bucket = get_bucket_name("chatfiles", s3_service.environment)
    encrypted = await s3_service.get_file(bucket_name=bucket, object_key=source["s3_key"])
    if not encrypted:
        raise EnhanceSourceUnavailable("The source file is missing")
    if len(encrypted) > MAX_SOURCE_BYTES:
        raise EnhanceSourceUnavailable("The source file is too large")
    variant = {"encryption": MEDIA_ENCRYPTION_V2} if source.get("encryption") == MEDIA_ENCRYPTION_V2 else {}
    try:
        image = decrypt_media_payload(
            encrypted_data=encrypted, aes_key=aes_key, variant=variant, legacy_nonce_b64=source.get("aes_nonce"),
        )
        _, mime_type = validate_raster_image(image)
    except (InvalidTag, ValueError) as exc:
        raise EnhanceSourceUnavailable("The source file could not be decrypted as an image") from exc
    return image, mime_type


def _size(content: bytes) -> tuple[int, int]:
    with Image.open(BytesIO(content)) as image:
        return image.size


async def _store_variants(
    task: Any, *, s3_service: Any, user_id: str, image: bytes, uploaded: List[Dict[str, str]],
) -> Dict[str, Any]:
    """Process into original/full/preview like images.generate, encrypt with one new key and upload.

    Each uploaded object is appended to ``uploaded`` at once, so the caller can
    delete everything when a later step fails.
    """
    from backend.core.api.app.utils.image_processing import process_image_for_storage

    generated_at = datetime.now(timezone.utc).isoformat()
    processed = process_image_for_storage(image, metadata={
        "prompt": ENHANCE_PROMPT, "model": jobs.MODEL_REF, "software": "OpenMates",
        "source": "OpenMates AI", "generated_at": generated_at,
    })
    encrypted = encrypt_media_variants(processed, write_version=load_media_write_version())
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    unique_id = uuid.uuid4().hex[:8]
    files: Dict[str, Dict[str, Any]] = {}
    for format_key, content in processed.items():
        extension, mime_type = validate_raster_image(content)
        file_key = f"{user_id}/{stamp}_{unique_id}_enhance_{format_key}.{extension}"
        result = await s3_service.upload_file(
            bucket_key="chatfiles", file_key=file_key, content=encrypted.payloads[format_key],
            content_type="application/octet-stream",
        )
        if not result.get("url"):
            raise RuntimeError(f"Failed to upload the {format_key} file of an enhanced image")
        uploaded.append({"bucket": "chatfiles", "key": file_key})
        width, height = _size(content)
        files[FORMAT_MAPPING.get(format_key, format_key)] = {
            "s3_key": file_key, "width": width, "height": height, "size_bytes": len(content),
            "format": extension, "mime_type": mime_type, **encrypted.metadata[format_key],
        }
    bucket = get_bucket_name("chatfiles", s3_service.environment)
    return {
        "files": files,
        "s3_base_url": f"https://{bucket}.{s3_service.base_domain}",
        "aes_key": encrypted.aes_key_b64,
        "aes_nonce": encrypted.legacy_nonce_b64 or "",
        "output_filetype": files["original"]["format"],
        "generated_at": generated_at,
    }


async def _fail(task: Any, job: Dict[str, Any], *, user_id: str, code: str, s3_service: Any,
                uploaded: List[Dict[str, str]], billing_state: Optional[str] = None) -> Dict[str, Any]:
    """Delete uploaded files, mark the job failed and tell the requester.

    ``billing_state`` None keeps the row's value: ``charging`` (charge or refund
    outcome unknown) is reconciled and refunded by the sweep.
    """
    for ref in uploaded:
        await s3_service.delete_file(bucket_key=ref["bucket"], file_key=ref["key"])
    changes: Dict[str, Any] = {"state": jobs.STATE_FAILED, "error_code": code}
    if billing_state is not None:
        changes["billing_state"] = billing_state
    failed = await jobs.transition(task._directus_service, job, expected_state=jobs.STATE_PENDING, changes=changes)
    await _publish(task, user_id=user_id, event=EVENT_FAILED, payload={
        "operation_id": job["operation_id"], "embed_id": job["embed_id"], "error_code": code,
    })
    return {"operation_id": job["operation_id"], "state": failed["state"], "error_code": code}


async def _rejected(task: Any, decision: Any, *, user_id: str, job: Mapping[str, Any], stage_embed: Optional[str],
                    log_prefix: str) -> None:
    """Record a safety refusal (strike, audit) exactly as images.generate does."""
    from backend.apps.images.tasks.generate_task import _handle_safety_rejection

    await _handle_safety_rejection(
        task, decision.rejection, user_id=user_id, prompt=ENHANCE_PROMPT, assistant_response_id=None,
        source_embed_id=str(job["embed_id"]), output_embed_id=stage_embed, provider=jobs.PROVIDER_ID,
        model=jobs.MODEL_REF, log_prefix=log_prefix,
    )


async def _claim(directus: Any, job: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Take a pending job for this run (compare-and-set); ``None`` when another run holds or just took it."""
    if job.get("worker_claim"):
        return None
    try:
        return await jobs.transition(directus, job, expected_state=jobs.STATE_PENDING,
                                     changes={"worker_claim": uuid.uuid4().hex})
    except jobs.EnhanceJobConflict:
        return None


async def _owned_pending(directus: Any, job: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """The current row if it is still pending under this run's claim, else ``None``."""
    latest = await jobs.get_job(directus, str(job["operation_id"]))
    if latest is None or latest["state"] != jobs.STATE_PENDING or latest.get("worker_claim") != job["worker_claim"]:
        return None
    return latest


async def _abandon(task: Any, job: Mapping[str, Any], *, s3_service: Any, uploaded: List[Dict[str, str]],
                   recorded: bool) -> None:
    """Cleanup after an unexpected failure: only a row this run still owns is failed.

    Files not yet recorded on the row are referenced by nothing else and are
    always deleted. Recorded files follow the row: they are deleted only with
    a row this run fails here (its billing_state stays as written, so a
    ``charging`` row is reconciled by the sweep).
    """
    if not recorded:
        for ref in uploaded:
            await s3_service.delete_file(bucket_key=ref["bucket"], file_key=ref["key"])
    latest = await _owned_pending(task._directus_service, job)
    if latest is None:
        return
    if recorded:
        for ref in uploaded:
            await s3_service.delete_file(bucket_key=ref["bucket"], file_key=ref["key"])
    await jobs.transition(task._directus_service, latest, expected_state=jobs.STATE_PENDING,
                          changes={"state": jobs.STATE_FAILED, "error_code": ERROR_INTERNAL})


async def run_enhance(
    task: Any, *, operation_id: str, user_id: str, vault_key_id: str, chat_id: Optional[str],
    source: Mapping[str, Any],
) -> Dict[str, Any]:
    """Process one pending job; a duplicate delivery that cannot claim it leaves everything alone."""
    log_prefix = f"[ImageEnhance {operation_id[:8]}]"
    await task.initialize_core_services()
    directus = task._directus_service
    job = await jobs.get_job(directus, operation_id)
    if job is None or job.get("hashed_user_id") != jobs.hash_id(user_id) or job["state"] != jobs.STATE_PENDING:
        logger.info("%s Nothing to do (job %s)", log_prefix, "missing" if job is None else job["state"])
        return {"operation_id": operation_id, "state": None if job is None else job["state"]}
    claimed = await _claim(directus, job)
    if claimed is None:
        logger.info("%s Another run owns the job; nothing to do", log_prefix)
        return {"operation_id": operation_id, "state": job["state"]}
    job = claimed
    s3_service: Any = None
    uploaded: List[Dict[str, str]] = []
    # settled: the row reached its next state through a handled path; recorded: files are on the row.
    settled = recorded = False
    try:
        s3_service = await initialize_task_storage(task)
        await require_storage_available(s3_service)
        try:
            image, mime_type = await _load_source(task, s3_service=s3_service, source=source, vault_key_id=vault_key_id)
        except EnhanceSourceUnavailable as exc:
            logger.warning("%s %s", log_prefix, exc)
            outcome = await _fail(task, job, user_id=user_id, code=ERROR_SOURCE, s3_service=s3_service,
                                  uploaded=uploaded)
            settled = True
            return outcome
        width, height = _size(image)

        pipeline = get_pipeline()
        decision = await pipeline.validate_input(
            prompt=ENHANCE_PROMPT, reference_images=[(image, mime_type)], secrets_manager=task._secrets_manager,
        )
        if not decision.allowed and decision.rejection:
            await _rejected(task, decision, user_id=user_id, job=job, stage_embed=None, log_prefix=log_prefix)
            outcome = await _fail(task, job, user_id=user_id, code=ERROR_SAFETY, s3_service=s3_service,
                                  uploaded=uploaded)
            settled = True
            return outcome

        try:
            enhanced = await enhance_image_google(
                image_bytes=image, mime_type=mime_type, width=width, height=height,
                secrets_manager=task._secrets_manager,
            )
            _, output_mime = validate_raster_image(enhanced.image_bytes)
        except (ImageEnhanceProviderError, ValueError) as exc:
            logger.warning("%s Provider produced no usable image: %s", log_prefix, exc)
            outcome = await _fail(task, job, user_id=user_id, code=ERROR_PROVIDER, s3_service=s3_service,
                                  uploaded=uploaded)
            settled = True
            return outcome

        decision = await pipeline.validate_output(
            prompt=ENHANCE_PROMPT, image_bytes=enhanced.image_bytes, mime_type=output_mime,
            secrets_manager=task._secrets_manager,
        )
        if not decision.allowed and decision.rejection:
            await _rejected(task, decision, user_id=user_id, job=job, stage_embed=str(job["embed_id"]),
                            log_prefix=log_prefix)
            outcome = await _fail(task, job, user_id=user_id, code=ERROR_SAFETY, s3_service=s3_service,
                                  uploaded=uploaded)
            settled = True
            return outcome

        stored = await _store_variants(task, s3_service=s3_service, user_id=user_id, image=enhanced.image_bytes,
                                       uploaded=uploaded)
        wrapped_key, _ = await task._encryption_service.encrypt_with_user_key(stored["aes_key"], vault_key_id)
        if not wrapped_key:
            raise RuntimeError("Failed to wrap the AES key of the enhanced image with Vault")
        # Files are recorded before the charge: a crash after it leaves a row the sweep can refund and clean.
        job = await jobs.transition(directus, job, expected_state=jobs.STATE_PENDING, changes={
            "result_file_keys": list(uploaded), "billing_state": jobs.BILLING_CHARGING,
        })
        recorded = True

        try:
            await jobs.charge(job=job, user_id=user_id, chat_id=chat_id)
        except httpx.HTTPStatusError as exc:
            # The ledger answered: nothing was charged.
            logger.error("%s Charge refused with HTTP %s", log_prefix, exc.response.status_code)
            outcome = await _fail(task, job, user_id=user_id, code=ERROR_BILLING, s3_service=s3_service,
                                  uploaded=uploaded, billing_state=jobs.BILLING_NONE)
            settled = True
            return outcome
        except httpx.HTTPError as exc:
            # Outcome unknown: billing_state stays "charging" and the sweep reconciles and refunds.
            logger.error("%s Charge outcome unknown: %s", log_prefix, exc)
            outcome = await _fail(task, job, user_id=user_id, code=ERROR_BILLING, s3_service=s3_service,
                                  uploaded=uploaded)
            settled = True
            return outcome

        result = {
            **stored,
            "vault_wrapped_aes_key": wrapped_key,
            "s3_file_keys": list(uploaded),
            "model": ENHANCE_MODEL_ID,
            "provider": jobs.PROVIDER_ID,
            "aspect_ratio": enhanced.aspect_ratio,
            "image_size": enhanced.image_size,
            "enhanced_from": {"embed_id": job["embed_id"], "version": job["base_version"]},
        }
        outcome = await _hand_over(task, job, result=result, user_id=user_id, vault_key_id=vault_key_id,
                                   s3_service=s3_service, uploaded=uploaded, log_prefix=log_prefix)
        settled = True
    finally:
        if not settled:
            await _abandon(task, job, s3_service=s3_service, uploaded=uploaded, recorded=recorded)
    if outcome["state"] == jobs.STATE_READY:
        original = stored["files"]["original"]
        logger.info("%s Ready: %sx%s, %s credits", log_prefix, original["width"], original["height"], job["credits"])
    return outcome


async def _hand_over(task: Any, job: Dict[str, Any], *, result: Mapping[str, Any], user_id: str, vault_key_id: str,
                     s3_service: Any, uploaded: List[Dict[str, str]], log_prefix: str) -> Dict[str, Any]:
    """After a confirmed charge: make the job ready, or fail it so that nothing stays charged.

    A transport failure of the ready write or of the refund leaves the outcome
    unknown: the job is failed with ``billing_state`` ``charging`` so the sweep
    re-issues the same charge and refunds it.
    """
    directus = task._directus_service
    try:
        sealed = await jobs.seal_result(task._encryption_service, vault_key_id=vault_key_id, result=result)
        job = await jobs.transition(directus, job, expected_state=jobs.STATE_PENDING, changes={
            "state": jobs.STATE_READY, "billing_state": jobs.BILLING_CHARGED,
            "charged_credits": int(job["credits"]), "encrypted_result": sealed.ciphertext,
        })
    except jobs.EnhanceJobError as exc:
        # Charged but the result cannot be handed over: refund, then fail without files.
        logger.error("%s Result could not be stored after the charge: %s", log_prefix, exc)
        try:
            await jobs.refund(job=job, user_id=user_id, reason="Enhanced image could not be stored",
                              log_prefix=log_prefix)
        except jobs.DIRECTUS_OR_LEDGER_ERRORS as refund_exc:
            logger.error("%s Refund outcome unknown; left for the sweep: %s", log_prefix, refund_exc)
            return await _fail(task, job, user_id=user_id, code=ERROR_STORAGE, s3_service=s3_service,
                               uploaded=uploaded, billing_state=jobs.BILLING_CHARGING)
        return await _fail(task, job, user_id=user_id, code=ERROR_STORAGE, s3_service=s3_service, uploaded=uploaded,
                           billing_state=jobs.BILLING_REFUNDED)
    except jobs.DIRECTUS_OR_LEDGER_ERRORS as exc:
        # The ready write may or may not have landed: read the row back.
        logger.error("%s Ready transition outcome unknown: %s", log_prefix, exc)
        latest = await jobs.get_job(directus, str(job["operation_id"]))
        if latest is not None and latest["state"] == jobs.STATE_READY and latest.get("worker_claim") == job["worker_claim"]:
            job = latest
        else:
            owned = await _owned_pending(directus, job)
            if owned is None:
                raise
            return await _fail(task, owned, user_id=user_id, code=ERROR_STORAGE, s3_service=s3_service,
                               uploaded=uploaded, billing_state=jobs.BILLING_CHARGING)
    await _publish(task, user_id=user_id, event=EVENT_READY, payload={
        "operation_id": job["operation_id"], "embed_id": job["embed_id"],
    })
    return {"operation_id": job["operation_id"], "state": job["state"]}


async def _reconcile_and_refund(job: Mapping[str, Any], *, reason: str, log_prefix: str) -> str:
    """Make the ledger match "nothing charged" and return the resulting billing_state."""
    user_id = str(job["user_id"])
    if job.get("billing_state") == jobs.BILLING_CHARGING:
        try:
            # Same identity: an earlier charge is returned as idempotent, a missing one is made now.
            await jobs.charge(job=job, user_id=user_id, chat_id=None)
        except httpx.HTTPStatusError:
            return jobs.BILLING_NONE
    elif job.get("billing_state") != jobs.BILLING_CHARGED:
        return str(job.get("billing_state") or jobs.BILLING_NONE)
    await jobs.refund(job=job, user_id=user_id, reason=reason, log_prefix=log_prefix)
    return jobs.BILLING_REFUNDED


async def _expire(task: Any, job: Dict[str, Any], *, s3_service: Any) -> None:
    """Delete an uncommitted result; refund it only if it never reached the requester."""
    log_prefix = f"[ImageEnhance {str(job['operation_id'])[:8]}]"
    if job.get("result_delivered_at") is not None:
        # The user has the picture: the charge stays, only the unsaved files go.
        billing_state = str(job.get("billing_state") or jobs.BILLING_NONE)
    else:
        billing_state = await _reconcile_and_refund(
            job, reason="Enhanced image never reached the user and was not saved", log_prefix=log_prefix,
        )
    await jobs.delete_result_files(s3_service, job)
    await jobs.transition(task._directus_service, job, expected_state=job["state"], changes={
        "state": jobs.STATE_EXPIRED, "billing_state": billing_state, "encrypted_result": None,
    })
    logger.info("%s Expired uncommitted (%s)", log_prefix, billing_state)


async def _fail_stale(task: Any, job: Dict[str, Any], *, s3_service: Any) -> None:
    """Fail the job of a hard-killed worker; the refund pass of the same sweep returns its charge.

    A charged job moves to ``charging`` (outcome to be reconciled), so the
    refund happens exactly once through the existing failed/charging path. The
    compare-and-set on the row loses against a worker that still finishes.
    """
    await jobs.delete_result_files(s3_service, job)
    billing_state = jobs.BILLING_CHARGING if job.get("billing_state") in (
        jobs.BILLING_CHARGING, jobs.BILLING_CHARGED) else str(job.get("billing_state") or jobs.BILLING_NONE)
    await jobs.transition(task._directus_service, job, expected_state=jobs.STATE_PENDING, changes={
        "state": jobs.STATE_FAILED, "error_code": ERROR_INTERNAL, "billing_state": billing_state,
    })
    await _publish(task, user_id=str(job["user_id"]), event=EVENT_FAILED, payload={
        "operation_id": job["operation_id"], "embed_id": job["embed_id"], "error_code": ERROR_INTERNAL,
    })
    logger.warning("[ImageEnhance %s] Worker claim went stale; job failed", str(job["operation_id"])[:8])


async def _sweep_candidates(directus: Any, *, state: str, cutoff: Optional[int] = None,
                           billing_state: Optional[str] = None,
                           extra_filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"filter[state][_eq]": state, "fields": jobs.JOB_FIELDS, "limit": SWEEP_BATCH}
    params.update(extra_filters or {})
    if cutoff is not None:
        params["filter[expires_at][_lt]"] = cutoff
    if billing_state is not None:
        params["filter[billing_state][_eq]"] = billing_state
    rows = await directus.get_items(jobs.COLLECTION, params=params, admin_required=True, no_cache=True,
                                    raise_on_error=True)
    if not isinstance(rows, list):
        raise jobs.EnhanceJobError("Enhance sweep lookup failed")
    return [{**row, "result_file_keys": jobs.json_value(row.get("result_file_keys"))} for row in rows]


async def sweep_enhance_jobs(task: Any, *, now: Optional[int] = None) -> Dict[str, int]:
    """Refund and clean uncommitted results, reconcile unknown charges, drop old terminal rows."""
    await task.initialize_core_services()
    directus = task._directus_service
    s3_service = await initialize_task_storage(task)
    current = jobs.now_ts() if now is None else now
    cutoff = current - jobs.EXPIRY_GRACE_SECONDS
    counts = {"expired": 0, "reconciled": 0, "errors": 0, "deleted_rows": 0}
    for state in (jobs.STATE_READY, jobs.STATE_PENDING):
        for job in await _sweep_candidates(directus, state=state, cutoff=cutoff):
            try:
                await _expire(task, job, s3_service=s3_service)
                counts["expired"] += 1
            except (httpx.HTTPError, jobs.EnhanceJobError) as exc:
                counts["errors"] += 1
                logger.error("Enhance sweep could not expire %s: %s", str(job["operation_id"])[:8], exc)
    stale_filters = {
        "filter[updated_at][_lt]": current - jobs.STALE_CLAIM_SECONDS,
        "filter[worker_claim][_null]": False,
        "filter[encrypted_result][_null]": True,
    }
    counts["stale_failed"] = 0
    for job in await _sweep_candidates(directus, state=jobs.STATE_PENDING, extra_filters=stale_filters):
        try:
            await _fail_stale(task, job, s3_service=s3_service)
            counts["stale_failed"] += 1
        except (httpx.HTTPError, jobs.EnhanceJobError) as exc:
            counts["errors"] += 1
            logger.error("Enhance sweep could not fail stale %s: %s", str(job["operation_id"])[:8], exc)
    for job in await _sweep_candidates(directus, state=jobs.STATE_FAILED, billing_state=jobs.BILLING_CHARGING):
        try:
            billing_state = await _reconcile_and_refund(
                job, reason="Enhance failed after an unconfirmed charge", log_prefix="[ImageEnhance sweep]",
            )
            await jobs.transition(directus, job, expected_state=jobs.STATE_FAILED,
                                  changes={"billing_state": billing_state})
            counts["reconciled"] += 1
        except (httpx.HTTPError, jobs.EnhanceJobError) as exc:
            counts["errors"] += 1
            logger.error("Enhance sweep could not reconcile %s: %s", str(job["operation_id"])[:8], exc)
    retention_cutoff = current - jobs.TERMINAL_ROW_RETENTION_SECONDS
    for state in (jobs.STATE_COMMITTED, jobs.STATE_EXPIRED):
        deleted = await directus.delete_items(jobs.COLLECTION, {
            "state": {"_eq": state}, "created_at": {"_lt": retention_cutoff},
        }, admin_required=True)
        counts["deleted_rows"] += int(deleted)
    deleted = await directus.delete_items(jobs.COLLECTION, {
        "state": {"_eq": jobs.STATE_FAILED}, "billing_state": {"_neq": jobs.BILLING_CHARGING},
        "created_at": {"_lt": retention_cutoff},
    }, admin_required=True)
    counts["deleted_rows"] += int(deleted)
    return counts


@app.task(bind=True, name="apps.images.tasks.enhance", base=BaseServiceTask, queue="app_images",
          soft_time_limit=540, time_limit=600)
def enhance_image_task(self, operation_id: str, user_id: str, vault_key_id: str, chat_id: Optional[str],
                       source: Dict[str, Any]) -> Dict[str, Any]:
    """Celery entry point of one Enhance job (dispatched by POST /v1/images/enhance)."""
    return asyncio.run(run_enhance(self, operation_id=operation_id, user_id=user_id, vault_key_id=vault_key_id,
                                   chat_id=chat_id, source=source))


@app.task(bind=True, name="apps.images.tasks.enhance_sweep", base=BaseServiceTask, queue="app_images",
          soft_time_limit=480, time_limit=540)
def sweep_enhance_jobs_task(self) -> Dict[str, int]:
    """Beat entry point of the Enhance expiry and refund sweep."""
    return asyncio.run(sweep_enhance_jobs(self))
