"""Tests for embed deletion project protection.

Project-referenced embeds must survive chat/message cleanup unless the caller
explicitly removes the project reference first.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.directus.embed_methods import EmbedMethods


@pytest.mark.asyncio
async def test_delete_all_embeds_for_chat_keeps_project_referenced_embeds() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(
        return_value=[
            {"id": "directus-a", "embed_id": "embed-a", "is_private": True, "is_shared": False},
            {"id": "directus-b", "embed_id": "embed-b", "is_private": True, "is_shared": False},
        ]
    )
    directus.bulk_delete_items = AsyncMock(return_value=True)
    directus.project = SimpleNamespace(
        get_project_embed_reference_counts=AsyncMock(return_value={"embed-a": 1, "embed-b": 0})
    )

    methods = EmbedMethods(directus)
    success, deleted_embed_ids = await methods.delete_all_embeds_for_chat(
        "hashed-chat",
        user_id="user-1",
    )

    assert success is True
    assert deleted_embed_ids == ["embed-b"]
    directus.bulk_delete_items.assert_awaited_once_with(
        collection="embeds",
        item_ids=["directus-b"],
    )
