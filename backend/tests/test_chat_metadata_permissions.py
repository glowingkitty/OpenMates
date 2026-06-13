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
