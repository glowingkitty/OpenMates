"""Personal account deletion preserves current Team authority and fails on partial reads."""

import hashlib
from types import SimpleNamespace

import pytest

from backend.core.api.app.services.account_content_deletion_service import (
    delete_account_personal_content,
    load_account_personal_embed_key_ids,
    delete_account_personal_embed_keys,
)


class Directus:
    def __init__(self):
        self.calls = []
        self.deleted = []
        self.fail_read = False
        self.fail_delete = False
        self.chats = [{"id": f"chat-{i:03d}", "hashed_user_id": "creator", "hashed_team_id": None}
                      for i in range(21)]
        self.chats.append({"id": "team-chat", "hashed_user_id": "creator", "hashed_team_id": "team"})
        self.messages = [{"id": f"message-{i:03d}", "chat_id": "chat-000"} for i in range(121)]
        self.messages.append({"id": "team-message", "chat_id": "team-chat"})
        self.keys = []
        self.specifications = []
        self.specification_revisions = []

    async def get_items(self, collection, *, params, **kwargs):
        self.calls.append((collection, params, kwargs))
        assert params["limit"] == 20 and kwargs["raise_on_error"] and kwargs["no_cache"]
        assert kwargs["admin_required"]
        if collection == "chats":
            assert params["filter[hashed_user_id][_eq]"] == "creator"
            assert params["filter[hashed_team_id][_null]"] is True
            rows = [row for row in self.chats if row["hashed_team_id"] is None]
        elif collection == "messages":
            assert collection == "messages"
            rows = [row for row in self.messages if row["chat_id"] == params["filter[chat_id][_eq]"]]
            if self.fail_read and params.get("filter[id][_nin]"):
                raise RuntimeError("database unavailable")
        elif collection in {"user_specifications", "user_specification_revisions"}:
            assert params["filter[hashed_user_id][_eq]"] == "creator"
            assert params["filter[hashed_team_id][_null]"] is True
            source = self.specifications if collection == "user_specifications" else self.specification_revisions
            rows = [row for row in source if row["hashed_team_id"] is None and row["hashed_user_id"] == "creator"]
        else:
            assert collection == "embed_keys"
            assert params["filter[hashed_user_id][_eq]"] == "creator"
            rows = self.keys
        return [row for row in rows if row["id"] not in params.get("filter[id][_nin]", [])][:20]

    async def bulk_delete_items(self, collection, ids):
        assert 0 < len(ids) <= 20
        self.deleted.append((collection, ids))
        return not self.fail_delete


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative,storage.cold.shared-team-authorized,storage.files.reference-safe-single-copy
@pytest.mark.asyncio
async def test_account_content_deletes_complete_personal_scope_in_bounded_batches():
    directus = Directus()
    # This immutable selection was captured by storage inventory before mutation.
    eligible = SimpleNamespace(embeds=[{"id": "personal-embed"}], versions=[])
    result = await delete_account_personal_content(
        directus_service=directus, user_id_hash="creator", eligible_embed_rows=eligible,
    )
    assert result == {"user_specification_revisions": 0, "user_specifications": 0, "messages": 121, "embeds": 1, "chats": 21}
    deleted = {value for _, ids in directus.deleted for value in ids}
    assert {"team-chat", "team-message", "team-project-embed"}.isdisjoint(deleted)
    assert "message-120" in deleted and "chat-020" in deleted
    collections = [collection for collection, _ in directus.deleted]
    assert collections == ["messages"] * 7 + ["embeds"] + ["chats"] * 2


# contract-test: supporting surface=rest_api assertions=contracts.project.encrypted-embed,storage.deletion.global-authoritative
@pytest.mark.asyncio
async def test_account_deletion_removes_personal_specifications_and_history_but_preserves_team_scope():
    directus = Directus()
    directus.specifications = [
        {"id": "spec-personal", "hashed_user_id": "creator", "hashed_team_id": None},
        {"id": "spec-team", "hashed_user_id": "creator", "hashed_team_id": "team"},
    ]
    directus.specification_revisions = [
        {"id": f"revision-{i:03d}", "hashed_user_id": "creator", "hashed_team_id": None}
        for i in range(23)
    ] + [{"id": "team-revision", "hashed_user_id": "creator", "hashed_team_id": "team"}]
    result = await delete_account_personal_content(
        directus_service=directus, user_id_hash="creator", eligible_embed_rows=SimpleNamespace(embeds=[], versions=[]),
    )
    assert result["user_specifications"] == 1 and result["user_specification_revisions"] == 23
    assert [collection for collection, _ in directus.deleted][:3] == [
        "user_specification_revisions", "user_specification_revisions", "user_specifications",
    ]
    deleted = {value for _, ids in directus.deleted for value in ids}
    assert {"spec-team", "team-revision"}.isdisjoint(deleted)


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative
@pytest.mark.asyncio
async def test_account_content_read_failure_stops_before_any_content_deletion():
    directus = Directus()
    directus.fail_read = True
    with pytest.raises(RuntimeError, match="database unavailable"):
        await delete_account_personal_content(
            directus_service=directus, user_id_hash="creator",
            eligible_embed_rows=SimpleNamespace(embeds=[{"id": "personal-embed"}], versions=[]),
        )
    assert directus.deleted == []


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative
@pytest.mark.asyncio
async def test_account_content_delete_failure_stops_before_embed_or_chat_removal():
    directus = Directus()
    directus.fail_delete = True
    with pytest.raises(RuntimeError, match="messages"):
        await delete_account_personal_content(
            directus_service=directus, user_id_hash="creator",
            eligible_embed_rows=SimpleNamespace(embeds=[{"id": "personal-embed"}], versions=[]),
        )
    assert len(directus.deleted) == 1 and directus.deleted[0][0] == "messages"


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative,storage.cold.shared-team-authorized,storage.files.reference-safe-single-copy
@pytest.mark.asyncio
async def test_account_key_cleanup_keeps_wrappers_for_retained_shared_artifacts():
    directus = Directus()
    def digest(value):
        return hashlib.sha256(value.encode()).hexdigest()
    directus.keys = [
        {"id": f"key-{i:03d}", "key_type": "master", "hashed_embed_id": "retained-embed"}
        for i in range(121)
    ] + [
        {"id": "key-121", "key_type": "chat", "hashed_chat_id": digest("chat-000")},
        {"id": "key-122", "key_type": "project", "hashed_embed_id": digest("deleted-embed")},
        {"id": "key-123", "key_type": "chat", "hashed_chat_id": digest("team-chat")},
        {"id": "key-124", "key_type": "project", "hashed_embed_id": "retained-embed"},
        {"id": "key-125", "key_type": "plan", "hashed_embed_id": "retained-embed"},
        {"id": "key-126", "key_type": "team", "hashed_team_id": "team", "hashed_embed_id": "retained-embed"},
        {"id": "key-127", "key_type": "unknown", "hashed_embed_id": "retained-embed"},
    ]
    eligible = SimpleNamespace(embeds=[{"id": "deleted-row", "embed_id": "deleted-embed"}], versions=[])
    ids = await load_account_personal_embed_key_ids(
        directus_service=directus, user_id_hash="creator", eligible_embed_rows=eligible,
    )
    assert ids == [f"key-{i:03d}" for i in range(123)]
    assert await delete_account_personal_embed_keys(directus_service=directus, key_ids=ids) == 123
    assert len(directus.deleted) == 7
    assert all(collection == "embed_keys" for collection, _ in directus.deleted)
