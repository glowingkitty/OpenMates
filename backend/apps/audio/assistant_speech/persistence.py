# backend/apps/audio/assistant_speech/persistence.py
#
# Durable metadata for assistant-response speech assets. Records contain only
# owner and source identities plus operational state: speakable plaintext stays
# in the transient worker argument and generated audio lives in chatfiles.
# This module deliberately has no provider dependency.

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.apps.audio.pricing import ASSISTANT_RESPONSE_SPEECH_MODEL

MANIFEST_COLLECTION = "assistant_speech_manifests"
SEGMENT_COLLECTION = "assistant_speech_segments"
LEASE_TTL_SECONDS = 210
MANIFEST_UPDATE_RETRIES = 5
SAFE_STATUS_FIELDS = ("segment_id", "status", "generated_asset_id", "duration_seconds", "error", "retryable", "kind")
PERSISTED_STATUS_FIELDS = SAFE_STATUS_FIELDS + ("billable_character_count",)


def manifest_id_for(*, chat_id: str, assistant_message_id: str, source_version: int, voice_key: str, voice_version: int) -> str:
    # Billing is message-scoped; source and voice revisions replace segment
    # membership inside this manifest instead of creating another usage row.
    identity = f"{chat_id}:{assistant_message_id}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


async def _items(directus: Any, collection: str, params: dict[str, object]) -> list[dict[str, object]]:
    get_items = getattr(directus, "get_items", None)
    if not callable(get_items):
        return []
    rows = await get_items(collection, params=params, no_cache=True)
    return rows if isinstance(rows, list) else []


async def create_manifest_and_segments(
    directus: Any,
    *,
    user_id: str,
    chat_id: str,
    assistant_message_id: str,
    source_version: int,
    voice_profile: Mapping[str, object],
    segments: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Create idempotent owner-scoped metadata without storing segment plaintext."""
    voice_key = str(voice_profile["key"])
    voice_version = int(voice_profile["version"])
    manifest_id = manifest_id_for(
        chat_id=chat_id,
        assistant_message_id=assistant_message_id,
        source_version=source_version,
        voice_key=voice_key,
        voice_version=voice_version,
    )
    ordered_segment_ids = [str(segment["segment_id"]) for segment in segments]
    manifest = {
        "manifest_id": manifest_id,
        "user_id": user_id,
        "chat_id": chat_id,
        "assistant_message_id": assistant_message_id,
        "source_version": source_version,
        "voice_profile_key": voice_key,
        "voice_profile_version": voice_version,
        "ordered_segment_ids": ordered_segment_ids,
        "status": "queued",
        "model": ASSISTANT_RESPONSE_SPEECH_MODEL,
        "sealed": False,
        "billing_status": "pending",
        "execution_version": 0,
    }
    existing_manifest = await _items(
        directus,
        MANIFEST_COLLECTION,
        {"filter[manifest_id][_eq]": manifest_id, "limit": 1},
    )
    if not existing_manifest:
        created, _ = await directus.create_item(MANIFEST_COLLECTION, manifest)
        if not created:
            existing_manifest = await _items(
                directus, MANIFEST_COLLECTION, {"filter[manifest_id][_eq]": manifest_id, "limit": 1},
            )
            if not existing_manifest:
                raise RuntimeError("Unable to persist assistant speech manifest")

    for _attempt in range(MANIFEST_UPDATE_RETRIES):
        current_rows = await _items(directus, MANIFEST_COLLECTION, {"filter[manifest_id][_eq]": manifest_id, "limit": 1})
        if not current_rows:
            raise RuntimeError("Assistant speech manifest disappeared during update")
        current = current_rows[0]
        current_ids = list(current.get("ordered_segment_ids") or [])
        requested_ids = {str(segment["segment_id"]) for segment in segments}
        if current.get("sealed") and requested_ids - set(current_ids):
            return {**current, "dispatch_segment_ids": []}
        merged_ids = list(current_ids)
        for segment in segments:
            segment_id = str(segment["segment_id"])
            replaced_segment_id = str(segment.get("replaces_segment_id") or "")
            if replaced_segment_id in merged_ids:
                merged_ids[merged_ids.index(replaced_segment_id)] = segment_id
            elif segment_id not in merged_ids:
                merged_ids.append(segment_id)
        if merged_ids == current_ids:
            break
        row_id = current.get("id") or current.get("manifest_id")
        if current.get("execution_version") is None or current.get("sealed") is None:
            return {**current, "dispatch_segment_ids": []}
        expected_version = int(current["execution_version"])
        update_if_version = getattr(directus, "update_item_if_version", None)
        if not callable(update_if_version):
            await directus.update_item(MANIFEST_COLLECTION, str(row_id), {"ordered_segment_ids": merged_ids})
            break
        updated = await update_if_version(
            MANIFEST_COLLECTION,
            str(row_id),
            {"ordered_segment_ids": merged_ids, "execution_version": expected_version + 1},
            expected_version,
            version_field="execution_version",
            extra_filters={"sealed": False},
        )
        if updated:
            break
    else:
        raise RuntimeError("Assistant speech manifest membership update conflicted repeatedly")

    dispatch_segment_ids: list[str] = []
    for segment in segments:
        segment_id = str(segment["segment_id"])
        existing = await _items(
            directus,
            SEGMENT_COLLECTION,
            {"filter[segment_id][_eq]": segment_id, "limit": 1},
        )
        if existing:
            if str(existing[0].get("status") or "") in {"error", "cancelled"}:
                dispatch_segment_ids.append(segment_id)
            continue
        record = {
            "segment_id": segment_id,
            "manifest_id": manifest_id,
            "user_id": user_id,
            "chat_id": chat_id,
            "assistant_message_id": assistant_message_id,
            "source_version": source_version,
            "sequence": int(segment["sequence"]),
            "kind": str(segment.get("kind") or "prose_paragraph"),
            "source_hash": str(segment["source_hash"]),
            "voice_profile_key": voice_key,
            "voice_profile_version": voice_version,
            "status": "queued",
            "execution_version": 0,
            "lease_id": None,
            "lease_expires_at": None,
        }
        created, _ = await directus.create_item(SEGMENT_COLLECTION, record)
        if not created:
            concurrent = await _items(
                directus, SEGMENT_COLLECTION, {"filter[segment_id][_eq]": segment_id, "limit": 1},
            )
            if not concurrent:
                raise RuntimeError("Unable to persist assistant speech segment")
            continue
        dispatch_segment_ids.append(segment_id)
    return {**manifest, "dispatch_segment_ids": dispatch_segment_ids}


async def seal_speech_manifest(directus: Any, manifest_id: str) -> bool:
    """Seal final segment membership before one aggregate billing attempt."""
    for _attempt in range(MANIFEST_UPDATE_RETRIES):
        rows = await _items(directus, MANIFEST_COLLECTION, {"filter[manifest_id][_eq]": manifest_id, "limit": 1})
        if not rows:
            return False
        manifest = rows[0]
        if manifest.get("sealed"):
            return True
        row_id = manifest.get("id") or manifest.get("manifest_id")
        update_if_version = getattr(directus, "update_item_if_version", None)
        if not callable(update_if_version):
            await directus.update_item(MANIFEST_COLLECTION, str(row_id), {"sealed": True})
            return True
        if manifest.get("execution_version") is None or manifest.get("sealed") is None:
            await directus.update_item(
                MANIFEST_COLLECTION,
                str(row_id),
                {"execution_version": 0, "sealed": True},
            )
            return True
        expected_version = int(manifest["execution_version"])
        sealed = await update_if_version(
            MANIFEST_COLLECTION,
            str(row_id),
            {"sealed": True, "execution_version": expected_version + 1},
            expected_version,
            version_field="execution_version",
            extra_filters={"sealed": False},
        )
        if sealed:
            return True
    raise RuntimeError("Assistant speech manifest sealing conflicted repeatedly")


async def prepare_manifest_billing(directus: Any, manifest_id: str) -> dict[str, object] | None:
    """Return plaintext-free aggregate metadata only when final work is terminal."""
    manifests = await _items(directus, MANIFEST_COLLECTION, {"filter[manifest_id][_eq]": manifest_id, "limit": 1})
    if not manifests:
        return None
    manifest = manifests[0]
    if not manifest.get("sealed") or manifest.get("billing_status") in {"committed", "not_billable"}:
        return None
    segments = await _items(directus, SEGMENT_COLLECTION, {"filter[manifest_id][_eq]": manifest_id, "limit": -1})
    expected_ids = {str(value) for value in (manifest.get("ordered_segment_ids") or [])}
    current = {str(segment.get("segment_id")): segment for segment in segments if str(segment.get("segment_id")) in expected_ids}
    if expected_ids - current.keys():
        return None
    if any(str(segment.get("status") or "") in {"queued", "generating"} for segment in current.values()):
        return None
    if any(segment.get("status") == "error" and segment.get("retryable") for segment in current.values()):
        return None
    ready = [segment for segment in current.values() if segment.get("status") == "ready"]
    if any(not isinstance(segment.get("billable_character_count"), int) or int(segment["billable_character_count"]) <= 0 for segment in ready):
        raise RuntimeError("Ready assistant speech segment is missing billable character metadata")
    return {
        "manifest_row_id": str(manifest.get("id") or manifest_id),
        "user_id": str(manifest["user_id"]),
        "chat_id": str(manifest["chat_id"]),
        "assistant_message_id": str(manifest["assistant_message_id"]),
        "model": str(manifest.get("model") or ""),
        "submitted_characters": sum(int(segment.get("billable_character_count") or 0) for segment in ready),
        "duration_seconds": sum(float(segment.get("duration_seconds") or 0) for segment in ready),
    }


async def complete_manifest_billing(directus: Any, manifest_row_id: str, *, usage_id: str | None) -> None:
    status = "committed" if usage_id else "not_billable"
    await directus.update_item(MANIFEST_COLLECTION, manifest_row_id, {"billing_status": status, "billing_usage_id": usage_id})


async def update_segment_status(directus: Any, segment_id: str, result: Mapping[str, object]) -> None:
    """Persist only safe operational metadata from a completed worker result."""
    record = {field: result[field] for field in PERSISTED_STATUS_FIELDS if field in result}
    record.pop("segment_id", None)
    if result.get("status") in {"ready", "error", "cancelled", "invalidated"}:
        record.update({"lease_id": None, "lease_expires_at": None})
    if not record:
        return
    rows = await _items(directus, SEGMENT_COLLECTION, {"filter[segment_id][_eq]": segment_id, "limit": 1})
    if not rows:
        raise RuntimeError("Assistant speech segment no longer exists")
    row_id = rows[0].get("id") or rows[0].get("segment_id")
    await directus.update_item(SEGMENT_COLLECTION, str(row_id), record)


async def finalize_speech_segment_execution(
    directus: Any,
    segment_id: str,
    result: Mapping[str, object],
    *,
    lease_id: str,
    execution_version: int,
) -> bool:
    """Publish a terminal result only from the exact worker claim that produced it."""
    record = {field: result[field] for field in PERSISTED_STATUS_FIELDS if field in result}
    record.pop("segment_id", None)
    record.update({"lease_id": None, "lease_expires_at": None})
    rows = await _items(directus, SEGMENT_COLLECTION, {"filter[segment_id][_eq]": segment_id, "limit": 1})
    if not rows:
        return False
    row_id = rows[0].get("id") or rows[0].get("segment_id")
    update_if_version = getattr(directus, "update_item_if_version", None)
    if not callable(update_if_version):
        raise RuntimeError("Assistant speech finalization requires conditional updates")
    finalized = await update_if_version(
        SEGMENT_COLLECTION,
        str(row_id),
        record,
        execution_version,
        version_field="execution_version",
        extra_filters={"status": "generating", "lease_id": lease_id},
    )
    if finalized:
        return True

    # Directus can acknowledge a filtered batch PATCH without returning the row.
    # Confirm the durable state before compensating a generated, charged asset.
    current = await get_speech_segment(directus, segment_id)
    return (
        current is not None
        and current.get("status") == result.get("status")
        and current.get("generated_asset_id") == result.get("generated_asset_id")
    )


async def get_speech_segment(directus: Any, segment_id: str) -> dict[str, object] | None:
    """Return durable state so redelivered tasks reuse a completed asset."""
    rows = await _items(directus, SEGMENT_COLLECTION, {"filter[segment_id][_eq]": segment_id, "limit": 1})
    return rows[0] if rows else None


async def invalidate_speech_segment(directus: Any, segment_id: str) -> None:
    """Make a rewritten source segment ineligible for current-message playback."""
    rows = await _items(directus, SEGMENT_COLLECTION, {"filter[segment_id][_eq]": segment_id, "limit": 1})
    if not rows:
        return
    row_id = rows[0].get("id") or rows[0].get("segment_id")
    await directus.update_item(SEGMENT_COLLECTION, str(row_id), {"status": "invalidated"})


async def tombstone_speech_assets(
    directus: Any,
    *,
    user_id: str,
    chat_id: str,
    assistant_message_id: str,
) -> bool:
    """Make assets ineligible before asynchronous cleanup can race a worker."""
    rows = await _items(
        directus,
        SEGMENT_COLLECTION,
        {
            "filter[user_id][_eq]": user_id,
            "filter[chat_id][_eq]": chat_id,
            "filter[assistant_message_id][_eq]": assistant_message_id,
            "limit": -1,
        },
    )
    changed = False
    for row in rows:
        row_id = row.get("id") or row.get("segment_id")
        if row_id and row.get("status") != "cancelled":
            await directus.update_item(SEGMENT_COLLECTION, str(row_id), {"status": "cancelled"})
            changed = True
    return changed


async def cancel_queued_speech_assets(
    directus: Any,
    *,
    user_id: str,
    chat_id: str,
    assistant_message_id: str,
) -> bool:
    """Cancel only unclaimed work; a claimed worker may settle its one execution."""
    rows = await _items(
        directus,
        SEGMENT_COLLECTION,
        {
            "filter[user_id][_eq]": user_id,
            "filter[chat_id][_eq]": chat_id,
            "filter[assistant_message_id][_eq]": assistant_message_id,
            "filter[status][_eq]": "queued",
            "limit": -1,
        },
    )
    update_if_version = getattr(directus, "update_item_if_version", None)
    changed = False
    for row in rows:
        row_id = row.get("id") or row.get("segment_id")
        if row_id and callable(update_if_version):
            cancelled = await update_if_version(
                SEGMENT_COLLECTION,
                str(row_id),
                {"status": "cancelled"},
                int(row.get("execution_version") or 0),
                version_field="execution_version",
                extra_filters={"status": "queued"},
            )
            changed = changed or bool(cancelled)
        elif row_id:
            await directus.update_item(SEGMENT_COLLECTION, str(row_id), {"status": "cancelled"})
            changed = True
    return changed


async def claim_speech_segment_execution(
    directus: Any,
    segment_id: str,
    *,
    lease_id: str,
) -> dict[str, object] | None:
    """Durably claim a queued segment before its provider request is issued."""
    segment = await get_speech_segment(directus, segment_id)
    if segment is None or str(segment.get("status") or "") in {"cancelled", "deleted", "invalidated", "ready"}:
        return None
    if str(segment.get("status") or "") == "generating" and segment.get("lease_id") != lease_id:
        lease_expires_at = _parse_timestamp(segment.get("lease_expires_at"))
        if lease_expires_at is None or lease_expires_at > datetime.now(timezone.utc):
            return None
    row_id = segment.get("id") or segment.get("segment_id")
    expected_version = int(segment.get("execution_version") or 0)
    claim = {
        "status": "generating",
        "lease_id": lease_id,
        "lease_expires_at": (datetime.now(timezone.utc) + timedelta(seconds=LEASE_TTL_SECONDS)).isoformat(),
        "execution_version": expected_version + 1,
    }
    update_if_version = getattr(directus, "update_item_if_version", None)
    if callable(update_if_version):
        claimed = await update_if_version(
            SEGMENT_COLLECTION,
            str(row_id),
            claim,
            expected_version,
            version_field="execution_version",
            extra_filters={"status": str(segment.get("status") or "queued")},
        )
        if not claimed:
            return None
        return {**segment, **claimed, **claim}
    # Minimal Directus doubles do not expose conditional updates. Production
    # services always use the versioned claim above before provider execution.
    await directus.update_item(SEGMENT_COLLECTION, str(row_id), claim)
    return {**segment, **claim}


async def delete_speech_assets(
    directus: Any,
    *,
    user_id: str,
    chat_id: str,
    assistant_message_id: str,
    delete_asset: Callable[[dict[str, object]], Awaitable[None]] | None = None,
) -> None:
    """Delete owner-scoped segment and manifest records after lifecycle removal."""
    rows = await _items(
        directus,
        SEGMENT_COLLECTION,
        {
            "filter[user_id][_eq]": user_id,
            "filter[chat_id][_eq]": chat_id,
            "filter[assistant_message_id][_eq]": assistant_message_id,
            "limit": -1,
        },
    )
    await tombstone_speech_assets(
        directus,
        user_id=user_id,
        chat_id=chat_id,
        assistant_message_id=assistant_message_id,
    )
    for row in rows:
        row_id = row.get("id") or row.get("segment_id")
        row = {**row, "status": "cancelled"}
        if delete_asset is not None:
            await delete_asset(row)
        if row_id:
            await directus.delete_item(SEGMENT_COLLECTION, str(row_id))
    manifests = await _items(
        directus,
        MANIFEST_COLLECTION,
        {
            "filter[user_id][_eq]": user_id,
            "filter[chat_id][_eq]": chat_id,
            "filter[assistant_message_id][_eq]": assistant_message_id,
            "limit": -1,
        },
    )
    for manifest in manifests:
        row_id = manifest.get("id") or manifest.get("manifest_id")
        if row_id:
            await directus.delete_item(MANIFEST_COLLECTION, str(row_id))


async def cleanup_generated_speech_asset(
    directus: Any,
    generated_asset_id: str,
    *,
    delete_file: Callable[[str], Awaitable[None]],
) -> None:
    """Remove the upload record and object created by a cancelled segment."""
    uploads = await _items(
        directus,
        "upload_files",
        {"filter[embed_id][_eq]": generated_asset_id, "fields": "id,files_metadata", "limit": -1},
    )
    for upload in uploads:
        files = upload.get("files_metadata") if isinstance(upload, dict) else None
        for metadata in files.values() if isinstance(files, dict) else []:
            if isinstance(metadata, dict) and metadata.get("s3_key"):
                await delete_file(str(metadata["s3_key"]))
        if upload.get("id"):
            await directus.delete_item("upload_files", str(upload["id"]))


def safe_segment_status(result: Mapping[str, object]) -> dict[str, object]:
    """Build a client event without plaintext, provider, or billing internals."""
    status = {field: result[field] for field in SAFE_STATUS_FIELDS if field in result}
    if "sequence" in result:
        status["sequence"] = result["sequence"]
    return status


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
