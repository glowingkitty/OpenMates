"""Job rows, price, result sealing and refunds of the image Enhance action.

Specification feature.embed-user-edits (embed-user-edits.enhance.faithful-2k,
embed-user-edits.enhance.billed-once-refunded-on-failure); Plan
docs/plans/embed-user-edit-versions (A2). Shared by the route
(``backend/core/api/app/routes/images_enhance.py``) and the worker
(``backend/apps/images/tasks/enhance_task.py``).

One ``image_enhance_jobs`` row per ``operation_id``. States:

* ``pending``   accepted, the worker is running; nothing charged yet. One worker
                run owns it at a time (``worker_claim``, set by compare-and-set).
* ``ready``     result files uploaded, charged once, result sealed for the requester.
* ``committed`` set by the user revision commit when the result became version N+1.
* ``failed``    provider, safety, storage or billing failure; no charge remains.
* ``expired``   never committed within 24 hours: files deleted. Refunded only when
                the result never reached the requester (``result_delivered_at`` unset);
                a delivered result keeps its charge.

``result_delivered_at`` is set before a route response first carries the
result payload (file keys and the result's AES key), so a picture the user
already has is never refunded just because it was not saved.

Every state change is a compare-and-set on the row ``version`` plus the expected
state, so a commit and the expiry sweep can never both win. ``billing_state``
tracks the ledger: ``charging`` means a charge may have been recorded (the call
did not answer) and is reconciled by re-issuing the same idempotent charge
before refunding it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

import httpx
from fastapi import HTTPException

from backend.shared.providers.google.gemini_image_enhance import ENHANCE_MODEL_ID
from backend.shared.python_utils.billing_utils import calculate_total_credits

logger = logging.getLogger(__name__)

COLLECTION = "image_enhance_jobs"
APP_ID = "images"
SKILL_ID = "enhance"
PROVIDER_ID = "google"
MODEL_REF = f"{PROVIDER_ID}/{ENHANCE_MODEL_ID}"
JOB_TTL_SECONDS = 24 * 3600
# The commit refuses a job at expires_at; the sweep waits this long more so an
# in-flight commit always finishes first.
EXPIRY_GRACE_SECONDS = 600
# A pending job whose worker claim has not been touched for this long and that
# has no result belongs to a hard-killed worker (OOM, container stop). It is
# well above the real provider time (~20 s) and above the task time limit
# (600 s), so a live run is never taken for dead; the sweep then fails the job
# and refunds its charge instead of waiting for the 24 h expiry.
STALE_CLAIM_SECONDS = 15 * 60
TERMINAL_ROW_RETENTION_SECONDS = 7 * 24 * 3600

STATE_PENDING = "pending"
STATE_READY = "ready"
STATE_COMMITTED = "committed"
STATE_FAILED = "failed"
STATE_EXPIRED = "expired"
STATES = (STATE_PENDING, STATE_READY, STATE_COMMITTED, STATE_FAILED, STATE_EXPIRED)

BILLING_NONE = "none"
BILLING_CHARGING = "charging"
BILLING_CHARGED = "charged"
BILLING_REFUNDED = "refunded"

JOB_FIELDS = (
    "id,operation_id,embed_id,hashed_user_id,user_id,scope_kind,scope_id_hash,state,base_version,target_version,"
    "version,credits,billing_event_id,billing_state,charged_credits,result_file_keys,encrypted_result,"
    "error_code,worker_claim,result_delivered_at,created_at,updated_at,expires_at"
)

# `project_items.item_type` values that make an embed a Project file; mirrors
# PROJECT_FILE_ITEM_TYPES in the embed-version-transaction extension
# (src/project-items.js). A link counts only while deleted_target_state is null.
PROJECT_FILE_ITEM_TYPES = ("embed", "upload")


# What the Directus client and the ledger calls raise when a request did not
# complete (transport failure, or the Directus client's HTTPException after its
# retries); the outcome of that write is unknown.
DIRECTUS_OR_LEDGER_ERRORS = (httpx.HTTPError, HTTPException)


class EnhanceJobError(RuntimeError):
    """A job row could not be read or written as required."""


class EnhanceJobConflict(EnhanceJobError):
    """The row changed under a compare-and-set (another writer won)."""


def hash_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def now_ts() -> int:
    return int(time.time())


def enhance_credits(config_manager: Any) -> int:
    """Price of one Enhance from the Google provider pricing entry (never hard-coded)."""
    model = config_manager.get_model_pricing(PROVIDER_ID, ENHANCE_MODEL_ID)
    if not model or not model.get("pricing"):
        raise EnhanceJobError(f"No pricing entry for {MODEL_REF}")
    credits = calculate_total_credits(pricing_config=model, units_processed=1)
    if credits <= 0:
        raise EnhanceJobError(f"Pricing entry for {MODEL_REF} yields no credits")
    return credits


def json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


async def get_job(directus: Any, operation_id: str) -> Optional[Dict[str, Any]]:
    rows = await directus.get_items(COLLECTION, params={
        "filter[operation_id][_eq]": operation_id, "fields": JOB_FIELDS, "limit": 2,
    }, admin_required=True, no_cache=True, raise_on_error=True)
    if not isinstance(rows, list):
        raise EnhanceJobError("Enhance job lookup failed")
    if len(rows) > 1:
        raise EnhanceJobError("Enhance operation id is not unique")
    if not rows:
        return None
    row = dict(rows[0])
    row["result_file_keys"] = json_value(row.get("result_file_keys"))
    return row


async def create_job(
    directus: Any, *, operation_id: str, embed_id: str, user_id: str, scope_kind: str, scope_id: str,
    base_version: int, credits: int,
) -> tuple[Dict[str, Any], bool]:
    """Insert a pending job; return ``(row, created)``. A concurrent insert of the same id returns that row."""
    # Imported here: the tasks package imports this module through enhance_task.
    from backend.apps.images.tasks.image_revision import billing_event_id

    created_at = now_ts()
    target_version = base_version + 1
    payload = {
        "operation_id": operation_id,
        "embed_id": embed_id,
        "hashed_user_id": hash_id(user_id),
        "user_id": user_id,
        "scope_kind": scope_kind,
        "scope_id_hash": hash_id(scope_id),
        "state": STATE_PENDING,
        "base_version": base_version,
        "target_version": target_version,
        "version": 1,
        "credits": credits,
        "billing_event_id": billing_event_id(embed_id, target_version, operation_id),
        "billing_state": BILLING_NONE,
        "charged_credits": None,
        "result_file_keys": None,
        "encrypted_result": None,
        "error_code": None,
        "worker_claim": None,
        "result_delivered_at": None,
        "created_at": created_at,
        "updated_at": created_at,
        "expires_at": created_at + JOB_TTL_SECONDS,
    }
    success, item = await directus.create_item(
        COLLECTION, payload, admin_required=True, expected_unique_conflict_field="operation_id",
    )
    if success and isinstance(item, Mapping):
        return {**payload, **item}, True
    existing = await get_job(directus, operation_id)
    if existing is None:
        raise EnhanceJobError("Enhance job could not be created")
    return existing, False


async def transition(
    directus: Any, job: Mapping[str, Any], *, expected_state: str, changes: Mapping[str, Any],
) -> Dict[str, Any]:
    """Compare-and-set one job row on its version and state; raise ``EnhanceJobConflict`` when another writer won."""
    data = {**changes, "version": int(job["version"]) + 1, "updated_at": now_ts()}
    if "state" in data and data["state"] not in STATES:
        raise ValueError(f"Unknown enhance job state {data['state']}")
    updated = await directus.update_item_if_version(
        COLLECTION, str(job["id"]), data, int(job["version"]),
        extra_filters={"state": expected_state}, admin_required=True,
    )
    if not updated:
        raise EnhanceJobConflict(f"Enhance job {str(job['operation_id'])[:8]} changed while moving from {expected_state}")
    merged = {**job, **data, **{key: value for key, value in updated.items() if key in data}}
    merged["result_file_keys"] = json_value(merged.get("result_file_keys"))
    return merged


async def mark_result_delivered(directus: Any, job: Mapping[str, Any]) -> Dict[str, Any]:
    """Record the first hand-over of a ready result before the response carries it.

    Returns the row to answer from. A concurrent writer that already recorded
    the delivery or committed the result is fine; any other change re-raises
    ``EnhanceJobConflict`` so no result leaves the server unrecorded.
    """
    if job["state"] != STATE_READY or job.get("result_delivered_at") is not None:
        return dict(job)
    try:
        return await transition(directus, job, expected_state=STATE_READY, changes={"result_delivered_at": now_ts()})
    except EnhanceJobConflict:
        latest = await get_job(directus, str(job["operation_id"]))
        if latest is not None and (latest["state"] == STATE_COMMITTED or (
                latest["state"] == STATE_READY and latest.get("result_delivered_at") is not None)):
            return latest
        raise


def result_deliverable(job: Mapping[str, Any], *, now: int) -> bool:
    """A ready result is handed over only before ``expires_at`` (the commit refuses it from then on)."""
    if job["state"] == STATE_COMMITTED:
        return True
    return job["state"] == STATE_READY and int(job["expires_at"]) > now


@dataclass(frozen=True)
class SealedResult:
    """The requester-readable result payload, Vault-encrypted for the job row."""

    ciphertext: str


async def seal_result(encryption_service: Any, *, vault_key_id: str, result: Mapping[str, Any]) -> SealedResult:
    ciphertext, _ = await encryption_service.encrypt_with_user_key(
        json.dumps(result, separators=(",", ":"), sort_keys=True), vault_key_id,
    )
    if not ciphertext:
        raise EnhanceJobError("The enhance result could not be encrypted")
    return SealedResult(ciphertext=ciphertext)


async def open_result(encryption_service: Any, *, vault_key_id: str, ciphertext: str) -> Dict[str, Any]:
    plaintext = await encryption_service.decrypt_with_user_key(ciphertext, vault_key_id)
    if not plaintext:
        raise EnhanceJobError("The enhance result could not be decrypted")
    result = json.loads(plaintext)
    if not isinstance(result, dict):
        raise EnhanceJobError("The enhance result is malformed")
    return result


def public_view(job: Mapping[str, Any], *, result: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """What the requester sees of a job: state, versions, price and, once ready, the result."""
    view: Dict[str, Any] = {
        "operation_id": job["operation_id"],
        "embed_id": job["embed_id"],
        "state": job["state"],
        "base_version": job["base_version"],
        "target_version": job["target_version"],
        "credits": job["credits"],
        "charged": job.get("billing_state") == BILLING_CHARGED,
        "created_at": job["created_at"],
        "expires_at": job["expires_at"],
    }
    if job.get("error_code"):
        view["error_code"] = job["error_code"]
    if result is not None:
        view["result"] = dict(result)
    return view


def file_keys(job: Mapping[str, Any]) -> List[Dict[str, str]]:
    keys = job.get("result_file_keys") or []
    if not isinstance(keys, list):
        raise EnhanceJobError("Enhance result file index is malformed")
    return [{"bucket": str(ref["bucket"]), "key": str(ref["key"])} for ref in keys]


async def delete_result_files(s3_service: Any, job: Mapping[str, Any]) -> None:
    """Delete every uploaded result object (S3 deletes are idempotent)."""
    for ref in file_keys(job):
        await s3_service.delete_file(bucket_key=ref["bucket"], file_key=ref["key"])


async def charge(*, job: Mapping[str, Any], user_id: str, chat_id: Optional[str]) -> None:
    """Charge the quoted price once under the job's billing identity; raise ``httpx.HTTPError`` on failure."""
    from backend.apps.images.tasks.modify_billing import charge_modify_credits

    await charge_modify_credits(
        user_id=user_id, user_id_hash=hash_id(user_id), app_id=APP_ID, skill_id=SKILL_ID,
        credits=int(job["credits"]), usage_details={}, model_ref=MODEL_REF, chat_id=chat_id, message_id=None, team_id=None, api_key_hash=None,
        device_hash=None, event_id=str(job["billing_event_id"]),
    )


async def refund(*, job: Mapping[str, Any], user_id: str, reason: str, log_prefix: str) -> None:
    """Give a Personal charge back under ``app-skill:{billing_event_id}:refund`` (idempotent per job)."""
    from backend.apps.images.tasks.image_revision import refund_refused_revision

    await refund_refused_revision(
        user_id=user_id, user_id_hash=hash_id(user_id), credits=int(job["credits"]), app_id=APP_ID,
        skill_id=SKILL_ID, event_id=str(job["billing_event_id"]), team_id=None, log_prefix=log_prefix,
        reason=reason,
    )
