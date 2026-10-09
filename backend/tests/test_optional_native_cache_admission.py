# contract-test-file: infrastructure
"""Optional encrypted replay cannot prevent a canonical reply entering AI history."""

import json
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.schemas.chat import MessageInCache
from backend.core.api.app.services.cache_chat_mixin import ChatCacheMixin


class Cache(ChatCacheMixin):
    @property
    async def client(self):
        return object()

    def __init__(self, admissions):
        self.add_ai_message_to_history = AsyncMock(side_effect=admissions)
        self.set_chat_version_component = AsyncMock(return_value=True)
        self.increment_chat_component_version = AsyncMock(return_value=7)
        self.update_chat_list_item_data = AsyncMock(return_value=True)
        self.update_chat_score_in_ids_versions = AsyncMock(return_value=True)


def message():
    return MessageInCache(
        id="assistant", chat_id="chat", role="assistant", created_at=2,
        encrypted_content="vault:canonical", encrypted_native_cache_context="vault:replay",
        status="synced",
    )


@pytest.mark.asyncio
async def test_replay_admission_failure_retries_canonical_message_before_version_change():
    cache = Cache([False, True])
    result = await cache.save_chat_message_and_update_versions(
        "owner", "chat", message(), explicit_messages_v=7,
    )
    saved = [json.loads(call.args[2]) for call in cache.add_ai_message_to_history.call_args_list]
    assert saved[0]["encrypted_native_cache_context"] == "vault:replay"
    assert saved[1].get("encrypted_native_cache_context") is None
    assert saved[0]["encrypted_content"] == saved[1]["encrypted_content"] == "vault:canonical"
    assert saved[0]["id"] == saved[1]["id"] == "assistant"
    cache.set_chat_version_component.assert_awaited_once_with("owner", "chat", "messages_v", 7)
    assert result is not None


@pytest.mark.asyncio
async def test_no_replay_retry_after_version_failure_on_already_admitted_row():
    cache = Cache([True])
    cache.set_chat_version_component.return_value = False
    result = await cache.save_chat_message_and_update_versions(
        "owner", "chat", message(), explicit_messages_v=7,
    )
    assert result is None
    cache.add_ai_message_to_history.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_canonical_admission_leaves_version_unchanged():
    cache = Cache([False, False])
    result = await cache.save_chat_message_and_update_versions(
        "owner", "chat", message(), explicit_messages_v=7,
    )
    assert result is None
    cache.set_chat_version_component.assert_not_awaited()
