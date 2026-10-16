# Storage reference reconciliation contract tests.
# The inventory merges current embed and upload metadata without S3 access.
# Malformed legacy records remain visible as ambiguity instead of disappearing.
# Physical deletion must consume this authoritative reference view.
# See contracts/architecture/storage-lifecycle/contract.yml.

from __future__ import annotations

import importlib
from datetime import datetime, timezone

import pytest

from scripts.audit_object_storage_inventory import classify_inventory


def _reference_module():
    try:
        return importlib.import_module("backend.core.api.app.services.storage_reference_service")
    except ModuleNotFoundError as exc:
        pytest.fail(f"Storage reference reconciliation is not implemented: {exc}")


# contract-test: direct surface=rest_api assertions=storage.files.reference-safe-single-copy,storage.integrity.observable-reconcilable
def test_embed_and_upload_metadata_merge_into_one_reference_view() -> None:
    module = _reference_module()
    embeds = [
        {
            "id": "embed-row-1",
            "s3_file_keys": [
                {"bucket": "chatfiles", "key": "owner-a/hash-a/original.bin"},
            ],
        }
    ]
    uploads = [
        {
            "id": "upload-row-1",
            "files_metadata": {
                "original": {"s3_key": "owner-a/hash-a/original.bin"},
                "preview": {"s3_key": "owner-a/hash-a/preview.bin"},
            },
        }
    ]

    inventory = module.collect_storage_references(embeds=embeds, uploads=uploads)

    assert inventory.references == {
        ("chatfiles", "owner-a/hash-a/original.bin"),
        ("chatfiles", "owner-a/hash-a/preview.bin"),
    }
    assert inventory.ambiguous == []


# contract-test: direct surface=rest_api assertions=storage.files.reference-safe-single-copy,storage.integrity.observable-reconcilable
def test_malformed_legacy_reference_is_reported_without_destructive_inference() -> None:
    module = _reference_module()
    embeds = [{"id": "legacy-embed", "s3_file_keys": [{"bucket": "chatfiles"}]}]
    uploads = [{"id": "legacy-upload", "files_metadata": {"original": {}}}]

    inventory = module.collect_storage_references(embeds=embeds, uploads=uploads)

    assert inventory.references == set()
    assert inventory.ambiguous == [
        {"source": "embed", "record_id": "legacy-embed", "reason": "missing_object_key"},
        {"source": "upload", "record_id": "legacy-upload", "reason": "missing_object_key"},
    ]


# contract-test: direct surface=rest_api assertions=storage.files.reference-safe-single-copy
def test_cold_manifest_file_references_remain_authoritative() -> None:
    module = _reference_module()
    inventory = module.collect_storage_references(
        embeds=[],
        uploads=[],
        cold_manifests=[
            {
                "id": "archive-1",
                "file_references": [
                    {"logical_bucket": "chatfiles", "object_key": "files/shared.enc"}
                ],
            }
        ],
    )

    assert inventory.references == {("chatfiles", "files/shared.enc")}


# contract-test: direct surface=rest_api assertions=storage.files.reference-safe-single-copy,storage.integrity.observable-reconcilable
def test_unarchived_usage_rows_are_not_malformed_storage_references() -> None:
    module = _reference_module()

    unarchived = module._inventory_for_reference_row(
        "usage_monthly_chat_summaries",
        {"id": "usage-hot", "archive_s3_key": None},
    )
    malformed = module._inventory_for_reference_row(
        "usage_monthly_chat_summaries",
        {"id": "usage-malformed", "archive_s3_key": ""},
    )

    assert unarchived.references == set()
    assert unarchived.ambiguous == []
    assert malformed.ambiguous == [{
        "source": "usage_monthly_chat_summaries",
        "record_id": "usage-malformed",
        "reason": "invalid_object_reference",
    }]


# contract-test: direct surface=rest_api assertions=storage.files.reference-safe-single-copy,storage.deletion.global-authoritative
def test_new_archive_and_recovery_rows_are_authoritative_references() -> None:
    module = _reference_module()
    rows = (
        ("chat_message_archive_pages", {"id": "page-1", "object_key": "pages/one.gz", "large_objects": [
            {"object_key": "pages/large.json"}
        ]}),
        ("embed_diffs", {"id": "diff-1", "archive_state": "copied", "archive_object_key": "versions/one.json"}),
        ("chat_recovery_outputs", {"id": "recovery-1", "payload_storage": "s3", "payload_s3_key": "recovery/one.json"}),
    )
    merged = set()
    for collection, row in rows:
        inventory = module._inventory_for_reference_row(collection, row)
        assert inventory.ambiguous == []
        merged.update(inventory.references)
    assert merged == {
        ("cold_archives", "pages/one.gz"),
        ("cold_archives", "pages/large.json"),
        ("chatfiles", "versions/one.json"),
        ("cold_archives", "recovery/one.json"),
    }


# contract-test: direct surface=rest_api assertions=storage.files.reference-safe-single-copy,storage.deletion.global-authoritative
def test_superseded_embed_version_locator_remains_authoritative_until_cleared() -> None:
    module = _reference_module()
    inventory = module._inventory_for_reference_row("embed_diffs", {
        "id": "diff-1", "archive_state": "copied",
        "archive_object_key": "versions/new.json",
        "archive_superseded_object_key": "versions/old.json",
    })
    assert inventory.references == {
        ("chatfiles", "versions/new.json"), ("chatfiles", "versions/old.json"),
    }
    assert inventory.ambiguous == []

    incomplete = module._inventory_for_reference_row("embed_diffs", {
        "id": "diff-2", "archive_state": "hot", "archive_object_key": None,
        "archive_superseded_object_key": "",
    })
    assert incomplete.ambiguous == [{
        "source": "embed_diffs", "record_id": "diff-2", "reason": "missing_object_key",
    }]


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative,storage.integrity.observable-reconcilable
def test_pending_version_and_recovery_upload_intents_remain_authoritative() -> None:
    module = _reference_module()
    version = module._inventory_for_reference_row("embed_diffs", {
        "id": "diff-pending", "archive_state": "preparing",
        "archive_object_key": "versions/verified.json",
        "archive_pending_object_key": "versions/uploading.json",
        "archive_superseded_object_key": "versions/old.json",
    })
    assert version.ambiguous == []
    assert version.references == {
        ("chatfiles", "versions/verified.json"),
        ("chatfiles", "versions/uploading.json"),
        ("chatfiles", "versions/old.json"),
    }
    first_copy = module._inventory_for_reference_row("embed_diffs", {
        "id": "diff-first", "archive_state": "preparing",
        "archive_object_key": None, "archive_pending_object_key": "versions/first.json",
    })
    assert first_copy.ambiguous == []
    assert first_copy.references == {("chatfiles", "versions/first.json")}
    recovery = module._inventory_for_reference_row("chat_recovery_outputs", {
        "id": "output-preparing", "state": "PREPARING", "payload_storage": "s3",
        "payload_s3_key": "chat-recovery/uploading.json",
    })
    assert recovery.ambiguous == []
    assert recovery.references == {("cold_archives", "chat-recovery/uploading.json")}


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative,storage.integrity.observable-reconcilable
def test_pending_writer_leases_block_reference_removal_until_settled() -> None:
    module = _reference_module()
    now = datetime(2026, 10, 3, tzinfo=timezone.utc)
    stamp = int(now.timestamp())
    with pytest.raises(RuntimeError, match="Embed version writer lease is active"):
        module._assert_no_live_embed_version_copy_leases([{
            "archive_state": "stale", "archive_pending_object_key": "versions/pending.json",
            "archive_copy_lease_until": stamp - 89,
        }], now=now)
    module._assert_no_live_embed_version_copy_leases([{
        "archive_state": "preparing", "archive_pending_object_key": "versions/pending.json",
        "archive_copy_lease_until": stamp - 90,
    }], now=now)
    with pytest.raises(RuntimeError, match="upload intent is invalid"):
        module._assert_no_live_embed_version_copy_leases([{
            "archive_state": "preparing", "archive_pending_object_key": None,
        }], now=now)
    with pytest.raises(RuntimeError, match="Recovery output writer lease is active"):
        module._assert_no_live_recovery_output_copy_leases([{
            "state": "PREPARING", "payload_storage": "s3", "payload_s3_key": "recovery/pending.json",
            "writer_lease_until": datetime.fromtimestamp(stamp - 89, timezone.utc).isoformat(),
        }], now=now)
    module._assert_no_live_recovery_output_copy_leases([{
        "state": "PREPARING", "payload_storage": "s3", "payload_s3_key": "recovery/pending.json",
        "writer_lease_until": datetime.fromtimestamp(stamp - 90, timezone.utc).isoformat(),
    }], now=now)


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative,storage.integrity.observable-reconcilable
def test_missing_archive_object_locator_blocks_deletion() -> None:
    module = _reference_module()
    for collection, row in (
        ("chat_message_archive_pages", {"id": "page-1", "object_key": "pages/one.gz", "large_objects": None}),
        ("embed_diffs", {"id": "diff-1", "archive_state": "copied", "archive_object_key": None}),
        ("chat_recovery_outputs", {"id": "recovery-1", "payload_storage": "s3", "payload_s3_key": None}),
    ):
        inventory = module._inventory_for_reference_row(collection, row)
        assert inventory.ambiguous
        with pytest.raises(ValueError, match="ambiguous"):
            module.plan_reference_safe_deletions(
                deleting=inventory,
                surviving=module.StorageReferenceInventory(references=set(), ambiguous=[]),
            )


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative
@pytest.mark.anyio
async def test_inventory_raises_when_directus_returns_no_page_on_schema_error() -> None:
    module = _reference_module()

    class FakeDirectus:
        async def get_items(self, collection: str, **_kwargs: object):
            return None if collection == "chat_message_archive_pages" else []

    with pytest.raises(RuntimeError, match="chat_message_archive_pages"):
        await module.load_authoritative_storage_reference_inventory(directus_service=FakeDirectus())


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative
@pytest.mark.anyio
async def test_malformed_surviving_archive_reference_blocks_purge() -> None:
    module = _reference_module()

    class FakeDirectus:
        async def get_items(self, collection: str, **_kwargs: object):
            if collection == "chat_message_archive_pages":
                return [{"id": "other-page", "object_key": "pages/other.gz", "large_objects": None}]
            return []

    surviving = await module.find_surviving_storage_references(
        directus_service=FakeDirectus(), candidates={("cold_archives", "pages/target.gz")},
        excluded_ids={},
    )
    assert surviving.ambiguous == [{
        "source": "chat_message_archive_pages", "record_id": "other-page", "reason": "invalid_large_objects",
    }]
    with pytest.raises(ValueError, match="ambiguous"):
        module.plan_reference_safe_deletions(
            deleting=module.StorageReferenceInventory(references={("cold_archives", "pages/target.gz")}, ambiguous=[]),
            surviving=surviving,
        )


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative,storage.files.reference-safe-single-copy
@pytest.mark.anyio
async def test_chat_archive_deletion_prepares_all_region_tombstones_before_row_removal(monkeypatch) -> None:
    module = _reference_module()
    monkeypatch.setattr(module, "REFERENCE_SCAN_PAGE_SIZE", 2)

    class FakeDirectus:
        def __init__(self):
            self.rows = {
                "chat_message_archive_pages": [
                    {"id": "page-1", "object_key": "pages/one.gz", "large_objects": [{"object_key": "pages/large.json"}]},
                    {"id": "page-2", "object_key": "pages/two.gz", "large_objects": []},
                    {"id": "page-3", "object_key": "pages/three.gz", "large_objects": []},
                ],
                "chat_message_archive_segments": [{"id": "segment-1"}],
            }
            self.created = []

        async def get_items(self, collection: str, **kwargs):
            rows = self.rows.get(collection, [])
            params = kwargs["params"]
            if collection == "chat_message_archive_pages" and params.get("filter", {}).get("chat_id") == {"_eq": "other"}:
                return []
            offset = int(params.get("offset", 0))
            return rows[offset:offset + params["limit"]]

        async def create_item(self, collection: str, payload: dict, **_kwargs):
            assert collection == "storage_deletion_tombstones"
            self.created.append(payload)
            return True, {"id": f"tombstone-{len(self.created)}", **payload}

        async def bulk_delete_items(self, collection: str, ids: list[str]):
            self.rows[collection] = [row for row in self.rows[collection] if row["id"] not in ids]
            return True

    directus = FakeDirectus()
    tombstones = await module.persist_chat_message_archive_tombstones(
        directus_service=directus, chat_id="chat-1", regions=("nbg1", "fsn1", "hel1"),
        now=datetime(2026, 10, 3, tzinfo=timezone.utc),
    )
    assert len(tombstones) == 4
    assert all(set(row["purge_states"][1]) == {"nbg1", "fsn1", "hel1"} for row in tombstones)
    assert len(directus.rows["chat_message_archive_pages"]) == 3
    deleted = await module.delete_chat_message_archive_rows(directus_service=directus, chat_id="chat-1")
    assert deleted == {"chat_message_archive_pages": 3, "chat_message_archive_segments": 1}
    assert directus.rows["chat_message_archive_pages"] == []


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative,storage.files.reference-safe-single-copy
@pytest.mark.anyio
async def test_orphan_version_purge_keeps_versions_with_a_surviving_embed() -> None:
    module = _reference_module()

    class FakeDirectus:
        def __init__(self):
            self.created = []

        async def get_items(self, collection: str, **kwargs):
            item_filter = kwargs["params"].get("filter", {})
            if collection == "embeds" and item_filter.get("embed_id") == {"_eq": "shared"}:
                return [{"id": "surviving-embed"}]
            if collection == "embed_diffs" and item_filter.get("embed_id") == {"_eq": "orphan"}:
                return [{"id": "diff-1", "archive_state": "copied", "archive_object_key": "versions/orphan.json"}]
            return []

        async def create_item(self, collection: str, payload: dict, **_kwargs):
            self.created.append(payload)
            return True, {"id": "tombstone-1", **payload}

    directus = FakeDirectus()
    tombstones, version_ids = await module.prepare_orphan_embed_version_deletion(
        directus_service=directus,
        deleted_embeds=[{"id": "embed-1", "embed_id": "orphan"}, {"id": "embed-2", "embed_id": "shared"}],
        deleted_embed_row_ids=["embed-1", "embed-2"], user_id_hash="owner",
        regions=("nbg1", "fsn1"), now=datetime(2026, 10, 3, tzinfo=timezone.utc),
    )
    assert version_ids == ["diff-1"]
    assert len(tombstones) == 1
    assert directus.created[0]["object_key"] == "versions/orphan.json"


# contract-test: direct surface=rest_api assertions=storage.files.reference-safe-single-copy,storage.deletion.global-authoritative
def test_deletion_plan_excludes_surviving_references_and_rejects_ambiguity() -> None:
    module = _reference_module()

    plan = module.plan_reference_safe_deletions(
        deleting=module.collect_storage_references(
            embeds=[
                {
                    "id": "deleted-embed",
                    "s3_file_keys": [
                        {"bucket": "chatfiles", "key": "owner/shared.bin"},
                        {"bucket": "chatfiles", "key": "owner/private.bin"},
                    ],
                }
            ],
            uploads=[],
        ),
        surviving=module.collect_storage_references(
            embeds=[
                {
                    "id": "surviving-embed",
                    "s3_file_keys": [
                        {"bucket": "chatfiles", "key": "owner/shared.bin"},
                    ],
                }
            ],
            uploads=[],
        ),
    )

    assert plan == {("chatfiles", "owner/private.bin")}

    with pytest.raises(ValueError, match="ambiguous"):
        module.plan_reference_safe_deletions(
            deleting=module.collect_storage_references(
                embeds=[{"id": "legacy", "s3_file_keys": [{"bucket": "chatfiles"}]}],
                uploads=[],
            ),
            surviving=module.collect_storage_references(embeds=[], uploads=[]),
        )


# contract-test: direct surface=rest_api assertions=storage.files.reference-safe-single-copy,storage.deletion.global-authoritative
@pytest.mark.anyio
async def test_reference_safe_plan_persists_one_tombstone_per_unshared_object() -> None:
    module = _reference_module()
    created: list[dict] = []

    class FakeDirectus:
        async def create_item(self, collection: str, payload: dict, **_kwargs: object):
            assert collection == "storage_deletion_tombstones"
            created.append(payload)
            return True, {"id": f"tombstone-{len(created)}", **payload}

    persisted = await module.persist_reference_safe_tombstones(
        directus_service=FakeDirectus(),
        deleting=module.collect_storage_references(
            embeds=[
                {
                    "id": "deleted-embed",
                    "s3_file_keys": [
                        {"bucket": "chatfiles", "key": "owner/private.bin"},
                    ],
                }
            ],
            uploads=[],
        ),
        surviving=module.collect_storage_references(embeds=[], uploads=[]),
        regions=("nbg1", "fsn1"),
        now=datetime(2026, 8, 26, tzinfo=timezone.utc),
    )

    assert len(persisted) == 1
    assert created[0]["state"] == "prepared"
    assert created[0]["object_key"] == "owner/private.bin"
    assert created[0]["generation_keys"] == {1: "owner/private.bin"}
    assert created[0]["purge_states"] == {
        1: {"nbg1": "pending", "fsn1": "pending"},
    }


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative
@pytest.mark.anyio
async def test_prepared_tombstone_activates_only_after_reference_deletion() -> None:
    module = _reference_module()
    updates: list[tuple[str, dict]] = []

    class FakeDirectus:
        async def get_items(self, _collection: str, **_kwargs: object):
            return [{"id": "prepared-1", "state": "prepared", "version": 1}]

        async def update_item_if_version(
            self, _collection: str, item_id: str, payload: dict,
            expected_version: int, **_kwargs: object,
        ) -> dict:
            assert expected_version == 1
            updates.append((item_id, payload))
            return payload

    await module.activate_storage_tombstones(
        directus_service=FakeDirectus(),
        tombstones=[{"id": "prepared-1", "state": "prepared", "version": 1}],
        now=datetime(2026, 8, 26, tzinfo=timezone.utc),
    )

    assert updates == [
        (
            "prepared-1",
            {
                "state": "pending",
                "version": 2,
                "next_attempt_at": "2026-08-26T00:00:00+00:00",
                "updated_at": "2026-08-26T00:00:00+00:00",
            },
        )
    ]


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative
@pytest.mark.anyio
async def test_deletion_activation_refreshes_prepared_version_after_sweep_deferral() -> None:
    module = _reference_module()
    updated = []

    class FakeDirectus:
        async def get_items(self, _collection: str, **_kwargs):
            return [{"id": "tombstone-1", "state": "prepared", "version": 2}]

        async def update_item_if_version(self, _collection: str, _item_id: str,
                                         payload: dict, expected_version: int, **_kwargs):
            updated.append((expected_version, payload))
            return payload

    await module.activate_storage_tombstones(
        directus_service=FakeDirectus(),
        tombstones=[{"id": "tombstone-1", "state": "prepared", "version": 1}],
        now=datetime(2026, 10, 3, tzinfo=timezone.utc),
    )
    assert updated[0][0] == 2
    assert updated[0][1]["version"] == 3


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative,storage.files.reference-safe-single-copy
@pytest.mark.anyio
async def test_prepared_tombstone_sweep_recovers_after_interrupted_reference_removal() -> None:
    module = _reference_module()
    started = datetime(2026, 10, 3, tzinfo=timezone.utc)

    class FakeDirectus:
        def __init__(self):
            self.row = {
                "id": "tombstone-1", "logical_bucket": "cold_archives",
                "object_key": "pages/one.gz", "state": "prepared", "version": 1,
                "next_attempt_at": started.isoformat(),
            }
            self.reference_exists = True
            self.now = started

        async def get_items(self, collection: str, **kwargs):
            if collection == "storage_deletion_tombstones":
                item_filter = kwargs["params"]["filter"]
                if "id" in item_filter:
                    return [dict(self.row)]
                due = datetime.fromisoformat(self.row["next_attempt_at"]) <= self.now
                return [dict(self.row)] if self.row["state"] == "prepared" and due else []
            if collection == "chat_message_archive_pages" and self.reference_exists:
                return [{"id": "page-1", "object_key": "pages/one.gz", "large_objects": []}]
            return []

        async def update_item_if_version(self, collection: str, item_id: str, patch: dict,
                                         expected_version: int, **_kwargs):
            assert collection == "storage_deletion_tombstones" and item_id == "tombstone-1"
            if expected_version != self.row["version"]:
                return None
            self.row.update(patch)
            return dict(self.row)

    directus = FakeDirectus()
    assert await module.reconcile_prepared_storage_tombstones(
        directus_service=directus, now=started,
    ) == {"prepared_activated": 0, "prepared_deferred": 1}
    assert directus.row["state"] == "prepared"

    # The original deletion crashed after removing the last reference.
    directus.reference_exists = False
    directus.now = started + module.PREPARED_TOMBSTONE_RECHECK_DELAY
    assert await module.reconcile_prepared_storage_tombstones(
        directus_service=directus, now=directus.now,
    ) == {"prepared_activated": 1, "prepared_deferred": 0}
    assert directus.row["state"] == "pending"
    assert directus.row["version"] == 3


# contract-test: direct surface=rest_api assertions=storage.files.reference-safe-single-copy
@pytest.mark.anyio
async def test_bounded_survivor_scan_finds_cross_resource_reference() -> None:
    module = _reference_module()

    class FakeDirectus:
        async def get_items(
            self,
            collection: str,
            **_kwargs: object,
        ) -> list[dict]:
            if collection == "upload_files":
                return [
                    {
                        "id": "surviving-upload",
                        "files_metadata": {
                            "original": {"s3_key": "owner/shared.bin"},
                        },
                    }
                ]
            return []

    surviving = await module.find_surviving_storage_references(
        directus_service=FakeDirectus(),
        candidates={("chatfiles", "owner/shared.bin")},
        excluded_ids={"embeds": {"deleted-embed"}},
    )

    assert surviving.references == {("chatfiles", "owner/shared.bin")}


# contract-test: direct surface=rest_api assertions=storage.files.reference-safe-single-copy,storage.privacy.ciphertext-boundary
@pytest.mark.anyio
async def test_survivor_scan_decrypts_legacy_profile_reference_before_purge() -> None:
    module = _reference_module()

    class FakeDirectus:
        async def get_items(self, collection: str, **_kwargs: object) -> list[dict]:
            if collection == "directus_users":
                return [
                    {
                        "id": "other-user",
                        "encrypted_profileimage_url": "vault:v1:other-profile",
                        "vault_key_id": "vault-other-user",
                    }
                ]
            return []

    class FakeEncryption:
        async def decrypt_with_user_key(self, _ciphertext: str, _key_id: str) -> str:
            return "https://dev-openmates-profile-images.nbg1.your-objectstorage.com/shared/avatar.webp"

    surviving = await module.find_surviving_storage_references(
        directus_service=FakeDirectus(),
        candidates={("profile_images_legacy", "shared/avatar.webp")},
        excluded_ids={"directus_users": {"deleted-user"}},
        encryption_service=FakeEncryption(),
    )

    assert surviving.references == {
        ("profile_images_legacy", "shared/avatar.webp")
    }


# contract-test: direct surface=rest_api assertions=storage.integrity.observable-reconcilable
def test_inventory_classifies_missing_and_unreferenced_objects_without_emitting_keys() -> None:
    report = classify_inventory(
        references={
            ("chatfiles", "owner-a/present.bin"),
            ("chatfiles", "owner-a/missing.bin"),
        },
        objects=[
            {"logical_bucket": "chatfiles", "object_key": "owner-a/present.bin", "size_bytes": 10},
            {"logical_bucket": "chatfiles", "object_key": "orphan.bin", "size_bytes": 5},
        ],
        ambiguous_reference_count=2,
    )

    assert report == {
        "reference_count": 2,
        "object_count": 2,
        "object_bytes": 15,
        "references_without_objects": 1,
        "objects_without_references": 1,
        "ambiguous_references": 2,
        "object_keys_in_output": False,
        "mutations_performed": False,
    }


# contract-test: direct surface=rest_api assertions=storage.files.reference-safe-single-copy,storage.integrity.observable-reconcilable
@pytest.mark.anyio
async def test_full_reference_inventory_loads_all_backfill_authority() -> None:
    module = _reference_module()

    class FakeDirectus:
        async def get_items(self, collection: str, **_kwargs: object) -> list[dict]:
            if collection == "upload_files":
                return [{"id": "upload-1", "files_metadata": {"original": {"s3_key": "owner/file.bin"}}}]
            if collection == "cold_archive_manifests":
                return [{"id": "archive-1", "file_references": [{"logical_bucket": "chatfiles", "object_key": "owner/cold.bin"}]}]
            return []

    inventory = await module.load_authoritative_storage_reference_inventory(
        directus_service=FakeDirectus()
    )

    assert inventory.references == {
        ("chatfiles", "owner/file.bin"),
        ("chatfiles", "owner/cold.bin"),
    }
    assert inventory.ambiguous == []


# contract-test: direct surface=rest_api assertions=storage.integrity.observable-reconcilable
@pytest.mark.anyio
async def test_reference_inventory_uses_offset_pages_for_uuid_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _reference_module()
    monkeypatch.setattr(module, "REFERENCE_SCAN_PAGE_SIZE", 2)
    calls: list[tuple[str, dict]] = []

    class FakeDirectus:
        async def get_items(self, collection: str, **kwargs: object) -> list[dict]:
            params = dict(kwargs["params"])
            calls.append((collection, params))
            if collection != "upload_files":
                return []
            rows = [
                {"id": "018f-a", "files_metadata": {"original": {"s3_key": "owner/a.bin"}}},
                {"id": "018f-b", "files_metadata": {"original": {"s3_key": "owner/b.bin"}}},
                {"id": "018f-c", "files_metadata": {"original": {"s3_key": "owner/c.bin"}}},
            ]
            offset = int(params.get("offset", 0))
            return rows[offset : offset + 2]

    inventory = await module.load_authoritative_storage_reference_inventory(
        directus_service=FakeDirectus()
    )

    upload_calls = [params for collection, params in calls if collection == "upload_files"]
    assert [params["offset"] for params in upload_calls] == [0, 2]
    assert all("id" not in (params.get("filter") or {}) for params in upload_calls)
    assert inventory.references == {
        ("chatfiles", "owner/a.bin"),
        ("chatfiles", "owner/b.bin"),
        ("chatfiles", "owner/c.bin"),
    }
