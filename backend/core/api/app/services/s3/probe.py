"""Pure regional object-storage probe helpers.

Scheduled workers and deterministic audits both need a small data-plane proof
that does not import Celery or task wiring. The helper writes only a temporary
zero-byte object with checksum metadata, verifies it through S3 metadata, and
always attempts cleanup after a successful write. It never logs credentials,
bucket names, object keys, or private object metadata.
"""

from __future__ import annotations

from typing import Any


EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
SHA256_METADATA_KEY = "openmates-sha256"


def probe_region_data_plane(client: Any, bucket: str, object_key: str) -> None:
    """Verify regional S3 put/head/delete semantics and clean up the probe."""
    written = False
    try:
        client.head_bucket(Bucket=bucket)
        client.put_object(
            Bucket=bucket,
            Key=object_key,
            Body=b"",
            Metadata={SHA256_METADATA_KEY: EMPTY_SHA256},
        )
        written = True
        response = client.head_object(Bucket=bucket, Key=object_key)
        if int(response.get("ContentLength", -1)) != 0:
            raise RuntimeError("Regional storage probe object size mismatch")
    finally:
        if written:
            client.delete_object(Bucket=bucket, Key=object_key)
