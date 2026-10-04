"""Bounded archived-page promotion before an individual message deletion."""

from __future__ import annotations

import hashlib

import pytest

from backend.core.api.app.services import chat_archive_mutation_service as mutation
from backend.core.api.app.services.chat_message_archive_service import encode_record
from backend.core.api.app.services.storage_reference_service import StorageReferenceInventory


OWNER = hashlib.sha256(b"owner-1").hexdigest()
TEAM = hashlib.sha256(b"team-1").hexdigest()
ROWS = [
    {"id": "row-1", "chat_id": "chat-1", "client_message_id": "m1", "created_at": 1, "encrypted_content": "cipher-1"},
    {"id": "row-2", "chat_id": "chat-1", "client_message_id": "m2", "created_at": 2, "encrypted_content": "cipher-2"},
]
PAGE = {
    "id": "page-1", "chat_id": "chat-1", "hashed_user_id": OWNER,
    "object_key": "message-pages/page.json.gz", "large_objects": [],
    "checksum": "b" * 64, "source_checksum": hashlib.sha256(encode_record(ROWS)).hexdigest(),
    "message_count": 2, "published": True,
}


class Directus:
    async def get_items(self, collection, **_kwargs):
        assert collection == "chats"
        return [{"id": "chat-1", "hashed_user_id": OWNER, "storage_state": "hot"}]


class S3:
    region_clients = {"nbg1": object(), "fsn1": object()}


# contract-test: direct surface=rest_api assertions=storage.cold.atomic-eligible-graphs
@pytest.mark.asyncio
async def test_team_mutation_preflight_uses_team_owner_and_rejects_revoked_actor(monkeypatch) -> None:
    class TeamDirectus:
        role = "member"

        async def get_items(self, collection, **_kwargs):
            if collection == "chats":
                return [{"id": "chat-1", "hashed_user_id": None, "hashed_team_id": TEAM,
                         "storage_state": "hot"}]
            if collection == "team_memberships":
                return [{"id": "membership-1"}] if self.role == "member" else []
            if collection == "teams":
                return [{"id": "team-1"}]
            raise AssertionError(collection)

    directus = TeamDirectus()
    calls: list[dict] = []

    async def transaction(_self, operation, data):
        assert operation == "lookup_mutation_page"
        calls.append(data)
        return {"page": None}

    monkeypatch.setattr(mutation.ChatMessageArchiveService, "transaction", transaction)
    service = mutation.ChatArchiveMutationService(directus_service=directus, s3_service=S3())
    result = await service.promote_for_message(
        user_id="owner-1", chat_id="chat-1", client_message_id="m1",
    )
    assert result == {"promoted": False, "reason": "not_archived"}
    assert calls == [{"chat_id": "chat-1", "message_id": "m1",
                      "expected_owner_hash": TEAM, "expected_actor_user_hash": OWNER}]
    directus.role = "viewer"
    with pytest.raises(PermissionError, match="Team chat mutation permission"):
        await service.promote_for_message(user_id="owner-1", chat_id="chat-1", client_message_id="m1")
    assert len(calls) == 1


# contract-test: direct surface=rest_api assertions=storage.cold.atomic-eligible-graphs,storage.deletion.global-authoritative
@pytest.mark.asyncio
async def test_page_tombstones_precede_atomic_restore_and_activate_after(monkeypatch) -> None:
    events: list[str] = []

    async def transaction(_self, operation, data):
        if operation == "lookup_mutation_page":
            return {"page": dict(PAGE), "segment": {"state": "reader_active"}}
        assert operation == "restore_and_retire_page"
        assert events == ["survivor_scan", "prepare"]
        assert data["source_rows"] == ROWS
        assert data["expected_source_checksum"] == PAGE["source_checksum"]
        events.append("restore")
        return {"promoted": True, "restored_count": 2}

    async def read_page(_self, _page):
        return list(ROWS)

    async def hydrate(_self, rows):
        return rows

    async def find_survivors(**_kwargs):
        events.append("survivor_scan")
        return StorageReferenceInventory(references=set(), ambiguous=[])

    async def prepare(**_kwargs):
        events.append("prepare")
        return [{"id": "tombstone-1"}]

    async def activate(**_kwargs):
        events.append("activate")

    monkeypatch.setattr(mutation.ChatMessageArchiveService, "transaction", transaction)
    monkeypatch.setattr(mutation.ChatMessageArchiveService, "read_page", read_page)
    monkeypatch.setattr(mutation.ChatMessageArchiveService, "hydrate_records", hydrate)
    monkeypatch.setattr(mutation, "find_surviving_storage_references", find_survivors)
    monkeypatch.setattr(mutation, "persist_reference_safe_tombstones", prepare)
    monkeypatch.setattr(mutation, "activate_storage_tombstones", activate)

    result = await mutation.ChatArchiveMutationService(directus_service=Directus(), s3_service=S3()).promote_for_message(
        user_id="owner-1", chat_id="chat-1", client_message_id="m1",
    )

    assert result["promoted"] is True
    assert events == ["survivor_scan", "prepare", "restore", "activate"]


# contract-test: direct surface=rest_api assertions=storage.cold.atomic-eligible-graphs,storage.integrity.observable-reconcilable
@pytest.mark.asyncio
async def test_changed_page_source_stops_before_purge_or_restore(monkeypatch) -> None:
    async def lookup(_self, operation, _data):
        assert operation == "lookup_mutation_page"
        return {"page": dict(PAGE), "segment": {"state": "reader_active"}}

    async def corrupt_page(_self, _page):
        return [{**ROWS[0], "encrypted_content": "tampered"}, ROWS[1]]

    monkeypatch.setattr(mutation.ChatMessageArchiveService, "transaction", lookup)
    monkeypatch.setattr(mutation.ChatMessageArchiveService, "read_page", corrupt_page)
    monkeypatch.setattr(mutation.ChatMessageArchiveService, "hydrate_records", lambda _self, rows: _identity(rows))
    service = mutation.ChatArchiveMutationService(directus_service=Directus(), s3_service=S3())

    with pytest.raises(mutation.ArchiveIntegrityError, match="SOURCE_CHANGED"):
        await service.promote_for_message(user_id="owner-1", chat_id="chat-1", client_message_id="m1")


# contract-test: direct surface=rest_api assertions=storage.cold.atomic-eligible-graphs,storage.deletion.global-authoritative
@pytest.mark.asyncio
async def test_published_copying_page_defers_before_s3_read_or_tombstone(monkeypatch) -> None:
    async def lookup(_self, operation, _data):
        assert operation == "lookup_mutation_page"
        return {"page": dict(PAGE), "segment": {"state": "copying", "lease_until": 9999999999}}

    async def cannot_read(_self, _page):
        raise AssertionError("Copying writer must settle before S3 read or purge")

    monkeypatch.setattr(mutation.ChatMessageArchiveService, "transaction", lookup)
    monkeypatch.setattr(mutation.ChatMessageArchiveService, "read_page", cannot_read)
    with pytest.raises(mutation.ArchiveIntegrityError, match="WRITER_MAY_STILL_UPLOAD"):
        await mutation.ChatArchiveMutationService(directus_service=Directus(), s3_service=S3()).promote_for_message(
            user_id="owner-1", chat_id="chat-1", client_message_id="m1",
        )


async def _identity(rows):
    return rows


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative,storage.integrity.observable-reconcilable
@pytest.mark.asyncio
async def test_failed_restore_leaves_prepared_tombstone_for_restart_reconciliation(monkeypatch) -> None:
    events: list[str] = []

    async def transaction(_self, operation, _data):
        if operation == "lookup_mutation_page":
            return {"page": dict(PAGE), "segment": {"state": "reader_active"}}
        events.append("restore_failed")
        raise RuntimeError("transaction interrupted")

    async def read_page(_self, _page):
        return list(ROWS)

    async def prepare(**_kwargs):
        events.append("prepared")
        return [{"id": "tombstone-1", "state": "prepared"}]

    async def activate(**_kwargs):
        events.append("activated")

    async def no_survivor(**_kwargs):
        return StorageReferenceInventory(references=set(), ambiguous=[])

    monkeypatch.setattr(mutation.ChatMessageArchiveService, "transaction", transaction)
    monkeypatch.setattr(mutation.ChatMessageArchiveService, "read_page", read_page)
    monkeypatch.setattr(mutation.ChatMessageArchiveService, "hydrate_records", lambda _self, rows: _identity(rows))
    monkeypatch.setattr(mutation, "find_surviving_storage_references", no_survivor)
    monkeypatch.setattr(mutation, "persist_reference_safe_tombstones", prepare)
    monkeypatch.setattr(mutation, "activate_storage_tombstones", activate)

    with pytest.raises(RuntimeError, match="transaction interrupted"):
        await mutation.ChatArchiveMutationService(directus_service=Directus(), s3_service=S3()).promote_for_message(
            user_id="owner-1", chat_id="chat-1", client_message_id="m1",
        )

    assert events == ["prepared", "restore_failed"]


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative,storage.cold.atomic-eligible-graphs
@pytest.mark.asyncio
async def test_unpublished_intent_waits_for_writer_then_aborts_without_s3_read(monkeypatch) -> None:
    page = {**PAGE, "published": False}
    segment = {"id": "segment-1", "state": "copying", "lease_until": 0}
    events: list[str] = []

    async def transaction(_self, operation, _data):
        if operation == "lookup_mutation_page":
            return {"page": page, "segment": segment}
        assert operation == "abort_unpublished_page"
        events.append("abort")
        return {"aborted": True}

    async def cannot_read(_self, _page):
        raise AssertionError("Unpublished object must not be read")

    async def no_survivor(**_kwargs):
        return StorageReferenceInventory(references=set(), ambiguous=[])

    async def prepare(**_kwargs):
        events.append("prepare")
        return [{"id": "tombstone-1"}]

    async def activate(**_kwargs):
        events.append("activate")

    monkeypatch.setattr(mutation.ChatMessageArchiveService, "transaction", transaction)
    monkeypatch.setattr(mutation.ChatMessageArchiveService, "read_page", cannot_read)
    monkeypatch.setattr(mutation, "find_surviving_storage_references", no_survivor)
    monkeypatch.setattr(mutation, "persist_reference_safe_tombstones", prepare)
    monkeypatch.setattr(mutation, "activate_storage_tombstones", activate)
    service = mutation.ChatArchiveMutationService(directus_service=Directus(), s3_service=S3())

    segment["lease_until"] = 4_102_444_800
    with pytest.raises(mutation.ArchiveIntegrityError, match="WRITER_MAY_STILL_UPLOAD"):
        await service.promote_for_message(user_id="owner-1", chat_id="chat-1", client_message_id="m1")
    assert events == []

    segment["lease_until"] = 0
    assert (await service.promote_for_message(
        user_id="owner-1", chat_id="chat-1", client_message_id="m1",
    ))["aborted"] is True
    assert events == ["prepare", "abort", "activate"]


# contract-test: direct surface=rest_api assertions=storage.cold.independent-message-pages,storage.integrity.observable-reconcilable
@pytest.mark.asyncio
async def test_oversized_large_object_window_rejected_before_read(monkeypatch) -> None:
    page = {**PAGE, "large_objects": [{"object_key": "large", "size_bytes": 3 * 1024 * 1024}]}

    async def transaction(_self, operation, _data):
        assert operation == "lookup_mutation_page"
        return {"page": page, "segment": {"state": "reader_active"}}

    async def cannot_read(_self, _page):
        raise AssertionError("Oversized promotion must not read S3")

    monkeypatch.setattr(mutation.ChatMessageArchiveService, "transaction", transaction)
    monkeypatch.setattr(mutation.ChatMessageArchiveService, "read_page", cannot_read)
    with pytest.raises(mutation.ArchiveIntegrityError, match="BUDGET_EXCEEDED"):
        await mutation.ChatArchiveMutationService(directus_service=Directus(), s3_service=S3()).promote_for_message(
            user_id="owner-1", chat_id="chat-1", client_message_id="m1",
        )
