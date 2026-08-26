"""Shared object-storage availability guard.

Storage-backed work uses this guard before paid provider execution or credit
charging. The public failure is stable and retryable and never includes provider,
bucket, object, credential, endpoint, or user details.
"""

from __future__ import annotations

from typing import Any, Protocol

from fastapi import HTTPException


STORAGE_AVAILABLE = "available"
STORAGE_UNAVAILABLE_CODE = "storage_temporarily_unavailable"


class StorageAvailabilityProbe(Protocol):
    async def check_availability(self) -> str: ...


def storage_unavailable_error() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={"code": STORAGE_UNAVAILABLE_CODE, "retryable": True},
    )


def is_storage_unavailable_error(error: BaseException) -> bool:
    if not isinstance(error, HTTPException) or error.status_code != 503:
        return False
    return (
        isinstance(error.detail, dict)
        and error.detail.get("code") == STORAGE_UNAVAILABLE_CODE
    )


async def require_storage_available(storage: StorageAvailabilityProbe) -> None:
    if await storage.check_availability() != STORAGE_AVAILABLE:
        raise storage_unavailable_error()


async def initialize_task_storage(task: Any) -> StorageAvailabilityProbe:
    """Initialize storage explicitly after the task's non-storage core services."""
    if task._secrets_manager is None:
        await task.initialize_core_services()
    if task._s3_service is None:
        from backend.core.api.app.services.s3.service import S3UploadService

        task._s3_service = S3UploadService(
            secrets_manager=task._secrets_manager,
            directus_service=task._directus_service,
        )
        await task._s3_service.initialize(configure_buckets=False)
    return task._s3_service
