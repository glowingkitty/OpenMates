"""
Regression tests for Directus chat metadata permission fallbacks.

Shared-chat short-link creation needs ownership metadata even when newly added
optional encrypted metadata fields have not been granted in Directus yet. A
field-level 403 must degrade to the minimal safe field set, not look like a
missing chat.
"""

# contract-test-file: infrastructure

import hashlib

import pytest

from backend.core.api.app.services.directus.chat_methods import (
    CHAT_METADATA_FIELDS,
    CHAT_METADATA_FIELDS_FALLBACK,
    CHAT_METADATA_FIELDS_WITHOUT_METADATA_VERSION,
    CHAT_METADATA_FIELDS_WITHOUT_METADATA_VERSION_OR_OPTIONAL_SHARE_FLAGS,
    CHAT_METADATA_FIELDS_WITHOUT_OPTIONAL_SHARE_FLAGS,
    ChatMethods,
)


class PermissionFallbackDirectus:
    def __init__(self) -> None:
        self.requested_fields: list[str] = []

    async def get_items(self, _collection, params, **_kwargs):
        fields = params["fields"]
        self.requested_fields.append(fields)
        if fields in {
            CHAT_METADATA_FIELDS,
            CHAT_METADATA_FIELDS_WITHOUT_METADATA_VERSION,
            CHAT_METADATA_FIELDS_WITHOUT_OPTIONAL_SHARE_FLAGS,
            CHAT_METADATA_FIELDS_WITHOUT_METADATA_VERSION_OR_OPTIONAL_SHARE_FLAGS,
        }:
            return None
        if fields == CHAT_METADATA_FIELDS_FALLBACK:
            return [{"id": "d7d558a5-2a8c-4fc4-9b1c-e21868b22bce", "hashed_user_id": "hash"}]
        raise AssertionError(f"Unexpected fields: {fields}")


class BatchMetadataDirectus:
    def __init__(self, denied_fields: set[str] | None = None) -> None:
        self.requests: list[dict] = []
        self.denied_fields = denied_fields or set()

    async def get_items(self, _collection, params, **_kwargs):
        self.requests.append(params)
        if params["fields"] in self.denied_fields:
            return None
        ids = params["filter"]["id"]["_in"]
        return [{"id": chat_id, "hashed_user_id": "hash"} for chat_id in ids]


class UserChatListDirectus:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def get_items(self, _collection, params, **kwargs):
        self.calls.append({"params": params, "kwargs": kwargs})
        return [{"id": "chat-owned", "hashed_user_id": params["filter[hashed_user_id][_eq]"]}]


class TeamChatSyncDirectus:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def get_items(self, collection, params, **kwargs):
        self.calls.append({"collection": collection, "params": params, "kwargs": kwargs})
        if params.get("aggregate[count]") == "*":
            return [{"count": 1}]
        if collection == "drafts":
            return []
        return [{"id": "team-chat", "hashed_team_id": params["filter[hashed_team_id][_eq]"]}]


@pytest.mark.anyio
async def test_chat_metadata_uses_minimal_fallback_after_optional_field_403():
    directus = PermissionFallbackDirectus()
    chat_methods = ChatMethods(directus)

    metadata = await chat_methods.get_chat_metadata(
        "d7d558a5-2a8c-4fc4-9b1c-e21868b22bce",
        admin_required=True,
    )

    assert metadata == {"id": "d7d558a5-2a8c-4fc4-9b1c-e21868b22bce", "hashed_user_id": "hash"}
    assert directus.requested_fields == [
        CHAT_METADATA_FIELDS,
        CHAT_METADATA_FIELDS_WITHOUT_METADATA_VERSION,
        CHAT_METADATA_FIELDS_WITHOUT_OPTIONAL_SHARE_FLAGS,
        CHAT_METADATA_FIELDS_WITHOUT_METADATA_VERSION_OR_OPTIONAL_SHARE_FLAGS,
        CHAT_METADATA_FIELDS_FALLBACK,
    ]


@pytest.mark.anyio
async def test_batch_chat_metadata_uses_json_in_filter():
    directus = BatchMetadataDirectus()
    chat_methods = ChatMethods(directus)
    chat_ids = [
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
    ]

    metadata = await chat_methods.get_chats_metadata_batch(chat_ids)

    assert set(metadata) == set(chat_ids)
    assert directus.requests[0]["filter"] == {"id": {"_in": chat_ids}}
    assert "filter[id][_in]" not in directus.requests[0]


@pytest.mark.anyio
async def test_batch_chat_metadata_uses_field_fallback_after_optional_field_403():
    directus = BatchMetadataDirectus(
        denied_fields={
            CHAT_METADATA_FIELDS,
            CHAT_METADATA_FIELDS_WITHOUT_METADATA_VERSION,
            CHAT_METADATA_FIELDS_WITHOUT_OPTIONAL_SHARE_FLAGS,
            CHAT_METADATA_FIELDS_WITHOUT_METADATA_VERSION_OR_OPTIONAL_SHARE_FLAGS,
        }
    )
    chat_methods = ChatMethods(directus)
    chat_id = "33333333-3333-4333-8333-333333333333"

    metadata = await chat_methods.get_chats_metadata_batch([chat_id])

    assert metadata == {chat_id: {"id": chat_id, "hashed_user_id": "hash"}}
    assert [request["fields"] for request in directus.requests] == [
        CHAT_METADATA_FIELDS,
        CHAT_METADATA_FIELDS_WITHOUT_METADATA_VERSION,
        CHAT_METADATA_FIELDS_WITHOUT_OPTIONAL_SHARE_FLAGS,
        CHAT_METADATA_FIELDS_WITHOUT_METADATA_VERSION_OR_OPTIONAL_SHARE_FLAGS,
        CHAT_METADATA_FIELDS_FALLBACK,
    ]


@pytest.mark.anyio
async def test_user_chat_metadata_can_use_admin_access_with_hashed_owner_filter():
    directus = UserChatListDirectus()
    chat_methods = ChatMethods(directus)

    metadata = await chat_methods.get_user_chats_metadata(
        "user-1",
        limit=40,
        sort="-pinned,-last_edited_overall_timestamp",
        admin_required=True,
    )

    assert metadata[0]["id"] == "chat-owned"
    call = directus.calls[0]
    assert call["params"]["filter[hashed_user_id][_eq]"]
    assert "filter[user_created][_eq]" not in call["params"]
    assert call["kwargs"]["admin_required"] is True


@pytest.mark.anyio
async def test_team_chat_count_uses_admin_access_with_hashed_team_filter():
    directus = TeamChatSyncDirectus()
    chat_methods = ChatMethods(directus)

    count = await chat_methods.get_user_chat_count("user-1", team_id="team-1")

    assert count == 1
    call = directus.calls[0]
    assert call["collection"] == "chats"
    assert call["params"]["filter[hashed_team_id][_eq]"] == hashlib.sha256("team-1".encode()).hexdigest()
    assert "filter[hashed_user_id][_eq]" not in call["params"]
    assert call["kwargs"]["admin_required"] is True


@pytest.mark.anyio
async def test_team_chat_cache_warming_uses_admin_access_with_hashed_team_filter():
    directus = TeamChatSyncDirectus()
    chat_methods = ChatMethods(directus)

    rows = await chat_methods.get_core_chats_and_user_drafts_for_cache_warming("user-1", team_id="team-1")

    assert rows[0]["chat_details"]["id"] == "team-chat"
    chat_call = next(call for call in directus.calls if call["collection"] == "chats")
    assert chat_call["params"]["filter[hashed_team_id][_eq]"] == hashlib.sha256("team-1".encode()).hexdigest()
    assert "filter[hashed_user_id][_eq]" not in chat_call["params"]
    assert chat_call["kwargs"]["admin_required"] is True
