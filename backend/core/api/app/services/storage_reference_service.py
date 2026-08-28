"""Build an authoritative view of S3 references stored in Directus rows.

The collector is intentionally pure: callers fetch bounded rows, then use this
module to merge current embed and upload metadata. Malformed legacy references
remain explicit ambiguity and must never become deletion authority.
See contracts/architecture/storage-lifecycle/contract.yml.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
from typing import Any, AsyncIterator, Iterable
from urllib.parse import urlparse


DEFAULT_UPLOAD_BUCKET = "chatfiles"
REFERENCE_SCAN_PAGE_SIZE = 500
REFERENCE_COLLECTION_FIELDS = (
    ("embeds", "id,s3_file_keys"),
    ("upload_files", "id,files_metadata"),
    ("directus_users", "id,profile_image_s3_key,encrypted_profileimage_url,vault_key_id"),
    ("usage_monthly_chat_summaries", "id,archive_s3_key"),
    ("usage_monthly_app_summaries", "id,archive_s3_key"),
    ("usage_monthly_api_key_summaries", "id,archive_s3_key"),
    ("user_task_archives", "id,archive_s3_key"),
    ("workspace_change_archives", "id,s3_bucket_key,s3_object_key"),
    ("cold_archive_manifests", "id,file_references"),
)


@dataclass(frozen=True)
class StorageReferenceInventory:
    references: set[tuple[str, str]]
    ambiguous: list[dict[str, str]]


def collect_storage_references(
    *,
    embeds: Iterable[dict[str, Any]],
    uploads: Iterable[dict[str, Any]],
    cold_manifests: Iterable[dict[str, Any]] = (),
) -> StorageReferenceInventory:
    """Merge valid object references and retain malformed records as ambiguity."""
    references: set[tuple[str, str]] = set()
    ambiguous: list[dict[str, str]] = []

    for embed in embeds:
        record_id = str(embed.get("id") or "unknown")
        entries = embed.get("s3_file_keys")
        if not isinstance(entries, list):
            if entries is not None:
                ambiguous.append(_ambiguity("embed", record_id, "invalid_reference_list"))
            continue
        for entry in entries:
            bucket = entry.get("bucket") if isinstance(entry, dict) else None
            key = entry.get("key") if isinstance(entry, dict) else None
            if not _non_empty(bucket) or not _non_empty(key):
                ambiguous.append(_ambiguity("embed", record_id, "missing_object_key"))
                continue
            references.add((bucket, key))

    for upload in uploads:
        record_id = str(upload.get("id") or "unknown")
        metadata = upload.get("files_metadata")
        if not isinstance(metadata, dict):
            if metadata is not None:
                ambiguous.append(_ambiguity("upload", record_id, "invalid_files_metadata"))
            continue
        for variant in metadata.values():
            key = variant.get("s3_key") if isinstance(variant, dict) else None
            if not _non_empty(key):
                ambiguous.append(_ambiguity("upload", record_id, "missing_object_key"))
                continue
            references.add((DEFAULT_UPLOAD_BUCKET, key))

    for manifest in cold_manifests:
        record_id = str(manifest.get("id") or "unknown")
        entries = manifest.get("file_references")
        if not isinstance(entries, list):
            ambiguous.append(_ambiguity("cold_archive_manifest", record_id, "invalid_reference_list"))
            continue
        for entry in entries:
            bucket = entry.get("logical_bucket") if isinstance(entry, dict) else None
            key = entry.get("object_key") if isinstance(entry, dict) else None
            if not _non_empty(bucket) or not _non_empty(key):
                ambiguous.append(_ambiguity("cold_archive_manifest", record_id, "missing_object_key"))
                continue
            references.add((bucket, key))

    return StorageReferenceInventory(references=references, ambiguous=ambiguous)


async def load_authoritative_storage_reference_inventory(
    *,
    directus_service: Any,
    encryption_service: Any | None = None,
) -> StorageReferenceInventory:
    """Load all current storage references in bounded Directus pages."""
    inventory = StorageReferenceInventory(references=set(), ambiguous=[])
    async for page_inventory in iter_authoritative_storage_reference_pages(
        directus_service=directus_service,
        encryption_service=encryption_service,
    ):
        inventory.references.update(page_inventory.references)
        inventory.ambiguous.extend(page_inventory.ambiguous)
    return inventory


async def iter_authoritative_storage_reference_pages(
    *,
    directus_service: Any,
    encryption_service: Any | None = None,
) -> AsyncIterator[StorageReferenceInventory]:
    """Yield bounded authoritative reference pages for resumable reconciliation."""
    for collection, fields in REFERENCE_COLLECTION_FIELDS:
        async for page in _iter_item_pages(
            directus_service=directus_service,
            collection=collection,
            fields=fields,
        ):
            inventory = StorageReferenceInventory(references=set(), ambiguous=[])
            for row in page:
                row_inventory = _inventory_for_reference_row(collection, row)
                inventory.references.update(row_inventory.references)
                inventory.ambiguous.extend(row_inventory.ambiguous)
                if collection != "directus_users" or not row.get("encrypted_profileimage_url"):
                    continue
                record_id = str(row.get("id") or "unknown")
                vault_key_id = row.get("vault_key_id")
                if encryption_service is None or not vault_key_id:
                    inventory.ambiguous.append(
                        _ambiguity("directus_users", record_id, "legacy_profile_unreadable")
                    )
                    continue
                try:
                    value = await encryption_service.decrypt_with_user_key(
                        row["encrypted_profileimage_url"], vault_key_id
                    )
                    inventory.references.add(("profile_images_legacy", _legacy_profile_object_key(value)))
                except Exception:
                    inventory.ambiguous.append(
                        _ambiguity("directus_users", record_id, "legacy_profile_unreadable")
                    )
            yield inventory


def plan_reference_safe_deletions(
    *,
    deleting: StorageReferenceInventory,
    surviving: StorageReferenceInventory,
) -> set[tuple[str, str]]:
    """Return only unshared objects when both reference views are authoritative."""
    if deleting.ambiguous or surviving.ambiguous:
        raise ValueError("Cannot plan storage deletion with ambiguous references")
    return deleting.references - surviving.references


async def persist_reference_safe_tombstones(
    *,
    directus_service: Any,
    deleting: StorageReferenceInventory,
    surviving: StorageReferenceInventory,
    regions: tuple[str, ...],
    now: datetime,
    region_overrides: dict[str, tuple[str, ...]] | None = None,
) -> list[dict[str, Any]]:
    """Persist one generation-fenced regional tombstone per unshared object."""
    from backend.core.api.app.services.s3.reconciliation import (
        build_deletion_tombstone,
        persist_deletion_tombstone,
    )

    persisted: list[dict[str, Any]] = []
    region_overrides = region_overrides or {}
    for logical_bucket, object_key in sorted(
        plan_reference_safe_deletions(deleting=deleting, surviving=surviving)
    ):
        tombstone = build_deletion_tombstone(
            logical_bucket=logical_bucket,
            object_key=object_key,
            generations=(1,),
            generation_keys={1: object_key},
            regions=region_overrides.get(logical_bucket, regions),
            surviving_reference_count=0,
            now=now,
        )
        tombstone["state"] = "prepared"
        persisted.append(
            await persist_deletion_tombstone(
                directus_service=directus_service,
                tombstone=tombstone,
            )
        )
    return persisted


async def activate_storage_tombstones(
    *,
    directus_service: Any,
    tombstones: Iterable[dict[str, Any]],
    now: datetime,
) -> None:
    """Make prepared tombstones worker-eligible only after references are gone."""
    for tombstone in tombstones:
        if tombstone.get("state") in {"pending", "retry_scheduled", "completed"}:
            continue
        tombstone_id = tombstone.get("id")
        if not tombstone_id:
            raise RuntimeError("Prepared storage tombstone is missing its Directus id")
        updated = await directus_service.update_item(
            "storage_deletion_tombstones",
            tombstone_id,
            {
                "state": "pending",
                "version": int(tombstone.get("version", 1)) + 1,
                "next_attempt_at": now.isoformat(),
                "updated_at": now.isoformat(),
            },
            admin_required=True,
        )
        if not updated:
            raise RuntimeError("Failed to activate prepared storage tombstone")


async def find_surviving_storage_references(
    *,
    directus_service: Any,
    candidates: set[tuple[str, str]],
    excluded_ids: dict[str, set[str]],
    encryption_service: Any | None = None,
) -> StorageReferenceInventory:
    """Scan reference metadata in bounded pages and retain candidate matches only."""
    if not candidates:
        return StorageReferenceInventory(references=set(), ambiguous=[])

    surviving: set[tuple[str, str]] = set()
    ambiguous: list[dict[str, str]] = []
    for collection, fields in REFERENCE_COLLECTION_FIELDS:
        rows = await _get_items_bounded(
            directus_service=directus_service,
            collection=collection,
            fields=fields,
        )
        for row in rows:
            record_id = str(row.get("id") or "")
            if record_id in excluded_ids.get(collection, set()):
                continue
            row_inventory = _inventory_for_reference_row(collection, row)
            surviving.update(row_inventory.references & candidates)
            if (
                collection == "directus_users"
                and any(bucket == "profile_images_legacy" for bucket, _key in candidates)
                and row.get("encrypted_profileimage_url")
            ):
                vault_key_id = row.get("vault_key_id")
                if encryption_service is None or not vault_key_id:
                    ambiguous.append(
                        _ambiguity("directus_users", record_id, "legacy_profile_unreadable")
                    )
                    continue
                try:
                    legacy_url = await encryption_service.decrypt_with_user_key(
                        row["encrypted_profileimage_url"],
                        vault_key_id,
                    )
                    legacy_key = _legacy_profile_object_key(legacy_url)
                except Exception:
                    ambiguous.append(
                        _ambiguity("directus_users", record_id, "legacy_profile_unreadable")
                    )
                    continue
                reference = ("profile_images_legacy", legacy_key)
                if reference in candidates:
                    surviving.add(reference)
    return StorageReferenceInventory(references=surviving, ambiguous=ambiguous)


async def persist_account_storage_tombstones(
    *,
    directus_service: Any,
    user_id: str,
    user_id_hash: str,
    regions: tuple[str, ...],
    now: datetime,
    encryption_service: Any | None = None,
) -> list[dict[str, Any]]:
    """Inventory and tombstone non-regulated account objects before row deletion."""
    user = await directus_service.get_user_fields_direct(
        user_id,
        [
            "id",
            "profile_image_s3_key",
            "encrypted_profileimage_url",
            "vault_key_id",
        ],
    )
    embeds = await _get_items_bounded(
        directus_service=directus_service,
        collection="embeds",
        fields="id,s3_file_keys",
        item_filter={"hashed_user_id": {"_eq": user_id_hash}},
    )
    uploads = await _get_items_bounded(
        directus_service=directus_service,
        collection="upload_files",
        fields="id,files_metadata",
        item_filter={"user_id": {"_eq": user_id}},
    )
    cold_manifests = await _get_items_bounded(
        directus_service=directus_service,
        collection="cold_archive_manifests",
        fields="id,archive_id,file_references",
        item_filter={"hashed_user_id": {"_eq": user_id_hash}},
    )

    inventory = collect_storage_references(
        embeds=embeds,
        uploads=uploads,
        cold_manifests=cold_manifests,
    )
    excluded_ids = {
        "embeds": {str(row["id"]) for row in embeds if row.get("id")},
        "upload_files": {str(row["id"]) for row in uploads if row.get("id")},
        "directus_users": {user_id},
        "cold_archive_manifests": {
            str(row["id"]) for row in cold_manifests if row.get("id")
        },
    }
    archive_ids = [str(row["archive_id"]) for row in cold_manifests if row.get("archive_id")]
    cold_parts = await _get_items_bounded(
        directus_service=directus_service,
        collection="cold_archive_parts",
        fields="id,archive_id,logical_bucket,object_key",
        item_filter={"archive_id": {"_in": archive_ids}},
    ) if archive_ids else []
    excluded_ids["cold_archive_parts"] = {
        str(row["id"]) for row in cold_parts if row.get("id")
    }
    for row in cold_parts:
        _add_direct_reference(
            inventory,
            source="cold_archive_parts",
            record_id=str(row.get("id") or "unknown"),
            logical_bucket=row.get("logical_bucket"),
            object_key=row.get("object_key"),
        )
    profile_key = (user or {}).get("profile_image_s3_key")
    if _non_empty(profile_key):
        inventory.references.add(("profile_images_private", profile_key))
    encrypted_legacy_url = (user or {}).get("encrypted_profileimage_url")
    if encrypted_legacy_url:
        vault_key_id = (user or {}).get("vault_key_id")
        if encryption_service is None or not vault_key_id:
            raise ValueError("Legacy profile image requires storage reference repair")
        legacy_url = await encryption_service.decrypt_with_user_key(
            encrypted_legacy_url,
            vault_key_id,
        )
        legacy_key = _legacy_profile_object_key(legacy_url)
        inventory.references.add(("profile_images_legacy", legacy_key))

    archive_collections = (
        ("usage_monthly_chat_summaries", "usage_archives"),
        ("usage_monthly_app_summaries", "usage_archives"),
        ("usage_monthly_api_key_summaries", "usage_archives"),
        ("user_task_archives", "task_archives"),
    )
    for collection, logical_bucket in archive_collections:
        rows = await _get_items_bounded(
            directus_service=directus_service,
            collection=collection,
            fields="id,archive_s3_key",
            item_filter={"hashed_user_id": {"_eq": user_id_hash}},
        )
        excluded_ids[collection] = {
            str(row["id"]) for row in rows if row.get("id")
        }
        for row in rows:
            if row.get("archive_s3_key") is None:
                continue
            _add_direct_reference(
                inventory,
                source=collection,
                record_id=str(row.get("id") or "unknown"),
                logical_bucket=logical_bucket,
                object_key=row.get("archive_s3_key"),
            )

    workspace_archives = await _get_items_bounded(
        directus_service=directus_service,
        collection="workspace_change_archives",
        fields="id,s3_bucket_key,s3_object_key",
        item_filter={"hashed_user_id": {"_eq": user_id_hash}},
    )
    excluded_ids["workspace_change_archives"] = {
        str(row["id"]) for row in workspace_archives if row.get("id")
    }
    for row in workspace_archives:
        _add_direct_reference(
            inventory,
            source="workspace_change_archives",
            record_id=str(row.get("id") or "unknown"),
            logical_bucket=row.get("s3_bucket_key"),
            object_key=row.get("s3_object_key"),
        )

    surviving = await find_surviving_storage_references(
        directus_service=directus_service,
        candidates=inventory.references,
        excluded_ids=excluded_ids,
        encryption_service=encryption_service,
    )
    return await persist_reference_safe_tombstones(
        directus_service=directus_service,
        deleting=inventory,
        surviving=surviving,
        regions=regions,
        now=now,
        region_overrides={"profile_images_legacy": ("nbg1",)},
    )


async def fence_account_chats_for_deletion(
    *,
    directus_service: Any,
    user_id_hash: str,
) -> int:
    """Conditionally fence every account chat before storage inventory starts."""
    chats = await _get_items_bounded(
        directus_service=directus_service,
        collection="chats",
        fields="id,storage_state,archive_version",
        item_filter={"hashed_user_id": {"_eq": user_id_hash}},
    )
    if any(chat.get("storage_state") in {"archiving", "promoting"} for chat in chats):
        raise RuntimeError("Account chat storage transition is in progress; retry deletion")
    fenced = 0
    for chat in chats:
        state = str(chat.get("storage_state") or "hot")
        if state == "deleting":
            continue
        version = int(chat.get("archive_version") or 1)
        updated = await directus_service.update_item_if_version(
            "chats",
            str(chat["id"]),
            {"storage_state": "deleting", "archive_version": version + 1},
            version,
            version_field="archive_version",
            extra_filters={"storage_state": state},
            admin_required=True,
        )
        if not updated:
            raise RuntimeError("Account chat changed while deletion was being fenced")
        fenced += 1
    return fenced


async def delete_account_storage_reference_rows(
    *,
    directus_service: Any,
    user_id: str,
    user_id_hash: str,
) -> dict[str, int]:
    """Delete account-owned storage reference rows in bounded required batches."""
    specifications = (
        ("account_export_parts", {"hashed_user_id": {"_eq": user_id_hash}}),
        ("account_export_jobs", {"hashed_user_id": {"_eq": user_id_hash}}),
        ("upload_files", {"user_id": {"_eq": user_id}}),
        ("user_task_archives", {"hashed_user_id": {"_eq": user_id_hash}}),
        ("workspace_change_archives", {"hashed_user_id": {"_eq": user_id_hash}}),
        ("cold_archive_parts", {"archive_id": {"_in": await _account_archive_ids(directus_service, user_id_hash)}}),
        ("cold_archive_manifests", {"hashed_user_id": {"_eq": user_id_hash}}),
    )
    deleted: dict[str, int] = {}
    for collection, item_filter in specifications:
        deleted[collection] = 0
        async for page in _iter_item_pages(
            directus_service=directus_service,
            collection=collection,
            fields="id",
            item_filter=item_filter,
        ):
            item_ids = [str(row["id"]) for row in page if row.get("id")]
            if not item_ids:
                continue
            if not await directus_service.bulk_delete_items(collection, item_ids):
                raise RuntimeError(f"Failed to delete account {collection} rows")
            deleted[collection] += len(item_ids)
    return deleted


async def _account_archive_ids(directus_service: Any, user_id_hash: str) -> list[str]:
    rows = await _get_items_bounded(
        directus_service=directus_service,
        collection="cold_archive_manifests",
        fields="archive_id",
        item_filter={"hashed_user_id": {"_eq": user_id_hash}},
    )
    return [str(row["archive_id"]) for row in rows if row.get("archive_id")]


def _non_empty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _ambiguity(source: str, record_id: str, reason: str) -> dict[str, str]:
    return {"source": source, "record_id": record_id, "reason": reason}


def _add_direct_reference(
    inventory: StorageReferenceInventory,
    *,
    source: str,
    record_id: str,
    logical_bucket: Any,
    object_key: Any,
) -> None:
    if not _non_empty(logical_bucket) or not _non_empty(object_key):
        inventory.ambiguous.append(_ambiguity(source, record_id, "missing_object_key"))
        return
    inventory.references.add((logical_bucket, object_key))


def _inventory_for_reference_row(
    collection: str,
    row: dict[str, Any],
) -> StorageReferenceInventory:
    if collection == "embeds":
        return collect_storage_references(embeds=[row], uploads=[])
    if collection == "upload_files":
        return collect_storage_references(embeds=[], uploads=[row])
    if collection == "cold_archive_manifests":
        return collect_storage_references(embeds=[], uploads=[], cold_manifests=[row])

    inventory = StorageReferenceInventory(references=set(), ambiguous=[])
    record_id = str(row.get("id") or "unknown")
    if collection == "directus_users":
        key = row.get("profile_image_s3_key")
        if _non_empty(key):
            inventory.references.add(("profile_images_private", key))
        elif key is not None:
            inventory.ambiguous.append(
                _ambiguity(collection, record_id, "invalid_object_key")
            )
        return inventory
    if collection.startswith("usage_monthly_"):
        bucket = "usage_archives"
        key = row.get("archive_s3_key")
        if key is None:
            return inventory
    elif collection == "user_task_archives":
        bucket = "task_archives"
        key = row.get("archive_s3_key")
        if key is None:
            return inventory
    else:
        bucket = row.get("s3_bucket_key")
        key = row.get("s3_object_key")
    if _non_empty(bucket) and _non_empty(key):
        inventory.references.add((bucket, key))
    elif bucket is not None or key is not None:
        inventory.ambiguous.append(
            _ambiguity(collection, record_id, "invalid_object_reference")
        )
    return inventory


def _legacy_profile_object_key(value: Any) -> str:
    if not _non_empty(value):
        raise ValueError("Legacy profile image URL could not be decrypted")
    parsed = urlparse(value)
    environment = os.getenv("SERVER_ENVIRONMENT", "development")
    expected_bucket = (
        "dev-openmates-profile-images"
        if environment == "development"
        else "openmates-profile-images"
    )
    hostname = parsed.hostname or ""
    if hostname.split(".", 1)[0] != expected_bucket:
        raise ValueError("Legacy profile image URL has an unknown storage bucket")
    object_key = parsed.path.lstrip("/")
    if not object_key:
        raise ValueError("Legacy profile image URL is missing its object key")
    return object_key


async def _get_items_bounded(
    *,
    directus_service: Any,
    collection: str,
    fields: str,
    item_filter: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    async for page in _iter_item_pages(
        directus_service=directus_service,
        collection=collection,
        fields=fields,
        item_filter=item_filter,
    ):
        rows.extend(page)
    return rows


async def _iter_item_pages(
    *,
    directus_service: Any,
    collection: str,
    fields: str,
    item_filter: dict[str, Any] | None = None,
) -> AsyncIterator[list[dict[str, Any]]]:
    offset = 0
    while True:
        filters = dict(item_filter or {})
        params: dict[str, Any] = {
            "fields": fields,
            "sort": "id",
            "limit": REFERENCE_SCAN_PAGE_SIZE,
            "offset": offset,
        }
        if filters:
            params["filter"] = filters
        page = await directus_service.get_items(
            collection,
            params=params,
            no_cache=True,
            admin_required=True,
            raise_on_error=True,
        ) or []
        if page:
            yield page
        if len(page) < REFERENCE_SCAN_PAGE_SIZE:
            return
        offset += len(page)
