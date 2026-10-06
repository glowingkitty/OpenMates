"""Build an authoritative view of S3 references stored in Directus rows.

The collector is intentionally pure: callers fetch bounded rows, then use this
module to merge current embed and upload metadata. Malformed legacy references
remain explicit ambiguity and must never become deletion authority.
See contracts/architecture/storage-lifecycle/contract.yml.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import os
from typing import Any, AsyncIterator, Iterable
from urllib.parse import urlparse


DEFAULT_UPLOAD_BUCKET = "chatfiles"
REFERENCE_SCAN_PAGE_SIZE = 500
PREPARED_TOMBSTONE_RECHECK_DELAY = timedelta(minutes=5)
ARCHIVE_WRITER_SETTLE_GRACE_SECONDS = 90
REFERENCE_COLLECTION_FIELDS = (
    ("embeds", "id,s3_file_keys"),
    ("embed_diffs", "id,archive_object_key,archive_superseded_object_key,archive_pending_object_key,archive_state"),
    ("upload_files", "id,files_metadata"),
    ("chat_message_archive_pages", "id,object_key,large_objects"),
    ("chat_recovery_outputs", "id,payload_storage,payload_s3_key"),
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


@dataclass(frozen=True)
class AccountDeletableEmbedRows:
    """Exact pre-deletion owner snapshot; retained Team/Project refs are excluded."""

    embeds: tuple[dict[str, Any], ...]
    versions: tuple[dict[str, Any], ...]


async def _surviving_project_target_hashes(
    *, directus_service: Any, target_ids: Iterable[str], item_type: str,
    user_id_hash: str,
) -> set[str]:
    """Find targets referenced outside the account's personal Project scope."""
    hashes = sorted({hashlib.sha256(str(value).encode()).hexdigest() for value in target_ids})
    surviving: set[str] = set()
    for start in range(0, len(hashes), REFERENCE_SCAN_PAGE_SIZE):
        rows = await _get_items_bounded(
            directus_service=directus_service, collection="project_items",
            fields="id,target_id_hash,hashed_user_id,hashed_team_id,deleted_target_state",
            item_filter={"item_type": {"_eq": item_type}, "deleted_target_state": {"_null": True},
                         "target_id_hash": {"_in": hashes[start:start + REFERENCE_SCAN_PAGE_SIZE]}},
        )
        for row in rows:
            target_hash = row.get("target_id_hash")
            if target_hash not in hashes[start:start + REFERENCE_SCAN_PAGE_SIZE]:
                raise RuntimeError("Project target inventory returned an unexpected identity")
            if row.get("hashed_team_id") or row.get("hashed_user_id") != user_id_hash:
                surviving.add(target_hash)
    return surviving


async def assert_no_surviving_account_project_references(
    *, directus_service: Any, user_id: str, user_id_hash: str,
) -> None:
    """Stop account deletion before fencing if a Team/other Project retains targets."""
    chats = await _get_items_bounded(
        directus_service=directus_service, collection="chats", fields="id",
        item_filter={"hashed_user_id": {"_eq": user_id_hash}, "hashed_team_id": {"_null": True}},
    )
    uploads = await _get_items_bounded(
        directus_service=directus_service, collection="upload_files", fields="id,embed_id",
        item_filter={"user_id": {"_eq": user_id}},
    )
    for item_type, target_ids in (
        ("chat", (row["id"] for row in chats if row.get("id"))),
        ("upload", (identity for row in uploads for identity in (row.get("id"), row.get("embed_id")) if identity)),
    ):
        if await _surviving_project_target_hashes(
            directus_service=directus_service,
            target_ids=target_ids,
            item_type=item_type, user_id_hash=user_id_hash,
        ):
            raise RuntimeError("A surviving Project references account content; move or detach it before deletion")


async def load_account_deletable_embed_rows(
    *, directus_service: Any, user_id_hash: str,
) -> AccountDeletableEmbedRows:
    """Resolve account embeds against personal chats and surviving key wrappers.

    A creator hash does not imply current ownership after a Team move. Unknown
    chat hashes and shared Team/Project/plan wrappers therefore retain their
    ciphertext and version rows. The returned IDs are fixed before row deletion.
    """
    owner_chats = await _get_items_bounded(
        directus_service=directus_service, collection="chats", fields="id,hashed_team_id",
        item_filter={"hashed_user_id": {"_eq": user_id_hash}},
    )
    personal_chat_hashes = {
        hashlib.sha256(str(row["id"]).encode()).hexdigest()
        for row in owner_chats if row.get("id") and not row.get("hashed_team_id")
    }
    known_team_chat_hashes = {
        hashlib.sha256(str(row["id"]).encode()).hexdigest()
        for row in owner_chats if row.get("id") and row.get("hashed_team_id")
    }
    candidates = await _get_items_bounded(
        directus_service=directus_service, collection="embeds",
        fields="id,embed_id,hashed_embed_id,hashed_chat_id,hashed_task_id,s3_file_keys",
        item_filter={"hashed_user_id": {"_eq": user_id_hash}},
    )
    candidates_by_hash: dict[str, dict[str, Any]] = {}
    unresolved_hashes: set[str] = set()
    for row in candidates:
        embed_id = row.get("embed_id")
        if not _non_empty(embed_id) or not row.get("id"):
            continue
        expected_hash = hashlib.sha256(embed_id.encode()).hexdigest()
        if row.get("hashed_embed_id") not in (None, expected_hash):
            continue
        chat_hash = row.get("hashed_chat_id")
        if chat_hash in known_team_chat_hashes:
            continue
        if chat_hash is not None and chat_hash not in personal_chat_hashes:
            unresolved_hashes.add(expected_hash)
        if chat_hash is None and row.get("hashed_task_id") is not None:
            unresolved_hashes.add(expected_hash)
        candidates_by_hash[expected_hash] = row

    blocked_hashes: set[str] = await _surviving_project_target_hashes(
        directus_service=directus_service,
        target_ids=(row["embed_id"] for row in candidates_by_hash.values()),
        item_type="embed", user_id_hash=user_id_hash,
    )
    hashes = sorted(candidates_by_hash)
    for start in range(0, len(hashes), REFERENCE_SCAN_PAGE_SIZE):
        wrappers = await _get_items_bounded(
            directus_service=directus_service, collection="embed_keys",
            fields="id,hashed_embed_id,key_type,hashed_chat_id,hashed_project_id,hashed_plan_id,hashed_team_id,hashed_user_id",
            item_filter={"hashed_embed_id": {"_in": hashes[start:start + REFERENCE_SCAN_PAGE_SIZE]}},
        )
        for wrapper in wrappers:
            embed_hash = wrapper.get("hashed_embed_id")
            if embed_hash not in candidates_by_hash:
                raise RuntimeError("Embed key owner inventory returned an unexpected identity")
            kind = wrapper.get("key_type")
            if kind == "master":
                safe = wrapper.get("hashed_user_id") == user_id_hash
            elif kind == "chat":
                safe = wrapper.get("hashed_chat_id") in personal_chat_hashes and not any(
                    wrapper.get(field) for field in ("hashed_team_id", "hashed_project_id", "hashed_plan_id")
                )
            else:
                safe = False
            if not safe:
                blocked_hashes.add(embed_hash)

    unresolved_chat_hashes = sorted({
        row["hashed_chat_id"] for embed_hash, row in candidates_by_hash.items()
        if embed_hash in unresolved_hashes - blocked_hashes and row.get("hashed_chat_id")
    })
    if unresolved_chat_hashes:
        from backend.core.api.app.services.chat_message_archive_service import ChatMessageArchiveService

        resolver = ChatMessageArchiveService(directus_service=directus_service, s3_service=None)
        resolved: dict[str, dict[str, Any]] = {}
        for start in range(0, len(unresolved_chat_hashes), 20):
            batch = unresolved_chat_hashes[start:start + 20]
            response = await resolver.transaction("resolve_chat_hashes", {"hashes": batch})
            rows = response.get("chats")
            if not isinstance(rows, list) or any(
                not isinstance(row, dict) or row.get("hashed_chat_id") not in batch for row in rows
            ):
                raise RuntimeError("Chat owner hash resolution failed")
            resolved.update({row["hashed_chat_id"]: row for row in rows})
        for embed_hash in unresolved_hashes - blocked_hashes:
            chat_hash = candidates_by_hash[embed_hash].get("hashed_chat_id")
            if not chat_hash:
                continue
            chat = resolved.get(chat_hash)
            if chat is None:
                raise RuntimeError("Embed chat owner is unresolved; reconcile before account deletion")
            if chat.get("hashed_team_id") or chat.get("hashed_user_id") != user_id_hash:
                blocked_hashes.add(embed_hash)
            else:
                raise RuntimeError("Personal chat owner changed during account inventory; retry deletion")
    unknown = unresolved_hashes - blocked_hashes
    if unknown:
        raise RuntimeError("Embed chat or task owner is unresolved; reconcile before account deletion")

    embeds = tuple(row for embed_hash, row in candidates_by_hash.items() if embed_hash not in blocked_hashes)
    versions: list[dict[str, Any]] = []
    embed_ids = sorted({row["embed_id"] for row in embeds})
    for start in range(0, len(embed_ids), REFERENCE_SCAN_PAGE_SIZE):
        versions.extend(await _get_items_bounded(
            directus_service=directus_service, collection="embed_diffs",
            fields="id,embed_id,archive_object_key,archive_superseded_object_key,archive_pending_object_key,archive_state,archive_copy_lease_until",
            item_filter={
                "embed_id": {"_in": embed_ids[start:start + REFERENCE_SCAN_PAGE_SIZE]},
                "hashed_user_id": {"_eq": user_id_hash},
            },
        ))
    # embed_diffs has no Team-owner column. Its eligible parent IDs above are
    # the ownership authority, including for live copy leases. Check both the
    # preflight and refreshed snapshot before preparing deletion tombstones.
    _assert_no_live_embed_version_copy_leases(versions, now=datetime.now(timezone.utc))
    return AccountDeletableEmbedRows(embeds=embeds, versions=tuple(versions))


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
        tombstone["next_attempt_at"] = now + PREPARED_TOMBSTONE_RECHECK_DELAY
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
        tombstone_id = tombstone.get("id")
        if not tombstone_id:
            raise RuntimeError("Prepared storage tombstone is missing its Directus id")
        for _attempt in range(3):
            rows = await directus_service.get_items(
                "storage_deletion_tombstones",
                params={"filter": {"id": {"_eq": tombstone_id}}, "fields": "id,state,version", "limit": 1},
                no_cache=True, admin_required=True, raise_on_error=True,
            )
            if not isinstance(rows, list) or not rows:
                raise RuntimeError("Prepared storage tombstone disappeared")
            current = rows[0]
            if current.get("state") in {"pending", "retry_scheduled", "completed"}:
                break
            if current.get("state") != "prepared":
                raise RuntimeError("Storage tombstone entered an unexpected state")
            version = int(current.get("version", 1))
            updated = await directus_service.update_item_if_version(
                "storage_deletion_tombstones", tombstone_id,
                {
                    "state": "pending", "version": version + 1,
                    "next_attempt_at": now.isoformat(), "updated_at": now.isoformat(),
                },
                version, admin_required=True,
            )
            if updated:
                break
        else:
            raise RuntimeError("Failed to activate prepared storage tombstone")


async def reconcile_prepared_storage_tombstones(
    *, directus_service: Any, now: datetime, limit: int = 100,
    encryption_service: Any | None = None,
) -> dict[str, int]:
    """Resume interrupted reference deletion after proving each key has no refs."""
    if limit <= 0 or limit > 100:
        raise ValueError("Prepared tombstone sweep limit must be between 1 and 100")
    rows = await directus_service.get_items(
        "storage_deletion_tombstones",
        params={
            "filter": {
                "state": {"_eq": "prepared"},
                "_or": [
                    {"next_attempt_at": {"_null": True}},
                    {"next_attempt_at": {"_lte": "$NOW"}},
                ],
            },
            "fields": "id,logical_bucket,object_key,state,version",
            "sort": "created_at", "limit": limit,
        },
        no_cache=True, admin_required=True, raise_on_error=True,
    )
    if not isinstance(rows, list):
        raise RuntimeError("Prepared storage tombstone inventory failed")
    candidates: set[tuple[str, str]] = set()
    for row in rows:
        bucket, key = row.get("logical_bucket"), row.get("object_key")
        if not _non_empty(bucket) or not _non_empty(key) or not row.get("id"):
            raise RuntimeError("Prepared storage tombstone has invalid identity")
        candidates.add((bucket, key))
    surviving = await find_surviving_storage_references(
        directus_service=directus_service, candidates=candidates, excluded_ids={},
        encryption_service=encryption_service,
    )
    activated = 0
    deferred = 0
    for row in rows:
        reference = (row["logical_bucket"], row["object_key"])
        if not surviving.ambiguous and reference not in surviving.references:
            await activate_storage_tombstones(
                directus_service=directus_service, tombstones=[row], now=now,
            )
            activated += 1
            continue
        version = int(row["version"])
        updated = await directus_service.update_item_if_version(
            "storage_deletion_tombstones", str(row["id"]),
            {
                "next_attempt_at": (now + PREPARED_TOMBSTONE_RECHECK_DELAY).isoformat(),
                "updated_at": now.isoformat(), "version": version + 1,
            },
            version, admin_required=True,
        )
        if updated:
            deferred += 1
    return {"prepared_activated": activated, "prepared_deferred": deferred}


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
        async for page in _iter_item_pages(
            directus_service=directus_service,
            collection=collection,
            fields=fields,
        ):
            for row in page:
                record_id = str(row.get("id") or "")
                if record_id in excluded_ids.get(collection, set()):
                    continue
                row_inventory = _inventory_for_reference_row(collection, row)
                surviving.update(row_inventory.references & candidates)
                ambiguous.extend(row_inventory.ambiguous)
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
    eligible_embed_rows: AccountDeletableEmbedRows | None = None,
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
    if eligible_embed_rows is None:
        eligible_embed_rows = await load_account_deletable_embed_rows(
            directus_service=directus_service, user_id_hash=user_id_hash,
        )
    embeds = eligible_embed_rows.embeds
    uploads = await _get_items_bounded(
        directus_service=directus_service,
        collection="upload_files",
        fields="id,embed_id,files_metadata",
        item_filter={"user_id": {"_eq": user_id}},
    )
    if await _surviving_project_target_hashes(
        directus_service=directus_service,
        target_ids=(identity for row in uploads for identity in (row.get("id"), row.get("embed_id")) if identity),
        item_type="upload", user_id_hash=user_id_hash,
    ):
        raise RuntimeError("A surviving Project references account uploads; move or detach them before deletion")
    cold_manifests = await _get_items_bounded(
        directus_service=directus_service,
        collection="cold_archive_manifests",
        fields="id,archive_id,file_references",
        item_filter={"hashed_user_id": {"_eq": user_id_hash}, "hashed_team_id": {"_null": True}},
    )

    additional_rows: dict[str, list[dict[str, Any]]] = {}
    additional_rows["embed_diffs"] = list(eligible_embed_rows.versions)
    for collection, fields in (
        ("chat_message_archive_pages", "id,object_key,large_objects"),
        ("chat_recovery_outputs", "id,payload_storage,payload_s3_key"),
    ):
        additional_rows[collection] = await _get_items_bounded(
            directus_service=directus_service,
            collection=collection,
            fields=fields,
            item_filter={
                "hashed_user_id": {"_eq": user_id_hash},
                **({"root_hashed_team_id": {"_null": True}} if collection == "chat_recovery_outputs"
                   else {"hashed_team_id": {"_null": True}}),
            },
        )

    inventory = collect_storage_references(
        embeds=embeds,
        uploads=uploads,
        cold_manifests=cold_manifests,
    )
    for collection, rows in additional_rows.items():
        for row in rows:
            row_inventory = _inventory_for_reference_row(collection, row)
            inventory.references.update(row_inventory.references)
            inventory.ambiguous.extend(row_inventory.ambiguous)
    excluded_ids = {
        "embeds": {str(row["id"]) for row in embeds if row.get("id")},
        "upload_files": {str(row["id"]) for row in uploads if row.get("id")},
        "directus_users": {user_id},
        "cold_archive_manifests": {
            str(row["id"]) for row in cold_manifests if row.get("id")
        },
        **{
            collection: {str(row["id"]) for row in rows if row.get("id")}
            for collection, rows in additional_rows.items()
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
        ("usage_monthly_chat_summaries", "usage_archives", "user_id_hash"),
        ("usage_monthly_app_summaries", "usage_archives", "user_id_hash"),
        ("usage_monthly_api_key_summaries", "usage_archives", "user_id_hash"),
        ("user_task_archives", "task_archives", "hashed_user_id"),
    )
    for collection, logical_bucket, owner_field in archive_collections:
        rows = await _get_items_bounded(
            directus_service=directus_service,
            collection=collection,
            fields="id,archive_s3_key",
            item_filter={owner_field: {"_eq": user_id_hash}},
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
        item_filter={"hashed_user_id": {"_eq": user_id_hash}, "hashed_team_id": {"_null": True}},
    )
    if await _surviving_project_target_hashes(
        directus_service=directus_service,
        target_ids=(row["id"] for row in chats if row.get("id")),
        item_type="chat", user_id_hash=user_id_hash,
    ):
        raise RuntimeError("A surviving Project references account chats; move or detach them before deletion")
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
    segments = await _get_items_bounded(
        directus_service=directus_service,
        collection="chat_message_archive_segments",
        fields="id,state,lease_until",
        item_filter={"hashed_user_id": {"_eq": user_id_hash}, "hashed_team_id": {"_null": True}},
    )
    _assert_no_live_copy_leases(segments, now=datetime.now(timezone.utc))
    outputs = await _get_items_bounded(
        directus_service=directus_service, collection="chat_recovery_outputs",
        fields="id,state,writer_lease_until,payload_storage,payload_s3_key",
        item_filter={"hashed_user_id": {"_eq": user_id_hash}, "root_hashed_team_id": {"_null": True}, "state": {"_eq": "PREPARING"}},
    )
    _assert_no_live_recovery_output_copy_leases(outputs, now=datetime.now(timezone.utc))
    return fenced


async def fence_chat_for_deletion(*, directus_service: Any, chat_id: str) -> bool:
    """Prevent new archive publications before preparing a chat deletion."""
    chats = await _get_items_bounded(
        directus_service=directus_service,
        collection="chats",
        fields="id,storage_state,archive_version",
        item_filter={"id": {"_eq": chat_id}},
    )
    if not chats:
        return False
    chat = chats[0]
    state = str(chat.get("storage_state") or "hot")
    if state in {"archiving", "promoting"}:
        raise RuntimeError("Chat storage transition is in progress; retry deletion")
    if state == "deleting":
        return True
    version = int(chat.get("archive_version") or 1)
    updated = await directus_service.update_item_if_version(
        "chats", str(chat["id"]),
        {"storage_state": "deleting", "archive_version": version + 1},
        version, version_field="archive_version",
        extra_filters={"storage_state": state}, admin_required=True,
    )
    if not updated:
        raise RuntimeError("Chat changed while deletion was being fenced")
    return True


async def assert_no_active_chat_archive_writer_leases(
    *, directus_service: Any, chat_id: str, now: datetime,
) -> None:
    """Wait for already claimed copiers after the chat deletion fence is set."""
    segments = await _get_items_bounded(
        directus_service=directus_service,
        collection="chat_message_archive_segments",
        fields="id,state,lease_until",
        item_filter={"chat_id": {"_eq": chat_id}},
    )
    _assert_no_live_copy_leases(segments, now=now)


def _assert_no_live_copy_leases(segments: Iterable[dict[str, Any]], *, now: datetime) -> None:
    now_timestamp = int(now.timestamp())
    for segment in segments:
        if segment.get("state") != "copying":
            continue
        try:
            lease_until = int(segment["lease_until"])
        except (KeyError, TypeError, ValueError):
            raise RuntimeError("Chat archive writer lease is invalid; retry deletion") from None
        if lease_until + ARCHIVE_WRITER_SETTLE_GRACE_SECONDS > now_timestamp:
            raise RuntimeError("Chat archive writer lease is active or settling; retry deletion")


def _assert_no_live_embed_version_copy_leases(rows: Iterable[dict[str, Any]], *, now: datetime) -> None:
    now_timestamp = int(now.timestamp())
    for row in rows:
        pending = row.get("archive_pending_object_key")
        if row.get("archive_state") == "preparing" and not _non_empty(pending):
            raise RuntimeError("Embed version upload intent is invalid; retry deletion")
        if pending is None:
            continue
        if not _non_empty(pending):
            raise RuntimeError("Embed version upload intent is invalid; retry deletion")
        try:
            lease_until = int(row["archive_copy_lease_until"])
        except (KeyError, TypeError, ValueError):
            raise RuntimeError("Embed version writer lease is invalid; retry deletion") from None
        if lease_until + ARCHIVE_WRITER_SETTLE_GRACE_SECONDS > now_timestamp:
            raise RuntimeError("Embed version writer lease is active or settling; retry deletion")


def _assert_no_live_recovery_output_copy_leases(rows: Iterable[dict[str, Any]], *, now: datetime) -> None:
    now_timestamp = int(now.timestamp())
    for row in rows:
        if row.get("state") != "PREPARING":
            continue
        if row.get("payload_storage") != "s3" or not _non_empty(row.get("payload_s3_key")):
            raise RuntimeError("Recovery output upload intent is invalid; retry deletion")
        try:
            lease = row["writer_lease_until"]
            if isinstance(lease, datetime):
                parsed = lease
            elif isinstance(lease, str):
                parsed = datetime.fromisoformat(lease.replace("Z", "+00:00"))
            else:
                raise ValueError("invalid datetime lease")
            lease_until = int((parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).timestamp())
        except (KeyError, TypeError, ValueError):
            raise RuntimeError("Recovery output writer lease is invalid; retry deletion") from None
        if lease_until + ARCHIVE_WRITER_SETTLE_GRACE_SECONDS > now_timestamp:
            raise RuntimeError("Recovery output writer lease is active or settling; retry deletion")


async def assert_no_active_chat_recovery_output_writer_leases(
    *, directus_service: Any, chat_id: str, now: datetime,
) -> None:
    """Wait for root and target output upload intents after the chat fence."""
    rows: dict[str, dict[str, Any]] = {}
    for field in ("root_chat_id", "target_chat_id"):
        for row in await _get_items_bounded(
            directus_service=directus_service, collection="chat_recovery_outputs",
            fields="id,state,writer_lease_until,payload_storage,payload_s3_key",
            item_filter={field: {"_eq": chat_id}, "state": {"_eq": "PREPARING"}},
        ):
            rows[str(row.get("id"))] = row
    _assert_no_live_recovery_output_copy_leases(rows.values(), now=now)


async def assert_no_active_chat_embed_version_copy_leases(
    *, directus_service: Any, chat_id: str, user_id_hash: str, now: datetime,
) -> None:
    """Wait for every pending version writer linked to a chat before embed cleanup."""
    import hashlib

    hashed_chat_id = hashlib.sha256(chat_id.encode()).hexdigest()
    embeds = await _get_items_bounded(
        directus_service=directus_service, collection="embeds", fields="embed_id",
        item_filter={"hashed_chat_id": {"_eq": hashed_chat_id}},
    )
    versions: list[dict[str, Any]] = []
    for embed_id in sorted({str(row["embed_id"]) for row in embeds if row.get("embed_id")}):
        versions.extend(await _get_items_bounded(
            directus_service=directus_service, collection="embed_diffs",
            fields="id,archive_state,archive_pending_object_key,archive_copy_lease_until",
            item_filter={"hashed_user_id": {"_eq": user_id_hash}, "embed_id": {"_eq": embed_id}},
        ))
    _assert_no_live_embed_version_copy_leases(versions, now=now)


async def persist_chat_message_archive_tombstones(
    *,
    directus_service: Any,
    chat_id: str,
    regions: tuple[str, ...],
    now: datetime,
) -> list[dict[str, Any]]:
    """Prepare reference-safe purge of one chat's archived message objects.

    The caller must fence the chat against new archive publication first and
    activate these tombstones only after deleting its page/segment rows.
    """
    pages = await _get_items_bounded(
        directus_service=directus_service,
        collection="chat_message_archive_pages",
        fields="id,object_key,large_objects",
        item_filter={"chat_id": {"_eq": chat_id}},
    )
    deleting = StorageReferenceInventory(references=set(), ambiguous=[])
    for page in pages:
        row_inventory = _inventory_for_reference_row("chat_message_archive_pages", page)
        deleting.references.update(row_inventory.references)
        deleting.ambiguous.extend(row_inventory.ambiguous)
    surviving = await find_surviving_storage_references(
        directus_service=directus_service,
        candidates=deleting.references,
        excluded_ids={
            "chat_message_archive_pages": {str(row["id"]) for row in pages if row.get("id")}
        },
    )
    return await persist_reference_safe_tombstones(
        directus_service=directus_service,
        deleting=deleting,
        surviving=surviving,
        regions=regions,
        now=now,
    )


async def delete_chat_message_archive_rows(*, directus_service: Any, chat_id: str) -> dict[str, int]:
    """Remove one chat's archive metadata after purge tombstones are prepared."""
    deleted: dict[str, int] = {}
    for collection in ("chat_message_archive_pages", "chat_message_archive_segments"):
        deleted[collection] = await _delete_rows_bounded(
            directus_service=directus_service,
            collection=collection,
            item_filter={"chat_id": {"_eq": chat_id}},
        )
    return deleted


async def prepare_orphan_embed_version_deletion(
    *, directus_service: Any, deleted_embeds: Iterable[dict[str, Any]],
    deleted_embed_row_ids: Iterable[str], user_id_hash: str,
    regions: tuple[str, ...], now: datetime,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Prepare purge and row deletion for versions with no remaining embed row."""
    deleted_ids = {str(value) for value in deleted_embed_row_ids}
    embed_ids = {
        str(row["embed_id"]) for row in deleted_embeds
        if str(row.get("id")) in deleted_ids and row.get("embed_id")
    }
    version_rows: list[dict[str, Any]] = []
    for embed_id in sorted(embed_ids):
        owner_filter = {
            "embed_id": {"_eq": embed_id},
            "hashed_user_id": {"_eq": user_id_hash},
        }
        if await _get_items_bounded(
            directus_service=directus_service, collection="embeds",
            fields="id", item_filter=owner_filter,
        ):
            continue
        version_rows.extend(await _get_items_bounded(
            directus_service=directus_service, collection="embed_diffs",
            fields="id,archive_object_key,archive_superseded_object_key,archive_pending_object_key,archive_state", item_filter=owner_filter,
        ))

    deleting = StorageReferenceInventory(references=set(), ambiguous=[])
    for row in version_rows:
        inventory = _inventory_for_reference_row("embed_diffs", row)
        deleting.references.update(inventory.references)
        deleting.ambiguous.extend(inventory.ambiguous)
    version_ids = [str(row["id"]) for row in version_rows if row.get("id")]
    surviving = await find_surviving_storage_references(
        directus_service=directus_service, candidates=deleting.references,
        excluded_ids={"embed_diffs": set(version_ids)},
    )
    tombstones = await persist_reference_safe_tombstones(
        directus_service=directus_service, deleting=deleting, surviving=surviving,
        regions=regions, now=now,
    )
    return tombstones, version_ids


async def load_chat_embed_rows(*, directus_service: Any, hashed_chat_id: str) -> list[dict[str, Any]]:
    """Capture embed identity before legacy chat deletion removes its rows."""
    return await _get_items_bounded(
        directus_service=directus_service, collection="embeds",
        fields="id,embed_id", item_filter={"hashed_chat_id": {"_eq": hashed_chat_id}},
    )


async def delete_embed_version_rows(*, directus_service: Any, version_ids: Iterable[str]) -> int:
    """Delete only the version rows whose purge authority was prepared."""
    ids = list(dict.fromkeys(str(value) for value in version_ids))
    for start in range(0, len(ids), REFERENCE_SCAN_PAGE_SIZE):
        batch = ids[start:start + REFERENCE_SCAN_PAGE_SIZE]
        if not await directus_service.bulk_delete_items("embed_diffs", batch):
            raise RuntimeError("Failed to delete orphan embed version rows")
    return len(ids)


async def delete_account_storage_reference_rows(
    *,
    directus_service: Any,
    user_id: str,
    user_id_hash: str,
    eligible_embed_rows: AccountDeletableEmbedRows | None = None,
) -> dict[str, int]:
    """Delete account-owned storage reference rows in bounded required batches."""
    if eligible_embed_rows is None:
        eligible_embed_rows = await load_account_deletable_embed_rows(
            directus_service=directus_service, user_id_hash=user_id_hash,
        )
    archive_ids = await _account_archive_ids(directus_service, user_id_hash)
    specifications = (
        ("account_export_parts", {"hashed_user_id": {"_eq": user_id_hash}}),
        ("account_export_jobs", {"hashed_user_id": {"_eq": user_id_hash}}),
        ("upload_files", {"user_id": {"_eq": user_id}}),
        ("chat_recovery_outputs", {"hashed_user_id": {"_eq": user_id_hash}, "root_hashed_team_id": {"_null": True}}),
        ("chat_message_archive_pages", {"hashed_user_id": {"_eq": user_id_hash}, "hashed_team_id": {"_null": True}}),
        ("chat_message_archive_segments", {"hashed_user_id": {"_eq": user_id_hash}, "hashed_team_id": {"_null": True}}),
        ("user_task_archives", {"hashed_user_id": {"_eq": user_id_hash}}),
        ("workspace_change_archives", {"hashed_user_id": {"_eq": user_id_hash}}),
        ("cold_archive_parts", {"archive_id": {"_in": archive_ids}}),
        ("cold_archive_manifests", {"hashed_user_id": {"_eq": user_id_hash}, "hashed_team_id": {"_null": True}}),
    )
    deleted: dict[str, int] = {}
    for collection, item_filter in specifications:
        if collection == "cold_archive_parts" and not archive_ids:
            # Directus rejects empty _in filters; no owned manifests means no parts.
            deleted[collection] = 0
            continue
        deleted[collection] = await _delete_rows_bounded(
            directus_service=directus_service,
            collection=collection,
            item_filter=item_filter,
        )
    deleted["embed_diffs"] = await delete_embed_version_rows(
        directus_service=directus_service,
        version_ids=[row["id"] for row in eligible_embed_rows.versions],
    )
    return deleted


async def _delete_rows_bounded(
    *, directus_service: Any, collection: str, item_filter: dict[str, Any]
) -> int:
    """Delete from page zero repeatedly so offset pagination cannot skip rows."""
    deleted = 0
    while True:
        page = await directus_service.get_items(
            collection,
            params={
                "fields": "id", "sort": "id", "limit": REFERENCE_SCAN_PAGE_SIZE,
                "offset": 0, "filter": item_filter,
            },
            no_cache=True, admin_required=True, raise_on_error=True,
        )
        if not isinstance(page, list):
            raise RuntimeError(f"Storage reference row deletion failed for {collection}")
        if not page:
            return deleted
        item_ids = [str(row["id"]) for row in page if row.get("id")]
        if len(item_ids) != len(page):
            raise RuntimeError(f"Storage reference row is missing id in {collection}")
        if not await directus_service.bulk_delete_items(collection, item_ids):
            raise RuntimeError(f"Failed to delete {collection} rows")
        deleted += len(item_ids)


async def _account_archive_ids(directus_service: Any, user_id_hash: str) -> list[str]:
    rows = await _get_items_bounded(
        directus_service=directus_service,
        collection="cold_archive_manifests",
        fields="archive_id",
        item_filter={"hashed_user_id": {"_eq": user_id_hash}, "hashed_team_id": {"_null": True}},
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

    if collection == "chat_message_archive_pages":
        inventory = StorageReferenceInventory(references=set(), ambiguous=[])
        record_id = str(row.get("id") or "unknown")
        _add_direct_reference(
            inventory, source=collection, record_id=record_id,
            logical_bucket="cold_archives", object_key=row.get("object_key"),
        )
        large_objects = row.get("large_objects")
        if not isinstance(large_objects, list):
            inventory.ambiguous.append(_ambiguity(collection, record_id, "invalid_large_objects"))
        else:
            for entry in large_objects:
                _add_direct_reference(
                    inventory, source=collection, record_id=record_id,
                    logical_bucket="cold_archives",
                    object_key=entry.get("object_key") if isinstance(entry, dict) else None,
                )
        return inventory

    if collection in {"embed_diffs", "chat_recovery_outputs"}:
        inventory = StorageReferenceInventory(references=set(), ambiguous=[])
        record_id = str(row.get("id") or "unknown")
        if collection == "embed_diffs":
            key = row.get("archive_object_key")
            state = row.get("archive_state")
            if state not in {None, "hot", "preparing", "stale", "copied", "ready", "reader_active", "pruned"}:
                inventory.ambiguous.append(_ambiguity(collection, record_id, "unknown_archive_state"))
            required = state in {"copied", "ready", "reader_active", "pruned"}
            bucket = "chatfiles"
        else:
            key = row.get("payload_s3_key")
            storage = row.get("payload_storage")
            if storage not in {None, "inline", "s3"}:
                inventory.ambiguous.append(_ambiguity(collection, record_id, "unknown_payload_storage"))
            required = storage not in {None, "inline"}
            bucket = "cold_archives"
        if key is not None or required:
            _add_direct_reference(
                inventory, source=collection, record_id=record_id,
                logical_bucket=bucket, object_key=key,
            )
        if collection == "embed_diffs":
            pending = row.get("archive_pending_object_key")
            if state == "preparing" and pending is None:
                inventory.ambiguous.append(_ambiguity(collection, record_id, "missing_pending_object_key"))
            if pending is not None:
                _add_direct_reference(
                    inventory, source=collection, record_id=record_id,
                    logical_bucket="chatfiles", object_key=pending,
                )
            superseded = row.get("archive_superseded_object_key")
            if superseded is not None:
                _add_direct_reference(
                    inventory, source=collection, record_id=record_id,
                    logical_bucket="chatfiles", object_key=superseded,
                )
        return inventory

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
        )
        if not isinstance(page, list):
            raise RuntimeError(f"Storage reference inventory failed for {collection}")
        if page:
            yield page
        if len(page) < REFERENCE_SCAN_PAGE_SIZE:
            return
        offset += len(page)
