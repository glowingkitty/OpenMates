"""Pure helpers for upload S3 object key construction.

Purpose: keep encrypted upload object keys unique and testable.
Security: each upload has a fresh AES key, so S3 keys must not collide.
Architecture: content_hash remains available for dedup; embed_id scopes storage.
Run: python3 -m pytest backend/tests/test_upload_s3_keys.py -q
"""


def upload_s3_prefix(user_id: str, content_hash: str, embed_id: str) -> str:
    return f"{user_id}/{content_hash}/{embed_id}"
