"""S3 outage resilience contracts.

These tests keep remote object storage optional for core API and text-AI
availability while requiring a stable fail-before-cost error for operations
whose output must be stored durably. Contract: architecture.storage-resilience.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from backend.shared.python_utils.storage_availability import (
    STORAGE_UNAVAILABLE_CODE,
    require_storage_available,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class _StorageProbe:
    def __init__(self, status: str) -> None:
        self.status = status
        self.calls = 0

    async def check_availability(self) -> str:
        self.calls += 1
        return self.status


# contract-test: direct surface=rest_api assertions=storage-resilience.operations.fail-before-cost,storage-resilience.content.privacy-boundary
@pytest.mark.asyncio
async def test_storage_guard_returns_stable_retryable_503() -> None:
    storage = _StorageProbe("unavailable")

    with pytest.raises(HTTPException) as exc_info:
        await require_storage_available(storage)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == {
        "code": STORAGE_UNAVAILABLE_CODE,
        "retryable": True,
    }
    assert storage.calls == 1


# contract-test: direct surface=rest_api assertions=storage-resilience.operations.fail-before-cost
@pytest.mark.asyncio
async def test_storage_guard_allows_available_storage() -> None:
    storage = _StorageProbe("available")

    await require_storage_available(storage)

    assert storage.calls == 1


# contract-test: direct surface=rest_api assertions=storage-resilience.operations.fail-before-cost,storage-resilience.content.privacy-boundary
def test_uninitialized_storage_read_uses_stable_retryable_error() -> None:
    source = (
        REPOSITORY_ROOT / "backend/core/api/app/services/s3/service.py"
    ).read_text()
    get_file_source = source[source.index("async def get_file("):source.index("async def get_file_stream(")]

    assert "raise storage_unavailable_error()" in get_file_source


# contract-test: direct surface=rest_api assertions=storage-resilience.core.s3-is-noncritical
def test_api_lifespan_does_not_await_remote_s3_initialization() -> None:
    source = (REPOSITORY_ROOT / "backend/core/api/main.py").read_text()

    assert "await app.state.s3_service.initialize()" not in source
    assert "S3_RECONCILIATION_RETRY_SECONDS" in source
    assert "await asyncio.sleep(S3_RECONCILIATION_RETRY_SECONDS)" in source


# contract-test: direct surface=rest_api assertions=storage-resilience.core.s3-is-noncritical
def test_bucket_reconciliation_surfaces_failures_for_background_retry() -> None:
    source = (
        REPOSITORY_ROOT / "backend/core/api/app/services/s3/service.py"
    ).read_text()
    reconciliation_source = source[
        source.index("async def _initialize_buckets("):source.index("def get_s3_url(")
    ]

    assert 'raise RuntimeError("object_storage_reconciliation_failed")' in reconciliation_source


# contract-test: direct surface=rest_api assertions=storage-resilience.core.s3-is-noncritical
def test_storage_task_initialization_is_explicit_and_core_first() -> None:
    source = (
        REPOSITORY_ROOT / "backend/shared/python_utils/storage_availability.py"
    ).read_text()

    assert "await task.initialize_core_services()" in source
    assert "initialize(configure_buckets=False)" in source


# contract-test: supporting surface=rest_api assertions=storage-resilience.core.s3-is-noncritical
def test_text_ai_task_has_no_s3_dependency() -> None:
    source = (
        REPOSITORY_ROOT / "backend/apps/ai/tasks/ask_skill_task.py"
    ).read_text()

    assert "S3UploadService" not in source
    assert "s3_service" not in source


# contract-test: direct surface=rest_api assertions=storage-resilience.operations.fail-before-cost
def test_remotion_render_guards_storage_before_e2b_and_billing() -> None:
    source = (
        REPOSITORY_ROOT / "backend/apps/videos/tasks/render_remotion_task.py"
    ).read_text()
    render_source = source[source.index("async def _async_render_remotion("):]

    guard_position = render_source.index("await require_storage_available(")
    render_position = render_source.index("render_remotion_in_e2b(")
    charge_position = render_source.index("await _charge_remotion_render_credits(")
    assert "await task.initialize_core_services()" in render_source
    assert "await initialize_task_storage(task)" in render_source
    assert guard_position < render_position < charge_position
