"""Cold chat archive service contract tests.

Complete client-encrypted chat graphs become immutable regional archive parts
only after every configured region verifies the same checksum. Hot content is
never removed after a partial archive write, and reads do not restore rows.
Contract: architecture.storage-lifecycle.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
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


async def existing_archive_fixture(service, *, now=40 * 86_400):
    """Construct a historical archive without invoking a held migration path."""
    directus, store = service.directus_service, service.s3_service
    graph = await service._collect_chat_graph(directus.collections["chats"][0])
    regions = sorted(store.region_clients)
    parts = []
    for number, content in enumerate(service._build_parts("archive-1", 1, graph), 1):
        key = f"historical/archive-1/part-{number}.gz"
        checksum = hashlib.sha256(content).hexdigest()
        for region in regions:
            await store.upload_file(bucket_key=COLD_ARCHIVE_BUCKET_KEY, file_key=key, content=content,
                                    content_type="application/gzip", metadata={}, region=region)
            assert await store.verify_regional_object(bucket_key=COLD_ARCHIVE_BUCKET_KEY, object_key=key,
                                                       region=region, checksum=checksum)
        parts.append({"id": f"part-{number}", "archive_id": "archive-1", "generation": 1,
                      "logical_bucket": COLD_ARCHIVE_BUCKET_KEY, "object_key": key, "checksum": checksum,
                      "size_bytes": len(content), "regional_states": {region: "verified" for region in regions}})
    manifest = {"id": "manifest-1", "archive_id": "archive-1", "resource_id": "chat-1",
                "active_generation": 1, "state": "cold", "part_count": len(parts),
                "graph_checksum": service._graph_checksum(graph), "verified_regions": regions,
                "file_references": service._file_references(graph), "archived_at": now}
    directus.collections["cold_archive_parts"] = parts
    directus.collections["cold_archive_manifests"] = [manifest]
    return manifest


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
async def test_complete_graph_policy_hold_retains_every_head_key_and_metadata_row() -> None:
    directus = FakeDirectus()
    original = deepcopy(directus.collections)
    service = ColdArchiveService(directus_service=directus, s3_service=FakeS3())
    with pytest.raises(ColdArchiveConflictError, match="FULL_GRAPH_PRUNING_POLICY_PENDING"):
        await service.archive_chat("chat-1", now_timestamp=40 * 86_400)
    assert directus.collections == original
    assert directus.events == []
    assert service.s3_service.objects == {}


# contract-test: direct surface=rest_api assertions=storage.cold.atomic-eligible-graphs
@pytest.mark.asyncio
async def test_degraded_regional_copy_preserves_original_graph_and_publishes_no_archive() -> None:
    directus = FakeDirectus()
    original = deepcopy(directus.collections)
    service = ColdArchiveService(directus_service=directus, s3_service=FakeS3(fail_region="hel1"))
    with pytest.raises(RuntimeError, match="regional write failed"):
        await existing_archive_fixture(service)
    assert directus.collections == original
    assert directus.events == []


# contract-test: direct surface=rest_api assertions=storage.cold.discoverable-bounded,storage.cold.rehydrate-on-mutation
@pytest.mark.asyncio
async def test_part_read_streams_without_restoring_hot_rows() -> None:
    directus = FakeDirectus()
    s3 = FakeS3()
    service = ColdArchiveService(directus_service=directus, s3_service=s3)
    manifest = await existing_archive_fixture(service)
    part = directus.collections["cold_archive_parts"][0]
    # Simulate source rows already removed by a historical deployment.
    directus.collections["messages"] = []

    chunks = [chunk async for chunk in service.stream_archive_part(manifest=manifest, part=part)]

    assert chunks
    assert directus.collections["messages"] == []
    assert directus.events == []


# contract-test: direct surface=rest_api assertions=storage.cold.atomic-eligible-graphs
@pytest.mark.asyncio
async def test_root_archive_contains_complete_sub_chat_tree() -> None:
    directus = FakeDirectus()
    directus.collections["chats"].append(
        {"id": "chat-2", "parent_id": "chat-1", "is_sub_chat": True, "hashed_user_id": "owner-hash", "updated_at": 1, "pinned": False, "is_shared": False}
    )
    directus.collections["messages"].append({"id": "message-2", "chat_id": "chat-2", "encrypted_content": "cipher-sub-chat"})
    s3 = FakeS3()

    await existing_archive_fixture(ColdArchiveService(directus_service=directus, s3_service=s3))

    archived_chat_ids: set[str] = set()
    for (region, _key), content in s3.objects.items():
        if region != "nbg1":
            continue
        payload = json.loads(gzip.decompress(content))
        archived_chat_ids.update(row["id"] for row in payload["records"].get("chats", []))
    assert archived_chat_ids == {"chat-1", "chat-2"}
    assert directus.collections["messages"]


# contract-test: direct surface=rest_api assertions=storage.cold.discoverable-bounded
@pytest.mark.asyncio
async def test_part_read_uses_verified_regional_failover() -> None:
    directus = FakeDirectus()
    s3 = RegionalFailoverS3()
    service = ColdArchiveService(directus_service=directus, s3_service=s3)
    manifest = await existing_archive_fixture(service)
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
async def test_concurrent_legacy_migrations_are_held_without_claims() -> None:
    directus = FakeDirectus()
    original = deepcopy(directus.collections)
    service = ColdArchiveService(directus_service=directus, s3_service=FakeS3())
    results = await asyncio.gather(service.archive_chat("chat-1"), service.archive_chat("chat-1"), return_exceptions=True)
    assert all(isinstance(result, ColdArchiveConflictError) and str(result) == "FULL_GRAPH_PRUNING_POLICY_PENDING" for result in results)
    assert directus.collections == original
    assert directus.events == []


# contract-test: direct surface=rest_api assertions=storage.cold.atomic-eligible-graphs
@pytest.mark.asyncio
async def test_expired_legacy_archive_lease_cannot_resume_head_or_metadata_deletion() -> None:
    directus = FakeDirectus()
    directus.collections["chats"][0].update(storage_state="archiving", cold_archive_id="old-archive", archive_started_at=1)
    original = deepcopy(directus.collections)
    service = ColdArchiveService(directus_service=directus, s3_service=FakeS3())
    with pytest.raises(ColdArchiveConflictError, match="FULL_GRAPH_PRUNING_POLICY_PENDING"):
        await service.archive_chat("chat-1", now_timestamp=40 * 86_400 + ARCHIVE_LEASE_SECONDS)
    assert directus.collections == original
    assert directus.events == []


# contract-test: direct surface=rest_api assertions=storage.cold.atomic-eligible-graphs
@pytest.mark.asyncio
async def test_policy_hold_precedes_object_copy_and_any_graph_claim() -> None:
    directus = FakeDirectus()
    class UnexpectedS3(FakeS3):
        async def upload_file(self, **kwargs):
            raise AssertionError("Held migration must not write objects")
    original = deepcopy(directus.collections)
    with pytest.raises(ColdArchiveConflictError, match="FULL_GRAPH_PRUNING_POLICY_PENDING"):
        await ColdArchiveService(directus_service=directus, s3_service=UnexpectedS3()).archive_chat("chat-1")
    assert directus.collections == original
    assert directus.events == []


# contract-test: direct surface=rest_api assertions=storage.cold.discoverable-bounded,storage.integrity.observable-reconcilable
@pytest.mark.asyncio
async def test_existing_archive_checksum_failure_keeps_hot_graph_unchanged() -> None:
    directus, store = FakeDirectus(), FakeS3()
    service = ColdArchiveService(directus_service=directus, s3_service=store)
    manifest = await existing_archive_fixture(service)
    original = deepcopy(directus.collections)
    part = directus.collections["cold_archive_parts"][0]
    store.objects["nbg1", part["object_key"]] = b"corrupt-archive"
    with pytest.raises(ColdArchiveError, match="ARCHIVE_PART_CHECKSUM_MISMATCH"):
        await service._load_archive_graph(manifest)
    assert directus.collections == original
    assert directus.events == []
