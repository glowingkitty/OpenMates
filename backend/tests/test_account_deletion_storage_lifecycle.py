"""Account deletion storage lifecycle contract tests.

Account deletion inventories non-regulated profile, chatfile, and archive
objects before deleting content or owner rows. Durable regional tombstones then
outlive the account and prevent replica repair from resurrecting ciphertext.
Contract: architecture.storage-lifecycle.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path

import pytest

from backend.core.api.app.services import storage_reference_service


REPO_ROOT = Path(__file__).resolve().parents[2]


class FakeDirectus:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self.get_items_calls: list[tuple[str, dict[str, object]]] = []
        self.chats = [{"id": "chat-1", "hashed_user_id": "hashed-user-1", "hashed_team_id": None,
                       "storage_state": "hot", "archive_version": 1}]

    async def get_user_fields_direct(self, _user_id: str, _fields: list[str]) -> dict:
        return {"id": "user-1", "profile_image_s3_key": "profiles/user-1.enc"}

    async def get_items(self, collection: str, **kwargs: object) -> list[dict]:
        self.get_items_calls.append((collection, kwargs))
        if collection == "chats":
            return self.chats
        rows = {
            "embeds": [
                {
                    "id": "embed-1",
                    "embed_id": "embed-identity-1",
                    "hashed_embed_id": hashlib.sha256(b"embed-identity-1").hexdigest(),
                    "hashed_chat_id": hashlib.sha256(b"chat-1").hexdigest(),
                    "hashed_user_id": "hashed-user-1",
                    "s3_file_keys": [{"bucket": "chatfiles", "key": "files/embed.enc"}],
                }
            ],
            "upload_files": [
                {
                    "id": "upload-1",
                    "user_id": "user-1",
                    "files_metadata": {
                        "original": {"s3_key": "files/upload.enc"},
                    },
                }
            ],
            "embed_diffs": [
                {"id": "diff-1", "embed_id": "embed-identity-1", "hashed_user_id": "hashed-user-1",
                 "hashed_team_id": None, "archive_state": "copied", "archive_object_key": "embed-versions/one.json"}
            ],
            "embed_keys": [],
            "project_items": [],
            "chat_message_archive_pages": [
                {"id": "page-1", "object_key": "message-pages/one.json.gz", "large_objects": [
                    {"object_key": "message-pages/large.json"}
                ]}
            ],
            "chat_message_archive_segments": [{"id": "segment-1"}],
            "chat_recovery_outputs": [
                {"id": "recovery-1", "payload_storage": "s3", "payload_s3_key": "chat-recovery/one.json"}
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
        ("chatfiles", "embed-versions/one.json"),
        ("cold_archives", "message-pages/one.json.gz"),
        ("cold_archives", "message-pages/large.json"),
        ("cold_archives", "chat-recovery/one.json"),
        ("usage_archives", "usage/archive-1.gz"),
        ("task_archives", "tasks/archive-1.gz"),
        ("workspace_history_archives", "workspace/archive-1.json"),
        ("cold_archives", "cold/chat-1/part-1.json.gz"),
    }
    assert all("user_id" not in row for row in directus.created)
    archive_filters = {
        collection: kwargs["params"]["filter"]
        for collection, kwargs in directus.get_items_calls
        if collection
        in {
            "usage_monthly_chat_summaries",
            "usage_monthly_app_summaries",
            "usage_monthly_api_key_summaries",
            "user_task_archives",
        }
        and "filter" in kwargs["params"]
    }
    assert archive_filters == {
        "usage_monthly_chat_summaries": {
            "user_id_hash": {"_eq": "hashed-user-1"}
        },
        "usage_monthly_app_summaries": {
            "user_id_hash": {"_eq": "hashed-user-1"}
        },
        "usage_monthly_api_key_summaries": {
            "user_id_hash": {"_eq": "hashed-user-1"}
        },
        "user_task_archives": {"hashed_user_id": {"_eq": "hashed-user-1"}},
    }


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


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative
@pytest.mark.anyio
async def test_explicit_chat_deletion_fences_archive_publication() -> None:
    directus = FakeDirectus()
    assert await storage_reference_service.fence_chat_for_deletion(
        directus_service=directus, chat_id="chat-1",
    ) is True
    assert directus.chats[0]["storage_state"] == "deleting"
    assert directus.chats[0]["archive_version"] == 2

    directus.chats[0]["storage_state"] = "archiving"
    with pytest.raises(RuntimeError, match="transition"):
        await storage_reference_service.fence_chat_for_deletion(
            directus_service=directus, chat_id="chat-1",
        )


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative
@pytest.mark.anyio
async def test_chat_deletion_waits_for_archiver_lease_before_reference_removal() -> None:
    directus = FakeDirectus()

    async def segments(collection: str, **_kwargs):
        if collection == "chat_message_archive_segments":
            return [{"id": "segment-1", "state": "copying", "lease_until": 200}]
        return []

    directus.get_items = segments
    now = datetime.fromtimestamp(100, tz=timezone.utc)
    with pytest.raises(RuntimeError, match="active or settling"):
        await storage_reference_service.assert_no_active_chat_archive_writer_leases(
            directus_service=directus, chat_id="chat-1", now=now,
        )
    with pytest.raises(RuntimeError, match="active or settling"):
        await storage_reference_service.assert_no_active_chat_archive_writer_leases(
            directus_service=directus, chat_id="chat-1",
            now=datetime.fromtimestamp(289, tz=timezone.utc),
        )
    await storage_reference_service.assert_no_active_chat_archive_writer_leases(
        directus_service=directus, chat_id="chat-1",
        now=datetime.fromtimestamp(290, tz=timezone.utc),
    )


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative
@pytest.mark.anyio
async def test_account_fence_waits_for_active_archive_writer_before_inventory() -> None:
    directus = FakeDirectus()
    original_get_items = directus.get_items

    async def rows(collection: str, **kwargs):
        if collection == "chat_message_archive_segments":
            return [{"id": "segment-1", "state": "copying", "lease_until": 4_102_444_800}]
        return await original_get_items(collection, **kwargs)

    directus.get_items = rows
    with pytest.raises(RuntimeError, match="active or settling"):
        await storage_reference_service.fence_account_chats_for_deletion(
            directus_service=directus, user_id_hash="hashed-user-1",
        )
    assert directus.chats[0]["storage_state"] == "deleting"


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

    reference_preflight = source.index("await assert_no_surviving_account_project_references(")
    owner_preflight = source.index("await load_account_deletable_embed_rows(")
    recovery_preflight = source.index("await assert_no_pending_team_account_recovery(")
    authentication_removal = source.index("# ===== PHASE 1: Authentication Data")
    fence_call = source.index("await fence_account_chats_for_deletion(")
    inventory_call = source.index("await persist_account_storage_tombstones(")
    message_delete = source.index("await delete_account_personal_content(", inventory_call)
    storage_row_delete = source.index(
        "await delete_account_storage_reference_rows(", inventory_call
    )
    activation_call = source.index("await activate_storage_tombstones(", inventory_call)
    user_delete = source.index("await directus_service.delete_user(", inventory_call)

    assert fence_call < inventory_call < message_delete < user_delete
    assert inventory_call < storage_row_delete < activation_call < user_delete
    assert reference_preflight < owner_preflight < recovery_preflight < authentication_removal


# contract-test: supporting surface=rest_api assertions=storage.deletion.global-authoritative
def test_chat_delete_task_prepares_archive_authority_before_content_removal() -> None:
    source = (REPO_ROOT / "backend/core/api/app/tasks/persistence_tasks.py").read_text(encoding="utf-8")
    task = source.split("async def _async_persist_delete_chat(", 1)[1].split("@app.task(", 1)[0]
    fence = task.index("await fence_chat_for_deletion(")
    leases = task.index("await assert_no_active_chat_archive_writer_leases(")
    prepare = task.index("archive_tombstones = await persist_chat_message_archive_tombstones(")
    messages = task.index("await directus_service.chat.delete_all_messages_for_chat(")
    row_delete = task.index("await delete_chat_message_archive_rows(")
    activate = task.index("await activate_storage_tombstones(")
    chat_delete = task.index("await directus_service.chat.persist_delete_chat(")
    assert fence < leases < prepare < messages < row_delete < activate < chat_delete


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
