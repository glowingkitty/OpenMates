"""Authoritative regional deletion tombstone contract tests.

Tombstones deny reads immediately, retain failed regional purge work, block
replica repair, and never purge an object with surviving references.
Contract: architecture.storage-lifecycle.
"""

from __future__ import annotations

from datetime import datetime, timezone
import importlib
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


def _reconciliation_module():
    try:
        return importlib.import_module("backend.core.api.app.services.s3.reconciliation")
    except ModuleNotFoundError as exc:
        pytest.fail(f"Deletion tombstones are not implemented: {exc}")


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative,storage.retention.system-generation-only
def test_tombstone_denies_reads_and_tracks_every_generation_and_region() -> None:
    module = _reconciliation_module()
    tombstone = module.build_deletion_tombstone(
        logical_bucket="chatfiles",
        object_key="owner/hash/original.bin",
        generations=(1, 2),
        generation_keys={
            1: "owner/hash/embed-1/original.bin",
            2: "owner/hash/embed-2/original.bin",
        },
        regions=("nbg1", "fsn1", "hel1"),
        surviving_reference_count=0,
        now=datetime(2026, 8, 26, tzinfo=timezone.utc),
    )

    assert not module.can_read_generation(tombstone, 1)
    assert not module.should_repair_generation(tombstone, 2)
    assert tombstone["purge_states"] == {
        1: {"nbg1": "pending", "fsn1": "pending", "hel1": "pending"},
        2: {"nbg1": "pending", "fsn1": "pending", "hel1": "pending"},
    }
    assert tombstone["generation_keys"][2] == "owner/hash/embed-2/original.bin"


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative,storage.files.reference-safe-single-copy
def test_failed_region_stays_pending_and_surviving_reference_blocks_purge() -> None:
    module = _reconciliation_module()
    now = datetime(2026, 8, 26, tzinfo=timezone.utc)
    tombstone = module.build_deletion_tombstone(
        logical_bucket="chatfiles",
        object_key="owner/hash/original.bin",
        generations=(1,),
        generation_keys={1: "owner/hash/embed-1/original.bin"},
        regions=("nbg1", "fsn1"),
        surviving_reference_count=0,
        now=now,
    )
    retried = module.record_purge_result(
        tombstone,
        generation=1,
        region="fsn1",
        success=False,
        now=now,
    )

    assert retried["purge_states"][1]["fsn1"] == "pending"
    assert retried["next_attempt_at"] > now

    with pytest.raises(ValueError, match="surviving references"):
        module.build_deletion_tombstone(
            logical_bucket="chatfiles",
            object_key="owner/hash/original.bin",
            generations=(1,),
            generation_keys={1: "owner/hash/embed-1/original.bin"},
            regions=("nbg1", "fsn1"),
            surviving_reference_count=1,
            now=now,
        )


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative,storage.privacy.ciphertext-boundary
def test_tombstone_schema_outlives_owner_rows_and_contains_only_routing_state() -> None:
    schema = yaml.safe_load(
        (REPO_ROOT / "backend/core/directus/schemas/storage_deletion_tombstones.yml").read_text()
    )["storage_deletion_tombstones"]["fields"]
    migration = (
        REPO_ROOT / "backend/core/directus/setup/migrate_storage_replication_indexes.sql"
    ).read_text()

    assert "user_id" not in schema
    assert schema["idempotency_key"]["required"] is True
    assert schema["generations"]["type"] == "json"
    assert schema["generation_keys"]["type"] == "json"
    assert schema["purge_states"]["type"] == "json"
    assert "storage_deletion_tombstones_identity_uq" in migration
    assert "storage_deletion_tombstones_due_idx" in migration


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative
@pytest.mark.anyio
async def test_duplicate_tombstone_persistence_returns_existing_authority() -> None:
    module = _reconciliation_module()
    tombstone = module.build_deletion_tombstone(
        logical_bucket="chatfiles",
        object_key="owner/hash/original.bin",
        generations=(1,),
        generation_keys={1: "owner/hash/embed-1/original.bin"},
        regions=("nbg1", "fsn1"),
        surviving_reference_count=0,
        now=datetime(2026, 8, 26, tzinfo=timezone.utc),
    )

    class DuplicateDirectus:
        async def create_item(self, *_args: object, **_kwargs: object) -> tuple[bool, None]:
            return False, None

        async def get_items(self, *_args: object, **_kwargs: object) -> list[dict]:
            return [{"id": "existing", "idempotency_key": tombstone["idempotency_key"]}]

    persisted = await module.persist_deletion_tombstone(
        directus_service=DuplicateDirectus(),
        tombstone=tombstone,
    )
    assert persisted["id"] == "existing"
