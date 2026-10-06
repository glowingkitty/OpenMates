"""Focused hot-count and existing encrypted-window query compatibility."""

import json
from types import SimpleNamespace

import pytest

from backend.core.api.app.services.directus.chat_methods import ChatMethods


# contract-test: supporting surface=rest_api assertions=storage.cold.discoverable-bounded
@pytest.mark.asyncio
async def test_hot_message_count_uses_filtered_aggregate_without_id_transfer() -> None:
    collections = []

    class Directus:
        async def get_items(self, collection, *, params, admin_required, no_cache, raise_on_error):
            collections.append(collection)
            assert admin_required is True
            assert no_cache is True
            assert raise_on_error is True
            if collection == "messages":
                assert params == {
                    "filter[chat_id][_eq]": "chat-1",
                    "aggregate[count]": "*",
                }
                return [{"count": "143"}]
            assert collection == "chats"
            assert params == {
                "filter[id][_eq]": "chat-1",
                "fields": "archived_message_count",
                "limit": 1,
            }
            return [{"archived_message_count": 7}]

    assert await ChatMethods(Directus()).get_message_count_for_chat("chat-1") == 150
    assert collections == ["messages", "chats"]


# contract-test: supporting surface=rest_api assertions=storage.cold.discoverable-bounded
@pytest.mark.asyncio
async def test_hot_message_count_never_treats_failed_read_as_zero() -> None:
    class Directus:
        async def get_items(self, *_args, **_kwargs):
            return None

    assert await ChatMethods(Directus()).get_message_count_for_chat("chat-1") is None


# contract-test: supporting surface=rest_api assertions=storage.warm.bounded-chat-tail
@pytest.mark.asyncio
async def test_existing_message_window_shape_and_cursor_survive_strict_query(monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "disposable-internal-test")

    class Directus:
        base_url = "http://cms:8055"

        async def _make_api_request(self, method, url, *, headers, json):
            assert method == "POST" and url == self.base_url + "/chat-archive-transaction"
            assert headers == {"X-Internal-Service-Token": "disposable-internal-test"}
            assert json["operation"] == "hot_message_window"
            assert json["data"]["chat_id"] == "chat-1"
            assert json["data"]["direction"] == "latest"
            assert json["data"]["limit"] == 3
            rows = [
                {"id": "db-3", "chat_id": "chat-1", "client_message_id": "m-3", "created_at": 3, "encrypted_content": "cipher-3"},
                {"id": "db-2", "chat_id": "chat-1", "client_message_id": "m-2", "created_at": 2, "encrypted_content": "cipher-2"},
                {"id": "db-1", "chat_id": "chat-1", "client_message_id": "m-1", "created_at": 1, "encrypted_content": "cipher-1"},
            ]
            return SimpleNamespace(status_code=200, json=lambda: {"data": {"messages": rows}})

    window = await ChatMethods(Directus()).get_message_window_for_chat("chat-1", limit=2)
    assert [json.loads(row)["message_id"] for row in window["messages"]] == ["m-2", "m-3"]
    assert window["has_more_before"] is True
    assert window["start_cursor"] == {"created_at": 2, "message_id": "m-2"}


# contract-test: supporting surface=rest_api assertions=storage.warm.bounded-chat-tail
@pytest.mark.asyncio
async def test_message_window_database_error_is_not_an_empty_page(monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "disposable-internal-test")

    class Directus:
        base_url = "http://cms:8055"

        async def _make_api_request(self, *_args, **_kwargs):
            raise RuntimeError("Directus unavailable")

    with pytest.raises(RuntimeError, match="Directus unavailable"):
        await ChatMethods(Directus()).get_message_window_for_chat("chat-1", limit=2)
