"""Account deletion storage lifecycle contract tests.

Account deletion inventories non-regulated profile, chatfile, and archive
objects before deleting content or owner rows. Durable regional tombstones then
outlive the account and prevent replica repair from resurrecting ciphertext.
Contract: architecture.storage-lifecycle.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.core.api.app.services import storage_reference_service


REPO_ROOT = Path(__file__).resolve().parents[2]


class FakeDirectus:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self.chats = [{"id": "chat-1", "storage_state": "hot", "archive_version": 1}]

    async def get_user_fields_direct(self, _user_id: str, _fields: list[str]) -> dict:
        return {"id": "user-1", "profile_image_s3_key": "profiles/user-1.enc"}

    async def get_items(self, collection: str, **_kwargs: object) -> list[dict]:
        if collection == "chats":
            return self.chats
        rows = {
            "embeds": [
                {
                    "id": "embed-1",
                    "s3_file_keys": [{"bucket": "chatfiles", "key": "files/embed.enc"}],
                }
            ],
            "upload_files": [
                {
                    "id": "upload-1",
                    "files_metadata": {
                        "original": {"s3_key": "files/upload.enc"},
                    },
                }
            ],
            "usage_monthly_chat_summaries": [
                {"id": "usage-1", "archive_s3_key": "usage/archive-1.gz"}
            ],
            "usage_monthly_app_summaries": [
                {"id": "hot-summary-without-archive", "archive_s3_key": None}
            ],
            "usage_monthly_api_key_summaries": [],
            "user_task_archives": [
                {"id": "task-archive-1", "archive_s3_key": "tasks/archive-1.gz"}
            ],
            "workspace_change_archives": [
                {
                    "id": "workspace-archive-1",
                    "s3_bucket_key": "workspace_history_archives",
                    "s3_object_key": "workspace/archive-1.json",
                }
            ],
            "cold_archive_manifests": [
                {
                    "id": "cold-manifest-1",
                    "archive_id": "cold-archive-1",
                    "file_references": [
                        {"logical_bucket": "chatfiles", "object_key": "files/embed.enc"}
                    ],
                }
            ],
            "cold_archive_parts": [
                {
                    "id": "cold-part-1",
                    "archive_id": "cold-archive-1",
                    "logical_bucket": "cold_archives",
                    "object_key": "cold/chat-1/part-1.json.gz",
                }
            ],
            "directus_users": [
                {"id": "user-1", "profile_image_s3_key": "profiles/user-1.enc"}
            ],
        }
        return rows[collection]

    async def update_item_if_version(self, collection, item_id, data, expected_version, **_kwargs):
        assert collection == "chats"
        chat = next(row for row in self.chats if row["id"] == item_id)
        if chat["archive_version"] != expected_version:
            return None
        chat.update(data)
        return dict(chat)

    async def create_item(self, collection: str, payload: dict, **_kwargs: object):
        assert collection == "storage_deletion_tombstones"
        self.created.append(payload)
        return True, {"id": f"tombstone-{len(self.created)}", **payload}

# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative,storage.files.reference-safe-single-copy,storage.privacy.ciphertext-boundary
@pytest.mark.anyio
async def test_account_inventory_persists_every_non_regulated_object_before_owner_removal() -> None:
    directus = FakeDirectus()

    persisted = await storage_reference_service.persist_account_storage_tombstones(
        directus_service=directus,
        user_id="user-1",
        user_id_hash="hashed-user-1",
        regions=("nbg1", "fsn1", "hel1"),
        now=datetime(2026, 8, 26, tzinfo=timezone.utc),
    )

    assert {
        (row["logical_bucket"], row["object_key"])
        for row in persisted
    } == {
        ("profile_images_private", "profiles/user-1.enc"),
        ("chatfiles", "files/embed.enc"),
        ("chatfiles", "files/upload.enc"),
        ("usage_archives", "usage/archive-1.gz"),
        ("task_archives", "tasks/archive-1.gz"),
        ("workspace_history_archives", "workspace/archive-1.json"),
        ("cold_archives", "cold/chat-1/part-1.json.gz"),
    }
    assert all("user_id" not in row for row in directus.created)


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative
@pytest.mark.anyio
async def test_account_deletion_fences_chats_before_inventory() -> None:
    directus = FakeDirectus()

    count = await storage_reference_service.fence_account_chats_for_deletion(
        directus_service=directus,
        user_id_hash="hashed-user-1",
    )

    assert count == 1
    assert directus.chats[0]["storage_state"] == "deleting"
    assert directus.chats[0]["archive_version"] == 2


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative,storage.privacy.ciphertext-boundary
@pytest.mark.anyio
async def test_account_inventory_decrypts_and_tombstones_legacy_profile_object() -> None:
    directus = FakeDirectus()

    async def legacy_user(_user_id: str, _fields: list[str]) -> dict:
        return {
            "id": "user-1",
            "profile_image_s3_key": None,
            "encrypted_profileimage_url": "vault:v1:legacy-url",
            "vault_key_id": "vault-user-1",
        }

    directus.get_user_fields_direct = legacy_user

    class FakeEncryption:
        async def decrypt_with_user_key(self, _ciphertext: str, _key_id: str) -> str:
            return "https://dev-openmates-profile-images.nbg1.your-objectstorage.com/legacy/avatar.webp"

    persisted = await storage_reference_service.persist_account_storage_tombstones(
        directus_service=directus,
        user_id="user-1",
        user_id_hash="hashed-user-1",
        regions=("nbg1", "fsn1", "hel1"),
        now=datetime(2026, 8, 26, tzinfo=timezone.utc),
        encryption_service=FakeEncryption(),
    )

    legacy = next(row for row in persisted if row["logical_bucket"] == "profile_images_legacy")
    assert legacy["object_key"] == "legacy/avatar.webp"
    assert legacy["purge_states"] == {1: {"nbg1": "pending"}}


# contract-test: supporting surface=rest_api assertions=storage.deletion.global-authoritative
def test_account_task_persists_storage_authority_before_bulk_content_deletion() -> None:
    source = (
        REPO_ROOT / "backend/core/api/app/tasks/user_cache_tasks.py"
    ).read_text(encoding="utf-8")

    fence_call = source.index("await fence_account_chats_for_deletion(")
    inventory_call = source.index("await persist_account_storage_tombstones(")
    message_delete = source.index('bulk_delete_items("messages"', inventory_call)
    storage_row_delete = source.index(
        "await delete_account_storage_reference_rows(", inventory_call
    )
    activation_call = source.index("await activate_storage_tombstones(", inventory_call)
    user_delete = source.index("await directus_service.delete_user(", inventory_call)

    assert fence_call < inventory_call < message_delete < user_delete
    assert inventory_call < storage_row_delete < activation_call < user_delete


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative
@pytest.mark.anyio
async def test_failed_storage_reference_row_delete_stops_account_finalization() -> None:
    class FailingDirectus:
        async def get_items(self, collection: str, **_kwargs: object) -> list[dict]:
            if collection == "upload_files":
                return [{"id": "upload-row"}]
            return []

        async def bulk_delete_items(self, _collection: str, _item_ids: list[str]) -> bool:
            return False

    with pytest.raises(RuntimeError, match="upload_files"):
        await storage_reference_service.delete_account_storage_reference_rows(
            directus_service=FailingDirectus(),
            user_id="user-1",
            user_id_hash="hashed-user-1",
        )


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative,storage.privacy.ciphertext-boundary
@pytest.mark.anyio
async def test_account_deletion_removes_persisted_export_jobs_and_parts() -> None:
    class DirectusWithExportRows:
        def __init__(self) -> None:
            self.rows = {
                "account_export_jobs": [{"id": "job-1"}],
                "account_export_parts": [{"id": "part-1"}, {"id": "part-2"}],
            }

        async def get_items(self, collection: str, **_kwargs: object) -> list[dict]:
            return list(self.rows.get(collection, []))

        async def bulk_delete_items(self, collection: str, item_ids: list[str]) -> bool:
            self.rows[collection] = [row for row in self.rows[collection] if row["id"] not in item_ids]
            return True

    directus = DirectusWithExportRows()

    deleted = await storage_reference_service.delete_account_storage_reference_rows(
        directus_service=directus,
        user_id="user-1",
        user_id_hash="hashed-user-1",
    )

    assert deleted["account_export_jobs"] == 1
    assert deleted["account_export_parts"] == 2
    assert directus.rows["account_export_jobs"] == []
    assert directus.rows["account_export_parts"] == []
