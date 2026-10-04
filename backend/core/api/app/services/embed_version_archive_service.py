"""Opaque artifact-version copy/read helpers; never decrypt embed content.

Copying is intentionally non-destructive. Payload removal is a separate,
rollout-gated operation after every supported reader and region is verified.
"""

from __future__ import annotations

import hashlib
import asyncio
import json
import logging
import os
import time
from typing import Any

from backend.core.api.app.services.s3.config import get_bucket_name

BUCKET_KEY = "chatfiles"
MAX_ENVELOPE_BYTES = 8 * 1024 * 1024
RECENT_VERSION_WINDOW = 32
logger = logging.getLogger(__name__)


def archive_key(embed_id: str, version_number: int, checksum: str) -> str:
    identity = hashlib.sha256(embed_id.encode("utf-8")).hexdigest()
    return f"embed-versions/{identity}/{version_number}/{checksum}.json"


def encode_ciphertext_row(row: dict[str, Any]) -> tuple[bytes, str]:
    envelope = {
        "version_number": int(row["version_number"]),
        "encrypted_snapshot": row.get("encrypted_snapshot"),
        "encrypted_patch": row.get("encrypted_patch"),
    }
    if not envelope["encrypted_snapshot"] and not envelope["encrypted_patch"]:
        raise ValueError("Version has no ciphertext to archive")
    data = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_ENVELOPE_BYTES:
        raise ValueError("Version ciphertext exceeds archive read budget")
    return data, hashlib.sha256(data).hexdigest()


async def copy_verified_version(*, s3_service: Any, row: dict[str, Any]) -> dict[str, Any]:
    """Write an immutable object to every configured region and verify SHA-256."""
    data, checksum = encode_ciphertext_row(row)
    key = archive_key(str(row["embed_id"]), int(row["version_number"]), checksum)
    regions = tuple(s3_service.region_clients)
    if not regions:
        raise RuntimeError("No object-storage region is configured")
    async with asyncio.timeout(60):
        for region in regions:
            await s3_service.upload_file(
                BUCKET_KEY, key, data, "application/json",
                metadata={"openmates-sha256": checksum}, region=region,
            )
        for region in regions:
            if not await s3_service.verify_regional_object(
                bucket_key=BUCKET_KEY, object_key=key, region=region, checksum=checksum,
            ):
                raise RuntimeError("Archived ciphertext is not verified in every region")
    return {"archive_object_key": key, "archive_checksum": checksum,
            "archive_regions": list(regions), "archive_state": "copied"}


async def read_archived_version(*, s3_service: Any, row: dict[str, Any]) -> dict[str, Any]:
    key = row.get("archive_object_key")
    checksum = row.get("archive_checksum")
    if not isinstance(key, str) or not isinstance(checksum, str):
        raise RuntimeError("Archived version is missing its verified locator")
    data = await s3_service.get_file(get_bucket_name(BUCKET_KEY, s3_service.environment), key)
    if data is None or len(data) > MAX_ENVELOPE_BYTES or hashlib.sha256(data).hexdigest() != checksum:
        raise RuntimeError("Archived version checksum mismatch or missing object")
    payload = json.loads(data)
    if payload.get("version_number") != row.get("version_number"):
        raise RuntimeError("Archived version identity mismatch")
    if not isinstance(payload.get("encrypted_snapshot"), (str, type(None))) or not isinstance(
        payload.get("encrypted_patch"), (str, type(None))
    ):
        raise RuntimeError("Archived version envelope is malformed")
    return payload


async def _require_verified_archive(*, s3_service: Any, row: dict[str, Any]) -> dict[str, Any]:
    """Recheck every configured regional replica before reader cutover or prune."""
    regions = row.get("archive_regions")
    current_regions = tuple(s3_service.region_clients)
    if (not isinstance(regions, list) or not current_regions
            or not set(current_regions).issubset(set(regions))):
        raise RuntimeError("Version archive is not verified in every configured region")
    for region in current_regions:
        if not await s3_service.verify_regional_object(
            bucket_key=BUCKET_KEY, object_key=row["archive_object_key"],
            region=region, checksum=row["archive_checksum"],
        ):
            raise RuntimeError("Version archive regional verification failed")
    return await read_archived_version(s3_service=s3_service, row=row)


async def _read_version_for_transition(
    *, directus_service: Any, embed_id: str, hashed_user_id: str, version_number: int,
) -> dict[str, Any]:
    rows = await directus_service.get_items("embed_diffs", params={
        "filter[embed_id][_eq]": embed_id,
        "filter[hashed_user_id][_eq]": hashed_user_id,
        "filter[version_number][_eq]": version_number,
        "fields": "id,embed_id,version_number,encrypted_snapshot,encrypted_patch,"
                  "archive_state,archive_object_key,archive_checksum,archive_regions,"
                  "archive_superseded_object_key,archive_reader_activated_at,archive_source_copy_until",
        "limit": 1,
    }, no_cache=True, admin_required=True)
    if not isinstance(rows, list) or len(rows) != 1:
        raise ValueError("Version metadata is unavailable")
    return rows[0]


async def _version_transition(
    *, directus_service: Any, operation: str, row: dict[str, Any],
) -> dict[str, Any]:
    token = os.getenv("INTERNAL_API_SHARED_TOKEN")
    if not token:
        raise RuntimeError("Archive transition transaction is unavailable")
    response = await directus_service._make_api_request(
        "POST", f"{directus_service.base_url.rstrip('/')}/embed-version-transaction/{operation}",
        headers={"X-Internal-Service-Token": token},
        json={
            "row_id": row["id"], "embed_id": row["embed_id"],
            "version_number": row["version_number"],
            "source_checksum": row["archive_checksum"],
        },
    )
    payload = response.json() if response.status_code == 200 else None
    result = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(result, dict) or result.get("status") not in {"reader_active", "pruned"}:
        raise RuntimeError("Version archive transition was rejected by its transaction fence")
    return result


async def activate_version_reader(
    *, directus_service: Any, s3_service: Any, embed_id: str,
    hashed_user_id: str, version_number: int,
) -> dict[str, Any]:
    """Enable the verified S3 reader; PostgreSQL payload remains for rollback."""
    if os.getenv("EMBED_VERSION_ARCHIVE_READ_ENABLED") != "1":
        raise RuntimeError("Version archive reader rollout is disabled")
    row = await _read_version_for_transition(
        directus_service=directus_service, embed_id=embed_id,
        hashed_user_id=hashed_user_id, version_number=version_number,
    )
    if row.get("archive_state") not in {"copied", "reader_active", "pruned"}:
        raise RuntimeError("Version archive has no current verified copy")
    archived = await _require_verified_archive(s3_service=s3_service, row=row)
    if row.get("archive_state") != "pruned" and any(
        row.get(field) != archived.get(field) for field in ("encrypted_snapshot", "encrypted_patch")
    ):
        raise RuntimeError("Version archive differs from PostgreSQL source")
    return await _version_transition(directus_service=directus_service, operation="archive-activate", row=row)


async def prune_version_payload(
    *, directus_service: Any, s3_service: Any, embed_id: str,
    hashed_user_id: str, version_number: int,
) -> dict[str, Any]:
    """Clear only the hot ciphertext after read, retention and recovery gates."""
    if (os.getenv("EMBED_VERSION_ARCHIVE_COPY_ENABLED") != "1"
            or os.getenv("EMBED_VERSION_ARCHIVE_READ_ENABLED") != "1"
            or os.getenv("EMBED_VERSION_ARCHIVE_PRUNE_ENABLED") != "1"):
        raise RuntimeError("Version archive pruning rollout is disabled")
    row = await _read_version_for_transition(
        directus_service=directus_service, embed_id=embed_id,
        hashed_user_id=hashed_user_id, version_number=version_number,
    )
    if row.get("archive_state") not in {"reader_active", "pruned"} or row.get("archive_superseded_object_key"):
        raise RuntimeError("Version archive is not eligible for pruning")
    archived = await _require_verified_archive(s3_service=s3_service, row=row)
    if row.get("archive_state") != "pruned":
        _, checksum = encode_ciphertext_row(row)
        if checksum != row.get("archive_checksum") or any(
            row.get(field) != archived.get(field) for field in ("encrypted_snapshot", "encrypted_patch")
        ):
            raise RuntimeError("Version archive source changed before pruning")
    elif row.get("encrypted_snapshot") or row.get("encrypted_patch"):
        raise RuntimeError("Pruned version unexpectedly retains PostgreSQL ciphertext")
    return await _version_transition(directus_service=directus_service, operation="archive-prune", row=row)


async def copy_and_index_version(
    *, directus_service: Any, s3_service: Any, embed_id: str,
    hashed_user_id: str, version_number: int, current_version: int,
    recent_window: int = RECENT_VERSION_WINDOW,
) -> dict[str, Any]:
    """Copy one sealed older version; leave PostgreSQL ciphertext authoritative.

    The window is deliberately conservative until workload measurements set it.
    A later cutover must independently recheck the row and regional copies.
    """
    if version_number < 1 or current_version - version_number < recent_window:
        raise ValueError("Version is in the current or recent PostgreSQL window")
    params = {
        "filter[embed_id][_eq]": embed_id,
        "filter[hashed_user_id][_eq]": hashed_user_id,
        "filter[version_number][_eq]": version_number,
        "fields": "id,embed_id,version_number,encrypted_snapshot,encrypted_patch,"
                  "archive_state,archive_object_key,archive_superseded_object_key,"
                  "archive_checksum,snapshot_digest,archive_regions,"
                  "archive_pending_object_key,archive_pending_checksum,archive_copy_lease_until",
        "limit": 1,
    }
    async def read_one() -> dict[str, Any]:
        rows = await directus_service.get_items(
            "embed_diffs", params=params, no_cache=True, admin_required=True,
        )
        if not isinstance(rows, list) or len(rows) != 1:
            raise ValueError("Version metadata is unavailable")
        return rows[0]

    async def clear_superseded(key: str) -> None:
        if getattr(s3_service, "directus_service", None) is None:
            raise RuntimeError("Regional deletion tombstones are unavailable")
        await s3_service.delete_file(BUCKET_KEY, key)
        updated = await directus_service.update_item(
            "embed_diffs", before["id"], {"archive_superseded_object_key": None},
        )
        if not updated:
            raise RuntimeError("Superseded archive locator cleanup was not indexed")

    async def archive_rpc(operation: str, row: dict[str, Any], *, checksum: str,
                          object_key: str, regions: list[str] | None = None) -> dict[str, Any]:
        token = os.getenv("INTERNAL_API_SHARED_TOKEN")
        if not token:
            raise RuntimeError("Archive index transaction is unavailable")
        body = {"row_id": row["id"], "embed_id": embed_id,
                "version_number": version_number, "archive_object_key": object_key}
        if operation != "archive-retire":
            body["source_checksum"] = checksum
        if regions is not None:
            body["archive_regions"] = regions
        response = await directus_service._make_api_request(
            "POST", f"{directus_service.base_url.rstrip('/')}/embed-version-transaction/{operation}",
            headers={"X-Internal-Service-Token": token}, json=body,
        )
        payload = response.json() if response.status_code == 200 else None
        result = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(result, dict):
            raise RuntimeError(f"Version archive {operation} lost its transaction fence")
        return result

    async def retire_stale_pending(row: dict[str, Any], intended_key: str) -> dict[str, Any]:
        pending = row.get("archive_pending_object_key")
        if not pending or pending == intended_key:
            return row
        lease = row.get("archive_copy_lease_until")
        if not isinstance(lease, int) or int(time.time()) < lease + 90:
            raise RuntimeError("Version archive writer lease is active or settling")
        if getattr(s3_service, "directus_service", None) is None:
            raise RuntimeError("Regional deletion tombstones are unavailable")
        await s3_service.delete_file(BUCKET_KEY, pending)
        retired = await archive_rpc("archive-retire", row, checksum="", object_key=pending)
        if retired.get("status") != "retired":
            raise RuntimeError("Stale archive intent was not retired")
        return await read_one()

    before = await read_one()
    if before.get("archive_state") == "pruned":
        regions = before.get("archive_regions")
        current_regions = tuple(s3_service.region_clients)
        if (not isinstance(regions, list) or not regions or not current_regions
                or not isinstance(before.get("archive_object_key"), str)
                or not isinstance(before.get("archive_checksum"), str)):
            raise RuntimeError("Pruned version lacks a verified archive locator")
        if set(current_regions).issubset(set(regions)):
            return {key: before.get(key) for key in (
                "archive_state", "archive_object_key", "archive_checksum",
            )}
        payload = await read_archived_version(s3_service=s3_service, row=before)
        data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if hashlib.sha256(data).hexdigest() != before["archive_checksum"]:
            raise RuntimeError("Pruned archive envelope is not canonical")
        await archive_rpc("archive-prepare", before, checksum=before["archive_checksum"],
                          object_key=before["archive_object_key"])
        async with asyncio.timeout(60):
            for region in current_regions:
                if region not in regions:
                    await s3_service.upload_file(
                        BUCKET_KEY, before["archive_object_key"], data, "application/json",
                        metadata={"openmates-sha256": before["archive_checksum"]}, region=region,
                    )
        for region in current_regions:
            if not await s3_service.verify_regional_object(
                bucket_key=BUCKET_KEY, object_key=before["archive_object_key"],
                region=region, checksum=before["archive_checksum"],
            ):
                raise RuntimeError("Pruned archive regional expansion was not verified")
        after = await read_one()
        if any(after.get(field) != before.get(field) for field in (
            "archive_state", "archive_object_key", "archive_checksum",
        )):
            raise RuntimeError("Pruned archive locator changed during regional expansion")
        indexed = await archive_rpc("archive-copy", before, checksum=before["archive_checksum"],
                                    object_key=before["archive_object_key"],
                                    regions=list(set(regions).union(current_regions)))
        if indexed.get("status") != "pruned":
            raise RuntimeError("Pruned regional expansion lost its locator fence")
        return {key: before.get(key) for key in (
            "archive_state", "archive_object_key", "archive_checksum",
        )}
    current_data, current_checksum = encode_ciphertext_row(before)
    del current_data
    intended_key = archive_key(embed_id, version_number, current_checksum)
    before = await retire_stale_pending(before, intended_key)
    verified_regions = before.get("archive_regions")
    has_all_regions = (isinstance(verified_regions, list)
                       and set(s3_service.region_clients).issubset(set(verified_regions)))
    if (before.get("archive_state") in {"copied", "reader_active"}
            and before.get("archive_checksum") == current_checksum and has_all_regions):
        if before.get("archive_superseded_object_key"):
            await clear_superseded(before["archive_superseded_object_key"])
        return {key: before.get(key) for key in (
            "archive_state", "archive_object_key", "archive_checksum",
        )}
    if before.get("archive_superseded_object_key"):
        await clear_superseded(before["archive_superseded_object_key"])
        before = await read_one()
    prepared = await archive_rpc("archive-prepare", before, checksum=current_checksum,
                                 object_key=intended_key)
    if prepared.get("status") != "preparing" or prepared.get("archive_object_key") != intended_key:
        raise RuntimeError("Version archive copy intent was not registered")
    locator = await copy_verified_version(s3_service=s3_service, row=before)
    after = await read_one()
    if any(before.get(key) != after.get(key) for key in (
        "encrypted_snapshot", "encrypted_patch", "snapshot_digest",
    )):
        raise RuntimeError("Version changed while its ciphertext was copied")
    indexed = await archive_rpc("archive-copy", before, checksum=locator["archive_checksum"],
                                object_key=locator["archive_object_key"],
                                regions=locator["archive_regions"])
    if indexed.get("status") not in {"copied", "reader_active"}:
        raise RuntimeError("Verified archive locator lost its source fence")
    if indexed.get("superseded_object_key"):
        await clear_superseded(indexed["superseded_object_key"])
    return locator


async def copy_archive_batch(
    *, directus_service: Any, s3_service: Any,
    cursor: str | None = None, limit: int = 25,
) -> dict[str, Any]:
    """Scan one stable row-id page and copy eligible older payloads only."""
    if not 1 <= limit <= 25:
        raise ValueError("Invalid version archive batch size")
    params: dict[str, Any] = {
        "fields": "id,embed_id,hashed_user_id,version_number,archive_state,"
                  "archive_regions,archive_superseded_object_key",
        "sort": "id", "limit": limit,
    }
    if cursor:
        params["filter[id][_gt]"] = cursor
    rows = await directus_service.get_items(
        "embed_diffs", params=params, no_cache=True, admin_required=True,
    )
    if not isinstance(rows, list):
        raise RuntimeError("Version archive metadata scan failed")
    copied = 0
    skipped = 0
    failed = 0
    for row in rows:
        regions = row.get("archive_regions")
        has_all_regions = (isinstance(regions, list)
                           and set(s3_service.region_clients).issubset(set(regions)))
        if ((row.get("archive_state") == "pruned" and has_all_regions)
                or (row.get("archive_state") in {"copied", "reader_active"}
                    and has_all_regions and not row.get("archive_superseded_object_key"))):
            skipped += 1
            continue
        embed = await directus_service.embed.get_embed_by_id(row["embed_id"])
        if not embed or embed.get("hashed_user_id") != row.get("hashed_user_id"):
            skipped += 1
            continue
        current_version = embed.get("version_number")
        if not isinstance(current_version, int) or current_version - row["version_number"] < RECENT_VERSION_WINDOW:
            skipped += 1
            continue
        try:
            await copy_and_index_version(
                directus_service=directus_service, s3_service=s3_service,
                embed_id=row["embed_id"], hashed_user_id=row["hashed_user_id"],
                version_number=row["version_number"], current_version=current_version,
            )
            copied += 1
        except Exception:
            failed += 1
            logger.exception("Embed version archive copy failed for row %s", row.get("id"))
    return {
        "copied": copied, "skipped": skipped, "failed": failed,
        "next_cursor": rows[-1]["id"] if len(rows) == limit else None,
    }


async def transition_archive_batch(
    *, directus_service: Any, s3_service: Any, operation: str,
    cursor: str | None = None, limit: int = 25,
) -> dict[str, Any]:
    """Advance one bounded metadata page, leaving failed rows for the next scan."""
    if operation not in {"activate", "prune"} or not 1 <= limit <= 25:
        raise ValueError("Invalid version archive transition page")
    state = "copied" if operation == "activate" else "reader_active"
    params: dict[str, Any] = {
        "filter[archive_state][_eq]": state,
        "fields": "id,embed_id,hashed_user_id,version_number,archive_source_copy_until",
        "sort": "id", "limit": limit,
    }
    if cursor:
        params["filter[id][_gt]"] = cursor
    rows = await directus_service.get_items(
        "embed_diffs", params=params, no_cache=True, admin_required=True,
    )
    if not isinstance(rows, list):
        raise RuntimeError("Version archive transition scan failed")
    advanced = skipped = failed = 0
    for row in rows:
        if operation == "prune" and (
            row.get("archive_source_copy_until") is None
            or row["archive_source_copy_until"] > int(time.time())
        ):
            skipped += 1
            continue
        embed = await directus_service.embed.get_embed_by_id(row["embed_id"])
        if (not embed or embed.get("hashed_user_id") != row.get("hashed_user_id")
                or not isinstance(embed.get("version_number"), int)
                or embed["version_number"] - row["version_number"] < RECENT_VERSION_WINDOW):
            skipped += 1
            continue
        try:
            transition = activate_version_reader if operation == "activate" else prune_version_payload
            await transition(
                directus_service=directus_service, s3_service=s3_service,
                embed_id=row["embed_id"], hashed_user_id=row["hashed_user_id"],
                version_number=row["version_number"],
            )
            advanced += 1
        except Exception:
            failed += 1
            logger.exception("Embed version archive %s failed for row %s", operation, row.get("id"))
    return {"advanced": advanced, "skipped": skipped, "failed": failed,
            "next_cursor": rows[-1]["id"] if len(rows) == limit else None}
