"""Conditional update acknowledgements preserve state and authorization guards."""

from unittest.mock import AsyncMock

import httpx
import pytest


def _service(response, candidate):
    from backend.core.api.app.services.directus.directus import DirectusService

    service = object.__new__(DirectusService)
    service.base_url = "http://cms:8055"
    service.ensure_auth_token = AsyncMock(return_value="test-admin-token")
    service._make_api_request = AsyncMock(return_value=response)
    service.get_items = AsyncMock(return_value=[candidate] if candidate else [])
    return service


# contract-test: supporting surface=rest_api assertions=storage.replication.active-write-durable-outbox,storage.failover.health-reconciled
@pytest.mark.asyncio
@pytest.mark.parametrize("response_body", [{}, {"data": []}, {"data": {}}])
@pytest.mark.parametrize("requested_at", ["2026-10-01T10:54:00.123456+00:00", "2026-10-01T10:54:00Z", "2026-10-01T12:54:00.987654+02:00"])
async def test_empty_patch_response_acknowledges_normalized_datetime_with_admin_scope(response_body, requested_at):
    candidate = {"id": "test-job", "version": 2, "status": "verified", "completed_at": "2026-10-01T10:54:00"}
    service = _service(httpx.Response(200, json=response_body), candidate)
    patch = {"version": 2, "status": "verified", "completed_at": requested_at}

    result = await service.update_item_if_version(
        "storage_replication_jobs", "test-job", patch, 1,
        owner_hash_field="owner_hash", owner_hash="test-owner", admin_required=True,
    )

    assert result == candidate
    service.ensure_auth_token.assert_awaited_once_with(admin_required=True)
    kwargs = service._make_api_request.call_args.kwargs
    assert kwargs["params"]["filter[version][_eq]"] == 1
    assert kwargs["params"]["filter[owner_hash][_eq]"] == "test-owner"
    assert kwargs["json"] == {"keys": ["test-job"], "data": patch}
    fallback = service.get_items.call_args.kwargs
    assert fallback["admin_required"] is True
    assert fallback["no_cache"] is True
    assert fallback["params"]["filter[owner_hash][_eq]"] == "test-owner"
    assert service.last_update_error is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", [
    {"version": 1},
    {"version": 3},
    {"status": "pending"},
    {"completed_at": "2026-10-01T10:54:01"},
    {"completed_at": "invalid"},
    {"completed_at": None},
])
# contract-test: supporting surface=rest_api assertions=storage.replication.active-write-durable-outbox
async def test_fallback_rejects_unchanged_version_or_different_persisted_state(mismatch):
    candidate = {"version": 2, "status": "verified", "completed_at": "2026-10-01T10:54:00", **mismatch}
    service = _service(httpx.Response(200, json={"data": []}), candidate)
    result = await service.update_item_if_version(
        "storage_replication_jobs", "test-job",
        {"version": 2, "status": "verified", "completed_at": "2026-10-01T10:54:00.123456+00:00"}, 1,
    )
    assert result is None
    assert service.last_update_error is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(("code", "field", "collection", "expected_field", "quiet"), [
    ("RECORD_NOT_UNIQUE", "idempotency_key", "storage_replication_jobs", "idempotency_key", True),
    ("RECORD_NOT_UNIQUE", "id", "storage_replication_jobs", "idempotency_key", False),
    ("RECORD_NOT_UNIQUE", "idempotency_key", "other_collection", "idempotency_key", False),
    ("FORBIDDEN", "idempotency_key", "storage_replication_jobs", "idempotency_key", False),
    ("RECORD_NOT_UNIQUE", "idempotency_key", "storage_replication_jobs", None, False),
])
# contract-test: supporting surface=rest_api assertions=operational-monitoring.alerts.actionable-low-noise,storage.replication.active-write-durable-outbox
async def test_only_explicitly_handled_unique_field_conflicts_are_quiet(caplog, code, field, collection, expected_field, quiet):
    import logging

    response = httpx.Response(400, json={"errors": [{"extensions": {
        "code": code, "field": field, "collection": collection,
    }}]})
    service = _service(response, None)
    with caplog.at_level(logging.INFO):
        success, details = await service.create_item(
            "storage_replication_jobs", {"idempotency_key": "test-key"},
            admin_required=True, expected_unique_conflict_field=expected_field,
        )

    assert success is False
    assert details == {"status_code": 400, "text": response.text}
    assert any(record.levelno == logging.ERROR for record in caplog.records) is not quiet
    service.ensure_auth_token.assert_awaited_once_with(admin_required=True)


# contract-test: supporting surface=rest_api assertions=storage.replication.active-write-durable-outbox
@pytest.mark.asyncio
async def test_failed_patch_does_not_acknowledge_matching_fallback_state():
    service = _service(httpx.Response(403, json={"errors": []}), {"version": 2})
    assert await service.update_item_if_version("storage_replication_jobs", "test-job", {"version": 2}, 1) is None
    service.get_items.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=storage.replication.active-write-durable-outbox
@pytest.mark.asyncio
async def test_missing_admin_auth_does_not_issue_patch():
    service = _service(httpx.Response(200, json={"data": []}), {"version": 2})
    service.ensure_auth_token.return_value = None
    assert await service.update_item_if_version("storage_replication_jobs", "test-job", {"version": 2}, 1, admin_required=True) is None
    service._make_api_request.assert_not_awaited()
    service.get_items.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=storage.failover.health-reconciled
@pytest.mark.asyncio
async def test_datetime_version_guard_requires_exact_match_in_fallback():
    service = _service(httpx.Response(200, json={"data": []}), {
        "updated_at": "2026-10-01T10:54:00", "failure_count": 2,
    })
    result = await service.update_item_if_version(
        "storage_region_health", "test-region",
        {"updated_at": "2026-10-01T10:54:00.123456+00:00", "failure_count": 2},
        "2026-10-01T10:53:59", version_field="updated_at", admin_required=True,
    )
    assert result is None
