"""Cold chat archive service contract tests.

Complete client-encrypted chat graphs become immutable regional archive parts
only after every configured region verifies the same checksum. Hot content is
never removed after a partial archive write, and reads do not restore rows.
Contract: architecture.storage-lifecycle.
"""

from __future__ import annotations

import asyncio
import hashlib
import gzip
import json
from pathlib import Path

import pytest

from backend.core.api.app.services.cold_archive_service import (
    ARCHIVE_LEASE_SECONDS,
    ARCHIVE_COLLECTIONS_BY_CHAT_ID,
    COLD_ARCHIVE_BUCKET_KEY,
    ColdArchiveConflictError,
    ColdArchiveError,
    ColdArchiveService,
    chat_is_archive_eligible,
    dispatch_due_cold_chat_archives,
)


class FakeDirectus:
    def __init__(self) -> None:
        self.collections = {
            "chats": [{"id": "chat-1", "hashed_user_id": "owner-hash", "updated_at": 1, "pinned": False, "is_shared": False, "share_with_community": False}],
            "messages": [{"id": "message-1", "chat_id": "chat-1", "encrypted_content": "cipher-message"}],
            "drafts": [{"id": "draft-1", "chat_id": "chat-1", "encrypted_content": "cipher-draft"}],
            "embeds": [{"id": "embed-1", "embed_id": "embed-1", "hashed_chat_id": hashlib.sha256(b"chat-1").hexdigest(), "encrypted_content": "cipher-embed", "s3_file_keys": [{"bucket": "chatfiles", "key": "files/shared.enc"}]}],
            "embed_keys": [
                {"id": "embed-key-1", "hashed_embed_id": hashlib.sha256(b"embed-1").hexdigest(), "hashed_chat_id": hashlib.sha256(b"chat-1").hexdigest(), "key_type": "chat", "encrypted_key": "cipher-key"},
                {"id": "embed-key-master", "hashed_embed_id": hashlib.sha256(b"embed-1").hexdigest(), "hashed_chat_id": None, "key_type": "master", "encrypted_key": "cipher-master"},
                {"id": "embed-key-foreign", "hashed_embed_id": hashlib.sha256(b"embed-1").hexdigest(), "hashed_chat_id": hashlib.sha256(b"other-chat").hexdigest(), "key_type": "chat", "encrypted_key": "cipher-foreign"},
            ],
            "chat_key_wrappers": [{"id": "wrapper-1", "hashed_chat_id": hashlib.sha256(b"chat-1").hexdigest(), "wrapped_key": "cipher-wrapper"}],
            "chat_compression_checkpoints": [{"id": "checkpoint-1", "chat_id": "chat-1", "encrypted_summary": "cipher-summary"}],
            "code_run_outputs": [{"id": "code-1", "chat_id": "chat-1", "encrypted_output": "cipher-code"}],
            "notebook_run_outputs": [{"id": "notebook-1", "chat_id": "chat-1", "encrypted_output": "cipher-notebook"}],
            "message_highlights": [{"id": "highlight-1", "chat_id": "chat-1", "encrypted_annotation": "cipher-highlight"}],
            "cold_archive_manifests": [],
            "cold_archive_parts": [],
            "storage_deletion_tombstones": [],
        }
        self.events: list[tuple[str, str]] = []
        self.created_payloads: list[tuple[str, dict]] = []

    async def get_items(self, collection, params=None, **_kwargs):
        rows = list(self.collections.get(collection, []))
        params = params or {}
        filters = params.get("filter") or {}
        for field, condition in filters.items():
            if isinstance(condition, dict) and "_eq" in condition:
                rows = [row for row in rows if row.get(field) == condition["_eq"]]
            if isinstance(condition, dict) and "_in" in condition:
                rows = [row for row in rows if row.get(field) in condition["_in"]]
        return rows

    async def create_item(self, collection, data, **_kwargs):
        row = {"id": f"{collection}-{len(self.collections[collection]) + 1}", **data}
        self.collections[collection].append(row)
        self.events.append(("create", collection))
        self.created_payloads.append((collection, dict(data)))
        return True, row

    async def update_item(self, collection, item_id, data, **_kwargs):
        row = next((row for row in self.collections[collection] if row.get("id") == item_id), None)
        if row is None:
            return None
        row.update(data)
        self.events.append(("update", collection))
        return dict(row)

    async def update_item_if_version(self, collection, item_id, data, expected_version, **_kwargs):
        row = next((row for row in self.collections[collection] if row.get("id") == item_id), None)
        version_field = _kwargs.get("version_field", "version")
        if row is None or int(row.get(version_field) or 1) != expected_version:
            return None
        row.update(data)
        self.events.append(("update", collection))
        return dict(row)

    async def delete_item(self, collection, item_id, **_kwargs):
        self.collections[collection] = [row for row in self.collections[collection] if row.get("id") != item_id]
        self.events.append(("delete", collection))
        return True


class FakeS3:
    def __init__(self, *, fail_region: str | None = None) -> None:
        self.region_clients = {"nbg1": object(), "fsn1": object(), "hel1": object()}
        self.environment = "development"
        self.fail_region = fail_region
        self.objects: dict[tuple[str, str], bytes] = {}

    async def upload_file(self, *, bucket_key, file_key, content, content_type, metadata, region):
        assert bucket_key == COLD_ARCHIVE_BUCKET_KEY
        assert content_type == "application/gzip"
        if region == self.fail_region:
            raise RuntimeError("regional write failed")
        self.objects[(region, file_key)] = content
        return {"region": region}

    async def verify_regional_object(self, *, bucket_key, object_key, region, checksum):
        content = self.objects.get((region, object_key))
        return bool(content and hashlib.sha256(content).hexdigest() == checksum)

    async def get_file_stream(self, _bucket_name, object_key, *, chunk_size):
        content = self.objects[("nbg1", object_key)]
        for offset in range(0, len(content), chunk_size):
            yield content[offset : offset + chunk_size]


class RegionalFailoverS3(FakeS3):
    def __init__(self) -> None:
        super().__init__()
        self.requested_regions: tuple[str, ...] = ()

    async def get_file_stream(self, _bucket_name, _object_key, *, chunk_size):
        raise AssertionError("archive reads must use regional failover")
        yield b""  # pragma: no cover

    async def get_replicated_file_stream(self, *, bucket_key, object_key, regions, chunk_size):
        self.requested_regions = tuple(regions)
        content = self.objects[("hel1", object_key)]
        for offset in range(0, len(content), chunk_size):
            yield content[offset : offset + chunk_size]


# contract-test: direct surface=rest_api assertions=storage.cold.atomic-eligible-graphs
def test_eligibility_rejects_recent_pinned_shared_and_processing_chats() -> None:
    base = {"updated_at": 1, "pinned": False, "is_shared": False, "share_with_community": False}
    now = 40 * 86_400

    assert chat_is_archive_eligible(base, now_timestamp=now, has_processing_task=False)
    assert not chat_is_archive_eligible({**base, "updated_at": now - 60}, now_timestamp=now, has_processing_task=False)
    assert not chat_is_archive_eligible({**base, "pinned": True}, now_timestamp=now, has_processing_task=False)
    assert not chat_is_archive_eligible({**base, "is_shared": True}, now_timestamp=now, has_processing_task=False)
    assert not chat_is_archive_eligible({**base, "storage_state": "cold"}, now_timestamp=now, has_processing_task=False)
    assert not chat_is_archive_eligible({**base, "storage_state": "deleting"}, now_timestamp=now, has_processing_task=False)
    assert not chat_is_archive_eligible(base, now_timestamp=now, has_processing_task=True)


# contract-test: direct surface=rest_api assertions=storage.cold.atomic-eligible-graphs,storage.files.reference-safe-single-copy
@pytest.mark.asyncio
async def test_complete_graph_verifies_every_region_before_hot_child_deletion() -> None:
    directus = FakeDirectus()
    service = ColdArchiveService(directus_service=directus, s3_service=FakeS3())

    result = await service.archive_chat("chat-1", now_timestamp=40 * 86_400)

    assert result["state"] == "cold"
    assert result["verified_regions"] == ["fsn1", "hel1", "nbg1"]
    assert directus.collections["chats"]
    assert directus.collections["messages"] == []
    assert directus.collections["embeds"] == []
    assert {row["id"] for row in directus.collections["embed_keys"]} == {
        "embed-key-master",
        "embed-key-foreign",
    }
    manifest = directus.collections["cold_archive_manifests"][0]
    assert manifest["file_references"] == [{"logical_bucket": "chatfiles", "object_key": "files/shared.enc"}]
    assert directus.events.index(("create", "cold_archive_manifests")) < directus.events.index(("delete", "messages"))
    created_manifest = next(payload for collection, payload in directus.created_payloads if collection == "cold_archive_manifests")
    assert created_manifest["state"] == "preparing"


# contract-test: direct surface=rest_api assertions=storage.cold.atomic-eligible-graphs
@pytest.mark.asyncio
async def test_degraded_region_leaves_complete_hot_graph_intact() -> None:
    directus = FakeDirectus()
    service = ColdArchiveService(directus_service=directus, s3_service=FakeS3(fail_region="hel1"))

    with pytest.raises(RuntimeError, match="regional write failed"):
        await service.archive_chat("chat-1", now_timestamp=40 * 86_400)

    assert directus.collections["messages"]
    assert directus.collections["embeds"]
    assert directus.collections["cold_archive_manifests"] == []
    assert directus.collections["cold_archive_parts"][0]["regional_states"] == {
        "fsn1": "pending",
        "hel1": "pending",
        "nbg1": "pending",
    }


# contract-test: direct surface=rest_api assertions=storage.cold.discoverable-bounded,storage.cold.rehydrate-on-mutation
@pytest.mark.asyncio
async def test_part_read_streams_without_restoring_hot_rows() -> None:
    directus = FakeDirectus()
    s3 = FakeS3()
    service = ColdArchiveService(directus_service=directus, s3_service=s3)
    manifest = await service.archive_chat("chat-1", now_timestamp=40 * 86_400)
    part = directus.collections["cold_archive_parts"][0]

    chunks = [chunk async for chunk in service.stream_archive_part(manifest=manifest, part=part)]

    assert chunks
    assert directus.collections["messages"] == []


# contract-test: direct surface=rest_api assertions=storage.cold.atomic-eligible-graphs
@pytest.mark.asyncio
async def test_root_archive_contains_complete_sub_chat_tree() -> None:
    directus = FakeDirectus()
    directus.collections["chats"].append(
        {"id": "chat-2", "parent_id": "chat-1", "is_sub_chat": True, "hashed_user_id": "owner-hash", "updated_at": 1, "pinned": False, "is_shared": False}
    )
    directus.collections["messages"].append({"id": "message-2", "chat_id": "chat-2", "encrypted_content": "cipher-sub-chat"})
    s3 = FakeS3()

    await ColdArchiveService(directus_service=directus, s3_service=s3).archive_chat("chat-1", now_timestamp=40 * 86_400)

    archived_chat_ids: set[str] = set()
    for (region, _key), content in s3.objects.items():
        if region != "nbg1":
            continue
        payload = json.loads(gzip.decompress(content))
        archived_chat_ids.update(row["id"] for row in payload["records"].get("chats", []))
    assert archived_chat_ids == {"chat-1", "chat-2"}
    assert directus.collections["messages"] == []


# contract-test: direct surface=rest_api assertions=storage.cold.discoverable-bounded
@pytest.mark.asyncio
async def test_part_read_uses_verified_regional_failover() -> None:
    directus = FakeDirectus()
    s3 = RegionalFailoverS3()
    service = ColdArchiveService(directus_service=directus, s3_service=s3)
    manifest = await service.archive_chat("chat-1", now_timestamp=40 * 86_400)
    part = directus.collections["cold_archive_parts"][0]

    chunks = [chunk async for chunk in service.stream_archive_part(manifest=manifest, part=part)]

    assert chunks
    assert s3.requested_regions == ("fsn1", "hel1", "nbg1")


# contract-test: direct surface=rest_api assertions=storage.cold.atomic-eligible-graphs
@pytest.mark.asyncio
async def test_sweep_dispatches_only_inactive_root_chats() -> None:
    directus = FakeDirectus()
    directus.collections["chats"].extend(
        [
            {"id": "chat-active", "updated_at": 1, "pinned": False, "is_shared": False},
            {"id": "chat-child", "updated_at": 1, "parent_id": "chat-1", "is_sub_chat": True},
        ]
    )

    class Cache:
        async def get_active_ai_task(self, chat_id):
            return "task-1" if chat_id == "chat-active" else None

    dispatched: list[str] = []
    count = await dispatch_due_cold_chat_archives(
        directus_service=directus,
        cache_service=Cache(),
        dispatch=dispatched.append,
        now_timestamp=40 * 86_400,
    )

    assert count == 1
    assert dispatched == ["chat-1"]


# contract-test: direct surface=rest_api assertions=storage.cold.atomic-eligible-graphs
def test_part_rollover_never_duplicates_or_exceeds_limit(monkeypatch) -> None:
    import backend.core.api.app.services.cold_archive_service as archive_module

    monkeypatch.setattr(archive_module, "MAX_ARCHIVE_PART_BYTES", 700)
    graph = {
        "messages": [
            {"id": f"message-{index}", "encrypted_content": hashlib.sha256(str(index).encode()).hexdigest() * 5}
            for index in range(6)
        ]
    }

    parts = ColdArchiveService(directus_service=object(), s3_service=object())._build_parts("archive-1", 1, graph)
    ids = [
        row["id"]
        for part in parts
        for row in json.loads(gzip.decompress(part))["records"].get("messages", [])
    ]

    assert ids == [f"message-{index}" for index in range(6)]
    assert all(len(part) <= 700 for part in parts)


# contract-test: direct surface=rest_api assertions=storage.cold.atomic-eligible-graphs
def test_database_guard_covers_every_mutable_chat_graph_collection() -> None:
    migration = (
        Path(__file__).resolve().parents[1]
        / "core/directus/setup/migrate_storage_replication_indexes.sql"
    ).read_text(encoding="utf-8")

    for collection in (*ARCHIVE_COLLECTIONS_BY_CHAT_ID, "embeds", "embed_keys", "chat_key_wrappers", "chats"):
        assert collection in migration
    assert "storage_state IN ('archiving', 'cold', 'deleting')" in migration
    assert migration.count("FOR SHARE") == 3


# contract-test: direct surface=rest_api assertions=storage.cold.atomic-eligible-graphs
@pytest.mark.asyncio
async def test_concurrent_archive_claim_creates_one_manifest() -> None:
    directus = FakeDirectus()
    service = ColdArchiveService(directus_service=directus, s3_service=FakeS3())

    results = await asyncio.gather(
        service.archive_chat("chat-1", now_timestamp=40 * 86_400),
        service.archive_chat("chat-1", now_timestamp=40 * 86_400),
        return_exceptions=True,
    )

    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, ColdArchiveConflictError) for result in results) == 1
    assert len(directus.collections["cold_archive_manifests"]) == 1


# contract-test: direct surface=rest_api assertions=storage.cold.atomic-eligible-graphs
@pytest.mark.asyncio
async def test_expired_archive_lease_resumes_partial_hot_deletion() -> None:
    class FailOnceDirectus(FakeDirectus):
        failed = False

        async def delete_item(self, collection, item_id, **kwargs):
            if collection == "messages" and not self.failed:
                self.failed = True
                return False
            return await super().delete_item(collection, item_id, **kwargs)

    directus = FailOnceDirectus()
    service = ColdArchiveService(directus_service=directus, s3_service=FakeS3())
    started_at = 40 * 86_400

    with pytest.raises(ColdArchiveError, match="HOT_GRAPH_DELETE_FAILED"):
        await service.archive_chat("chat-1", now_timestamp=started_at)

    result = await service.archive_chat("chat-1", now_timestamp=started_at + ARCHIVE_LEASE_SECONDS + 1)

    assert result["state"] == "cold"
    assert directus.collections["messages"] == []
    assert directus.collections["chats"][0]["storage_state"] == "cold"


# contract-test: direct surface=rest_api assertions=storage.cold.atomic-eligible-graphs
@pytest.mark.asyncio
async def test_graph_change_after_claim_aborts_and_activates_part_cleanup() -> None:
    directus = FakeDirectus()

    class MutatingS3(FakeS3):
        mutated = False

        async def upload_file(self, **kwargs):
            result = await super().upload_file(**kwargs)
            if not self.mutated:
                self.mutated = True
                directus.collections["messages"].append(
                    {"id": "late-message", "chat_id": "chat-1", "encrypted_content": "late-cipher"}
                )
            return result

    with pytest.raises(ColdArchiveConflictError, match="CHAT_GRAPH_CHANGED_DURING_ARCHIVE"):
        await ColdArchiveService(directus_service=directus, s3_service=MutatingS3()).archive_chat(
            "chat-1",
            now_timestamp=40 * 86_400,
        )

    assert directus.collections["chats"][0]["storage_state"] == "hot"
    assert directus.collections["cold_archive_parts"] == []
    assert directus.collections["storage_deletion_tombstones"][0]["state"] == "pending"
