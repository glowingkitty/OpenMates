"""Zero-inference storage quote client contracts."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.core.api.app.services.storage_usage_metering import (
    StorageUsageIncompleteError,
    StorageUsageMeteringService,
)


class FakeDirectus:
    base_url = "http://directus.internal"

    def __init__(self, data: list[object], status_code: int = 200):
        self.data = data
        self.status_code = status_code
        self.calls: list[dict] = []

    async def _make_api_request(self, method, url, *, headers, json):
        self.calls.append({"method": method, "url": url, "headers": headers, "body": json})
        return SimpleNamespace(status_code=self.status_code, json=lambda: {"data": self.data})


# contract-test: supporting surface=rest_api assertions=billing.storage.weekly-quote
@pytest.mark.asyncio
async def test_personal_quote_preserves_measured_categories_and_source_version(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "local-placeholder")
    monkeypatch.setenv("STORAGE_LOGICAL_S3_BILLING_ENABLED", "1")
    directus = FakeDirectus([{
        "owner_kind": "personal", "owner_id": "user-1", "complete": True,
        "policy_version": "personal-storage-1gb-3credits-week-v1",
        "source_version": "logical-s3-v1", "measurement_at": 1791082800,
        "categories": {"legacy_uploads": 100, "chat_pages": 30, "sealed_recovery": 10},
        "legacy_upload_bytes": 100, "logical_s3_bytes": 40, "total_bytes": 140,
    }])
    quote = (await StorageUsageMeteringService(directus).quote_personal(["user-1"]))["user-1"]
    assert quote.total_bytes == 140
    assert quote.measurement_at == 1791082800
    assert quote.categories == {"legacy_uploads": 100, "chat_pages": 30, "sealed_recovery": 10}
    assert directus.calls[0]["body"] == {
        "operation": "quote", "user_ids": ["user-1"], "team_hashes": [], "legacy_only": False,
    }
    assert directus.calls[0]["headers"] == {"X-Internal-Service-Token": "local-placeholder"}


# contract-test: supporting surface=rest_api assertions=billing.storage.weekly-quote
@pytest.mark.asyncio
async def test_incomplete_or_missing_quote_cannot_become_zero(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "local-placeholder")
    monkeypatch.setenv("STORAGE_LOGICAL_S3_BILLING_ENABLED", "1")
    service = StorageUsageMeteringService(FakeDirectus([]))
    with pytest.raises(StorageUsageIncompleteError, match="missing_owner"):
        await service.quote_personal(["user-1"])
    service = StorageUsageMeteringService(FakeDirectus([{
        "owner_kind": "personal", "owner_id": "user-1", "complete": True,
        "policy_version": "personal-storage-1gb-3credits-week-v1",
        "source_version": "logical-s3-v1", "measurement_at": 1791082800, "categories": {"legacy_uploads": 100},
        "legacy_upload_bytes": 100, "logical_s3_bytes": 0, "total_bytes": 99,
    }]))
    with pytest.raises(StorageUsageIncompleteError, match="total_mismatch"):
        await service.quote_personal(["user-1"])


# contract-test: supporting surface=rest_api assertions=billing.storage.weekly-quote
@pytest.mark.asyncio
async def test_owner_discovery_uses_bounded_keyset_page(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "local-placeholder")
    directus = FakeDirectus(["user-b", "user-c"])
    ids = await StorageUsageMeteringService(directus).list_personal_owner_ids(
        after_user_id="user-a", limit=2,
    )
    assert ids == ["user-b", "user-c"]
    assert directus.calls[0]["body"] == {
        "operation": "list_personal_owners", "after_user_id": "user-a", "limit": 2,
    }
    directus.data = ["user-a"]
    with pytest.raises(StorageUsageIncompleteError, match="invalid_owner_page"):
        await StorageUsageMeteringService(directus).list_personal_owner_ids(
            after_user_id="user-a", limit=2,
        )


# contract-test: supporting surface=rest_api assertions=billing.storage.team-policy-gate
@pytest.mark.asyncio
async def test_team_quote_uses_separate_weekly_policy(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "local-placeholder")
    team_hash = "b" * 64
    directus = FakeDirectus([{
        "owner_kind": "team", "owner_id": team_hash, "complete": True,
        "policy_version": "team-storage-1gb-3credits-week-v1", "source_version": "logical-s3-v1", "measurement_at": 1791082800,
        "categories": {"chat_pages": 40}, "legacy_upload_bytes": 0,
        "logical_s3_bytes": 40, "total_bytes": 40,
    }])
    quote = (await StorageUsageMeteringService(directus).quote_team([team_hash]))[team_hash]
    assert quote.policy_version == "team-storage-1gb-3credits-week-v1"
    assert directus.calls[0]["body"]["user_ids"] == []
    assert directus.calls[0]["body"]["team_hashes"] == [team_hash]
    assert directus.calls[0]["body"]["legacy_only"] is False


# contract-test: supporting surface=rest_api assertions=billing.storage.weekly-quote
@pytest.mark.asyncio
async def test_personal_logical_s3_billing_defaults_off_with_legacy_upload_quote(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "local-placeholder")
    monkeypatch.delenv("STORAGE_LOGICAL_S3_BILLING_ENABLED", raising=False)
    directus = FakeDirectus([{
        "owner_kind": "personal", "owner_id": "user-1", "complete": True,
        "policy_version": "legacy-upload-storage-1gb-3credits-week-v1",
        "source_version": "legacy-upload-files-v1", "measurement_at": 1791082800,
        "categories": {"legacy_uploads": 100}, "legacy_upload_bytes": 100,
        "logical_s3_bytes": 0, "total_bytes": 100,
    }])
    quote = (await StorageUsageMeteringService(directus).quote_personal(["user-1"]))["user-1"]
    assert quote.total_bytes == quote.legacy_upload_bytes == 100
    assert quote.logical_s3_bytes == 0
    assert quote.source_version == "legacy-upload-files-v1"
    assert directus.calls[0]["body"]["legacy_only"] is True


# contract-test: supporting surface=rest_api assertions=billing.storage.weekly-quote
@pytest.mark.asyncio
async def test_personal_logical_s3_billing_requires_exact_enabled_value(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "local-placeholder")
    monkeypatch.setenv("STORAGE_LOGICAL_S3_BILLING_ENABLED", "true")
    directus = FakeDirectus([{
        "owner_kind": "personal", "owner_id": "user-1", "complete": True,
        "policy_version": "legacy-upload-storage-1gb-3credits-week-v1",
        "source_version": "legacy-upload-files-v1", "measurement_at": 1791082800,
        "categories": {"legacy_uploads": 100}, "legacy_upload_bytes": 100,
        "logical_s3_bytes": 0, "total_bytes": 100,
    }])
    await StorageUsageMeteringService(directus).quote_personal(["user-1"])
    assert directus.calls[0]["body"]["legacy_only"] is True


# contract-test: supporting surface=rest_api assertions=billing.storage.disclosures
@pytest.mark.asyncio
async def test_settings_breakdown_uses_bounded_aggregate_and_rejects_incomplete(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "local-placeholder")
    directus = FakeDirectus([
        {"category": "images", "file_count": 2, "bytes_used": 42},
        {"category": "other", "file_count": 1, "bytes_used": 3},
    ])
    assert await StorageUsageMeteringService(directus).upload_breakdown("user-1") == directus.data
    assert directus.calls[0]["body"] == {"operation": "upload_breakdown", "user_id": "user-1"}
    directus.status_code = 503
    with pytest.raises(StorageUsageIncompleteError, match="unavailable"):
        await StorageUsageMeteringService(directus).upload_breakdown("user-1")
    directus.status_code = 200
    directus.data = [{"category": "images", "file_count": 0, "bytes_used": 42}]
    with pytest.raises(StorageUsageIncompleteError, match="invalid_breakdown"):
        await StorageUsageMeteringService(directus).upload_breakdown("user-1")
