"""
Regression tests for Directus chat metadata permission fallbacks.

Shared-chat short-link creation needs ownership metadata even when newly added
optional encrypted metadata fields have not been granted in Directus yet. A
field-level 403 must degrade to the minimal safe field set, not look like a
missing chat.
"""

import pytest

from backend.core.api.app.services.directus.chat_methods import (
    CHAT_METADATA_FIELDS,
    CHAT_METADATA_FIELDS_FALLBACK,
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
            CHAT_METADATA_FIELDS_WITHOUT_OPTIONAL_SHARE_FLAGS,
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
        CHAT_METADATA_FIELDS_WITHOUT_OPTIONAL_SHARE_FLAGS,
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
        denied_fields={CHAT_METADATA_FIELDS, CHAT_METADATA_FIELDS_WITHOUT_OPTIONAL_SHARE_FLAGS}
    )
    chat_methods = ChatMethods(directus)
    chat_id = "33333333-3333-4333-8333-333333333333"

    metadata = await chat_methods.get_chats_metadata_batch([chat_id])

    assert metadata == {chat_id: {"id": chat_id, "hashed_user_id": "hash"}}
    assert [request["fields"] for request in directus.requests] == [
        CHAT_METADATA_FIELDS,
        CHAT_METADATA_FIELDS_WITHOUT_OPTIONAL_SHARE_FLAGS,
        CHAT_METADATA_FIELDS_FALLBACK,
    ]
