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
        async def update_item(
            self,
            _collection: str,
            item_id: str,
            payload: dict,
            **_kwargs: object,
        ) -> dict:
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
