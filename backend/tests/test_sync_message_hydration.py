"""Bounded encrypted sync windows keep durable count separate from payloads."""

import json
import hashlib

import pytest

from backend.core.api.app.routes.handlers.websocket_handlers import sync_message_hydration as hydration
from backend.core.api.app.services.directus.chat_methods import ChatMethods
from backend.core.api.app.services.directus.embed_methods import EmbedMethods


def _message(number: int, content: str = "cipher") -> str:
    return json.dumps({
        "id": f"row-{number}",
        "message_id": f"msg-{number}",
        "created_at": number,
        "encrypted_content": content,
    })


class FakeDirectusChat:
    def __init__(self, messages: list[str], count: int):
        self.messages = messages
        self.count = count
        self.window_calls: list[dict] = []

    async def get_message_window_for_chat(self, **kwargs):
        self.window_calls.append(kwargs)
        messages = self.messages
        if kwargs.get("before_timestamp") is not None:
            messages = [
                message for message in messages
                if json.loads(message)["created_at"] < kwargs["before_timestamp"]
            ]
        page = messages[-kwargs["limit"]:]
        return {
            "messages": page,
            "has_more_before": len(messages) > len(page),
            "has_more_after": kwargs["direction"] == "before",
            "start_cursor": {
                "created_at": json.loads(page[0])["created_at"],
                "message_id": json.loads(page[0])["message_id"],
            } if page else None,
            "end_cursor": {
                "created_at": json.loads(page[-1])["created_at"],
                "message_id": json.loads(page[-1])["message_id"],
            } if page else None,
        }

    async def get_message_count_for_chat(self, chat_id):
        return self.count


class FakeCache:
    async def get_sync_messages_history(self, user_id, chat_id):
        raise AssertionError("Unbounded sync cache must not be read")


# contract-test: direct surface=rest_api assertions=storage.cold.independent-message-pages
@pytest.mark.anyio
async def test_latest_sync_window_is_bounded_and_reports_complete_history_count() -> None:
    chat = FakeDirectusChat([_message(index) for index in range(101)], count=101)
    window = await hydration.load_bounded_sync_message_window(
        cache_service=FakeCache(),
        directus_service=type("Directus", (), {"chat": chat})(),
        user_id="user-1",
        chat_id="chat-1",
        log_prefix="[TEST]",
    )

    assert len(window["messages"]) == hydration.SYNC_MESSAGE_PAGE_LIMIT
    assert json.loads(window["messages"][0])["message_id"] == "msg-81"
    assert window["server_message_count"] == 101
    assert window["has_more_before"] is True
    assert window["start_cursor"] == {"created_at": 81, "message_id": "msg-81"}
    assert chat.window_calls[0]["limit"] == hydration.SYNC_MESSAGE_PAGE_LIMIT


# contract-test: direct surface=rest_api assertions=storage.cold.independent-message-pages
@pytest.mark.anyio
async def test_message_byte_budget_preserves_continuation_at_first_retained_row(monkeypatch) -> None:
    monkeypatch.setattr(hydration, "SYNC_MESSAGE_PAGE_MAX_BYTES", 200)
    chat = FakeDirectusChat([_message(index, "x" * 40) for index in range(3)], count=3)
    window = await hydration.load_bounded_sync_message_window(
        cache_service=FakeCache(),
        directus_service=type("Directus", (), {"chat": chat})(),
        user_id="user-1",
        chat_id="chat-1",
        log_prefix="[TEST]",
    )

    assert 0 < len(window["messages"]) < 3
    assert window["payload_bytes"] <= 200
    assert window["has_more_before"] is True
    assert window["start_cursor"]["message_id"] == json.loads(window["messages"][0])["message_id"]


# contract-test: supporting surface=rest_api assertions=storage.cold.independent-message-pages
@pytest.mark.anyio
async def test_oversized_newest_message_is_reported_for_on_demand_read(monkeypatch) -> None:
    monkeypatch.setattr(hydration, "SYNC_MESSAGE_PAGE_MAX_BYTES", 100)
    chat = FakeDirectusChat([_message(1, "x" * 200)], count=1)
    window = await hydration.load_bounded_sync_message_window(
        cache_service=FakeCache(),
        directus_service=type("Directus", (), {"chat": chat})(),
        user_id="user-1",
        chat_id="chat-1",
        log_prefix="[TEST]",
    )

    assert window["messages"] == []
    assert window["oversized_message"] is True
    assert window["oversized_message_cursor"] == {"created_at": 1, "message_id": "msg-1"}
    assert window["has_more_before"] is True


# contract-test: supporting surface=rest_api assertions=storage.cold.discoverable-bounded
@pytest.mark.anyio
async def test_message_count_uses_aggregate_plus_archived_count() -> None:
    class FakeDirectus:
        def __init__(self):
            self.queries = []

        async def get_items(self, collection, *, params, no_cache, admin_required, raise_on_error):
            assert no_cache is True and raise_on_error is True
            self.queries.append((collection, params, admin_required))
            if collection == "messages":
                return [{"count": 18}]
            return [{"archived_message_count": 82}]

    directus = FakeDirectus()
    assert await ChatMethods(directus).get_message_count_for_chat("chat-1") == 100
    assert directus.queries[0][1]["aggregate[count]"] == "*"
    assert directus.queries[0][1].get("limit") is None
    assert all(query[2] for query in directus.queries)


# contract-test: supporting surface=rest_api assertions=storage.cold.discoverable-bounded
@pytest.mark.anyio
async def test_embed_window_uses_created_at_and_id_cursor_with_byte_cap(monkeypatch) -> None:
    from backend.core.api.app.services.directus import embed_methods

    monkeypatch.setattr(embed_methods, "SYNC_EMBED_PAGE_MAX_BYTES", 300)

    class FakeDirectus:
        def __init__(self):
            self.params = None

        async def get_items(self, collection, *, params, no_cache, raise_on_error):
            assert raise_on_error is True
            self.params = params
            return [
                {"id": "id-3", "embed_id": "embed-3", "created_at": 12, "encrypted_content": "x" * 100},
                {"id": "id-2", "embed_id": "embed-2", "created_at": 12, "encrypted_content": "x" * 100},
                {"id": "id-1", "embed_id": "embed-1", "created_at": 11, "encrypted_content": "x" * 100},
            ]

    directus = FakeDirectus()
    window = await EmbedMethods(directus).get_embed_window_by_hashed_chat_id(
        "chat-hash", before_created_at=13, before_id="id-4",
    )
    assert directus.params["limit"] == embed_methods.SYNC_EMBED_PAGE_LIMIT + 1
    assert directus.params["sort"] == ["-created_at", "-id"]
    assert directus.params["filter"]["hashed_chat_id"] == {"_eq": "chat-hash"}
    assert len(window["embeds"]) == 1
    assert window["start_cursor"] == {"created_at": 12, "id": "id-3"}
    assert window["has_more_before"] is True
    assert window["payload_bytes"] <= 300


# contract-test: supporting surface=rest_api assertions=storage.cold.discoverable-bounded
@pytest.mark.anyio
async def test_oversized_embed_exposes_skip_cursor(monkeypatch) -> None:
    from backend.core.api.app.services.directus import embed_methods

    monkeypatch.setattr(embed_methods, "SYNC_EMBED_PAGE_MAX_BYTES", 100)

    class FakeDirectus:
        async def get_items(self, collection, *, params, no_cache, raise_on_error):
            assert raise_on_error is True
            return [{"id": "row-1", "embed_id": "embed-1", "created_at": 12,
                     "encrypted_content": "x" * 200}]

    window = await EmbedMethods(FakeDirectus()).get_embed_window_by_hashed_chat_id("chat-hash")
    assert window["embeds"] == []
    assert window["oversized_embed_id"] == "embed-1"
    assert window["oversized_embed_cursor"] == {"created_at": 12, "id": "row-1"}
    assert window["has_more_before"] is True


# contract-test: supporting surface=rest_api assertions=storage.cold.discoverable-bounded
@pytest.mark.anyio
async def test_embed_key_window_has_cursor_without_dropping_extra_wrappers() -> None:
    from backend.core.api.app.services.directus import embed_methods

    class FakeDirectus:
        def __init__(self):
            self.params = None

        async def get_items(self, collection, *, params, no_cache, raise_on_error):
            assert raise_on_error is True
            self.params = params
            return [{"id": f"key-{index:03d}", "encrypted_embed_key": "cipher"}
                    for index in range(embed_methods.SYNC_EMBED_KEY_PAGE_LIMIT + 1)]

    directus = FakeDirectus()
    page = await EmbedMethods(directus).get_sync_embed_key_window_for_page(
        "chat-hash", "user-hash", ["embed-hash"], after_key_id="previous-key",
    )
    assert len(page["embed_keys"]) == embed_methods.SYNC_EMBED_KEY_PAGE_LIMIT
    assert page["has_more_after"] is True
    assert page["end_cursor"] == "key-059"
    assert directus.params["filter"]["id"] == {"_gt": "previous-key"}
    assert directus.params["filter"]["_or"][1]["hashed_user_id"] == {"_eq": "user-hash"}


# contract-test: supporting surface=rest_api assertions=storage.cold.shared-team-authorized
@pytest.mark.anyio
async def test_embed_key_cursor_ids_must_belong_to_authorized_chat() -> None:
    class FakeDirectus:
        async def get_items(self, collection, *, params, no_cache, raise_on_error):
            assert raise_on_error is True
            assert params["filter"]["hashed_chat_id"] == {"_eq": "chat-hash"}
            return [{"embed_id": "valid-id", "hashed_embed_id": None}]

    embeds = EmbedMethods(FakeDirectus())
    assert await embeds.validate_embed_ids_in_chat("chat-hash", ["valid-id"]) == [
        hashlib.sha256(b"valid-id").hexdigest(),
    ]
    with pytest.raises(ValueError):
        await embeds.validate_embed_ids_in_chat("chat-hash", ["valid-id", "foreign-id"])


# contract-test: direct surface=rest_api assertions=storage.cold.discoverable-bounded,storage.cold.shared-team-authorized
@pytest.mark.anyio
async def test_bounded_embed_and_key_reads_propagate_directus_failure() -> None:
    class UnavailableDirectus:
        async def get_items(self, collection, *, params, raise_on_error, **_kwargs):
            assert raise_on_error is True
            raise RuntimeError("Directus unavailable")

    embeds = EmbedMethods(UnavailableDirectus())
    for read in (
        embeds.get_embed_window_by_hashed_chat_id("chat-hash"),
        embeds.validate_embed_ids_in_chat("chat-hash", ["embed-1"]),
        embeds.get_sync_embed_key_window_for_page("chat-hash", "user-hash", ["embed-hash"]),
        embeds.get_sync_embed_key_by_id("chat-hash", "user-hash", ["embed-hash"], "key-1"),
        embeds.get_sync_embed_by_id("embed-1"),
    ):
        with pytest.raises(RuntimeError, match="Directus unavailable"):
            await read


# contract-test: direct surface=rest_api assertions=storage.cold.independent-message-pages
@pytest.mark.anyio
async def test_pruned_chat_sync_merges_authorized_archive_window() -> None:
    class ArchivedChat(FakeDirectusChat):
        async def get_message_count_breakdown_for_chat(self, chat_id):
            return 1, 2

    class ArchiveReader:
        def __init__(self):
            self.calls = []

        async def merge_window(self, **kwargs):
            self.calls.append(kwargs)
            return {
                "messages": [json.loads(_message(2)), json.loads(_message(3))],
                "has_more_before": True,
                "start_cursor": {"created_at": 2, "message_id": "msg-2"},
                "end_cursor": {"created_at": 3, "message_id": "msg-3"},
                "storage_tier": "mixed",
            }

    chat = ArchivedChat([_message(3)], count=3)
    archive = ArchiveReader()
    window = await hydration.load_bounded_sync_message_window(
        cache_service=FakeCache(),
        directus_service=type("Directus", (), {"chat": chat})(),
        user_id="user-1",
        chat_id="chat-1",
        log_prefix="[TEST]",
        archive_service=archive,
    )
    assert [json.loads(row)["message_id"] for row in window["messages"]] == ["msg-2", "msg-3"]
    assert window["server_message_count"] == 3
    assert window["has_more_before"] is True
    assert window["storage_tier"] == "mixed"
    assert archive.calls[0]["chat_id"] == "chat-1"
