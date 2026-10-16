"""Private, owner-scoped metadata for the daily scheduled Workflow email."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

from backend.shared.python_utils.frontend_url import get_frontend_base_url


PAGE_SIZE = 200
MAX_EMAIL_ROWS = 50
ELIGIBLE_TRIGGER_TYPES = frozenset({"schedule"})
VISIBLE_STATUSES = frozenset({
    "planned", "queued", "running", "waiting", "cancellation_requested",
    "completed", "failed", "cancelled", "skipped_by_user",
})
DELIVERY_STATUSES = frozenset({"delivery_pending", "claimed", "acknowledged", "cancelled", "expired", "failed"})
PREVIEWABLE_DELIVERY_STATUSES = frozenset({"delivery_pending", "claimed", "acknowledged"})
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def digest_window(cutoff_utc: datetime) -> tuple[int, int]:
    """Return the immutable half-open UTC window ending at the daily 09:00 sweep."""
    if cutoff_utc.tzinfo is None or cutoff_utc.utcoffset() is None:
        raise ValueError("Digest cutoff must be timezone-aware")
    end = cutoff_utc.astimezone(timezone.utc)
    if (end.hour, end.minute, end.second, end.microsecond) != (9, 0, 0, 0):
        raise ValueError("Digest cutoff must be 09:00 UTC")
    return int((end - timedelta(days=1)).timestamp()), int(end.timestamp())


def _valid_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_SAFE_ID.fullmatch(value))


def _run_url(workflow_id: str, run_id: str) -> str:
    return (
        f"{get_frontend_base_url()}/#workflow-id={quote(workflow_id, safe='')}"
        f"&workflow-tab=runs&run-id={quote(run_id, safe='')}"
    )


async def _rows(directus: Any, collection: str, *, fields: str, filters: dict[str, Any], sort: str) -> list[dict[str, Any]]:
    """Read every page; Directus may cap a single request below the result size."""
    result: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = await directus.get_items(
            collection,
            params={"fields": fields, "filter": filters, "sort": sort, "page": page, "limit": PAGE_SIZE},
            admin_required=True,
            raise_on_error=True,
        )
        if not isinstance(batch, list):
            raise RuntimeError(f"Unexpected {collection} response")
        result.extend(row for row in batch if isinstance(row, dict))
        if len(batch) < PAGE_SIZE:
            return result
        page += 1


async def collect_workflow_digest(directus: Any, user_id: str, cutoff_utc: datetime) -> dict[str, Any] | None:
    """Return status and delivery counts without reading encrypted run content."""
    if not user_id:
        raise ValueError("User id required")
    window_start, window_end = digest_window(cutoff_utc)
    owner_hash = "user_sha256:" + hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    raw_runs = await _rows(
        directus,
        "workflow_runs",
        fields="run_id,workflow_id,hashed_user_id,trigger_type,accepted_at,status,started_at,finished_at",
        filters={"_and": [
            {"hashed_user_id": {"_eq": owner_hash}},
            {"trigger_type": {"_in": sorted(ELIGIBLE_TRIGGER_TYPES)}},
            {"accepted_at": {"_gte": window_start, "_lt": window_end}},
            {"status": {"_neq": "deleted"}},
        ]},
        sort="accepted_at,run_id",
    )
    runs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_runs:
        run_id, workflow_id = raw.get("run_id"), raw.get("workflow_id")
        accepted_at = raw.get("accepted_at")
        if (
            raw.get("hashed_user_id") != owner_hash
            or raw.get("trigger_type") not in ELIGIBLE_TRIGGER_TYPES
            or not _valid_id(run_id) or not _valid_id(workflow_id)
            or not isinstance(accepted_at, int) or not window_start <= accepted_at < window_end
            or raw.get("status") == "deleted" or run_id in seen
        ):
            continue
        seen.add(run_id)
        status = raw.get("status") if raw.get("status") in VISIBLE_STATUSES else "unknown"
        runs.append({
            "run_id": run_id,
            "workflow_id": workflow_id,
            "status": status,
            "accepted_at": accepted_at,
            "started_at": raw.get("started_at") if isinstance(raw.get("started_at"), int) else None,
            "finished_at": raw.get("finished_at") if isinstance(raw.get("finished_at"), int) else None,
            "url": _run_url(workflow_id, run_id),
        })
    if not runs:
        return None

    runs.sort(key=lambda row: (row["accepted_at"], row["run_id"]))
    delivery_by_run: dict[str, Counter[str]] = defaultdict(Counter)
    now = int(datetime.now(timezone.utc).timestamp())
    run_ids = [row["run_id"] for row in runs]
    # The delivery owner hash is intentionally stored without the run-table prefix.
    delivery_owner_hash = owner_hash.removeprefix("user_sha256:")
    for offset in range(0, len(run_ids), 100):
        deliveries = await _rows(
            directus,
            "workflow_chat_deliveries",
            fields="delivery_id,run_id,hashed_user_id,status,expires_at,client_persisted_at",
            filters={"_and": [
                {"hashed_user_id": {"_eq": delivery_owner_hash}},
                {"run_id": {"_in": run_ids[offset:offset + 100]}},
                {"status": {"_in": sorted(DELIVERY_STATUSES)}},
            ]},
            sort="run_id,delivery_id",
        )
        seen_deliveries: set[str] = set()
        for delivery in deliveries:
            delivery_id, run_id, status = delivery.get("delivery_id"), delivery.get("run_id"), delivery.get("status")
            if (
                delivery.get("hashed_user_id") == delivery_owner_hash
                and _valid_id(delivery_id) and delivery_id not in seen_deliveries
                and run_id in run_ids[offset:offset + 100] and status in DELIVERY_STATUSES
            ):
                seen_deliveries.add(delivery_id)
                effective_status = status
                if (
                    status in ("delivery_pending", "claimed")
                    and isinstance(delivery.get("expires_at"), int)
                    and delivery["expires_at"] <= now
                    and not delivery.get("client_persisted_at")
                ):
                    # A stale unpersisted lease is effectively expired even
                    # before a producer writes its terminal cleanup status.
                    effective_status = "expired"
                delivery_by_run[run_id][effective_status] += 1

    for run in runs:
        counts = delivery_by_run[run["run_id"]]
        run["delivery_pending_count"] = counts["delivery_pending"] + counts["claimed"]
        run["delivery_acknowledged_count"] = counts["acknowledged"]
        run["delivery_cancelled_count"] = counts["cancelled"]
        run["delivery_expired_count"] = counts["expired"]
        run["delivery_failed_count"] = counts["failed"]
    status_counts = Counter(row["status"] for row in runs)
    return {
        "window_start": window_start,
        "window_end": window_end,
        "run_count": len(runs),
        "status_counts": dict(status_counts),
        "delivery_pending_count": sum(row["delivery_pending_count"] for row in runs),
        "delivery_acknowledged_count": sum(row["delivery_acknowledged_count"] for row in runs),
        "delivery_cancelled_count": sum(row["delivery_cancelled_count"] for row in runs),
        "delivery_expired_count": sum(row["delivery_expired_count"] for row in runs),
        "delivery_failed_count": sum(row["delivery_failed_count"] for row in runs),
        "rows": runs[:MAX_EMAIL_ROWS],
        "omitted_count": max(0, len(runs) - MAX_EMAIL_ROWS),
    }


async def load_workflow_title_previews(
    directus: Any, encryption: Any, *, user_id: str, vault_key_id: str | None,
    rows: list[dict[str, Any]],
) -> dict[str, str]:
    """Decrypt bounded owner titles only after explicit email-content opt-in.

    Run output_summary is an execution context with inputs and node internals,
    not a safe short preview field, so it is deliberately never emailed.
    """
    if not vault_key_id or not rows:
        return {}
    owner_hash = "user_sha256:" + hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    workflow_ids = sorted({row["workflow_id"] for row in rows if _valid_id(row.get("workflow_id"))})
    if not workflow_ids:
        return {}
    workflows = await _rows(
        directus, "workflows", fields="workflow_id,hashed_user_id,record_json",
        filters={"_and": [
            {"hashed_user_id": {"_eq": owner_hash}},
            {"workflow_id": {"_in": workflow_ids}},
            {"status": {"_neq": "deleted"}},
        ]}, sort="workflow_id",
    )
    refs: dict[str, str] = {}
    for workflow in workflows:
        record = workflow.get("record_json")
        ref = record.get("encrypted_title_ref") if isinstance(record, dict) else None
        if workflow.get("hashed_user_id") == owner_hash and workflow.get("workflow_id") in workflow_ids and isinstance(ref, str):
            refs[ref] = workflow["workflow_id"]
    if not refs:
        return {}
    blobs = await _rows(
        directus, "workflow_encrypted_blobs",
        fields="ref,hashed_user_id,kind,ciphertext,checksum,vault_key_ref,expires_at",
        filters={"_and": [
            {"hashed_user_id": {"_eq": owner_hash}},
            {"ref": {"_in": sorted(refs)}},
            {"kind": {"_eq": "workflow_title"}},
        ]}, sort="ref",
    )
    titles: dict[str, str] = {}
    for blob in blobs:
        ref = blob.get("ref")
        if blob.get("hashed_user_id") != owner_hash or blob.get("kind") != "workflow_title" or ref not in refs:
            continue
        if not isinstance(blob.get("ciphertext"), str):
            continue
        if isinstance(blob.get("expires_at"), int) and blob["expires_at"] <= int(datetime.now(timezone.utc).timestamp()):
            continue
        try:
            plaintext = await encryption.decrypt_with_user_key(blob["ciphertext"], blob.get("vault_key_ref") or vault_key_id)
            if not isinstance(plaintext, str):
                continue
            if blob.get("checksum") != "sha256:" + hashlib.sha256(plaintext.encode("utf-8")).hexdigest():
                continue
            title = json.loads(plaintext)
            if isinstance(title, str) and title.strip():
                titles[refs[ref]] = " ".join(title.split())[:80]
        except Exception:
            # One unavailable/rotated title must not block the private digest.
            continue
    return titles


async def load_workflow_message_previews(
    directus: Any, encryption: Any, *, user_id: str, vault_key_id: str | None,
    rows: list[dict[str, Any]],
) -> dict[str, str]:
    """Read one intended Send message per run after explicit content opt-in.

    Delivery payloads are already the user-facing result selected by the Send
    message action. Run output summaries and selected embeds are never read.
    """
    if not vault_key_id or not rows:
        return {}
    owner_hash = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    workflow_by_run = {
        row["run_id"]: row["workflow_id"] for row in rows
        if _valid_id(row.get("run_id")) and _valid_id(row.get("workflow_id"))
    }
    if not workflow_by_run:
        return {}
    now = int(datetime.now(timezone.utc).timestamp())
    previews: dict[str, str] = {}
    for offset in range(0, len(workflow_by_run), 100):
        run_ids = sorted(workflow_by_run)[offset:offset + 100]
        deliveries = await _rows(
            directus, "workflow_chat_deliveries",
            fields="delivery_id,run_id,workflow_id,hashed_user_id,status,expires_at,encrypted_payload,created_at",
            filters={"_and": [
                {"hashed_user_id": {"_eq": owner_hash}},
                {"run_id": {"_in": run_ids}},
                {"status": {"_in": sorted(PREVIEWABLE_DELIVERY_STATUSES)}},
                {"expires_at": {"_gt": now}},
            ]},
            sort="run_id,created_at,delivery_id",
        )
        for delivery in deliveries:
            run_id = delivery.get("run_id")
            if (
                run_id not in workflow_by_run or run_id in previews
                or delivery.get("workflow_id") != workflow_by_run[run_id]
                or delivery.get("hashed_user_id") != owner_hash
                or delivery.get("status") not in PREVIEWABLE_DELIVERY_STATUSES
                or not _valid_id(delivery.get("delivery_id"))
                or not isinstance(delivery.get("expires_at"), int) or delivery["expires_at"] <= now
            ):
                continue
            try:
                envelope = json.loads(delivery.get("encrypted_payload") or "")
                if not isinstance(envelope, dict) or envelope.get("vault_key_id") != vault_key_id:
                    continue
                ciphertext = envelope.get("ciphertext")
                if not isinstance(ciphertext, str) or not ciphertext:
                    continue
                plaintext = await encryption.decrypt_with_user_key(ciphertext, vault_key_id)
                payload = json.loads(plaintext) if isinstance(plaintext, str) else None
                message = payload.get("message") if isinstance(payload, dict) else None
                if not isinstance(message, str) or not message.strip():
                    continue
                excerpt = "\n".join(message.strip().splitlines()[:10])[:2000]
                if excerpt:
                    previews[run_id] = excerpt
            except Exception:
                # Missing/rotated/cleared Vault content leaves a private row.
                continue
    return previews
