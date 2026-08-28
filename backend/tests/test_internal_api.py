# contract-test-file: infrastructure
# backend/tests/test_internal_api.py
#
# Focused contracts for internal-only API task dispatch.
# These tests verify structured payload propagation without sending email or
# crossing the internal service-token boundary.

import asyncio

import pytest


def test_dispatch_test_summary_email_forwards_canonical_failure_groups(monkeypatch) -> None:
    try:
        from backend.core.api.app.routes import internal_api
        from backend.core.api.app.tasks import celery_config
    except ImportError as exc:
        pytest.skip(f"Backend dependencies not installed: {exc}")

    captured = {}

    class FakeCeleryApp:
        def send_task(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(celery_config, "app", FakeCeleryApp())
    payload = internal_api.TestRunSummaryEmailPayload(
        recipient_email="admin@example.test",
        run_id="2026-08-07T03:00:01Z",
        git_sha="e5c186d82",
        git_branch="dev",
        duration_seconds=120,
        total=2,
        passed=0,
        failed=2,
        skipped=0,
        not_started=0,
        suites=[],
        failed_tests=[],
        failure_groups=[{"title": "Playwright", "description": "Core chat"}],
    )

    result = asyncio.run(internal_api.dispatch_test_summary_email(payload, request=None))

    assert result == {"status": "dispatched"}
    assert captured["kwargs"]["failure_groups"] == [
        {"title": "Playwright", "description": "Core chat"}
    ]


# contract-test: direct surface=rest_api assertions=storage.replication.active-write-durable-outbox
def test_upload_record_is_not_visible_before_replication_intent() -> None:
    from fastapi import HTTPException
    try:
        from backend.core.api.app.routes import internal_api
    except ImportError as exc:
        pytest.skip(f"Backend dependencies not installed: {exc}")

    events = []

    class FakeDirectus:
        async def create_item(self, collection, record):
            events.append(("record", collection))

    class FailingS3:
        async def persist_external_upload_replication(self, **kwargs):
            events.append(("replication", kwargs["object_key"]))
            raise RuntimeError("outbox unavailable")

    payload = internal_api.UploadStoreRecordRequest(
        embed_id="embed-id",
        user_id="user-id",
        content_hash="content-hash",
        original_filename="image.png",
        content_type="image/png",
        file_size_bytes=100,
        s3_base_url="https://objects.example.test",
        files_metadata={"original": {"s3_key": "user/hash/embed/original.bin"}},
        aes_nonce="nonce",
        vault_wrapped_aes_key="vault:v1:key",
        created_at=1,
    )

    with pytest.raises(HTTPException, match="outbox unavailable"):
        asyncio.run(internal_api.store_upload_record(payload, FakeDirectus(), FailingS3()))

    assert events == [("replication", "user/hash/embed/original.bin")]


# contract-test: direct surface=rest_api assertions=storage.failover.health-reconciled,storage.replication.active-write-durable-outbox
def test_upload_record_trusts_upload_service_active_regions(monkeypatch) -> None:
    try:
        from backend.core.api.app.routes import internal_api
    except ImportError as exc:
        pytest.skip(f"Backend dependencies not installed: {exc}")
    monkeypatch.setenv("S3_REGIONS", "nbg1,fsn1,hel1")

    class FakeDirectus:
        created = None

        async def create_item(self, collection, record):
            assert collection == "upload_files"
            self.created = dict(record)

        async def get_items(self, collection, **_kwargs):
            assert collection == "directus_users"
            return []

        async def update_user(self, *_args, **_kwargs):
            return None

    class FailingS3:
        async def persist_external_upload_replication(self, **_kwargs):
            raise AssertionError("store-record must not re-head an already-journaled upload")

    object_key = "user/hash/embed/original.bin"
    directus = FakeDirectus()
    payload = internal_api.UploadStoreRecordRequest(
        embed_id="embed-id",
        user_id="user-id",
        content_hash="a" * 64,
        original_filename="image.png",
        content_type="image/png",
        file_size_bytes=100,
        s3_base_url="https://dev-openmates-chatfiles-fsn1.example.test",
        files_metadata={"original": {"s3_key": object_key}},
        aes_nonce="nonce",
        vault_wrapped_aes_key="vault:v1:key",
        created_at=1,
        storage_active_regions={object_key: "fsn1"},
    )

    result = asyncio.run(internal_api.store_upload_record(payload, directus, FailingS3()))

    assert result == {"status": "success", "embed_id": "embed-id"}
    assert directus.created is not None
    assert "storage_active_regions" not in directus.created
    assert directus.created["files_metadata"]["original"]["active_region"] == "fsn1"


# contract-test: direct surface=rest_api assertions=storage.failover.health-reconciled,storage.replication.active-write-durable-outbox
def test_upload_record_rejects_mismatched_active_region_metadata(monkeypatch) -> None:
    from fastapi import HTTPException
    try:
        from backend.core.api.app.routes import internal_api
    except ImportError as exc:
        pytest.skip(f"Backend dependencies not installed: {exc}")
    monkeypatch.setenv("S3_REGIONS", "nbg1,fsn1,hel1")

    class FakeDirectus:
        async def create_item(self, *_args, **_kwargs):
            raise AssertionError("record should not persist")

    class FailingS3:
        async def persist_external_upload_replication(self, **_kwargs):
            raise AssertionError("already-journaled upload should not re-head")

    object_key = "user/hash/embed/original.bin"
    payload = internal_api.UploadStoreRecordRequest(
        embed_id="embed-id",
        user_id="user-id",
        content_hash="a" * 64,
        original_filename="image.png",
        content_type="image/png",
        file_size_bytes=100,
        s3_base_url="https://dev-openmates-chatfiles-fsn1.example.test",
        files_metadata={"original": {"s3_key": object_key, "active_region": "nbg1"}},
        aes_nonce="nonce",
        vault_wrapped_aes_key="vault:v1:key",
        created_at=1,
        storage_active_regions={object_key: "fsn1"},
    )

    with pytest.raises(HTTPException, match="active region does not match"):
        asyncio.run(internal_api.store_upload_record(payload, FakeDirectus(), FailingS3()))
