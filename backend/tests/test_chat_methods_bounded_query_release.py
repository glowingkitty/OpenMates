"""Focused hot-count and existing encrypted-window query compatibility."""

import json

import pytest

from backend.core.api.app.services.directus.chat_methods import ChatMethods


# contract-test: supporting surface=rest_api assertions=storage.cold.discoverable-bounded
@pytest.mark.asyncio
async def test_hot_message_count_uses_filtered_aggregate_without_id_transfer() -> None:
    class Directus:
        async def get_items(self, collection, *, params, admin_required, no_cache, raise_on_error):
            assert collection == "messages"
            assert params == {
                "filter[chat_id][_eq]": "chat-1",
                "aggregate[count]": "*",
            }
            assert admin_required is True
            assert no_cache is True
            assert raise_on_error is True
            return [{"count": "143"}]

    assert await ChatMethods(Directus()).get_message_count_for_chat("chat-1") == 143


# contract-test: supporting surface=rest_api assertions=storage.cold.discoverable-bounded
@pytest.mark.asyncio
async def test_hot_message_count_never_treats_failed_read_as_zero() -> None:
    class Directus:
        async def get_items(self, *_args, **_kwargs):
            return None

    assert await ChatMethods(Directus()).get_message_count_for_chat("chat-1") is None


# contract-test: supporting surface=rest_api assertions=storage.warm.bounded-chat-tail
@pytest.mark.asyncio
async def test_existing_message_window_shape_and_cursor_survive_strict_query() -> None:
    class Directus:
        async def get_items(self, collection, *, params, admin_required, no_cache, raise_on_error):
            assert collection == "messages"
            assert params["limit"] == 3
            assert params["filter"] == {"chat_id": {"_eq": "chat-1"}}
            assert admin_required is True and no_cache is True and raise_on_error is True
            return [
                {"id": "db-3", "client_message_id": "m-3", "created_at": 3, "encrypted_content": "cipher-3"},
                {"id": "db-2", "client_message_id": "m-2", "created_at": 2, "encrypted_content": "cipher-2"},
                {"id": "db-1", "client_message_id": "m-1", "created_at": 1, "encrypted_content": "cipher-1"},
            ]

    window = await ChatMethods(Directus()).get_message_window_for_chat("chat-1", limit=2)
    assert [json.loads(row)["message_id"] for row in window["messages"]] == ["m-2", "m-3"]
    assert window["has_more_before"] is True
    assert window["start_cursor"] == {"created_at": 2, "message_id": "m-2"}


# contract-test: supporting surface=rest_api assertions=storage.warm.bounded-chat-tail
@pytest.mark.asyncio
async def test_message_window_database_error_is_not_an_empty_page() -> None:
    class Directus:
        async def get_items(self, *_args, **_kwargs):
            raise RuntimeError("Directus unavailable")

    with pytest.raises(RuntimeError, match="Directus unavailable"):
        await ChatMethods(Directus()).get_message_window_for_chat("chat-1", limit=2)
