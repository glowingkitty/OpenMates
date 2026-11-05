# Storage reference reconciliation contract tests.
# The inventory merges current embed and upload metadata without S3 access.
# Malformed legacy records remain visible as ambiguity instead of disappearing.
# Physical deletion must consume this authoritative reference view.
# See contracts/architecture/storage-lifecycle/contract.yml.

from __future__ import annotations

import importlib
import copy
import hashlib
from types import SimpleNamespace
import uuid
from datetime import datetime, timezone

import pytest

from scripts.audit_object_storage_inventory import classify_inventory


@pytest.fixture(autouse=True)
def _internal_asset_transaction_test_token(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "unit-test-asset-reference-token")


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
        base_url = "http://directus.test"

        def __init__(self):
            self.created = []

        async def _make_api_request(self, _method, _url, **kwargs):
            assert kwargs["json"]["operation"] == "inspect_output_asset_references"
            return SimpleNamespace(status_code=200, json=lambda: {"data": {"slots": [], "next_cursor": None}})

        async def get_items(self, collection: str, **kwargs):
            item_filter = kwargs["params"].get("filter", {})
            if collection == "embeds" and item_filter.get("embed_id") == {"_eq": "shared"}:
                return [{"id": "surviving-embed"}]
            if collection == "embed_diffs" and item_filter.get("embed_id") == {"_eq": "orphan"}:
                return [{"id": "diff-1", "embed_id": "orphan", "hashed_user_id": "owner",
                         "archive_state": "copied", "archive_object_key": "versions/orphan.json"}]
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


@pytest.mark.parametrize("entries", [
    [{"bucket": "other", "key": "foreign"}],
    [{"bucket": "chatfiles", "key": "private", "source_embed_id": "not-a-grant"}],
    [{"bucket": "chatfiles", "key": "private"}] * 2,
    [{"bucket": "chatfiles", "key": " "}],
    [{"bucket": "chatfiles", "key": "x" * 4097}],
    [{"bucket": "chatfiles", "key": str(index)} for index in range(65)],
])
# contract-test: direct surface=rest_api assertions=authored-results.media.safe-and-attributed,storage.integrity.observable-reconcilable

def test_malformed_durable_output_assets_block_deletion_instead_of_disappearing(entries):
    module = _reference_module()
    inventory = module._inventory_for_reference_row("chat_recovery_outputs", {
        "id": "output", "payload_storage": "inline", "s3_file_keys": entries,
    })
    assert inventory.ambiguous
    with pytest.raises(ValueError, match="ambiguous"):
        module.plan_reference_safe_deletions(
            deleting=module.collect_storage_references(embeds=[], uploads=[]), surviving=inventory,
        )


# contract-test: direct surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable,storage.files.reference-safe-single-copy

def test_legacy_claim_keeps_each_historical_output_version_selected_assets():
    module = _reference_module()
    entries = [{"embed_id": "card", "output_version": version, "target_chat_id": "chat",
                "hashed_chat_id": "a" * 64, "hashed_message_id": "b" * 64,
                "parent_embed_id": "carrier", "content_commitment": str(version) * 64,
                "s3_file_keys": [{"bucket": "chatfiles", "key": key}]}
               for version, key in ((1, "old-selected"), (2, "new-selected"))]
    inventory = module._inventory_for_reference_row("chat_recovery_legacy_batch_claims", {
        "id": "permanent-claim", "state": "COMPLETED", "output_asset_references": entries,
    })
    assert inventory.references == {("chatfiles", "old-selected"), ("chatfiles", "new-selected")}
    assert inventory.ambiguous == []
    assert module._inventory_for_reference_row("chat_recovery_outputs", {
        "id": "legacy-output", "payload_storage": "inline", "s3_file_keys": None,
    }).references == set()


class _OutputAssetDeletionIO:
    """Transaction I/O fake; production slot selection/collector/order stay real."""
    base_url = "http://directus.test"

    def __init__(self):
        self.rows = {}
        self.events = []
        self.retain_release = False

    def add_slot(self, *, source="legacy", chat=None, embed=None, key="selected/preview.enc", version=1,
                 message_hash="a" * 64):
        chat, embed = chat or str(uuid.uuid4()), embed or str(uuid.uuid4())
        record = str(uuid.uuid4())
        refs = [{"bucket": "chatfiles", "key": key}]
        entry = {"embed_id": embed, "output_version": version, "target_chat_id": chat,
                 "hashed_chat_id": hashlib.sha256(chat.encode()).hexdigest(),
                 "hashed_message_id": message_hash, "parent_embed_id": str(uuid.uuid4()),
                 "content_commitment": "c" * 64, "s3_file_keys": refs}
        if source == "legacy":
            row = {"id": record, "output_asset_references": [entry]}
            self.rows.setdefault("chat_recovery_legacy_batch_claims", []).append(row)
        else:
            row = {"id": record, "subject_id": embed, "output_version": version,
                   "target_chat_id": chat, "content_commitment": "c" * 64,
                   "s3_file_keys": refs, "payload_storage": "inline",
                   "hashed_message_id": message_hash,
                   "hashed_user_id": "owner", "root_hashed_team_id": None}
            self.rows.setdefault("chat_recovery_outputs", []).append(row)
        return {"source": source, "record_id": record, "embed_id": embed,
                "output_version": version, "target_chat_id": chat,
                "content_commitment": "c" * 64, "s3_file_keys": refs}

    def slots(self):
        slots = []
        for collection, source in (("chat_recovery_outputs", "sealed"),
                                   ("chat_recovery_legacy_batch_claims", "legacy")):
            for row in self.rows.get(collection, []):
                for entry in row.get("output_asset_references", []) if source == "legacy" else [row]:
                    if entry.get("s3_file_keys") is not None:
                        slots.append({"source": source, "record_id": row["id"],
                                      "embed_id": entry.get("embed_id", entry.get("subject_id")),
                                      **{key: entry[key] for key in ("output_version", "target_chat_id",
                                                                    "content_commitment", "s3_file_keys")}})
        return copy.deepcopy(slots)

    def slot_message_hash(self, slot):
        table = "chat_recovery_outputs" if slot["source"] == "sealed" else "chat_recovery_legacy_batch_claims"
        row = next(row for row in self.rows[table] if row["id"] == slot["record_id"])
        if slot["source"] == "sealed":
            return row["hashed_message_id"]
        return next(entry["hashed_message_id"] for entry in row["output_asset_references"]
                    if (entry["embed_id"], entry["output_version"]) == (slot["embed_id"], slot["output_version"]))

    async def _make_api_request(self, _method, _url, **kwargs):
        body = kwargs["json"]
        operation, data = body["operation"], body["data"]
        if operation == "invalidate_deletion":
            fences = self.rows.setdefault("chat_recovery_chat_deletion_fences", [])
            if data["scope"] == "message":
                message_hash = hashlib.sha256(data["message_id"].encode()).hexdigest()
                chat_hash = hashlib.sha256(data["chat_id"].encode()).hexdigest()
                identity = str(uuid.uuid5(uuid.UUID(int=0), f"message-delete:{data['hashed_user_id']}:{chat_hash}:{message_hash}"))
                if not any(row["id"] == identity for row in fences):
                    fences.append({"id": identity, "chat_id": data["chat_id"], "scope": "message",
                                   "hashed_message_id": message_hash, "hashed_user_id": data["hashed_user_id"],
                                   "hashed_team_id": None})
                result = {"message_deletion_fenced": True, "chat_id": data["chat_id"],
                          "hashed_message_id": message_hash}
                self.events.append(("message-fence", message_hash))
            else:
                assert data["scope"] == "chat"
                if not any(row["id"] == data["chat_id"] for row in fences):
                    fences.append({"id": data["chat_id"], "chat_id": data["chat_id"],
                                   "hashed_user_id": data["hashed_user_id"], "hashed_team_id": None})
                result = {"chat_deletion_fenced": True, "chat_id": data["chat_id"]}
        elif operation == "inspect_output_asset_references":
            selector = "embed_ids" if "embed_ids" in data else "target_chat_ids"
            field = "embed_id" if selector == "embed_ids" else "target_chat_id"
            key = _reference_module()._output_asset_cursor_key
            candidates = sorted((slot for slot in self.slots() if slot[field] in data[selector]), key=key)
            if data.get("hashed_message_id"):
                candidates = [slot for slot in candidates if self.slot_message_hash(slot) == data["hashed_message_id"]]
            if data.get("after"):
                candidates = [slot for slot in candidates if key(slot) > key(data["after"])]
            page = candidates[:128]
            result = {"slots": page, "next_cursor": (
                {field: page[-1][field] for field in ("source", "record_id", "embed_id", "output_version")}
                if len(candidates) > len(page) else None)}
            self.events.append(("inspect", copy.deepcopy(data)))
        elif operation == "release_output_asset_references":
            selected = data["slots"]
            self.events.append(("release", copy.deepcopy(selected)))
            if self.retain_release:
                result = {"released": [], "retained": selected}
            else:
                for slot in selected:
                    assert not any(row.get("embed_id") == slot["embed_id"] for table in ("embeds", "embed_diffs")
                                   for row in self.rows.get(table, []))
                    assert not any(row.get("hashed_embed_id") == hashlib.sha256(slot["embed_id"].encode()).hexdigest()
                                   for row in self.rows.get("embed_keys", []))
                    assert slot in self.slots()
                    table = "chat_recovery_outputs" if slot["source"] == "sealed" else "chat_recovery_legacy_batch_claims"
                    row = next(row for row in self.rows[table] if row["id"] == slot["record_id"])
                    if slot["source"] == "sealed":
                        row["s3_file_keys"] = None
                    else:
                        row["output_asset_references"] = [entry for entry in row["output_asset_references"]
                                                          if (entry["embed_id"], entry["output_version"])
                                                          != (slot["embed_id"], slot["output_version"])]
                result = {"released": selected, "retained": []}
        else:
            raise AssertionError(operation)
        return SimpleNamespace(status_code=200, json=lambda: {"data": result})

    @staticmethod
    def matches(row, item_filter):
        for field, condition in item_filter.items():
            if field == "_or":
                if not any(_OutputAssetDeletionIO.matches(row, option) for option in condition):
                    return False
            elif "_eq" in condition and row.get(field) != condition["_eq"]:
                return False
            elif "_in" in condition and row.get(field) not in condition["_in"]:
                return False
            elif "_null" in condition and (row.get(field) is None) != condition["_null"]:
                return False
        return True

    async def get_items(self, collection, params, **_kwargs):
        rows = [row for row in self.rows.get(collection, []) if self.matches(row, params.get("filter", {}))]
        offset, limit = params.get("offset", 0), params.get("limit", 500)
        fields = params.get("fields", "").split(",")
        return copy.deepcopy([{key: row[key] for key in fields if key in row}
                              for row in rows[offset:offset + limit]])

    async def get_user_fields_direct(self, *_args):
        return {}

    async def create_item(self, collection, payload, **_kwargs):
        row = {"id": str(uuid.uuid4()), **payload}
        self.rows.setdefault(collection, []).append(row)
        self.events.append(("tombstone", row["object_key"]))
        return True, row

    async def bulk_delete_items(self, collection, ids):
        self.events.append(("delete", collection, list(ids)))
        self.rows[collection] = [row for row in self.rows.get(collection, []) if row["id"] not in ids]
        return True

    async def update_item_if_version(self, collection, item_id, payload, expected_version, **_kwargs):
        row = next(row for row in self.rows[collection] if row["id"] == item_id)
        assert row.get("archive_version", 1) == expected_version
        row.update(payload)
        return row


# contract-test: supporting surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable,storage.deletion.global-authoritative
@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["legacy", "sealed"])
async def test_deleted_versionless_child_prepares_selected_assets_then_releases_only_its_slot(source):
    module = _reference_module()
    io = _OutputAssetDeletionIO()
    selected = io.add_slot(source=source)
    unrelated = io.add_slot(chat=str(uuid.uuid4()), key="other/retained.enc")
    if source == "legacy":
        # Same permanent claim, unrelated target: never clear the whole manifest.
        claims = io.rows["chat_recovery_legacy_batch_claims"]
        claims[0]["output_asset_references"].extend(claims[1]["output_asset_references"])
        claims.pop()
    tombstones, versions = await module.prepare_orphan_embed_version_deletion(
        directus_service=io, deleted_embeds=[], deleted_embed_row_ids=[],
        target_chat_id=selected["target_chat_id"], user_id_hash="owner", regions=("nbg1",),
        now=datetime(2026, 10, 26, tzinfo=timezone.utc),
    )
    assert versions == []
    assert [row["object_key"] for row in tombstones] == [selected["s3_file_keys"][0]["key"]]
    assert [event[0] for event in io.events] == ["inspect", "tombstone", "release"]
    assert any(slot["embed_id"] == unrelated["embed_id"] for slot in io.slots())
    assert all(slot["embed_id"] != selected["embed_id"] for slot in io.slots())
    surviving = await module.find_surviving_storage_references(
        directus_service=io, candidates={("chatfiles", "other/retained.enc"), ("chatfiles", "selected/preview.enc")},
        excluded_ids={},
    )
    assert surviving.references == {("chatfiles", "other/retained.enc")}
    # A retry after the head was removed can discover completion by exact target.
    retry, _ = await module.prepare_orphan_embed_version_deletion(
        directus_service=io, deleted_embeds=[], deleted_embed_row_ids=[],
        target_chat_id=selected["target_chat_id"], user_id_hash="owner", regions=("nbg1",),
        now=datetime(2026, 10, 26, tzinfo=timezone.utc),
    )
    assert retry == []


# contract-test: supporting surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable,storage.deletion.global-authoritative
@pytest.mark.asyncio
async def test_deleted_child_keeps_historical_dependencies_until_last_history_row_is_removed():
    module = _reference_module()
    io = _OutputAssetDeletionIO()
    slot = io.add_slot()
    io.rows["embed_diffs"] = [{"id": "history", "embed_id": slot["embed_id"], "hashed_user_id": "owner",
                               "archive_state": "hot"}]
    tombstones, versions = await module.prepare_orphan_embed_version_deletion(
        directus_service=io, deleted_embeds=[], deleted_embed_row_ids=[], target_chat_id=slot["target_chat_id"],
        user_id_hash="owner", regions=("nbg1",), now=datetime(2026, 10, 26, tzinfo=timezone.utc),
    )
    assert len(tombstones) == 1 and versions == ["history"] and io.slots() == [slot]
    assert not any(event[0] == "release" for event in io.events)
    assert await module.delete_embed_version_rows(directus_service=io, version_ids=versions) == 1
    assert io.slots() == []
    assert [event[0] for event in io.events][-2:] == ["delete", "release"]


# contract-test: supporting surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable,storage.deletion.global-authoritative
@pytest.mark.asyncio
@pytest.mark.parametrize("guard", ["embeds", "embed_keys", "embed_diffs"])
async def test_explicit_asset_deletion_preserves_surviving_or_foreign_heads_history_and_wrappers(guard):
    module = _reference_module()
    io = _OutputAssetDeletionIO()
    slot = io.add_slot()
    io.rows[guard] = [{"id": "foreign-survivor", "embed_id": slot["embed_id"], "hashed_user_id": "foreign",
                       "hashed_embed_id": hashlib.sha256(slot["embed_id"].encode()).hexdigest()}]
    tombstones, versions = await module.prepare_orphan_embed_version_deletion(
        directus_service=io, deleted_embeds=[], deleted_embed_row_ids=[], target_chat_id=slot["target_chat_id"],
        user_id_hash="owner", regions=("nbg1",), now=datetime(2026, 10, 26, tzinfo=timezone.utc),
    )
    assert tombstones == versions == [] and io.slots() == [slot]
    assert not any(event[0] == "release" for event in io.events)


# contract-test: supporting surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable,storage.deletion.global-authoritative
@pytest.mark.asyncio
async def test_retained_transaction_slot_stops_tombstone_activation_and_keeps_durable_reference():
    module = _reference_module()
    io = _OutputAssetDeletionIO()
    slot = io.add_slot()
    io.retain_release = True
    with pytest.raises(RuntimeError, match="surviving content"):
        await module.prepare_orphan_embed_version_deletion(
            directus_service=io, deleted_embeds=[], deleted_embed_row_ids=[], target_chat_id=slot["target_chat_id"],
            user_id_hash="owner", regions=("nbg1",), now=datetime(2026, 10, 26, tzinfo=timezone.utc),
        )
    assert io.slots() == [slot]
    assert all(row["state"] == "prepared" for row in io.rows["storage_deletion_tombstones"])


# contract-test: supporting surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable,storage.deletion.global-authoritative
@pytest.mark.asyncio
async def test_account_carries_exact_personal_target_snapshot_for_pending_nohead_assets():
    module = _reference_module()
    io = _OutputAssetDeletionIO()
    personal = io.add_slot(source="sealed")
    team = io.add_slot(source="sealed", key="team/retained.enc")
    io.rows["chats"] = [{"id": personal["target_chat_id"], "hashed_user_id": "owner", "hashed_team_id": None},
                        {"id": team["target_chat_id"], "hashed_user_id": "owner", "hashed_team_id": "team"}]
    snapshot = await module.load_account_deletable_embed_rows(directus_service=io, user_id_hash="owner")
    assert snapshot.personal_chat_ids == (personal["target_chat_id"],)
    tombstones = await module.persist_account_storage_tombstones(
        directus_service=io, user_id="user", user_id_hash="owner", eligible_embed_rows=snapshot,
        regions=("nbg1",), now=datetime(2026, 10, 26, tzinfo=timezone.utc),
    )
    assert snapshot.output_asset_slots == [personal]
    assert [row["object_key"] for row in tombstones] == [personal["s3_file_keys"][0]["key"]]
    io.rows["chats"] = []  # Actual personal content deletion has now completed.
    await module.delete_account_storage_reference_rows(
        directus_service=io, user_id="user", user_id_hash="owner", eligible_embed_rows=snapshot,
    )
    assert io.slots() == [team]
    assert all(event[1].get("target_chat_ids") == [personal["target_chat_id"]]
               for event in io.events if event[0] == "inspect")


# contract-test: supporting surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable,storage.deletion.global-authoritative
@pytest.mark.asyncio
@pytest.mark.parametrize("has_history", [False, True])
async def test_account_deletion_cold_retry_uses_exact_durable_personal_target_fences(has_history):
    module = _reference_module()
    io = _OutputAssetDeletionIO()
    personal = io.add_slot()
    team = io.add_slot(key="team/keep.enc")
    io.rows["chats"] = [{"id": personal["target_chat_id"], "hashed_user_id": "owner", "hashed_team_id": None},
                        {"id": team["target_chat_id"], "hashed_user_id": "owner", "hashed_team_id": "team"}]
    assert await module.fence_account_chats_for_deletion(directus_service=io, user_id_hash="owner") == 1
    assert io.rows["chat_recovery_chat_deletion_fences"] == [{
        "id": personal["target_chat_id"], "chat_id": personal["target_chat_id"],
        "hashed_user_id": "owner", "hashed_team_id": None,
    }]
    # Lose every Python snapshot after personal content deletion, before release.
    io.rows["chats"] = [io.rows["chats"][1]]
    if has_history:
        io.rows["embed_diffs"] = [{"id": "orphan-history", "embed_id": personal["embed_id"],
                                   "hashed_user_id": "owner", "archive_state": "copied",
                                   "archive_object_key": "versions/orphan-history.enc"}]
    restored = await module.load_account_deletable_embed_rows(directus_service=io, user_id_hash="owner")
    assert restored.personal_chat_ids == (personal["target_chat_id"],)
    tombstones = await module.persist_account_storage_tombstones(
        directus_service=io, user_id="user", user_id_hash="owner", eligible_embed_rows=restored,
        regions=("nbg1",), now=datetime(2026, 10, 26, tzinfo=timezone.utc),
    )
    expected_keys = {personal["s3_file_keys"][0]["key"]}
    if has_history:
        expected_keys.add("versions/orphan-history.enc")
        assert [row["id"] for row in restored.orphan_output_versions] == ["orphan-history"]
    assert {row["object_key"] for row in tombstones} == expected_keys
    await module.delete_account_storage_reference_rows(
        directus_service=io, user_id="user", user_id_hash="owner", eligible_embed_rows=restored,
    )
    assert io.slots() == [team]
    assert io.rows.get("embed_diffs", []) == []


# contract-test: supporting surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable,storage.deletion.global-authoritative
@pytest.mark.asyncio
async def test_three_fifty_card_replies_delete_all_slots_in_bounded_inventory_and_release_pages():
    module = _reference_module()
    io = _OutputAssetDeletionIO()
    chat = str(uuid.uuid4())
    for reply in range(3):
        for child in range(50):
            io.add_slot(chat=chat, key=f"reply-{reply}/card-{child}/preview.enc")
    claim_rows = io.rows["chat_recovery_legacy_batch_claims"]
    io.rows["chat_recovery_legacy_batch_claims"] = [
        {"id": claim_rows[start]["id"],
         "output_asset_references": [entry for row in claim_rows[start:start + 50]
                                     for entry in row["output_asset_references"]]}
        for start in range(0, 150, 50)
    ]
    tombstones, versions = await module.prepare_orphan_embed_version_deletion(
        directus_service=io, deleted_embeds=[], deleted_embed_row_ids=[], target_chat_id=chat,
        user_id_hash="owner", regions=("nbg1",), now=datetime(2026, 10, 26, tzinfo=timezone.utc),
    )
    assert versions == [] and len(tombstones) == 150 and len({row["object_key"] for row in tombstones}) == 150
    assert io.slots() == []
    inspections = [event[1] for event in io.events if event[0] == "inspect"]
    assert len(inspections) == 2 and "after" not in inspections[0] and "after" in inspections[1]
    assert all(request["target_chat_ids"] == [chat] for request in inspections)
    assert [len(event[1]) for event in io.events if event[0] == "release"] == [128, 22]


# contract-test: supporting surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable,storage.deletion.global-authoritative
@pytest.mark.asyncio
async def test_output_asset_inventory_accepts_empty_advancing_pages_and_rejects_repeated_cursor():
    module = _reference_module()
    io = _OutputAssetDeletionIO()
    slot = io.add_slot()
    cursor = {"source": "legacy", "record_id": "00000000-0000-4000-8000-000000000000",
              "embed_id": slot["embed_id"], "output_version": 1}
    pages = [{"slots": [], "next_cursor": cursor}, {"slots": [slot], "next_cursor": None}]

    async def paged(_method, _url, **kwargs):
        result = pages.pop(0)
        if len(pages) == 0:
            assert kwargs["json"]["data"]["after"] == cursor
        return SimpleNamespace(status_code=200, json=lambda: {"data": result})

    io._make_api_request = paged
    assert await module._inspect_output_asset_slots(
        directus_service=io, user_id_hash="owner", target_chat_ids=[slot["target_chat_id"]],
    ) == [slot]
    pages[:] = [{"slots": [], "next_cursor": cursor}, {"slots": [], "next_cursor": cursor}]
    with pytest.raises(RuntimeError, match="did not advance"):
        await module._inspect_output_asset_slots(
            directus_service=io, user_id_hash="owner", target_chat_ids=[slot["target_chat_id"]],
        )


# contract-test: supporting surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable,storage.deletion.global-authoritative
@pytest.mark.asyncio
async def test_output_asset_release_respects_bytes_as_well_as_slot_count():
    module = _reference_module()
    io = _OutputAssetDeletionIO()
    slots = [io.add_slot(), io.add_slot()]
    for index, slot in enumerate(slots):
        refs = [{"bucket": "chatfiles", "key": f"{index}-{item}-" + "x" * 4000} for item in range(64)]
        slot["s3_file_keys"] = refs
        row = next(row for row in io.rows["chat_recovery_legacy_batch_claims"] if row["id"] == slot["record_id"])
        row["output_asset_references"][0]["s3_file_keys"] = refs
    await module._release_output_asset_slots(directus_service=io, user_id_hash="owner", slots=slots)
    assert [len(event[1]) for event in io.events if event[0] == "release"] == [1, 1]
    assert io.slots() == []


# contract-test: supporting surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable,storage.deletion.global-authoritative
@pytest.mark.asyncio
@pytest.mark.parametrize("guard", ["embeds", "embed_diffs", "embed_keys"])
async def test_account_orphan_history_recovery_preserves_any_foreign_head_history_or_wrapper(guard):
    module = _reference_module()
    io = _OutputAssetDeletionIO()
    slot = io.add_slot()
    io.rows[guard] = [{"id": "foreign", "embed_id": slot["embed_id"], "hashed_user_id": "foreign",
                       "hashed_embed_id": hashlib.sha256(slot["embed_id"].encode()).hexdigest()}]
    snapshot = module.AccountDeletableEmbedRows(embeds=(), versions=(), personal_chat_ids=(slot["target_chat_id"],))
    assert await module._account_output_asset_slots(
        directus_service=io, user_id_hash="owner", eligible=snapshot,
    ) == []
    assert snapshot.orphan_output_versions == [] and io.slots() == [slot]


# contract-test: supporting surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable,storage.deletion.global-authoritative
@pytest.mark.asyncio
async def test_account_orphan_history_recovery_waits_for_live_version_writer_lease():
    module = _reference_module()
    io = _OutputAssetDeletionIO()
    slot = io.add_slot()
    io.rows["embed_diffs"] = [{"id": "copying", "embed_id": slot["embed_id"], "hashed_user_id": "owner",
                               "archive_state": "preparing", "archive_pending_object_key": "versions/copy.enc",
                               "archive_copy_lease_until": 4_102_444_800}]
    snapshot = module.AccountDeletableEmbedRows(embeds=(), versions=(), personal_chat_ids=(slot["target_chat_id"],))
    with pytest.raises(RuntimeError, match="active or settling"):
        await module._account_output_asset_slots(directus_service=io, user_id_hash="owner", eligible=snapshot)
    assert io.slots() == [slot]
    assert not any(event[0] == "release" for event in io.events)


# contract-test: supporting surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable,storage.deletion.global-authoritative,storage.files.reference-safe-single-copy
@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["legacy", "sealed"])
@pytest.mark.parametrize("interrupt_after_heads", [False, True])
@pytest.mark.parametrize("has_hot_message", [False, True])
async def test_real_message_delete_worker_releases_only_its_assets_and_recovers_after_heads_removed(
    monkeypatch, source, interrupt_after_heads, has_hot_message,
):
    from unittest.mock import AsyncMock
    from backend.core.api.app.tasks import persistence_tasks
    from backend.core.api.app.services import chat_archive_mutation_service

    io = _OutputAssetDeletionIO()
    owner, chat, message, other_message = "owner", str(uuid.uuid4()), "delete-this-message", "keep-this-message"
    owner_hash = hashlib.sha256(owner.encode()).hexdigest()
    message_hash = hashlib.sha256(message.encode()).hexdigest()
    other_hash = hashlib.sha256(other_message.encode()).hexdigest()
    selected = io.add_slot(source=source, chat=chat, message_hash=message_hash)
    other = io.add_slot(source=source, chat=chat, message_hash=other_hash, key="other-message/keep.enc")
    io.rows["chats"] = [{"id": chat, "hashed_user_id": owner_hash, "hashed_team_id": None}]
    io.rows["messages"] = [{"id": "message-row", "client_message_id": message, "chat_id": chat},
                           {"id": "other-row", "client_message_id": other_message, "chat_id": chat}]
    if not has_hot_message:
        io.rows["messages"] = io.rows["messages"][1:]
    io.rows["embeds"] = [{"id": str(uuid.uuid4()), "embed_id": slot["embed_id"],
                          "hashed_chat_id": hashlib.sha256(chat.encode()).hexdigest(),
                          "hashed_message_id": hashed, "s3_file_keys": slot["s3_file_keys"]}
                         for slot, hashed in ((selected, message_hash), (other, other_hash))]
    io.ensure_auth_token = AsyncMock()

    async def delete_message(actual_chat, actual_message):
        assert actual_chat == chat and actual_message == message
        io.events.append(("delete-message", actual_message))
        io.rows["messages"] = [row for row in io.rows["messages"] if row["client_message_id"] != actual_message]
        return True

    async def delete_heads(hashed_chat, hashed_message, **_kwargs):
        assert hashed_chat == hashlib.sha256(chat.encode()).hexdigest() and hashed_message == message_hash
        io.events.append(("delete-heads", hashed_message))
        removed = [row["embed_id"] for row in io.rows["embeds"] if row["hashed_message_id"] == hashed_message]
        io.rows["embeds"] = [row for row in io.rows["embeds"] if row["hashed_message_id"] != hashed_message]
        return removed

    io.chat = SimpleNamespace(delete_message_by_client_id=delete_message)
    io.embed = SimpleNamespace(delete_embeds_for_message=delete_heads,
                               delete_upload_files_for_embeds=AsyncMock(return_value=0))
    monkeypatch.setattr(persistence_tasks, "DirectusService", lambda: io)
    monkeypatch.setattr(persistence_tasks, "SecretsManager", lambda: SimpleNamespace(
        initialize=AsyncMock(side_effect=RuntimeError("unit test has no product storage")),
    ))
    monkeypatch.setattr(chat_archive_mutation_service, "ChatArchiveMutationService", lambda **_kwargs: SimpleNamespace(
        promote_for_message=AsyncMock(),
    ))
    real_rpc = io._make_api_request
    interrupted = False

    async def rpc(_method, _url, **kwargs):
        nonlocal interrupted
        if interrupt_after_heads and not interrupted and kwargs["json"]["operation"] == "inspect_output_asset_references":
            interrupted = True
            raise RuntimeError("interrupted after head removal")
        return await real_rpc(_method, _url, **kwargs)

    io._make_api_request = rpc
    if interrupt_after_heads:
        with pytest.raises(RuntimeError, match="interrupted after head removal"):
            await persistence_tasks._async_persist_delete_message(owner, chat, message)
        assert [row["embed_id"] for row in io.rows["embeds"]] == [other["embed_id"]]
        assert selected in io.slots()  # The only durable selected refs survive the crash.
    await persistence_tasks._async_persist_delete_message(owner, chat, message)
    assert io.rows["chats"] == [{"id": chat, "hashed_user_id": owner_hash, "hashed_team_id": None}]
    assert [row["client_message_id"] for row in io.rows["messages"]] == [other_message]
    assert [row["embed_id"] for row in io.rows["embeds"]] == [other["embed_id"]]
    assert io.slots() == [other]
    fences = io.rows["chat_recovery_chat_deletion_fences"]
    assert len(fences) == 1 and fences[0]["scope"] == "message" and fences[0]["hashed_message_id"] == message_hash
    assert fences[0]["id"] != chat
    assert all(row["object_key"] == selected["s3_file_keys"][0]["key"] and row["state"] == "pending"
               for row in io.rows["storage_deletion_tombstones"])
    events = [event[0] for event in io.events]
    assert events.index("message-fence") < events.index("delete-message") < events.index("delete-heads")
    assert events.index("tombstone") < events.index("release")
    # Exact-message fences never enter the whole-chat/account target inventory.
    snapshot = await _reference_module().load_account_deletable_embed_rows(
        directus_service=io, user_id_hash=owner_hash,
    )
    assert snapshot.personal_chat_ids == (chat,)


# contract-test: supporting surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable,storage.deletion.global-authoritative
@pytest.mark.asyncio
async def test_message_orphan_history_waits_for_copy_writer_and_settlement_before_retry():
    module = _reference_module()
    io = _OutputAssetDeletionIO()
    slot = io.add_slot()
    started = datetime(2026, 10, 26, tzinfo=timezone.utc)
    io.rows["embed_diffs"] = [{"id": "copying-history", "embed_id": slot["embed_id"],
                               "hashed_user_id": "owner", "archive_state": "preparing",
                               "archive_pending_object_key": "versions/pending.enc",
                               "archive_copy_lease_until": int(started.timestamp()) + 60}]
    kwargs = {"directus_service": io, "deleted_embeds": [], "deleted_embed_row_ids": [],
              "target_chat_id": slot["target_chat_id"], "hashed_message_id": "a" * 64,
              "user_id_hash": "owner", "regions": ("nbg1",)}
    for elapsed in (0, 149):
        with pytest.raises(RuntimeError, match="active or settling"):
            await module.prepare_orphan_embed_version_deletion(
                **kwargs, now=datetime.fromtimestamp(started.timestamp() + elapsed, tz=timezone.utc),
            )
    assert not any(event[0] in {"tombstone", "release"} for event in io.events)
    assert io.slots() == [slot] and io.rows["embed_diffs"]
    tombstones, versions = await module.prepare_orphan_embed_version_deletion(
        **kwargs, now=datetime.fromtimestamp(started.timestamp() + 150, tz=timezone.utc),
    )
    assert versions == ["copying-history"]
    assert {row["object_key"] for row in tombstones} == {"selected/preview.enc", "versions/pending.enc"}
    assert io.slots() == [slot]  # History is still live until the canonical delete.
    await module.delete_embed_version_rows(directus_service=io, version_ids=versions)
    assert io.slots() == [] and io.rows["embed_diffs"] == []


# contract-test: supporting surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable,storage.deletion.global-authoritative
@pytest.mark.asyncio
async def test_message_asset_fence_preserves_existing_team_scope_without_personal_authority():
    module = _reference_module()
    io = _OutputAssetDeletionIO()
    chat = str(uuid.uuid4())
    io.rows["chats"] = [{"id": chat, "hashed_user_id": "owner", "hashed_team_id": "team"}]
    assert await module.fence_message_for_asset_deletion(
        directus_service=io, user_id_hash="owner", chat_id=chat, message_id="message",
    ) is False
    assert io.events == [] and "chat_recovery_chat_deletion_fences" not in io.rows


# contract-test: supporting surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable,storage.deletion.global-authoritative
@pytest.mark.asyncio
async def test_message_asset_fence_rejects_a_receipt_for_another_message():
    module = _reference_module()
    io = _OutputAssetDeletionIO()
    chat = str(uuid.uuid4())
    io.rows["chats"] = [{"id": chat, "hashed_user_id": "owner", "hashed_team_id": None}]

    async def wrong_receipt(*_args, **_kwargs):
        return SimpleNamespace(status_code=200, json=lambda: {"data": {
            "message_deletion_fenced": True, "chat_id": chat, "hashed_message_id": "f" * 64,
        }})

    io._make_api_request = wrong_receipt
    with pytest.raises(RuntimeError, match="not confirmed"):
        await module.fence_message_for_asset_deletion(
            directus_service=io, user_id_hash="owner", chat_id=chat, message_id="message",
        )
    assert io.events == []


# contract-test: supporting surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable,storage.deletion.global-authoritative
@pytest.mark.asyncio
async def test_message_asset_release_waits_only_for_its_exact_recovery_s3_writer_lease():
    module = _reference_module()
    io = _OutputAssetDeletionIO()
    selected = io.add_slot(source="sealed")
    other = io.add_slot(source="sealed", chat=selected["target_chat_id"], message_hash="b" * 64,
                        key="other-message/keep.enc")
    started = datetime(2026, 10, 26, tzinfo=timezone.utc)
    rows = io.rows["chat_recovery_outputs"]
    for row, expiry in zip(rows, (60, 3600), strict=True):
        row.update(state="PREPARING", payload_storage="s3", payload_s3_key=f"recovery/{row['id']}.enc",
                   writer_lease_until=datetime.fromtimestamp(started.timestamp() + expiry, tz=timezone.utc).isoformat())
    kwargs = {"directus_service": io, "deleted_embeds": [], "deleted_embed_row_ids": [],
              "target_chat_id": selected["target_chat_id"], "hashed_message_id": "a" * 64,
              "user_id_hash": "owner", "regions": ("nbg1",)}
    for elapsed in (0, 149):
        with pytest.raises(RuntimeError, match="active or settling"):
            await module.prepare_orphan_embed_version_deletion(
                **kwargs, now=datetime.fromtimestamp(started.timestamp() + elapsed, tz=timezone.utc),
            )
    assert not any(event[0] in {"tombstone", "release"} for event in io.events)
    assert io.slots() == [selected, other]
    tombstones, versions = await module.prepare_orphan_embed_version_deletion(
        **kwargs, now=datetime.fromtimestamp(started.timestamp() + 150, tz=timezone.utc),
    )
    assert versions == [] and [row["object_key"] for row in tombstones] == [selected["s3_file_keys"][0]["key"]]
    assert io.slots() == [other]  # The unrelated active writer did not block or lose refs.
