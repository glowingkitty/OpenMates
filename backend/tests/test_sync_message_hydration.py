# backend/tests/test_sync_message_hydration.py
#
# Regression tests for encrypted sync-message hydration.
# Redis sync messages are an optimization, not an authority. These tests cover
# the cold-boot race where chat version metadata is present while the Redis
# message list is missing or shorter than Directus durable history.

import pytest

from backend.core.api.app.routes.handlers.websocket_handlers.sync_message_hydration import (
    load_sync_messages_with_directus_fallback,
)


class FakeDirectusChat:
    def __init__(self, *, count, messages):
        self.count = count
        self.messages = messages
        self.fetch_count = 0

    async def get_message_count_for_chat(self, chat_id):
        return self.count

    async def get_all_messages_for_chat(self, chat_id, decrypt_content=False):
        self.fetch_count += 1
        return self.messages


class FakeDirectus:
    def __init__(self, *, count, messages):
        self.chat = FakeDirectusChat(count=count, messages=messages)


class FakeCache:
    def __init__(self, messages):
        self.messages = messages

    async def get_sync_messages_history(self, user_id, chat_id):
        return self.messages


@pytest.mark.anyio
async def test_sync_messages_use_complete_cache_without_directus_fetch() -> None:
    directus = FakeDirectus(count=2, messages=["directus-user", "directus-assistant"])

    messages, message_count = await load_sync_messages_with_directus_fallback(
        cache_service=FakeCache(["cached-user", "cached-assistant"]),
        directus_service=directus,
        user_id="user-1",
        chat_id="chat-1",
        log_prefix="[TEST]",
    )

    assert messages == ["cached-user", "cached-assistant"]
    assert message_count == 2
    assert directus.chat.fetch_count == 0


@pytest.mark.anyio
async def test_sync_messages_refetch_directus_when_cache_is_partial() -> None:
    directus = FakeDirectus(count=2, messages=["directus-user", "directus-assistant"])

    messages, message_count = await load_sync_messages_with_directus_fallback(
        cache_service=FakeCache(["cached-user"]),
        directus_service=directus,
        user_id="user-1",
        chat_id="chat-1",
        log_prefix="[TEST]",
    )

    assert messages == ["directus-user", "directus-assistant"]
    assert message_count == 2
    assert directus.chat.fetch_count == 1
