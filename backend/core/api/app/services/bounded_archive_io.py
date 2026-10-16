"""Private regional ciphertext I/O with explicit read budgets and integrity.

Callers authorize resource access before reading. This module never accepts a
client-supplied object key or decrypts client ciphertext.
"""
from __future__ import annotations

import hashlib
from typing import Any, Iterable

from backend.core.api.app.services.s3.config import get_bucket_name
from backend.shared.python_utils.object_storage_regions import resolve_regional_bucket_name


class ArchiveIntegrityError(RuntimeError):
    """A bounded archive cannot be verified or safely returned."""


async def put_verified_bytes(
    s3: Any,
    key: str,
    content: bytes,
    *,
    bucket_key: str = "cold_archives",
    content_type: str = "application/octet-stream",
    metadata: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Copy immutable ciphertext and verify every configured regional copy."""
    regions = sorted(s3.region_clients)
    if not regions or not content:
        raise ArchiveIntegrityError("ARCHIVE_NO_REGIONS_OR_EMPTY_PAYLOAD")
    checksum = hashlib.sha256(content).hexdigest()
    for region in regions:
        await s3.upload_file(
            bucket_key=bucket_key, file_key=key, content=content,
            content_type=content_type, metadata=metadata or {}, region=region,
        )
        if not await s3.verify_regional_object(
            bucket_key=bucket_key, object_key=key, region=region, checksum=checksum,
        ):
            raise ArchiveIntegrityError("ARCHIVE_REGION_CHECKSUM_MISMATCH")
    return {"checksum": checksum, "size_bytes": len(content), "verified_regions": regions}


async def read_verified_bytes(
    s3: Any,
    key: str,
    *,
    checksum: str,
    size_bytes: int,
    regions: Iterable[str],
    max_bytes: int,
    bucket_key: str = "cold_archives",
) -> bytes:
    """Read one admitted object, enforcing size both before and during transfer."""
    if not 0 < size_bytes <= max_bytes or len(checksum) != 64:
        raise ArchiveIntegrityError("ARCHIVE_READ_BUDGET_OR_METADATA_INVALID")
    allowed = tuple(sorted(set(regions)))
    if not allowed:
        raise ArchiveIntegrityError("ARCHIVE_NO_VERIFIED_REGIONS")
    chunk_size = min(64 * 1024, max_bytes)
    if hasattr(s3, "get_replicated_file_stream"):
        stream = s3.get_replicated_file_stream(
            bucket_key=bucket_key, object_key=key, regions=allowed, chunk_size=chunk_size,
        )
    else:
        region = next((r for r in allowed if r in s3.region_clients), None)
        if region is None:
            raise ArchiveIntegrityError("ARCHIVE_NO_AVAILABLE_REGION")
        bucket = resolve_regional_bucket_name(get_bucket_name(bucket_key, s3.environment), region)
        stream = s3.get_file_stream(bucket, key, chunk_size=chunk_size)
    result = bytearray()
    try:
        async for chunk in stream:
            if len(result) + len(chunk) > min(size_bytes, max_bytes):
                raise ArchiveIntegrityError("ARCHIVE_STREAM_EXCEEDS_DECLARED_SIZE")
            result.extend(chunk)
    finally:
        if hasattr(stream, "aclose"):
            await stream.aclose()
    if len(result) != size_bytes or hashlib.sha256(result).hexdigest() != checksum:
        raise ArchiveIntegrityError("ARCHIVE_OBJECT_INTEGRITY_FAILED")
    return bytes(result)
