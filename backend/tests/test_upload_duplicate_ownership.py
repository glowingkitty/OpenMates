"""Tests for upload deduplication ownership validation.

Purpose: prevent upload_files dedup records from reusing embeds owned by a
legacy/non-canonical user hash.
Security: dedup must not bypass store_embed ownership checks.
Architecture: upload service asks core API to validate Directus rows.
Run: python3 -m pytest backend/tests/test_upload_duplicate_ownership.py -q
"""

import hashlib

import pytest

from backend.core.api.app.routes.internal_api import UploadCheckDuplicateRequest, check_upload_duplicate


class FakeDirectusService:
    def __init__(self, embed_owner_hash: str, s3_key: str = "user/hash/embed-1/20260720_full.bin"):
        self.embed_owner_hash = embed_owner_hash
        self.s3_key = s3_key
        self.deleted_items: list[tuple[str, str]] = []

    async def get_items(self, collection: str, params: dict):
        if collection == "upload_files":
            return [
                {
                    "id": "upload-row-1",
                    "embed_id": "embed-1",
                    "files_metadata": {"full": {"s3_key": self.s3_key}},
                }
            ]
        if collection == "embeds":
            return [{"embed_id": "embed-1", "status": "finished", "hashed_user_id": self.embed_owner_hash}]
        raise AssertionError(f"unexpected collection {collection}")

    async def delete_item(self, collection: str, item_id: str):
        self.deleted_items.append((collection, item_id))


@pytest.mark.anyio
async def test_check_upload_duplicate_discards_wrong_owner_embed():
    directus = FakeDirectusService(embed_owner_hash=hashlib.sha256(b"legacy-email-hash").hexdigest())

    result = await check_upload_duplicate(
        UploadCheckDuplicateRequest(user_id="user-uuid-1", content_hash="hash-1"),
        directus_service=directus,
    )

    assert result.duplicate is False
    assert result.record is None
    assert directus.deleted_items == [("upload_files", "upload-row-1")]


@pytest.mark.anyio
async def test_check_upload_duplicate_accepts_canonical_owner_embed():
    user_id = "user-uuid-1"
    directus = FakeDirectusService(embed_owner_hash=hashlib.sha256(user_id.encode()).hexdigest())

    result = await check_upload_duplicate(
        UploadCheckDuplicateRequest(user_id=user_id, content_hash="hash-1"),
        directus_service=directus,
    )

    assert result.duplicate is True
    assert result.record == {
        "id": "upload-row-1",
        "embed_id": "embed-1",
        "files_metadata": {"full": {"s3_key": "user/hash/embed-1/20260720_full.bin"}},
    }
    assert directus.deleted_items == []


@pytest.mark.anyio
async def test_check_upload_duplicate_discards_legacy_unscoped_s3_keys():
    user_id = "user-uuid-1"
    directus = FakeDirectusService(
        embed_owner_hash=hashlib.sha256(user_id.encode()).hexdigest(),
        s3_key="user/hash/20260720_full.bin",
    )

    result = await check_upload_duplicate(
        UploadCheckDuplicateRequest(user_id=user_id, content_hash="hash-1"),
        directus_service=directus,
    )

    assert result.duplicate is False
    assert result.record is None
    assert directus.deleted_items == [("upload_files", "upload-row-1")]
