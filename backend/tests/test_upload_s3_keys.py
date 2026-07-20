"""Tests for upload S3 object key construction.

Purpose: prevent concurrent same-file uploads from sharing encrypted S3 keys.
Security: each upload uses a unique AES key, so object overwrites break decrypt.
Architecture: upload records keep content_hash for dedup and embed_id for storage.
Run: python3 -m pytest backend/tests/test_upload_s3_keys.py -q
"""

from backend.upload.s3_keys import upload_s3_prefix


def test_upload_s3_prefix_separates_same_hash_uploads_by_embed_id() -> None:
    user_id = "user-uuid-1"
    content_hash = "same-file-hash"

    first = upload_s3_prefix(user_id, content_hash, "embed-1")
    second = upload_s3_prefix(user_id, content_hash, "embed-2")

    assert first == "user-uuid-1/same-file-hash/embed-1"
    assert second == "user-uuid-1/same-file-hash/embed-2"
    assert first != second
