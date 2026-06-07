"""Regression tests for Directus chat ownership checks.

The ownership helper protects shared chats from non-owner writes, but cache
misses must still fall back to Directus before rejecting. Forked/background
chats can be persisted before the user's chat-list cache includes the new chat,
so treating a primed-cache miss as terminal makes valid owner writes fail.
"""

import hashlib
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.core.api.app.services.directus.chat_methods import ChatMethods


def test_check_chat_ownership_falls_back_to_db_when_primed_cache_misses():
    user_id = "user-123"
    chat_id = "chat-123"
    cache = SimpleNamespace(
        check_chat_exists_for_user=AsyncMock(return_value=False),
        is_user_cache_primed=AsyncMock(return_value=True),
    )
    directus_service = SimpleNamespace(cache=cache)
    chat_methods = ChatMethods(directus_service)
    chat_methods.get_chat_metadata = AsyncMock(
        return_value={"id": chat_id, "hashed_user_id": hashlib.sha256(user_id.encode()).hexdigest()}
    )

    assert asyncio.run(chat_methods.check_chat_ownership(chat_id, user_id)) is True
    chat_methods.get_chat_metadata.assert_awaited_once_with(chat_id)


def test_check_chat_ownership_rejects_db_owner_mismatch_after_cache_miss():
    user_id = "user-123"
    chat_id = "chat-123"
    cache = SimpleNamespace(
        check_chat_exists_for_user=AsyncMock(return_value=False),
        is_user_cache_primed=AsyncMock(return_value=True),
    )
    directus_service = SimpleNamespace(cache=cache)
    chat_methods = ChatMethods(directus_service)
    chat_methods.get_chat_metadata = AsyncMock(
        return_value={"id": chat_id, "hashed_user_id": hashlib.sha256(b"other-user").hexdigest()}
    )

    assert asyncio.run(chat_methods.check_chat_ownership(chat_id, user_id)) is False
    chat_methods.get_chat_metadata.assert_awaited_once_with(chat_id)
