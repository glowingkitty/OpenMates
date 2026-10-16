# contract-test-file: supporting surface=rest_api assertions=wikipedia-mentions.learning.chat-and-memory
from unittest.mock import AsyncMock
import pytest
from backend.core.api.app.routes.handlers.websocket_handlers.draft_submission import (
    clear_sent_message_draft,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "preserve,incognito,cleared",
    [
        (True, False, False),
        (False, False, True),
        ("true", False, True),
        (None, False, True),
        (False, True, False),
    ],
)
# contract-test: supporting surface=rest_api assertions=wikipedia-mentions.learning.chat-and-memory
async def test_separate_submission_retains_draft_while_ordinary_send_broadcasts_tombstone(
    preserve, incognito, cleared
):
    cache, manager = AsyncMock(), AsyncMock()
    cache.increment_and_tombstone_user_draft.return_value = 9
    await clear_sent_message_draft(
        cache_service=cache,
        manager=manager,
        user_id="owner",
        chat_id="chat",
        message_id="message",
        device_hash="current-device",
        is_incognito=incognito,
        preserve_draft=preserve,
    )
    if cleared:
        cache.increment_and_tombstone_user_draft.assert_awaited_once_with(
            "owner", "chat"
        )
        manager.broadcast_to_user.assert_awaited_once_with(
            message={
                "type": "draft_deleted",
                "payload": {"chat_id": "chat", "draft_v": 9},
            },
            user_id="owner",
            exclude_device_hash="current-device",
        )
    else:
        cache.increment_and_tombstone_user_draft.assert_not_awaited()
        manager.broadcast_to_user.assert_not_awaited()


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=wikipedia-mentions.learning.chat-and-memory
async def test_cleanup_failure_does_not_fail_accepted_submission():
    cache, manager = AsyncMock(), AsyncMock()
    cache.increment_and_tombstone_user_draft.side_effect = RuntimeError("Unavailable")
    await clear_sent_message_draft(
        cache_service=cache,
        manager=manager,
        user_id="owner",
        chat_id="chat",
        message_id="message",
        device_hash="current-device",
        is_incognito=False,
    )
    manager.broadcast_to_user.assert_not_awaited()
