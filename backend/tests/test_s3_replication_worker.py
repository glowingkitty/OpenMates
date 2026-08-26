"""Durable regional replication job contract tests.

The pure job model is the authority beneath Celery delivery and Directus
persistence. Tests use deterministic timestamps and perform no S3 operations.
Contract: architecture.storage-lifecycle.
"""

from __future__ import annotations

from io import BytesIO
from datetime import datetime, timezone
import hashlib
import importlib
from pathlib import Path

import pytest
import yaml
from fastapi import HTTPException

from backend.tests.s3_service_test_support import ensure_s3_dependencies
from backend.tests.s3_service_test_support import load_s3_service_module


REPO_ROOT = Path(__file__).resolve().parents[2]


def _replication_module():
    try:
        return importlib.import_module("backend.core.api.app.services.s3.replication")
    except ModuleNotFoundError as exc:
        pytest.fail(f"Durable replication jobs are not implemented: {exc}")


def _job_processor_module():
    ensure_s3_dependencies()
    return importlib.import_module("backend.core.api.app.services.s3.job_processor")


# contract-test: direct surface=rest_api assertions=storage.replication.active-write-durable-outbox
def test_active_success_creates_one_deterministic_desired_generation() -> None:
    module = _replication_module()
    now = datetime(2026, 8, 26, tzinfo=timezone.utc)

    first = module.build_replication_job(
        logical_bucket="chatfiles",
        object_key="owner/hash/original.bin",
        generation=7,
        checksum="sha256:ciphertext",
        active_region="nbg1",
        configured_regions=("nbg1", "fsn1", "hel1"),
        now=now,
    )
    duplicate = module.build_replication_job(
        logical_bucket="chatfiles",
        object_key="owner/hash/original.bin",
        generation=7,
        checksum="sha256:ciphertext",
        active_region="nbg1",
        configured_regions=("nbg1", "fsn1", "hel1"),
        now=now,
    )

    assert first["idempotency_key"] == duplicate["idempotency_key"]
    assert first["region_states"] == {
        "nbg1": "verified",
        "fsn1": "pending",
        "hel1": "pending",
    }
    assert first["state"] == "pending"


# contract-test: direct surface=rest_api assertions=storage.replication.active-write-durable-outbox,storage.failover.health-reconciled
def test_replica_failure_persists_bounded_retry_without_failing_active_write() -> None:
    module = _replication_module()
    now = datetime(2026, 8, 26, tzinfo=timezone.utc)
    job = module.build_replication_job(
        logical_bucket="chatfiles",
        object_key="owner/hash/original.bin",
        generation=7,
        checksum="sha256:ciphertext",
        active_region="nbg1",
        configured_regions=("nbg1", "fsn1"),
        now=now,
    )

    updated = module.record_replica_failure(job, region="fsn1", now=now)

    assert updated["region_states"]["nbg1"] == "verified"
    assert updated["region_states"]["fsn1"] == "pending"
    assert updated["attempts"] == 1
    assert now < updated["next_attempt_at"] <= module.MAX_RETRY_DELAY + now


# contract-test: direct surface=rest_api assertions=storage.replication.active-write-durable-outbox
@pytest.mark.anyio
async def test_duplicate_generation_persistence_returns_the_existing_outbox_row() -> None:
    module = _replication_module()
    now = datetime(2026, 8, 26, tzinfo=timezone.utc)
    job = module.build_replication_job(
        logical_bucket="chatfiles",
        object_key="owner/hash/original.bin",
        generation=7,
        checksum="a" * 64,
        active_region="nbg1",
        configured_regions=("nbg1", "fsn1"),
        now=now,
    )

    class DuplicateDirectus:
        async def create_item(self, *_args: object, **_kwargs: object) -> tuple[bool, None]:
            return False, None

        async def get_items(self, *_args: object, **_kwargs: object) -> list[dict]:
            return [{
                "id": "existing",
                "idempotency_key": job["idempotency_key"],
                "checksum": job["checksum"],
            }]

    persisted = await module.persist_replication_job(
        directus_service=DuplicateDirectus(),
        job=job,
    )
    assert persisted["id"] == "existing"
    assert job["desired_regions"] == ["nbg1", "fsn1"]


# contract-test: direct surface=rest_api assertions=storage.replication.active-write-durable-outbox
def test_replication_schema_and_indexes_make_delivery_idempotent_and_due_query_bounded() -> None:
    schema = yaml.safe_load(
        (REPO_ROOT / "backend/core/directus/schemas/storage_replication_jobs.yml").read_text()
    )["storage_replication_jobs"]["fields"]
    migration = (
        REPO_ROOT / "backend/core/directus/setup/migrate_storage_replication_indexes.sql"
    ).read_text()

    assert schema["idempotency_key"]["required"] is True
    assert schema["desired_regions"]["type"] == "json"
    assert schema["region_states"]["type"] == "json"
    assert schema["next_attempt_at"]["type"] == "datetime"
    assert "storage_replication_jobs_identity_uq" in migration
    assert "storage_replication_jobs_due_idx" in migration


# contract-test: supporting surface=rest_api assertions=storage.replication.active-write-durable-outbox,storage.deletion.global-authoritative
@pytest.mark.anyio
async def test_storage_sweep_dispatches_only_bounded_due_work() -> None:
    module = _replication_module()

    class FakeDirectus:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        async def get_items(self, collection: str, *, params: dict, **_kwargs: object) -> list[dict]:
            self.calls.append((collection, params))
            return [{"id": f"{collection}-1", "version": 1}]

    directus = FakeDirectus()
    replication_ids: list[tuple[str, int]] = []
    tombstone_ids: list[tuple[str, int]] = []
    result = await module.dispatch_due_storage_jobs(
        directus_service=directus,
        replication_dispatch=lambda item_id, version: replication_ids.append((item_id, version)),
        tombstone_dispatch=lambda item_id, version: tombstone_ids.append((item_id, version)),
        limit=25,
    )

    assert [call[0] for call in directus.calls] == [
        "storage_replication_jobs",
        "storage_deletion_tombstones",
    ]
    assert all(call[1]["limit"] == 25 for call in directus.calls)
    assert replication_ids == [("storage_replication_jobs-1", 1)]
    assert tombstone_ids == [("storage_deletion_tombstones-1", 1)]
    assert result == {"replication_dispatched": 1, "tombstones_dispatched": 1}


# contract-test: infrastructure
def test_storage_tasks_are_registered_on_the_persistence_queue() -> None:
    config = (REPO_ROOT / "backend/core/api/app/tasks/celery_config.py").read_text()
    tasks = (REPO_ROOT / "backend/core/api/app/tasks/storage_tasks.py").read_text()

    assert "backend.core.api.app.tasks.storage_tasks" in config
    assert '"storage.*": {\'queue\': \'persistence\'}' in config
    assert "storage.sweep_due_jobs" in config
    assert "storage-replication:{job_id}:v{version}" in tasks


# contract-test: infrastructure
def test_storage_migration_is_packaged_for_dev_and_self_host() -> None:
    expected_path = "migrate_storage_replication_indexes.sql"
    packaging_files = (
        "backend/core/directus/Dockerfile.setup.selfhost",
        "backend/core/docker-compose.yml",
        "backend/core/docker-compose.selfhost.yml",
        "frontend/packages/openmates-cli/templates/core/docker-compose.selfhost.yml",
    )
    for relative_path in packaging_files:
        assert expected_path in (REPO_ROOT / relative_path).read_text(), relative_path


# contract-test: direct surface=rest_api assertions=storage.replication.active-write-durable-outbox
@pytest.mark.anyio
async def test_core_active_write_persists_outbox_before_returning() -> None:
    service_module = load_s3_service_module()
    content = b"encrypted-active-write"

    class FakeClient:
        def __init__(self) -> None:
            self.puts: list[dict] = []

        def put_object(self, **kwargs: object) -> None:
            if self.puts:
                raise service_module.ClientError(
                    {"Error": {"Code": "PreconditionFailed"}},
                    "PutObject",
                )
            self.puts.append(dict(kwargs))

        def head_object(self, **_kwargs: object) -> dict:
            return {"Metadata": dict(self.puts[0]["Metadata"])}

        def generate_presigned_url(self, *_args: object, **_kwargs: object) -> str:
            return "https://example.invalid/ciphertext"

    class FakeDirectus:
        def __init__(self) -> None:
            self.created: dict | None = None

        async def create_item(self, collection: str, payload: dict, **_kwargs: object) -> tuple[bool, dict]:
            assert collection == "storage_replication_jobs"
            if self.created is not None:
                return False, {}
            self.created = payload
            return True, {"id": "job-1", **payload}

        async def get_items(self, *_args: object, **_kwargs: object) -> list[dict]:
            return [{"id": "job-1", **dict(self.created or {})}]

    client = FakeClient()
    directus = FakeDirectus()
    service = service_module.S3UploadService(
        secrets_manager=None,
        directus_service=directus,
    )
    service.environment = "development"
    service.region_name = "nbg1"
    service.region_clients = {"nbg1": client, "fsn1": FakeClient()}
    service.upload_region_clients = {"nbg1": client, "fsn1": FakeClient()}

    result = await service.upload_file(
        bucket_key="chatfiles",
        file_key="owner/hash/embed/original.bin",
        content=content,
        content_type="application/octet-stream",
    )

    assert client.puts[0]["Bucket"] == "dev-openmates-chatfiles"
    assert result["region"] == "nbg1"
    assert directus.created is not None
    assert directus.created["checksum"] == hashlib.sha256(content).hexdigest()
    assert directus.created["region_states"] == {"nbg1": "verified", "fsn1": "pending"}
    assert client.puts[0]["IfNoneMatch"] == "*"

    with pytest.raises(HTTPException) as collision:
        await service.upload_file(
            bucket_key="chatfiles",
            file_key="owner/hash/embed/original.bin",
            content=b"different-ciphertext",
            content_type="application/octet-stream",
        )
    assert collision.value.status_code == 503


# contract-test: direct surface=rest_api assertions=storage.replication.active-write-durable-outbox,storage.regions.configurable-redundancy
@pytest.mark.anyio
async def test_upload_microservice_uses_active_bucket_and_internal_outbox(monkeypatch: pytest.MonkeyPatch) -> None:
    ensure_s3_dependencies()
    upload_module = importlib.import_module("backend.upload.services.s3_upload")
    content = b"encrypted-upload-service-write"

    class FakeClient:
        def __init__(self) -> None:
            self.puts: list[dict] = []

        def put_object(self, **kwargs: object) -> None:
            self.puts.append(dict(kwargs))

    requests: list[tuple[str, dict]] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    class FakeHttpClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, url: str, **kwargs: object) -> FakeResponse:
            requests.append((url, dict(kwargs)))
            return FakeResponse()

    monkeypatch.setattr(upload_module.httpx, "AsyncClient", FakeHttpClient)
    monkeypatch.setenv("DEV_CORE_API_URL", "https://api.dev.invalid")
    monkeypatch.setenv("DEV_INTERNAL_API_SHARED_TOKEN", "test-internal-token")
    client = FakeClient()
    service = upload_module.UploadsS3Service()
    service.region_name = "fsn1"
    service.configured_regions = ("nbg1", "fsn1", "hel1")
    service.region_clients = {"fsn1": client}
    service.client = client

    result = await service.upload_file(
        "owner/hash/embed/original.bin",
        content,
        target_env="dev",
    )

    assert result == "owner/hash/embed/original.bin"
    assert client.puts[0]["Bucket"] == "dev-openmates-chatfiles-fsn1"
    assert requests[0][0] == "https://api.dev.invalid/internal/storage/replication-jobs"
    assert requests[0][1]["json"]["checksum"] == hashlib.sha256(content).hexdigest()
    assert requests[0][1]["json"]["active_region"] == "fsn1"


# contract-test: direct surface=rest_api assertions=storage.replication.active-write-durable-outbox,storage.deletion.global-authoritative
@pytest.mark.anyio
async def test_processor_copies_verifies_and_then_purges_the_same_immutable_key() -> None:
    processor_module = _job_processor_module()
    content = b"encrypted-ciphertext"
    checksum = hashlib.sha256(content).hexdigest()
    object_key = "user-hash/content-hash/embed-id/20260826_120000_original.bin"
    buckets = {
        region: "dev-openmates-chatfiles" if region == "nbg1" else f"dev-openmates-chatfiles-{region}"
        for region in ("nbg1", "fsn1", "hel1")
    }
    objects = {(buckets["nbg1"], object_key): content}

    class FakeS3Client:
        def head_object(self, *, Bucket: str, Key: str) -> dict:
            assert (Bucket, Key) in objects
            return {"ContentType": "application/octet-stream", "Metadata": {}}

        def download_fileobj(self, bucket: str, key: str, target: BytesIO) -> None:
            target.write(objects[(bucket, key)])

        def upload_fileobj(self, source: BytesIO, bucket: str, key: str, **_kwargs: object) -> None:
            objects[(bucket, key)] = source.read()

        def get_object(self, *, Bucket: str, Key: str) -> dict:
            return {"Body": BytesIO(objects[(Bucket, Key)])}

        def delete_object(self, *, Bucket: str, Key: str) -> None:
            objects.pop((Bucket, Key), None)

    class FakeS3Service:
        environment = "development"
        region_clients = {region: FakeS3Client() for region in buckets}
        upload_region_clients = region_clients

    class FakeDirectus:
        def __init__(self) -> None:
            self.rows = {
                "storage_replication_jobs": {
                    "job-1": {
                        "id": "job-1",
                        "logical_bucket": "chatfiles",
                        "object_key": object_key,
                        "generation": 1,
                        "checksum": checksum,
                        "active_region": "nbg1",
                        "region_states": {"nbg1": "verified", "fsn1": "pending", "hel1": "pending"},
                        "state": "pending",
                        "version": 1,
                        "attempts": 0,
                    }
                },
                "storage_deletion_tombstones": {
                    "tombstone-1": {
                        "id": "tombstone-1",
                        "logical_bucket": "chatfiles",
                        "object_key": object_key,
                        "generations": [1],
                        "generation_keys": {"1": object_key},
                        "purge_states": {"1": {region: "pending" for region in buckets}},
                        "state": "pending",
                        "version": 1,
                        "attempts": 0,
                    }
                },
            }

        async def get_items(self, collection: str, *, params: dict, **_kwargs: object) -> list[dict]:
            item_id = params["filter"]["id"]["_eq"]
            return [dict(self.rows[collection][item_id])]

        async def update_item_if_version(
            self,
            collection: str,
            item_id: str,
            patch: dict,
            expected_version: int,
            **_kwargs: object,
        ) -> dict:
            assert self.rows[collection][item_id]["version"] == expected_version
            self.rows[collection][item_id].update(patch)
            return dict(self.rows[collection][item_id])

    directus = FakeDirectus()
    processor = processor_module.RegionalStorageJobProcessor(
        directus_service=directus,
        s3_service=FakeS3Service(),
    )

    replicated = await processor.process_replication_job("job-1", 1)
    assert replicated == {"job_id": "job-1", "state": "verified", "processed": 2}
    assert directus.rows["storage_replication_jobs"]["job-1"]["version"] == 2
    assert all(objects[(bucket, object_key)] == content for bucket in buckets.values())

    purged = await processor.process_deletion_tombstone("tombstone-1", 1)
    assert purged == {"tombstone_id": "tombstone-1", "state": "completed", "processed": 3}
    assert objects == {}
