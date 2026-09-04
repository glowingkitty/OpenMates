"""File-mapped regional replication policy tests.

Broader contract tests live in the regional S3 suites, but deploy coverage is
filename based. These tests keep replication.py behavior discoverable without
network calls, workers, or Directus setup.
Contract: architecture.storage-lifecycle.
"""

from __future__ import annotations

from datetime import datetime, timezone
import importlib

import pytest


def _module():
    return importlib.import_module("backend.core.api.app.services.s3.replication")


# contract-test: direct surface=rest_api assertions=storage.replication.active-write-durable-outbox,storage.failover.health-reconciled
def test_replication_job_keeps_active_region_verified_and_retries_replicas() -> None:
    module = _module()
    now = datetime(2026, 8, 26, tzinfo=timezone.utc)
    job = module.build_replication_job(
        logical_bucket="chatfiles",
        object_key="owner/file.enc",
        generation=3,
        checksum="a" * 64,
        active_region="nbg1",
        configured_regions=("nbg1", "fsn1"),
        now=now,
    )

    updated = module.record_replica_failure(job, region="fsn1", now=now)

    assert job["region_states"] == {"nbg1": "verified", "fsn1": "pending"}
    assert updated["region_states"] == {"nbg1": "verified", "fsn1": "pending"}
    assert updated["state"] == "pending"
    assert updated["next_attempt_at"] > now


# contract-test: direct surface=rest_api assertions=storage.replication.active-write-durable-outbox
def test_replication_job_rejects_unknown_active_region() -> None:
    module = _module()

    with pytest.raises(ValueError, match="Active region"):
        module.build_replication_job(
            logical_bucket="chatfiles",
            object_key="owner/file.enc",
            generation=3,
            checksum="a" * 64,
            active_region="hel1",
            configured_regions=("nbg1", "fsn1"),
            now=datetime(2026, 8, 26, tzinfo=timezone.utc),
        )
