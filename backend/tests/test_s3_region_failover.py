"""Regional storage circuit and failback contract tests.

Only retryable provider failures affect health; missing objects remain data
state. Failback requires cooldown, a successful probe, and reconciliation.
Contract: architecture.storage-lifecycle.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
