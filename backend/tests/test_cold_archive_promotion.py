"""Generation-fenced cold archive promotion contract tests.

Mutation restores one complete graph using optimistic version control. Stale or
concurrent requests fail visibly and cannot create duplicate hot rows.
Contract: architecture.storage-lifecycle.
"""

from __future__ import annotations

import asyncio
import hashlib

import pytest

from backend.core.api.app.services.cold_archive_service import ColdArchiveConflictError, ColdArchiveService


class Directus:
    def __init__(self) -> None:
        self.manifest = {
            "id": "row-1",
            "archive_id": "archive-1",
            "resource_id": "chat-1",
            "hashed_user_id": hashlib.sha256(b"alice").hexdigest(),
            "hashed_team_id": None,
            "active_generation": 4,
            "version": 1,
            "state": "cold",
        }
        self.restored: set[tuple[str, str]] = set()
        self.updated_chat_state: str | None = None
        self.chat = {"id": "chat-1", "storage_state": "cold", "archive_version": 1}
        self.team = None

    async def get_items(self, collection, params=None, **_kwargs):
        if collection == "cold_archive_manifests":
            return [dict(self.manifest)]
        if collection == "chats":
            return [dict(self.chat)]
        return []

    async def update_item_if_version(self, _collection, _item_id, data, expected_version, **_kwargs):
        await asyncio.sleep(0)
        if _collection == "chats":
            if self.chat["archive_version"] != expected_version:
                return None
            self.chat.update(data)
            self.updated_chat_state = data.get("storage_state")
            return dict(self.chat)
        if self.manifest["version"] != expected_version:
            return None
        self.manifest.update(data)
        return dict(self.manifest)

    async def create_item(self, collection, row, **_kwargs):
        identity = (collection, str(row["id"]))
        if identity in self.restored:
            return True, row
        self.restored.add(identity)
        return True, row

class ArchiveReader:
    async def load_graph(self, _manifest):
        return {"chats": [{"id": "chat-1", "encrypted_title": "cipher"}], "messages": [{"id": "message-1", "chat_id": "chat-1", "encrypted_content": "cipher"}]}


# contract-test: direct surface=rest_api assertions=storage.cold.rehydrate-on-mutation,storage.cold.shared-team-authorized
@pytest.mark.asyncio
async def test_stale_generation_fails_before_restore() -> None:
    directus = Directus()
    service = ColdArchiveService(directus_service=directus, s3_service=object(), archive_reader=ArchiveReader())

    with pytest.raises(ColdArchiveConflictError):
        await service.promote_archive("archive-1", user_id="alice", team_id=None, expected_generation=3, mutation_intent="add_message")

    assert directus.restored == set()


# contract-test: direct surface=rest_api assertions=storage.cold.rehydrate-on-mutation
@pytest.mark.asyncio
async def test_concurrent_promotion_restores_one_duplicate_free_graph() -> None:
    directus = Directus()
    service = ColdArchiveService(directus_service=directus, s3_service=object(), archive_reader=ArchiveReader())

    results = await asyncio.gather(
        service.promote_archive("archive-1", user_id="alice", team_id=None, expected_generation=4, mutation_intent="add_message"),
        service.promote_archive("archive-1", user_id="alice", team_id=None, expected_generation=4, mutation_intent="add_message"),
        return_exceptions=True,
    )

    assert sum(isinstance(result, ColdArchiveConflictError) for result in results) == 1
    assert sum(isinstance(result, dict) and result.get("state") == "hot" for result in results) == 1
    assert directus.restored == {("messages", "message-1")}
    assert directus.updated_chat_state == "hot"


# contract-test: direct surface=rest_api assertions=storage.cold.rehydrate-on-mutation
@pytest.mark.asyncio
async def test_expired_promotion_lease_resumes_idempotently() -> None:
    directus = Directus()
    directus.manifest.update(
        {
            "state": "promoting",
            "version": 2,
            "promotion_intent": "add_message",
            "updated_at": 0,
        }
    )
    directus.chat["storage_state"] = "promoting"
    directus.restored.add(("messages", "message-1"))
    service = ColdArchiveService(directus_service=directus, s3_service=object(), archive_reader=ArchiveReader())

    result = await service.promote_archive(
        "archive-1",
        user_id="alice",
        team_id=None,
        expected_generation=4,
        mutation_intent="add_message",
    )

    assert result["state"] == "hot"
    assert directus.restored == {("messages", "message-1")}
