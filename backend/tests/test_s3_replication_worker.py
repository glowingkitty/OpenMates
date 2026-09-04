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


# contract-test: direct surface=rest_api assertions=storage.failover.health-reconciled
def test_upload_microservice_retryable_s3_codes_align_with_core() -> None:
    ensure_s3_dependencies()
    upload_module = importlib.import_module("backend.upload.services.s3_upload")
    replication_module = _replication_module()

    expected_provider_codes = {
        "429",
        "502",
        "504",
        "BadGateway",
        "GatewayTimeout",
        "RequestTimeoutException",
        "ThrottlingException",
        "TooManyRequests",
    }
    assert expected_provider_codes <= upload_module.RETRYABLE_UPLOAD_ERROR_CODES
    assert expected_provider_codes <= replication_module.RETRYABLE_ERROR_CODES


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
            self.deletes: list[dict] = []

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

        def delete_object(self, **kwargs: object) -> None:
            self.deletes.append(dict(kwargs))

    class FakeDirectus:
        def __init__(self) -> None:
            self.created: dict | None = None

        async def create_item(self, collection: str, payload: dict, **_kwargs: object) -> tuple[bool, dict]:
            assert collection == "storage_replication_jobs"
            if self.created is not None:
                return False, {}
            self.created = payload
            return True, {"id": "job-1", **payload}

        async def get_items(self, collection: str, *_args: object, **_kwargs: object) -> list[dict]:
            if collection == "storage_deletion_tombstones":
                return []
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


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative,storage.replication.active-write-durable-outbox
@pytest.mark.anyio
async def test_core_active_write_removes_object_when_tombstone_wins_race() -> None:
    service_module = load_s3_service_module()

    class FakeClient:
        def __init__(self) -> None:
            self.puts: list[dict] = []
            self.deletes: list[dict] = []

        def put_object(self, **kwargs: object) -> None:
            self.puts.append(dict(kwargs))

        def delete_object(self, **kwargs: object) -> None:
            self.deletes.append(dict(kwargs))

    class TombstonedDirectus:
        async def get_items(self, collection: str, **_kwargs: object) -> list[dict]:
            assert collection == "storage_deletion_tombstones"
            return [{"id": "tombstone-1", "state": "completed", "version": 2}]

    client = FakeClient()
    service = service_module.S3UploadService(
        secrets_manager=None,
        directus_service=TombstonedDirectus(),
    )
    service.environment = "development"
    service.region_name = "nbg1"
    service.region_clients = {"nbg1": client}
    service.upload_region_clients = {"nbg1": client}

    with pytest.raises(HTTPException):
        await service.upload_file(
            bucket_key="chatfiles",
            file_key="owner/deleted.bin",
            content=b"late-ciphertext",
            content_type="application/octet-stream",
        )

    assert client.puts
    assert client.deletes == [
        {"Bucket": "dev-openmates-chatfiles", "Key": "owner/deleted.bin"}
    ]


# contract-test: direct surface=rest_api assertions=storage.replication.active-write-durable-outbox,storage.regions.configurable-redundancy
@pytest.mark.anyio
async def test_upload_microservice_uses_active_bucket_and_internal_outbox(monkeypatch: pytest.MonkeyPatch) -> None:
    ensure_s3_dependencies()
    upload_module = importlib.import_module("backend.upload.services.s3_upload")
    content = b"encrypted-upload-service-write"

    class FakeClient:
        def __init__(self) -> None:
            self.puts: list[dict] = []
            self.deletes: list[dict] = []

        def put_object(self, **kwargs: object) -> None:
            self.puts.append(dict(kwargs))

        def delete_object(self, **kwargs: object) -> None:
            self.deletes.append(dict(kwargs))

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
    service.base_domain = "s3.example.invalid"

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
    assert service.get_base_url(target_env="dev", region="fsn1") == (
        "https://dev-openmates-chatfiles-fsn1.fsn1.your-objectstorage.com"
    )


# contract-test: direct surface=rest_api assertions=storage.failover.health-reconciled
@pytest.mark.anyio
async def test_upload_microservice_exists_probe_uses_stored_active_region() -> None:
    ensure_s3_dependencies()
    upload_module = importlib.import_module("backend.upload.services.s3_upload")

    class PrimaryClient:
        buckets: list[str] = []

        def head_object(self, *, Bucket: str, **_kwargs: object) -> None:
            self.buckets.append(Bucket)
            raise upload_module.ClientError(
                {"Error": {"Code": "NoSuchKey"}, "ResponseMetadata": {"HTTPStatusCode": 404}},
                "HeadObject",
            )

    class SecondaryClient:
        buckets: list[str] = []

        def head_object(self, *, Bucket: str, **_kwargs: object) -> dict:
            self.buckets.append(Bucket)
            return {"Metadata": {"openmates-sha256": "unused"}}

    primary = PrimaryClient()
    secondary = SecondaryClient()
    service = upload_module.UploadsS3Service()
    service.region_name = "nbg1"
    service.configured_regions = ("nbg1", "fsn1")
    service.region_clients = {"nbg1": primary, "fsn1": secondary}
    service.client = primary

    assert await service.check_file_exists("owner/fallback.bin", target_env="dev", region="fsn1")
    assert primary.buckets == []
    assert secondary.buckets == ["dev-openmates-chatfiles-fsn1"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("error_code", "http_status"),
    [
        ("ServiceUnavailable", 503),
        ("BadGateway", 502),
        ("GatewayTimeout", 504),
        ("UnknownProviderCode", 501),
        ("UnknownProviderCode", 502),
        ("TooManyRequests", 429),
    ],
)
# contract-test: direct surface=rest_api assertions=storage.failover.health-reconciled,storage.replication.active-write-durable-outbox
async def test_upload_microservice_fails_over_and_persists_secondary_as_active(
    monkeypatch: pytest.MonkeyPatch,
    error_code: str,
    http_status: int,
) -> None:
    ensure_s3_dependencies()
    upload_module = importlib.import_module("backend.upload.services.s3_upload")

    class PrimaryClient:
        def put_object(self, **_kwargs: object) -> None:
            raise upload_module.ClientError(
                {
                    "Error": {"Code": error_code},
                    "ResponseMetadata": {"HTTPStatusCode": http_status},
                },
                "PutObject",
            )

        def head_object(self, **_kwargs: object) -> None:
            raise upload_module.ClientError(
                {"Error": {"Code": "NoSuchKey"}, "ResponseMetadata": {"HTTPStatusCode": 404}},
                "HeadObject",
            )

    class SecondaryClient:
        puts: list[dict] = []

        def put_object(self, **kwargs: object) -> None:
            self.puts.append(dict(kwargs))

    requests: list[dict] = []

    class Response:
        def raise_for_status(self) -> None:
            return None

    class HttpClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, _url: str, **kwargs: object) -> Response:
            requests.append(dict(kwargs))
            return Response()

    monkeypatch.setattr(upload_module.httpx, "AsyncClient", HttpClient)
    monkeypatch.setenv("DEV_CORE_API_URL", "https://api.dev.invalid")
    monkeypatch.setenv("DEV_INTERNAL_API_SHARED_TOKEN", "test-internal-token")
    secondary = SecondaryClient()
    service = upload_module.UploadsS3Service()
    service.region_name = "nbg1"
    service.configured_regions = ("nbg1", "fsn1")
    service.region_clients = {"nbg1": PrimaryClient(), "fsn1": secondary}
    service.client = service.region_clients["nbg1"]

    result = await service.upload_file_with_region(
        "owner/hash/embed/failover.bin",
        b"encrypted-upload-service-write",
        target_env="dev",
    )

    health_requests = [request for request in requests if request["json"].get("region") == "nbg1"]
    outbox_requests = [request for request in requests if request["json"].get("active_region") == "fsn1"]
    assert result.key == "owner/hash/embed/failover.bin"
    assert result.region == "fsn1"
    assert secondary.puts[0]["Bucket"] == "dev-openmates-chatfiles-fsn1"
    assert health_requests[0]["json"]["http_status"] == http_status
    assert outbox_requests[0]["json"]["active_region"] == "fsn1"


# contract-test: direct surface=rest_api assertions=storage.failover.health-reconciled,storage.replication.active-write-durable-outbox
@pytest.mark.anyio
async def test_upload_microservice_fails_over_on_transport_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_s3_dependencies()
    upload_module = importlib.import_module("backend.upload.services.s3_upload")

    class PrimaryClient:
        def put_object(self, **_kwargs: object) -> None:
            raise upload_module.EndpointConnectionError(endpoint_url="https://nbg1.example.invalid")

        def head_object(self, **_kwargs: object) -> None:
            raise upload_module.ClientError(
                {"Error": {"Code": "NoSuchKey"}, "ResponseMetadata": {"HTTPStatusCode": 404}},
                "HeadObject",
            )

    class SecondaryClient:
        puts: list[dict] = []

        def put_object(self, **kwargs: object) -> None:
            self.puts.append(dict(kwargs))

    class Response:
        def raise_for_status(self) -> None:
            return None

    class HttpClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, _url: str, **_kwargs: object) -> Response:
            return Response()

    monkeypatch.setattr(upload_module.httpx, "AsyncClient", HttpClient)
    monkeypatch.setenv("DEV_CORE_API_URL", "https://api.dev.invalid")
    monkeypatch.setenv("DEV_INTERNAL_API_SHARED_TOKEN", "test-internal-token")
    secondary = SecondaryClient()
    service = upload_module.UploadsS3Service()
    service.region_name = "nbg1"
    service.configured_regions = ("nbg1", "fsn1")
    service.region_clients = {"nbg1": PrimaryClient(), "fsn1": secondary}
    service.client = service.region_clients["nbg1"]

    result = await service.upload_file_with_region(
        "owner/hash/embed/transport.bin",
        b"encrypted-upload-service-write",
        target_env="dev",
    )

    assert result.region == "fsn1"
    assert secondary.puts[0]["Bucket"] == "dev-openmates-chatfiles-fsn1"


# contract-test: direct surface=rest_api assertions=storage.failover.health-reconciled,storage.replication.active-write-durable-outbox
@pytest.mark.anyio
async def test_upload_microservice_journals_retryable_failure_on_last_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_s3_dependencies()
    upload_module = importlib.import_module("backend.upload.services.s3_upload")

    class FinalClient:
        puts = 0

        def put_object(self, **_kwargs: object) -> None:
            self.puts += 1
            raise upload_module.ClientError(
                {"Error": {"Code": "ServiceUnavailable"}, "ResponseMetadata": {"HTTPStatusCode": 503}},
                "PutObject",
            )

        def head_object(self, **_kwargs: object) -> None:
            raise upload_module.ClientError(
                {"Error": {"Code": "NoSuchKey"}, "ResponseMetadata": {"HTTPStatusCode": 404}},
                "HeadObject",
            )

    requests: list[dict] = []

    class Response:
        def raise_for_status(self) -> None:
            return None

    class HttpClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, url: str, **kwargs: object) -> Response:
            requests.append({"url": url, **dict(kwargs)})
            return Response()

    monkeypatch.setattr(upload_module.httpx, "AsyncClient", HttpClient)
    monkeypatch.setenv("DEV_CORE_API_URL", "https://api.dev.invalid")
    monkeypatch.setenv("DEV_INTERNAL_API_SHARED_TOKEN", "test-internal-token")
    final_client = FinalClient()
    service = upload_module.UploadsS3Service()
    service.region_name = "nbg1"
    service.configured_regions = ("nbg1", "fsn1")
    service.region_clients = {"fsn1": final_client}
    service.client = final_client

    with pytest.raises(RuntimeError, match="S3 upload failed"):
        await service.upload_file_with_region(
            "owner/hash/embed/final-candidate.bin",
            b"encrypted-upload-service-write",
            target_env="dev",
        )

    assert final_client.puts == 1
    assert len(requests) == 1
    assert requests[0]["url"].endswith("/internal/storage/region-errors")
    assert requests[0]["json"] == {
        "region": "fsn1",
        "error_code": "ServiceUnavailable",
        "http_status": 503,
    }


# contract-test: direct surface=rest_api assertions=storage.failover.health-reconciled,storage.replication.active-write-durable-outbox
@pytest.mark.anyio
async def test_upload_microservice_journals_pinned_variant_failure_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_s3_dependencies()
    upload_module = importlib.import_module("backend.upload.services.s3_upload")

    class PinnedClient:
        puts = 0

        def put_object(self, **_kwargs: object) -> None:
            self.puts += 1
            raise upload_module.ClientError(
                {"Error": {"Code": "ServiceUnavailable"}, "ResponseMetadata": {"HTTPStatusCode": 503}},
                "PutObject",
            )

        def head_object(self, **_kwargs: object) -> None:
            raise upload_module.ClientError(
                {"Error": {"Code": "NoSuchKey"}, "ResponseMetadata": {"HTTPStatusCode": 404}},
                "HeadObject",
            )

    class SecondaryClient:
        puts: list[dict] = []

        def put_object(self, **kwargs: object) -> None:
            self.puts.append(dict(kwargs))

    requests: list[dict] = []

    class Response:
        def raise_for_status(self) -> None:
            return None

    class HttpClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, url: str, **kwargs: object) -> Response:
            requests.append({"url": url, **dict(kwargs)})
            return Response()

    monkeypatch.setattr(upload_module.httpx, "AsyncClient", HttpClient)
    monkeypatch.setenv("DEV_CORE_API_URL", "https://api.dev.invalid")
    monkeypatch.setenv("DEV_INTERNAL_API_SHARED_TOKEN", "test-internal-token")
    pinned_client = PinnedClient()
    secondary = SecondaryClient()
    service = upload_module.UploadsS3Service()
    service.region_name = "nbg1"
    service.configured_regions = ("nbg1", "fsn1")
    service.region_clients = {"nbg1": pinned_client, "fsn1": secondary}
    service.client = pinned_client

    with pytest.raises(RuntimeError, match="S3 upload failed"):
        await service.upload_file_with_region(
            "owner/hash/embed/full.enc",
            b"encrypted-full-image-variant",
            target_env="dev",
            preferred_region="nbg1",
            allow_region_fallback=False,
        )

    assert pinned_client.puts == 1
    assert secondary.puts == []
    assert len(requests) == 1
    assert requests[0]["url"].endswith("/internal/storage/region-errors")
    assert requests[0]["json"] == {
        "region": "nbg1",
        "error_code": "ServiceUnavailable",
        "http_status": 503,
    }


@pytest.mark.anyio
@pytest.mark.parametrize("case", ["last_candidate", "pinned_variant"])
@pytest.mark.parametrize("write_failure", ["client", "transport"])
@pytest.mark.parametrize("head_failure", ["client", "transport"])
# contract-test: direct surface=rest_api assertions=storage.failover.health-reconciled,storage.replication.active-write-durable-outbox
async def test_upload_microservice_journals_ambiguous_probe_failures(
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    write_failure: str,
    head_failure: str,
) -> None:
    ensure_s3_dependencies()
    upload_module = importlib.import_module("backend.upload.services.s3_upload")

    class FailingClient:
        def put_object(self, **_kwargs: object) -> None:
            if write_failure == "transport":
                raise upload_module.EndpointConnectionError(endpoint_url="https://region.example.invalid")
            raise upload_module.ClientError(
                {"Error": {"Code": "ServiceUnavailable"}, "ResponseMetadata": {"HTTPStatusCode": 503}},
                "PutObject",
            )

        def head_object(self, **_kwargs: object) -> None:
            if head_failure == "transport":
                raise upload_module.EndpointConnectionError(endpoint_url="https://region.example.invalid")
            raise upload_module.ClientError(
                {"Error": {"Code": "ServiceUnavailable"}, "ResponseMetadata": {"HTTPStatusCode": 503}},
                "HeadObject",
            )

    class SecondaryClient:
        puts: list[dict] = []

        def put_object(self, **kwargs: object) -> None:
            self.puts.append(dict(kwargs))

    requests: list[dict] = []

    class Response:
        def raise_for_status(self) -> None:
            return None

    class HttpClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, url: str, **kwargs: object) -> Response:
            requests.append({"url": url, **dict(kwargs)})
            return Response()

    monkeypatch.setattr(upload_module.httpx, "AsyncClient", HttpClient)
    monkeypatch.setenv("DEV_CORE_API_URL", "https://api.dev.invalid")
    monkeypatch.setenv("DEV_INTERNAL_API_SHARED_TOKEN", "test-internal-token")
    failing_client = FailingClient()
    secondary = SecondaryClient()
    service = upload_module.UploadsS3Service()
    service.configured_regions = ("nbg1", "fsn1")
    service.region_name = "nbg1"
    if case == "last_candidate":
        failed_region = "fsn1"
        service.region_clients = {"fsn1": failing_client}
        kwargs: dict[str, object] = {}
    else:
        failed_region = "nbg1"
        service.region_clients = {"nbg1": failing_client, "fsn1": secondary}
        kwargs = {"preferred_region": "nbg1", "allow_region_fallback": False}
    service.client = failing_client

    with pytest.raises(RuntimeError, match="ambiguous"):
        await service.upload_file_with_region(
            "owner/hash/embed/ambiguous-probe.bin",
            b"encrypted-upload-service-write",
            target_env="dev",
            **kwargs,
        )

    assert secondary.puts == []
    assert len(requests) == 1
    assert requests[0]["url"].endswith("/internal/storage/region-errors")
    assert requests[0]["json"] == {
        "region": failed_region,
        "error_code": "EndpointConnectionError" if write_failure == "transport" else "ServiceUnavailable",
        "http_status": None if write_failure == "transport" else 503,
    }


# contract-test: direct surface=rest_api assertions=storage.failover.health-reconciled,storage.replication.active-write-durable-outbox
@pytest.mark.anyio
async def test_upload_microservice_persists_primary_when_transport_error_left_matching_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_s3_dependencies()
    upload_module = importlib.import_module("backend.upload.services.s3_upload")
    content = b"encrypted-upload-service-write"

    class AmbiguousPrimaryClient:
        def put_object(self, **_kwargs: object) -> None:
            raise upload_module.EndpointConnectionError(endpoint_url="https://nbg1.example.invalid")

        def head_object(self, **_kwargs: object) -> dict:
            return {"Metadata": {"openmates-sha256": hashlib.sha256(content).hexdigest()}}

    class SecondaryClient:
        puts: list[dict] = []

        def put_object(self, **kwargs: object) -> None:
            self.puts.append(dict(kwargs))

    requests: list[dict] = []

    class Response:
        def raise_for_status(self) -> None:
            return None

    class HttpClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, _url: str, **kwargs: object) -> Response:
            requests.append(dict(kwargs))
            return Response()

    monkeypatch.setattr(upload_module.httpx, "AsyncClient", HttpClient)
    monkeypatch.setenv("DEV_CORE_API_URL", "https://api.dev.invalid")
    monkeypatch.setenv("DEV_INTERNAL_API_SHARED_TOKEN", "test-internal-token")
    secondary = SecondaryClient()
    service = upload_module.UploadsS3Service()
    service.region_name = "nbg1"
    service.configured_regions = ("nbg1", "fsn1")
    service.region_clients = {"nbg1": AmbiguousPrimaryClient(), "fsn1": secondary}
    service.client = service.region_clients["nbg1"]

    result = await service.upload_file_with_region(
        "owner/hash/embed/ambiguous.bin",
        content,
        target_env="dev",
    )

    assert result.region == "nbg1"
    assert secondary.puts == []
    assert requests[0]["json"]["active_region"] == "nbg1"


# contract-test: direct surface=rest_api assertions=storage.failover.health-reconciled,storage.replication.active-write-durable-outbox
@pytest.mark.anyio
async def test_upload_microservice_profile_private_fails_over_and_persists_secondary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_s3_dependencies()
    upload_module = importlib.import_module("backend.upload.services.s3_upload")

    class PrimaryClient:
        def put_object(self, **_kwargs: object) -> None:
            raise upload_module.ClientError(
                {"Error": {"Code": "ServiceUnavailable"}, "ResponseMetadata": {"HTTPStatusCode": 503}},
                "PutObject",
            )

        def head_object(self, **_kwargs: object) -> None:
            raise upload_module.ClientError(
                {"Error": {"Code": "NoSuchKey"}, "ResponseMetadata": {"HTTPStatusCode": 404}},
                "HeadObject",
            )

    class SecondaryClient:
        puts: list[dict] = []

        def put_object(self, **kwargs: object) -> None:
            self.puts.append(dict(kwargs))

    requests: list[dict] = []

    class Response:
        def raise_for_status(self) -> None:
            return None

    class HttpClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, _url: str, **kwargs: object) -> Response:
            requests.append(dict(kwargs))
            return Response()

    monkeypatch.setattr(upload_module.httpx, "AsyncClient", HttpClient)
    monkeypatch.setenv("DEV_CORE_API_URL", "https://api.dev.invalid")
    monkeypatch.setenv("DEV_INTERNAL_API_SHARED_TOKEN", "test-internal-token")
    secondary = SecondaryClient()
    service = upload_module.UploadsS3Service()
    service.region_name = "nbg1"
    service.configured_regions = ("nbg1", "fsn1")
    service.region_clients = {"nbg1": PrimaryClient(), "fsn1": secondary}
    service.client = service.region_clients["nbg1"]

    result = await service.upload_profile_image_private_with_region(
        "profile.enc",
        b"encrypted-profile-image",
        target_env="dev",
    )

    assert result.key == "profile.enc"
    assert result.region == "fsn1"
    assert secondary.puts[0]["Bucket"] == "dev-openmates-profile-images-private-fsn1"
    assert secondary.puts[0]["CacheControl"] == "no-cache, no-store, must-revalidate"
    outbox_requests = [request for request in requests if request["json"].get("logical_bucket")]
    assert outbox_requests[0]["json"]["logical_bucket"] == "profile_images_private"
    assert outbox_requests[0]["json"]["active_region"] == "fsn1"


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative,storage.replication.active-write-durable-outbox
@pytest.mark.anyio
async def test_upload_microservice_removes_late_write_when_core_rejects_outbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_s3_dependencies()
    upload_module = importlib.import_module("backend.upload.services.s3_upload")

    class FakeClient:
        def __init__(self) -> None:
            self.deletes: list[dict] = []

        def put_object(self, **_kwargs: object) -> None:
            return None

        def delete_object(self, **kwargs: object) -> None:
            self.deletes.append(dict(kwargs))

    class RejectedResponse:
        def raise_for_status(self) -> None:
            raise RuntimeError("409 tombstoned")

    class FakeHttpClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, _url: str, **_kwargs: object) -> RejectedResponse:
            return RejectedResponse()

    monkeypatch.setattr(upload_module.httpx, "AsyncClient", FakeHttpClient)
    monkeypatch.setenv("DEV_CORE_API_URL", "https://api.dev.invalid")
    monkeypatch.setenv("DEV_INTERNAL_API_SHARED_TOKEN", "test-internal-token")
    client = FakeClient()
    service = upload_module.UploadsS3Service()
    service.region_name = "nbg1"
    service.configured_regions = ("nbg1",)
    service.region_clients = {"nbg1": client}
    service.client = client

    with pytest.raises(RuntimeError, match="409 tombstoned"):
        await service.upload_file(
            "owner/deleted.bin",
            b"late-ciphertext",
            target_env="dev",
        )

    assert client.deletes == [
        {"Bucket": "dev-openmates-chatfiles", "Key": "owner/deleted.bin"}
    ]


# contract-test: direct surface=rest_api assertions=storage.replication.active-write-durable-outbox
@pytest.mark.anyio
async def test_upload_microservice_keeps_late_write_when_outbox_transport_status_is_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_s3_dependencies()
    upload_module = importlib.import_module("backend.upload.services.s3_upload")

    class FakeClient:
        def __init__(self) -> None:
            self.deletes: list[dict] = []

        def put_object(self, **_kwargs: object) -> None:
            return None

        def delete_object(self, **kwargs: object) -> None:
            self.deletes.append(dict(kwargs))

    class FailedHttpClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, _url: str, **_kwargs: object) -> None:
            raise upload_module.httpx.ConnectError("outbox unreachable")

    monkeypatch.setattr(upload_module.httpx, "AsyncClient", FailedHttpClient)
    monkeypatch.setenv("DEV_CORE_API_URL", "https://api.dev.invalid")
    monkeypatch.setenv("DEV_INTERNAL_API_SHARED_TOKEN", "test-internal-token")
    client = FakeClient()
    service = upload_module.UploadsS3Service()
    service.region_name = "nbg1"
    service.configured_regions = ("nbg1",)
    service.region_clients = {"nbg1": client}
    service.client = client

    with pytest.raises(RuntimeError, match="outbox status is ambiguous"):
        await service.upload_file(
            "owner/outbox-transport.bin",
            b"late-ciphertext",
            target_env="dev",
        )

    assert client.deletes == []


# contract-test: direct surface=rest_api assertions=storage.replication.active-write-durable-outbox
@pytest.mark.anyio
async def test_upload_microservice_retries_outbox_transport_before_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_s3_dependencies()
    upload_module = importlib.import_module("backend.upload.services.s3_upload")

    class FakeClient:
        def __init__(self) -> None:
            self.deletes: list[dict] = []

        def put_object(self, **_kwargs: object) -> None:
            return None

        def delete_object(self, **kwargs: object) -> None:
            self.deletes.append(dict(kwargs))

    class Response:
        def raise_for_status(self) -> None:
            return None

    class FlakyHttpClient:
        calls = 0

        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, _url: str, **_kwargs: object) -> Response:
            self.__class__.calls += 1
            if self.__class__.calls == 1:
                raise upload_module.httpx.ConnectError("outbox response lost")
            return Response()

    monkeypatch.setattr(upload_module.httpx, "AsyncClient", FlakyHttpClient)
    monkeypatch.setenv("DEV_CORE_API_URL", "https://api.dev.invalid")
    monkeypatch.setenv("DEV_INTERNAL_API_SHARED_TOKEN", "test-internal-token")
    client = FakeClient()
    service = upload_module.UploadsS3Service()
    service.region_name = "nbg1"
    service.configured_regions = ("nbg1",)
    service.region_clients = {"nbg1": client}
    service.client = client

    result = await service.upload_file(
        "owner/outbox-retry.bin",
        b"late-ciphertext",
        target_env="dev",
    )

    assert result == "owner/outbox-retry.bin"
    assert FlakyHttpClient.calls == 2
    assert client.deletes == []


# contract-test: direct surface=rest_api assertions=storage.replication.active-write-durable-outbox
@pytest.mark.anyio
async def test_upload_microservice_does_not_cleanup_after_transport_then_4xx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_s3_dependencies()
    upload_module = importlib.import_module("backend.upload.services.s3_upload")

    class FakeClient:
        def __init__(self) -> None:
            self.deletes: list[dict] = []

        def put_object(self, **_kwargs: object) -> None:
            return None

        def delete_object(self, **kwargs: object) -> None:
            self.deletes.append(dict(kwargs))

    class RejectedResponse:
        def raise_for_status(self) -> None:
            request = upload_module.httpx.Request("POST", "https://api.dev.invalid/internal/storage/replication-jobs")
            response = upload_module.httpx.Response(409, request=request)
            raise upload_module.httpx.HTTPStatusError("outbox rejected", request=request, response=response)

    class TransportThenRejectedHttpClient:
        calls = 0

        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, _url: str, **_kwargs: object) -> RejectedResponse:
            self.__class__.calls += 1
            if self.__class__.calls == 1:
                raise upload_module.httpx.ConnectError("outbox response lost")
            return RejectedResponse()

    monkeypatch.setattr(upload_module.httpx, "AsyncClient", TransportThenRejectedHttpClient)
    monkeypatch.setenv("DEV_CORE_API_URL", "https://api.dev.invalid")
    monkeypatch.setenv("DEV_INTERNAL_API_SHARED_TOKEN", "test-internal-token")
    client = FakeClient()
    service = upload_module.UploadsS3Service()
    service.region_name = "nbg1"
    service.configured_regions = ("nbg1",)
    service.region_clients = {"nbg1": client}
    service.client = client

    with pytest.raises(RuntimeError, match="outbox status is ambiguous"):
        await service.upload_file(
            "owner/outbox-transport-then-4xx.bin",
            b"late-ciphertext",
            target_env="dev",
        )

    assert TransportThenRejectedHttpClient.calls == 2
    assert client.deletes == []


# contract-test: direct surface=rest_api assertions=storage.replication.active-write-durable-outbox
@pytest.mark.anyio
async def test_upload_microservice_does_not_cleanup_after_ambiguous_outbox_5xx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_s3_dependencies()
    upload_module = importlib.import_module("backend.upload.services.s3_upload")

    class FakeClient:
        def __init__(self) -> None:
            self.deletes: list[dict] = []

        def put_object(self, **_kwargs: object) -> None:
            return None

        def delete_object(self, **kwargs: object) -> None:
            self.deletes.append(dict(kwargs))

    class AmbiguousResponse:
        def raise_for_status(self) -> None:
            request = upload_module.httpx.Request("POST", "https://api.dev.invalid/internal/storage/replication-jobs")
            response = upload_module.httpx.Response(500, request=request)
            raise upload_module.httpx.HTTPStatusError("outbox response failed", request=request, response=response)

    class FailedStatusHttpClient:
        calls = 0

        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, _url: str, **_kwargs: object) -> AmbiguousResponse:
            self.__class__.calls += 1
            return AmbiguousResponse()

    monkeypatch.setattr(upload_module.httpx, "AsyncClient", FailedStatusHttpClient)
    monkeypatch.setenv("DEV_CORE_API_URL", "https://api.dev.invalid")
    monkeypatch.setenv("DEV_INTERNAL_API_SHARED_TOKEN", "test-internal-token")
    client = FakeClient()
    service = upload_module.UploadsS3Service()
    service.region_name = "nbg1"
    service.configured_regions = ("nbg1",)
    service.region_clients = {"nbg1": client}
    service.client = client

    with pytest.raises(RuntimeError, match="outbox status is ambiguous"):
        await service.upload_file(
            "owner/outbox-5xx.bin",
            b"late-ciphertext",
            target_env="dev",
        )

    assert FailedStatusHttpClient.calls == 2
    assert client.deletes == []


# contract-test: direct surface=rest_api assertions=storage.files.reference-safe-single-copy,storage.replication.active-write-durable-outbox
@pytest.mark.anyio
async def test_upload_outbox_failure_never_deletes_preexisting_dedup_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_s3_dependencies()
    upload_module = importlib.import_module("backend.upload.services.s3_upload")
    content = b"existing-ciphertext"

    class FakeClient:
        def __init__(self) -> None:
            self.deletes: list[dict] = []

        def put_object(self, **_kwargs: object) -> None:
            raise upload_module.ClientError(
                {"Error": {"Code": "PreconditionFailed"}},
                "PutObject",
            )

        def head_object(self, **_kwargs: object) -> dict:
            return {"Metadata": {"openmates-sha256": hashlib.sha256(content).hexdigest()}}

        def delete_object(self, **kwargs: object) -> None:
            self.deletes.append(dict(kwargs))

    class RejectedResponse:
        def raise_for_status(self) -> None:
            raise RuntimeError("outbox unavailable")

    class FakeHttpClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, _url: str, **_kwargs: object) -> RejectedResponse:
            return RejectedResponse()

    monkeypatch.setattr(upload_module.httpx, "AsyncClient", FakeHttpClient)
    monkeypatch.setenv("DEV_CORE_API_URL", "https://api.dev.invalid")
    monkeypatch.setenv("DEV_INTERNAL_API_SHARED_TOKEN", "test-internal-token")
    client = FakeClient()
    service = upload_module.UploadsS3Service()
    service.region_name = "nbg1"
    service.configured_regions = ("nbg1",)
    service.region_clients = {"nbg1": client}
    service.client = client

    with pytest.raises(RuntimeError, match="outbox unavailable"):
        await service.upload_file("owner/existing.bin", content, target_env="dev")

    assert client.deletes == []


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative
@pytest.mark.anyio
async def test_replicated_delete_file_persists_regional_tombstone() -> None:
    service_module = load_s3_service_module()

    class FakeDirectus:
        def __init__(self) -> None:
            self.created: dict | None = None

        async def create_item(self, collection: str, payload: dict, **_kwargs: object):
            assert collection == "storage_deletion_tombstones"
            self.created = payload
            return True, {"id": "tombstone-1", **payload}

    class FakeClient:
        def __init__(self) -> None:
            self.deletes: list[dict] = []

        def delete_object(self, **kwargs: object) -> None:
            self.deletes.append(dict(kwargs))

    directus = FakeDirectus()
    clients = {"nbg1": FakeClient(), "fsn1": FakeClient()}
    service = service_module.S3UploadService(
        secrets_manager=None,
        directus_service=directus,
    )
    service.environment = "development"
    service.region_name = "nbg1"
    service.client = clients["nbg1"]
    service.region_clients = clients

    await service.delete_file("chatfiles", "owner/deleted.bin")

    assert directus.created is not None
    assert directus.created["purge_states"] == {
        1: {"nbg1": "pending", "fsn1": "pending"}
    }
    assert all(client.deletes == [] for client in clients.values())


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative
@pytest.mark.anyio
async def test_tombstone_blocks_buffered_and_streaming_reads_immediately() -> None:
    service_module = load_s3_service_module()

    class FakeDirectus:
        async def get_items(self, collection: str, **_kwargs: object) -> list[dict]:
            assert collection == "storage_deletion_tombstones"
            return [{"id": "tombstone-1", "state": "prepared", "version": 1}]

    class FakeClient:
        def get_object(self, **_kwargs: object) -> dict:
            raise AssertionError("Tombstoned object must not reach S3")

    service = service_module.S3UploadService(
        secrets_manager=None,
        directus_service=FakeDirectus(),
    )
    service.client = FakeClient()

    buffered = await service.get_file(
        "dev-openmates-chatfiles",
        "owner/deleted.bin",
    )
    assert buffered is None

    with pytest.raises(HTTPException) as missing:
        async for _chunk in service.get_file_stream(
            "dev-openmates-chatfiles",
            "owner/deleted.bin",
        ):
            pass
    assert missing.value.status_code == 404


# contract-test: direct surface=rest_api assertions=storage.replication.active-write-durable-outbox,storage.deletion.global-authoritative
@pytest.mark.anyio
async def test_processor_copies_verifies_and_then_purges_the_same_immutable_key() -> None:
    processor_module = _job_processor_module()
    from backend.shared.python_utils.object_storage_regions import resolve_regional_bucket_name

    content = b"encrypted-ciphertext"
    checksum = hashlib.sha256(content).hexdigest()
    object_key = "user-hash/content-hash/embed-id/20260826_120000_original.bin"
    buckets = {
        region: resolve_regional_bucket_name("dev-openmates-chatfiles", region)
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
            if Bucket not in buckets.values():
                from botocore.exceptions import ClientError

                raise ClientError(
                    {"Error": {"Code": "NoSuchBucket"}, "ResponseMetadata": {"HTTPStatusCode": 404}},
                    "DeleteObject",
                )
            objects.pop((Bucket, Key), None)

    class FakeS3Service:
        environment = "development"
        region_clients = {region: FakeS3Client() for region in buckets}
        upload_region_clients = region_clients

    class FakeDirectus:
        def __init__(self) -> None:
            self.tombstone_query_count = 0
            self.tombstone_visible_after = 10_000
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
            item_filter = params["filter"]
            if "id" in item_filter:
                item_id = item_filter["id"]["_eq"]
                return [dict(self.rows[collection][item_id])]
            self.tombstone_query_count += 1
            if self.tombstone_query_count >= self.tombstone_visible_after:
                return [dict(self.rows["storage_deletion_tombstones"]["tombstone-1"])]
            return []

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

    # A tombstone that appears after the pre-copy check must win the race and
    # remove the just-created replica before the job can report verification.
    objects.pop((buckets["fsn1"], object_key))
    replication_job = directus.rows["storage_replication_jobs"]["job-1"]
    replication_job.update({
        "region_states": {"nbg1": "verified", "fsn1": "pending", "hel1": "verified"},
        "state": "pending",
    })
    directus.rows["storage_deletion_tombstones"]["tombstone-1"]["state"] = "prepared"
    directus.tombstone_query_count = 0
    directus.tombstone_visible_after = 2

    fenced = await processor.process_replication_job("job-1", 2)
    assert fenced == {"job_id": "job-1", "state": "cancelled", "processed": 0}
    assert (buckets["fsn1"], object_key) not in objects

    directus.rows["storage_deletion_tombstones"]["tombstone-1"]["state"] = "prepared"
    prepared = await processor.process_deletion_tombstone("tombstone-1", 1)
    assert prepared == {"tombstone_id": "tombstone-1", "state": "prepared", "processed": 0}
    assert objects

    directus.rows["storage_deletion_tombstones"]["tombstone-1"]["state"] = "pending"
    purged = await processor.process_deletion_tombstone("tombstone-1", 1)
    assert purged == {"tombstone_id": "tombstone-1", "state": "completed", "processed": 3}
    assert objects == {}

    directus.rows["storage_deletion_tombstones"]["tombstone-legacy"] = {
        "id": "tombstone-legacy",
        "logical_bucket": "profile_images_legacy",
        "object_key": "legacy-profile.bin",
        "generations": [1],
        "generation_keys": {"1": "legacy-profile.bin"},
        "purge_states": {"1": {region: "pending" for region in buckets}},
        "state": "pending",
        "version": 1,
        "attempts": 0,
    }

    missing_bucket = await processor.process_deletion_tombstone("tombstone-legacy", 1)
    assert missing_bucket == {"tombstone_id": "tombstone-legacy", "state": "completed", "processed": 3}
    assert directus.rows["storage_deletion_tombstones"]["tombstone-legacy"]["last_error_code"] == "NoSuchBucket"
