"""Recovery-aware bounded regional backfill contract tests.

Recovered source bytes, rather than newly empty secondary buckets, establish
historical authority. The service creates only durable generation jobs and
returns aggregate progress suitable for a resumable internal caller.
Contract: architecture.storage-lifecycle.
"""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import importlib

import pytest


class _ClientError(Exception):
    def __init__(self, response: dict, operation_name: str) -> None:
        super().__init__(operation_name)
        self.response = response


def _module():
    try:
        return importlib.import_module("backend.core.api.app.services.s3.recovery_backfill")
    except ModuleNotFoundError as exc:
        pytest.fail(f"Recovery backfill service is not implemented: {exc}")


class _S3Client:
    def __init__(self, objects: dict[tuple[str, str], dict]) -> None:
        self.objects = objects
        self.get_calls = 0

    def head_object(self, *, Bucket: str, Key: str) -> dict:
        try:
            return self.objects[(Bucket, Key)]["head"]
        except KeyError as exc:
            raise _ClientError({"Error": {"Code": "NoSuchKey"}}, "HeadObject") from exc

    def get_object(self, *, Bucket: str, Key: str) -> dict:
        self.get_calls += 1
        try:
            return {"Body": BytesIO(self.objects[(Bucket, Key)]["bytes"])}
        except KeyError as exc:
            raise _ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject") from exc


class _Directus:
    def __init__(self, *, tombstoned: set[tuple[str, str]] | None = None, jobs: list[dict] | None = None) -> None:
        self.tombstoned = tombstoned or set()
        self.jobs = jobs or []
        self.created: list[dict] = []
        self.calls: list[tuple[str, dict]] = []

    async def get_items(self, collection: str, *, params: dict, **_kwargs: object) -> list[dict]:
        self.calls.append((collection, params))
        filter_ = params["filter"]
        if collection == "storage_deletion_tombstones":
            bucket = filter_.get("logical_bucket", {}).get("_eq")
            key = filter_.get("object_key", {}).get("_eq")
            if bucket and key:
                return [{"id": "tombstone"}] if (bucket, key) in self.tombstoned else []
            return []
        if collection == "storage_replication_jobs":
            bucket = filter_.get("logical_bucket", {}).get("_eq")
            key = filter_.get("object_key", {}).get("_eq")
            if bucket is None or key is None:
                return list(self.jobs)
            return [
                job for job in self.jobs
                if job.get("logical_bucket", "chatfiles") == bucket
                and job.get("object_key", "historic.bin") == key
            ]
        if collection == "storage_region_health":
            return [{"probe_succeeded": True}]
        return []

    async def create_item(self, _collection: str, payload: dict, **_kwargs: object) -> tuple[bool, dict]:
        self.created.append(payload)
        return True, payload


def _s3(objects: dict[tuple[str, str], dict]) -> dict[str, _S3Client]:
    return {region: _S3Client(objects) for region in ("nbg1", "fsn1", "hel1")}


# contract-test: direct surface=rest_api assertions=storage.replication.active-write-durable-outbox,storage.integrity.observable-reconcilable
@pytest.mark.anyio
async def test_recovered_source_creates_checksum_verified_repair_jobs_and_sanitized_cursor() -> None:
    module = _module()
    payload = b"legacy encrypted bytes"
    checksum = module.sha256_hex(payload)
    source_bucket = "dev-openmates-chatfiles"
    objects = {
        (source_bucket, "historic.bin"): {"bytes": payload, "head": {"Metadata": {}}},
        ("dev-openmates-chatfiles-fsn1", "historic.bin"): {
            "bytes": b"stale",
            "head": {"Metadata": {"openmates-sha256": checksum}},
        },
    }
    directus = _Directus()

    result = await module.backfill_recovered_page(
        references=[{
            "logical_bucket": "chatfiles",
            "object_key": "historic.bin",
            "generation": 3,
            "checksum": checksum,
        }],
        source_region="nbg1",
        configured_regions=("nbg1", "fsn1", "hel1"),
        s3_clients=_s3(objects),
        directus_service=directus,
        environment="development",
        now=datetime(2026, 8, 26, tzinfo=timezone.utc),
        next_cursor="opaque-next",
    )

    assert result == {
        "processed": 1,
        "scheduled": 1,
        "skipped_tombstoned": 0,
        "skipped_unavailable_source": 0,
        "skipped_source_checksum_mismatch": 0,
        "skipped_newer_authority": 0,
        "cursor": "opaque-next",
        "complete": False,
    }
    assert directus.created[0]["active_region"] == "nbg1"
    assert directus.created[0]["checksum"] == checksum
    assert directus.created[0]["region_states"] == {"nbg1": "verified", "fsn1": "pending", "hel1": "pending"}


# contract-test: direct surface=rest_api assertions=storage.integrity.observable-reconcilable
@pytest.mark.anyio
async def test_backfill_uses_sha_metadata_before_downloading_ciphertext() -> None:
    module = _module()
    checksum = "a" * 64
    objects = {
        ("dev-openmates-chatfiles", "historic.bin"): {
            "bytes": b"would be slow",
            "head": {"Metadata": {"openmates-sha256": checksum}},
        },
    }
    clients = _s3(objects)

    result = await module.backfill_recovered_page(
        references=[{
            "logical_bucket": "chatfiles",
            "object_key": "historic.bin",
            "generation": 1,
            "checksum": checksum,
        }],
        source_region="nbg1",
        configured_regions=("nbg1", "fsn1", "hel1"),
        s3_clients=clients,
        directus_service=_Directus(),
        environment="development",
        now=datetime(2026, 8, 26, tzinfo=timezone.utc),
    )

    assert result["scheduled"] == 1
    assert clients["nbg1"].get_calls == 0


# contract-test: direct surface=rest_api assertions=storage.replication.active-write-durable-outbox
@pytest.mark.anyio
async def test_backfill_rerun_reuses_existing_matching_job_without_duplicate_create() -> None:
    module = _module()
    checksum = "c" * 64
    directus = _Directus(jobs=[{
        "logical_bucket": "chatfiles",
        "object_key": "historic.bin",
        "generation": 1,
        "checksum": checksum,
    }])

    result = await module.backfill_recovered_page(
        references=[{
            "logical_bucket": "chatfiles",
            "object_key": "historic.bin",
            "generation": 1,
            "checksum": checksum,
        }],
        source_region="nbg1",
        configured_regions=("nbg1", "fsn1", "hel1"),
        s3_clients=_s3({}),
        directus_service=directus,
        environment="development",
        now=datetime(2026, 8, 26, tzinfo=timezone.utc),
    )

    assert result["scheduled"] == 1
    assert result["skipped_newer_authority"] == 0
    assert directus.created == []


# contract-test: supporting surface=rest_api assertions=storage.integrity.observable-reconcilable,storage.privacy.ciphertext-boundary
def test_inventory_fingerprint_uses_metadata_or_etag_without_body_download() -> None:
    from scripts import audit_object_storage_inventory as module

    class Client:
        def __init__(self, metadata: dict[str, str]) -> None:
            self.metadata = metadata

        def head_object(self, **_kwargs: object) -> dict:
            return {"Metadata": self.metadata}

        def get_object(self, **_kwargs: object) -> dict:
            raise AssertionError("inventory should not download object bodies")

    assert module._inventory_object_fingerprint(
        client=Client({"openmates-sha256": "b" * 64}),
        bucket="private-bucket",
        item={"Key": "private/object.bin", "ETag": '"etag-value"'},
    ) == f"sha256:{'b' * 64}"
    assert module._inventory_object_fingerprint(
        client=Client({}),
        bucket="private-bucket",
        item={"Key": "private/object.bin", "ETag": '"etag-value"'},
    ) == "etag:etag-value"


# contract-test: supporting surface=rest_api assertions=storage.integrity.observable-reconcilable
def test_inventory_maintenance_clients_use_long_scan_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import types

    from scripts import audit_object_storage_inventory as module

    created_clients = []
    fake_boto3 = types.ModuleType("boto3")
    fake_botocore = types.ModuleType("botocore")
    fake_botocore_config = types.ModuleType("botocore.config")

    class FakeConfig:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    def fake_client(service_name: str, **kwargs: object) -> dict[str, object]:
        client = {"service_name": service_name, **kwargs}
        created_clients.append(client)
        return client

    fake_boto3.client = fake_client
    fake_botocore_config.Config = FakeConfig
    fake_botocore.config = fake_botocore_config
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
    monkeypatch.setitem(sys.modules, "botocore", fake_botocore)
    monkeypatch.setitem(sys.modules, "botocore.config", fake_botocore_config)

    clients = module._build_maintenance_region_clients(
        access_key="test-access",
        secret_key="test-secret",
        regions=("nbg1", "fsn1"),
    )

    assert created_clients[0]["service_name"] == "s3"
    assert created_clients[0]["config"].kwargs["read_timeout"] == module.MAINTENANCE_S3_READ_TIMEOUT_SECONDS
    assert clients["fsn1"]["endpoint_url"] == "https://fsn1.your-objectstorage.com"


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative,storage.integrity.observable-reconcilable
@pytest.mark.anyio
async def test_backfill_never_uses_empty_secondary_authority_or_resurrects_tombstones() -> None:
    module = _module()
    directus = _Directus(tombstoned={("chatfiles", "deleted.bin")})

    result = await module.backfill_recovered_page(
        references=[{
            "logical_bucket": "chatfiles",
            "object_key": "deleted.bin",
            "generation": 1,
            "checksum": "0" * 64,
        }],
        source_region="nbg1",
        configured_regions=("nbg1", "fsn1"),
        s3_clients=_s3({}),
        directus_service=directus,
        environment="development",
        now=datetime(2026, 8, 26, tzinfo=timezone.utc),
    )

    assert result["skipped_tombstoned"] == 1
    assert result["skipped_unavailable_source"] == 0
    assert directus.created == []


# contract-test: direct surface=rest_api assertions=storage.replication.active-write-durable-outbox,storage.failover.health-reconciled
@pytest.mark.anyio
async def test_backfill_preserves_newer_secondary_generation_and_source_failures_are_not_authority() -> None:
    module = _module()
    payload = b"historic bytes"
    directus = _Directus(jobs=[{
        "logical_bucket": "chatfiles",
        "object_key": "historic.bin",
        "generation": 4,
        "checksum": "f" * 64,
        "active_region": "fsn1",
    }])

    result = await module.backfill_recovered_page(
        references=[{
            "logical_bucket": "chatfiles",
            "object_key": "historic.bin",
            "generation": 3,
            "checksum": module.sha256_hex(payload),
        }, {
            "logical_bucket": "chatfiles",
            "object_key": "unavailable.bin",
            "generation": 1,
            "checksum": "1" * 64,
        }],
        source_region="nbg1",
        configured_regions=("nbg1", "fsn1"),
        s3_clients=_s3({("dev-openmates-chatfiles", "historic.bin"): {"bytes": payload, "head": {}}}),
        directus_service=directus,
        environment="development",
        now=datetime(2026, 8, 26, tzinfo=timezone.utc),
    )

    assert result["skipped_newer_authority"] == 1
    assert result["skipped_unavailable_source"] == 1
    assert directus.created == []


# contract-test: direct surface=rest_api assertions=storage.failover.health-reconciled,storage.integrity.observable-reconcilable
@pytest.mark.anyio
async def test_recovered_region_is_ready_for_failback_only_after_all_durable_fences_clear() -> None:
    module = _module()

    class ReadinessDirectus(_Directus):
        def __init__(self, *, jobs: list[dict], tombstones: list[dict]) -> None:
            super().__init__()
            self.jobs = jobs
            self.tombstones = tombstones

        async def get_items(self, collection: str, *, params: dict, **kwargs: object) -> list[dict]:
            if collection == "storage_deletion_tombstones" and "purge_states" in params["fields"]:
                return self.tombstones
            return await super().get_items(collection, params=params, **kwargs)

    assert await module.is_region_failback_ready(
        directus_service=ReadinessDirectus(jobs=[], tombstones=[]),
        region="nbg1",
        historical_backfill_complete=True,
    ) is True
    assert await module.is_region_failback_ready(
        directus_service=ReadinessDirectus(
            jobs=[{"state": "failed", "desired_regions": ["nbg1"], "region_states": {"nbg1": "pending"}}], tombstones=[]
        ),
        region="nbg1",
        historical_backfill_complete=True,
    ) is False
    assert await module.is_region_failback_ready(
        directus_service=ReadinessDirectus(
            jobs=[{"state": "failed", "desired_regions": ["nbg1", "fsn1"], "region_states": {"nbg1": "verified", "fsn1": "pending"}}],
            tombstones=[],
        ),
        region="nbg1",
        historical_backfill_complete=True,
    ) is True
    assert await module.is_region_failback_ready(
        directus_service=ReadinessDirectus(
            jobs=[], tombstones=[{"state": "pending", "purge_states": {"1": {"nbg1": "pending"}}}]
        ),
        region="nbg1",
        historical_backfill_complete=True,
    ) is False
    assert await module.is_region_failback_ready(
        directus_service=ReadinessDirectus(jobs=[], tombstones=[]),
        region="nbg1",
        historical_backfill_complete=False,
    ) is False


# contract-test: supporting surface=rest_api assertions=storage.integrity.observable-reconcilable,storage.privacy.ciphertext-boundary
def test_replica_inventory_report_is_aggregate_and_detects_drift() -> None:
    from scripts.audit_object_storage_inventory import compare_regional_inventory

    report = compare_regional_inventory(
        source_region="nbg1",
        regions=("nbg1", "fsn1", "hel1"),
        inventories={
            "nbg1": {
                ("chatfiles", "private/a.bin"): (10, f"sha256:{'a' * 64}"),
                ("chatfiles", "private/b.bin"): (20, "etag:legacy-b"),
            },
            "fsn1": {
                ("chatfiles", "private/a.bin"): (10, f"sha256:{'a' * 64}"),
            },
            "hel1": {
                ("chatfiles", "private/a.bin"): (10, f"sha256:{'c' * 64}"),
                ("chatfiles", "private/b.bin"): (20, f"sha256:{'b' * 64}"),
            },
        },
    )

    assert report == {
        "source_region": "nbg1",
        "source_object_count": 2,
        "source_bytes": 30,
        "regions": {
            "nbg1": {"object_count": 2, "bytes": 30, "missing": 0, "mismatched": 0, "fingerprint_unverified": 0, "extra": 0},
            "fsn1": {"object_count": 1, "bytes": 10, "missing": 1, "mismatched": 0, "fingerprint_unverified": 0, "extra": 0},
            "hel1": {"object_count": 2, "bytes": 30, "missing": 0, "mismatched": 1, "fingerprint_unverified": 1, "extra": 0},
        },
        "replicas_match": False,
        "object_keys_in_output": False,
    }


# contract-test: supporting surface=rest_api assertions=storage.integrity.observable-reconcilable,storage.privacy.ciphertext-boundary
def test_authoritative_replica_inventory_separates_orphans_from_repairable_drift() -> None:
    from scripts.audit_object_storage_inventory import compare_authoritative_regional_inventory

    report = compare_authoritative_regional_inventory(
        source_region="nbg1",
        regions=("nbg1", "fsn1"),
        references={
            ("chatfiles", "private/a.bin"),
            ("chatfiles", "private/b.bin"),
            ("chatfiles", "private/source-missing.bin"),
        },
        ambiguous_reference_count=7,
        inventories={
            "nbg1": {
                ("chatfiles", "private/a.bin"): (10, f"sha256:{'a' * 64}"),
                ("chatfiles", "private/b.bin"): (20, "etag:legacy-b"),
                ("chatfiles", "private/orphan.bin"): (30, "etag:orphan"),
            },
            "fsn1": {
                ("chatfiles", "private/a.bin"): (10, f"sha256:{'a' * 64}"),
                ("chatfiles", "private/b.bin"): (20, f"sha256:{'b' * 64}"),
            },
        },
    )

    assert report == {
        "source_region": "nbg1",
        "source_object_count": 3,
        "source_objects_without_references": 1,
        "authoritative_reference_count": 3,
        "references_without_source_objects": 1,
        "ambiguous_reference_count": 7,
        "regions": {
            "nbg1": {
                "authoritative_present": 2,
                "missing": 0,
                "mismatched": 0,
                "fingerprint_unverified": 0,
            },
            "fsn1": {
                "authoritative_present": 2,
                "missing": 0,
                "mismatched": 0,
                "fingerprint_unverified": 1,
            },
        },
        "authoritative_replicas_match": False,
        "object_keys_in_output": False,
        "mutations_performed": False,
    }


# contract-test: supporting surface=rest_api assertions=storage.integrity.observable-reconcilable,storage.privacy.ciphertext-boundary
def test_provider_error_evidence_is_sanitized() -> None:
    from scripts.audit_object_storage_inventory import sanitized_provider_error

    error = _ClientError(
        {
            "Error": {"Code": "AccessDenied", "Message": "private provider detail"},
            "ResponseMetadata": {"HTTPStatusCode": 403, "RequestId": "private-request-id"},
        },
        "CreateBucket",
    )

    evidence = sanitized_provider_error(error)

    assert evidence["error_code"] == "AccessDenied"
    assert evidence["http_status"] == 403
    assert "private" not in str(evidence)
