# Storage reference reconciliation contract tests.
# The inventory merges current embed and upload metadata without S3 access.
# Malformed legacy records remain visible as ambiguity instead of disappearing.
# Physical deletion must consume this authoritative reference view.
# See contracts/architecture/storage-lifecycle/contract.yml.

from __future__ import annotations

import importlib

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
