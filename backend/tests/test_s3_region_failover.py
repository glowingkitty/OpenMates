"""Regional storage circuit and failback contract tests.

Only retryable provider failures affect health; missing objects remain data
state. Failback requires cooldown, a successful probe, and reconciliation.
Contract: architecture.storage-lifecycle.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
import hashlib
import importlib
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


def _replication_module():
    try:
        return importlib.import_module("backend.core.api.app.services.s3.replication")
    except ModuleNotFoundError as exc:
        pytest.fail(f"Regional circuit state is not implemented: {exc}")


def _service_module():
    return importlib.import_module("backend.core.api.app.services.s3.service")


# contract-test: direct surface=rest_api assertions=storage.failover.health-reconciled
def test_retryable_failures_open_circuit_but_missing_object_is_neutral() -> None:
    module = _replication_module()
    now = datetime(2026, 8, 26, tzinfo=timezone.utc)
    circuit = module.RegionCircuitBreaker(failure_threshold=2, cooldown=timedelta(seconds=60))

    circuit.record_error("nbg1", error_code="NoSuchKey", now=now)
    assert circuit.is_available("nbg1", now=now)

    circuit.record_error("nbg1", error_code="ServiceUnavailable", now=now)
    assert circuit.is_available("nbg1", now=now)
    circuit.record_error("nbg1", error_code="503", now=now)
    assert not circuit.is_available("nbg1", now=now)

    status_circuit = module.RegionCircuitBreaker(failure_threshold=1, cooldown=timedelta(seconds=60))
    status_circuit.record_error("fsn1", error_code="501", now=now)
    assert not status_circuit.is_available("fsn1", now=now)


# contract-test: direct surface=rest_api assertions=storage.failover.health-reconciled
@pytest.mark.anyio
async def test_persisted_health_counts_transport_errors_but_not_missing_objects() -> None:
    module = _replication_module()

    class FakeDirectus:
        def __init__(self) -> None:
            self.created: dict | None = None

        async def get_items(self, *_args: object, **_kwargs: object) -> list[dict]:
            return []

        async def create_item(self, _collection: str, payload: dict, **_kwargs: object) -> tuple[bool, dict]:
            self.created = payload
            return True, payload

    directus = FakeDirectus()
    now = datetime(2026, 8, 26, tzinfo=timezone.utc)
    await module.record_persisted_region_error(
        directus_service=directus,
        region="fsn1",
        error_code="EndpointConnectionError",
        now=now,
    )
    assert directus.created is not None
    assert directus.created["failure_count"] == 1

    directus.created = None
    await module.record_persisted_region_error(
        directus_service=directus,
        region="fsn1",
        error_code="NoSuchKey",
        now=now,
    )
    assert directus.created is None

    await module.record_persisted_region_error(
        directus_service=directus,
        region="hel1",
        error_code="501",
        now=now,
    )
    assert directus.created is not None
    assert directus.created["region"] == "hel1"


# contract-test: direct surface=rest_api assertions=storage.failover.health-reconciled
def test_failback_waits_for_probe_and_reconciliation_after_cooldown() -> None:
    module = _replication_module()
    now = datetime(2026, 8, 26, tzinfo=timezone.utc)
    circuit = module.RegionCircuitBreaker(failure_threshold=1, cooldown=timedelta(seconds=60))
    circuit.record_error("nbg1", error_code="ServiceUnavailable", now=now)
    recovered_at = now + timedelta(seconds=61)

    assert not circuit.can_fail_back("nbg1", now=recovered_at)
    circuit.record_probe_success("nbg1", now=recovered_at)
    assert not circuit.can_fail_back("nbg1", now=recovered_at)
    circuit.mark_reconciled("nbg1")
    assert circuit.can_fail_back("nbg1", now=recovered_at)


# contract-test: direct surface=rest_api assertions=storage.failover.health-reconciled
def test_region_health_schema_persists_circuit_and_failback_fences() -> None:
    schema = yaml.safe_load(
        (REPO_ROOT / "backend/core/directus/schemas/storage_region_health.yml").read_text()
    )["storage_region_health"]["fields"]

    assert schema["region"]["required"] is True
    assert schema["failure_count"]["type"] == "integer"
    assert schema["open_until"]["type"] == "datetime"
    assert schema["probe_succeeded"]["type"] == "boolean"
    assert schema["reconciled"]["type"] == "boolean"


# contract-test: direct surface=rest_api assertions=storage.failover.health-reconciled
@pytest.mark.anyio
@pytest.mark.parametrize("error_code", ["404", "NoSuchKey"])
async def test_replicated_read_does_not_fail_over_on_missing_object(error_code: str) -> None:
    service_module = _service_module()

    class MissingObjectClient:
        calls = 0

        def get_object(self, **_kwargs: object) -> None:
            self.calls += 1
            raise service_module.ClientError(
                {"Error": {"Code": error_code}, "ResponseMetadata": {"HTTPStatusCode": 404}},
                "GetObject",
            )

    class SecondaryClient:
        calls = 0

        def get_object(self, **_kwargs: object) -> None:
            self.calls += 1
            return {"Body": None}

    primary = MissingObjectClient()
    secondary = SecondaryClient()
    service = service_module.S3UploadService(secrets_manager=None)
    service.region_clients = {"nbg1": primary, "fsn1": secondary}

    with pytest.raises(service_module.HTTPException) as error:
        async for _chunk in service.get_replicated_file_stream(
            bucket_key="chatfiles",
            object_key="missing.bin",
            regions=("nbg1", "fsn1"),
        ):
            pass

    assert error.value.status_code == 404
    assert primary.calls == 1
    assert secondary.calls == 0


# contract-test: direct surface=rest_api assertions=storage.failover.health-reconciled
@pytest.mark.anyio
async def test_get_file_reads_replicated_bucket_from_secondary_when_primary_missing() -> None:
    service_module = _service_module()

    class PrimaryClient:
        buckets: list[str] = []

        def get_object(self, *, Bucket: str, **_kwargs: object) -> None:
            self.buckets.append(Bucket)
            raise service_module.ClientError(
                {"Error": {"Code": "NoSuchKey"}, "ResponseMetadata": {"HTTPStatusCode": 404}},
                "GetObject",
            )

    class SecondaryClient:
        buckets: list[str] = []

        def get_object(self, *, Bucket: str, **_kwargs: object) -> dict:
            self.buckets.append(Bucket)
            return {"Body": BytesIO(b"encrypted-profile-image")}

    primary = PrimaryClient()
    secondary = SecondaryClient()
    service = service_module.S3UploadService(secrets_manager=None)
    service.environment = "development"
    service.region_name = "nbg1"
    service.client = primary
    service.region_clients = {"nbg1": primary, "fsn1": secondary}

    content = await service.get_file(
        bucket_name="dev-openmates-profile-images-private",
        object_key="profile.enc",
    )

    assert content == b"encrypted-profile-image"
    assert primary.buckets == ["dev-openmates-profile-images-private"]
    assert secondary.buckets == ["dev-openmates-profile-images-private-fsn1"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("error_code", "http_status"),
    [
        ("ServiceUnavailable", 503),
        ("BadGateway", 502),
        ("UnknownProviderCode", 501),
        ("GatewayTimeout", 504),
        ("TooManyRequests", 429),
    ],
)
# contract-test: direct surface=rest_api assertions=storage.failover.health-reconciled
async def test_get_file_reads_replicated_bucket_from_secondary_on_retryable_primary_error(
    error_code: str,
    http_status: int,
) -> None:
    service_module = _service_module()

    class PrimaryClient:
        buckets: list[str] = []

        def get_object(self, *, Bucket: str, **_kwargs: object) -> None:
            self.buckets.append(Bucket)
            raise service_module.ClientError(
                {
                    "Error": {"Code": error_code},
                    "ResponseMetadata": {"HTTPStatusCode": http_status},
                },
                "GetObject",
            )

    class SecondaryClient:
        buckets: list[str] = []

        def get_object(self, *, Bucket: str, **_kwargs: object) -> dict:
            self.buckets.append(Bucket)
            return {"Body": BytesIO(b"encrypted-profile-image")}

    primary = PrimaryClient()
    secondary = SecondaryClient()
    service = service_module.S3UploadService(secrets_manager=None)
    service.environment = "development"
    service.region_name = "nbg1"
    service.client = primary
    service.region_clients = {"nbg1": primary, "fsn1": secondary}

    content = await service.get_file(
        bucket_name="dev-openmates-profile-images-private",
        object_key="profile.enc",
    )

    assert content == b"encrypted-profile-image"
    assert primary.buckets == ["dev-openmates-profile-images-private"]
    assert secondary.buckets == ["dev-openmates-profile-images-private-fsn1"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("error_code", "http_status", "health_error_code"),
    [
        ("ServiceUnavailable", 503, "ServiceUnavailable"),
        ("BadGateway", 502, "BadGateway"),
        ("GatewayTimeout", 504, "GatewayTimeout"),
        ("UnknownProviderCode", 501, "501"),
        ("UnknownProviderCode", 502, "502"),
        ("TooManyRequests", 429, "TooManyRequests"),
    ],
)
# contract-test: direct surface=rest_api assertions=storage.failover.health-reconciled,storage.replication.active-write-durable-outbox
async def test_retryable_active_write_failure_uses_secondary_and_journals_primary(
    monkeypatch: pytest.MonkeyPatch,
    error_code: str,
    http_status: int,
    health_error_code: str,
) -> None:
    service_module = _service_module()
    monkeypatch.setattr(service_module.asyncio, "sleep", lambda *_args, **_kwargs: _completed())

    class PrimaryClient:
        calls = 0

        def put_object(self, **_kwargs: object) -> None:
            self.calls += 1
            raise service_module.ClientError(
                {
                    "Error": {"Code": error_code},
                    "ResponseMetadata": {"HTTPStatusCode": http_status},
                },
                "PutObject",
            )

        def head_object(self, **_kwargs: object) -> None:
            raise service_module.ClientError(
                {"Error": {"Code": "NoSuchKey"}, "ResponseMetadata": {"HTTPStatusCode": 404}},
                "HeadObject",
            )

    class SecondaryClient:
        calls = 0

        def put_object(self, **_kwargs: object) -> None:
            self.calls += 1

        def generate_presigned_url(self, *_args: object, **_kwargs: object) -> str:
            return "https://example.invalid/secondary"

    class Directus:
        health_payload: dict | None = None
        replication_payload: dict | None = None

        async def get_items(self, collection: str, **_kwargs: object) -> list[dict]:
            if collection in {"storage_region_health", "storage_deletion_tombstones"}:
                return []
            return []

        async def create_item(self, collection: str, payload: dict, **_kwargs: object) -> tuple[bool, dict]:
            if collection == "storage_region_health":
                self.health_payload = payload
            elif collection == "storage_replication_jobs":
                self.replication_payload = payload
            return True, {"id": f"{collection}-1", **payload}

    primary = PrimaryClient()
    secondary = SecondaryClient()
    directus = Directus()
    service = service_module.S3UploadService(secrets_manager=None, directus_service=directus)
    service.environment = "development"
    service.region_name = "nbg1"
    service.region_clients = {"nbg1": primary, "fsn1": secondary}
    service.upload_region_clients = {"nbg1": primary, "fsn1": secondary}
    service._upload_access_key = "test-access-key"
    service._upload_secret_key = "test-secret-key"

    result = await service.upload_file(
        bucket_key="chatfiles",
        file_key="owner/hash/ciphertext.bin",
        content=b"encrypted-ciphertext",
        content_type="application/octet-stream",
    )

    assert primary.calls == 5
    assert secondary.calls == 1
    assert result["region"] == "fsn1"
    assert directus.health_payload is not None
    assert directus.health_payload["region"] == "nbg1"
    assert directus.health_payload["last_error_code"] == health_error_code
    assert directus.replication_payload is not None
    assert directus.replication_payload["active_region"] == "fsn1"
    assert directus.replication_payload["region_states"] == {"nbg1": "pending", "fsn1": "verified"}


# contract-test: direct surface=rest_api assertions=storage.failover.health-reconciled,storage.replication.active-write-durable-outbox
@pytest.mark.anyio
async def test_active_write_transport_error_keeps_primary_when_head_confirms_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service_module = _service_module()
    monkeypatch.setattr(service_module.asyncio, "sleep", lambda *_args, **_kwargs: _completed())

    content = b"encrypted-ciphertext"

    class PrimaryClient:
        calls = 0

        def put_object(self, **_kwargs: object) -> None:
            self.calls += 1
            raise service_module.EndpointConnectionError(endpoint_url="https://nbg1.example.invalid")

        def head_object(self, **_kwargs: object) -> dict:
            return {"Metadata": {"openmates-sha256": hashlib.sha256(content).hexdigest()}}

        def generate_presigned_url(self, *_args: object, **_kwargs: object) -> str:
            return "https://example.invalid/primary"

    class SecondaryClient:
        calls = 0

        def put_object(self, **_kwargs: object) -> None:
            self.calls += 1

    class Directus:
        replication_payload: dict | None = None

        async def get_items(self, *_args: object, **_kwargs: object) -> list[dict]:
            return []

        async def create_item(self, collection: str, payload: dict, **_kwargs: object) -> tuple[bool, dict]:
            if collection == "storage_replication_jobs":
                self.replication_payload = payload
            return True, {"id": f"{collection}-1", **payload}

    primary = PrimaryClient()
    secondary = SecondaryClient()
    directus = Directus()
    monkeypatch.setattr(service_module.boto3, "client", lambda *_args, **_kwargs: primary)
    service = service_module.S3UploadService(secrets_manager=None, directus_service=directus)
    service.environment = "development"
    service.region_name = "nbg1"
    service.region_clients = {"nbg1": primary, "fsn1": secondary}
    service.upload_region_clients = {"nbg1": primary, "fsn1": secondary}
    service._upload_access_key = "test-access-key"
    service._upload_secret_key = "test-secret-key"

    result = await service.upload_file(
        bucket_key="chatfiles",
        file_key="owner/hash/ciphertext.bin",
        content=content,
        content_type="application/octet-stream",
    )

    assert primary.calls == 5
    assert secondary.calls == 0
    assert result["region"] == "nbg1"
    assert directus.replication_payload is not None
    assert directus.replication_payload["active_region"] == "nbg1"


async def _completed() -> None:
    return None
