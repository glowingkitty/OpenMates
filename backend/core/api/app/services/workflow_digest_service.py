"""Private, owner-scoped metadata for the daily scheduled Workflow email."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

from backend.shared.python_utils.frontend_url import get_frontend_base_url


PAGE_SIZE = 200
MAX_EMAIL_ROWS = 10
ACTIVE_STATUSES = frozenset({"planned", "queued", "running", "waiting", "cancellation_requested"})
DELIVERY_COUNT_KEYS = ("pending", "acknowledged", "cancelled", "expired", "failed")
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
    async for batch in _pages(directus, collection, fields=fields, filters=filters, sort=sort):
        result.extend(batch)
    return result


async def _pages(directus: Any, collection: str, *, fields: str, filters: dict[str, Any], sort: str):
    """Keep database reads and in-memory aggregation bounded to one page."""
    offset = 0
    while True:
        batch = await directus.get_items(
            collection, params={"fields": fields, "filter": filters, "sort": sort,
                                "offset": offset, "limit": PAGE_SIZE},
            admin_required=True, raise_on_error=True,
        )
        if not isinstance(batch, list):
            raise RuntimeError(f"Unexpected {collection} response")
        if not batch:
            break
        yield [row for row in batch if isinstance(row, dict)]
        offset += len(batch)


def _activity_run(raw: dict[str, Any], owner: str, start: int, end: int) -> dict[str, Any] | None:
    accepted, finished = raw.get("accepted_at"), raw.get("finished_at")
    status = raw.get("status")
    if (raw.get("hashed_user_id") != owner or raw.get("trigger_type") not in ELIGIBLE_TRIGGER_TYPES
        or not _valid_id(raw.get("run_id")) or not _valid_id(raw.get("workflow_id"))
        or not isinstance(accepted, int) or accepted >= end or status == "deleted"):
        return None
    if accepted < start and not (isinstance(finished, int) and finished >= start) and status not in ACTIVE_STATUSES:
        return None
    # Never present a later completion as an outcome inside this fixed window.
    at_cutoff = "in_progress" if status in ACTIVE_STATUSES or (isinstance(finished, int) and finished >= end) else status
    at_cutoff = at_cutoff if at_cutoff in VISIBLE_STATUSES or at_cutoff == "in_progress" else "unknown"
    started = raw.get("started_at")
    started = started if isinstance(started, int) and started < end else None
    finished = finished if isinstance(finished, int) and finished < end else None
    return {"workflow_id": raw["workflow_id"], "run_id": raw["run_id"], "status": at_cutoff,
            "accepted_at": accepted, "started_at": started, "finished_at": finished,
            "activity_at": max(value for value in (accepted, started, finished) if value is not None),
            "url": _run_url(raw["workflow_id"], raw["run_id"])}


async def collect_workflow_digest(directus: Any, user_id: str, cutoff_utc: datetime) -> dict[str, Any] | None:
    """Fold exhaustive metadata pages into totals and at most ten Workflow cards.

    Database ordering makes each Workflow contiguous, so neither all runs nor all
    Workflow groups are retained. Delivery queries contain at most 100 run ids.
    No encrypted content is read during aggregation.
    """
    if not user_id:
        raise ValueError("User id required")
    start, end = digest_window(cutoff_utc)
    owner = "user_sha256:" + hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    delivery_owner = owner.removeprefix("user_sha256:")
    totals: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    cards: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    workflow_count = 0
    last_run_id: str | None = None
    now = int(datetime.now(timezone.utc).timestamp())

    def rank(card: dict[str, Any]):
        return (-int(card["attention"]), -card["activity_at"], card["workflow_id"])

    def finish_group():
        nonlocal current, workflow_count
        if current is not None:
            workflow_count += 1
            current["status_counts"] = dict(current["status_counts"])
            cards.append(current)
            cards.sort(key=rank)
            del cards[MAX_EMAIL_ROWS:]
            current = None

    async for batch in _pages(
        directus, "workflow_runs",
        fields="run_id,workflow_id,hashed_user_id,trigger_type,accepted_at,status,started_at,finished_at",
        filters={"_and": [
            {"hashed_user_id": {"_eq": owner}},
            {"trigger_type": {"_in": sorted(ELIGIBLE_TRIGGER_TYPES)}},
            {"accepted_at": {"_lt": end}}, {"status": {"_neq": "deleted"}},
            {"_or": [{"accepted_at": {"_gte": start}}, {"finished_at": {"_gte": start}},
                     {"status": {"_in": sorted(ACTIVE_STATUSES)}}]},
        ]}, sort="workflow_id,run_id",
    ):
        runs = []
        for raw in batch:
            row = _activity_run(raw, owner, start, end)
            if row is not None and row["run_id"] != last_run_id:
                runs.append(row)
                last_run_id = row["run_id"]
        by_run = {row["run_id"]: Counter() for row in runs}
        for offset in range(0, len(runs), 100):
            ids = {row["run_id"] for row in runs[offset:offset + 100]}
            previous_delivery = None
            async for deliveries in _pages(
                directus, "workflow_chat_deliveries",
                fields="delivery_id,run_id,hashed_user_id,status,expires_at,client_persisted_at,created_at",
                filters={"_and": [{"hashed_user_id": {"_eq": delivery_owner}},
                                  {"run_id": {"_in": sorted(ids)}},
                                  {"status": {"_in": sorted(DELIVERY_STATUSES)}},
                                  {"created_at": {"_lt": end}}]},
                sort="delivery_id",
            ):
                for delivery in deliveries:
                    did, rid, state = delivery.get("delivery_id"), delivery.get("run_id"), delivery.get("status")
                    if (delivery.get("hashed_user_id") != delivery_owner or rid not in ids
                        or not _valid_id(did) or did == previous_delivery or state not in DELIVERY_STATUSES
                        or not isinstance(delivery.get("created_at"), int) or delivery["created_at"] >= end):
                        continue
                    previous_delivery = did
                    if (state in {"delivery_pending", "claimed"}
                        and isinstance(delivery.get("expires_at"), int) and delivery["expires_at"] <= now
                        and not delivery.get("client_persisted_at")):
                        state = "expired"
                    by_run[rid]["pending" if state in {"delivery_pending", "claimed"} else state] += 1
        for row in runs:
            if current is None or current["workflow_id"] != row["workflow_id"]:
                finish_group()
                current = {**row, "workflow_url": f"{get_frontend_base_url()}/#workflow-id={quote(row['workflow_id'], safe='')}&workflow-tab=runs",
                           "run_count": 0, "status_counts": Counter(), "attention": False,
                           **{f"delivery_{key}_count": 0 for key in DELIVERY_COUNT_KEYS}}
            current["run_count"] += 1
            current["status_counts"][row["status"]] += 1
            # No timestamp proves historical waiting/cancellation state. Only
            # failures known inside the cutoff can truthfully drive priority.
            current["attention"] |= row["status"] == "failed"
            if (row["activity_at"], row["run_id"]) > (current["activity_at"], current["run_id"]):
                current.update(row)
            totals["run_count"] += 1
            statuses[row["status"]] += 1
            for key in DELIVERY_COUNT_KEYS:
                field = f"delivery_{key}_count"
                current[field] += by_run[row["run_id"]][key]
                totals[field] += by_run[row["run_id"]][key]
    finish_group()
    if not totals["run_count"]:
        return None
    return {"window_start": start, "window_end": end, "run_count": totals["run_count"],
            "workflow_count": workflow_count, "status_counts": dict(statuses),
            **{f"delivery_{key}_count": totals[f"delivery_{key}_count"] for key in DELIVERY_COUNT_KEYS},
            "rows": cards, "omitted_count": max(0, workflow_count - MAX_EMAIL_ROWS)}


async def load_workflow_title_previews(
    directus: Any, encryption: Any, *, user_id: str, vault_key_id: str | None,
    rows: list[dict[str, Any]],
) -> dict[str, str]:
    """Decrypt bounded owner identities after the caller checks hide-content choices.

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
    rows: list[dict[str, Any]], window_end: int | None = None,
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
        async for deliveries in _pages(
            directus, "workflow_chat_deliveries",
            fields="delivery_id,run_id,workflow_id,hashed_user_id,status,expires_at,encrypted_payload,created_at",
            filters={"_and": [
                {"hashed_user_id": {"_eq": owner_hash}},
                {"run_id": {"_in": run_ids}},
                {"status": {"_in": sorted(PREVIEWABLE_DELIVERY_STATUSES)}},
                {"expires_at": {"_gt": now}},
                *([{"created_at": {"_lt": window_end}}] if window_end is not None else []),
            ]},
            sort="run_id,created_at,delivery_id",
        ):
            for delivery in deliveries:
                run_id = delivery.get("run_id")
                if (
                    run_id not in workflow_by_run or run_id in previews
                    or delivery.get("workflow_id") != workflow_by_run[run_id]
                    or delivery.get("hashed_user_id") != owner_hash
                    or delivery.get("status") not in PREVIEWABLE_DELIVERY_STATUSES
                    or not _valid_id(delivery.get("delivery_id"))
                    or not isinstance(delivery.get("expires_at"), int) or delivery["expires_at"] <= now
                    or (window_end is not None and (not isinstance(delivery.get("created_at"), int) or delivery["created_at"] >= window_end))
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
