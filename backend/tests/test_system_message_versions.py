from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.system_message_versions import advance_system_message_version


# contract-test: supporting surface=rest_api assertions=video-call.chat.transcripts,chats.message.identity-idempotent
@pytest.mark.asyncio
@pytest.mark.parametrize("minimum,current,expected", [(None, 6, 7), (7, 8, 8), (7, 6, 7)])
async def test_system_message_revision_uses_canonical_floor(minimum, current, expected):
    directus = SimpleNamespace(
        chat=SimpleNamespace(get_chat_metadata=AsyncMock(return_value={
            "hashed_user_id": "owner", "messages_v": current,
            "last_edited_overall_timestamp": 200, "last_message_timestamp": 200,
        })), update_item_if_version=AsyncMock(return_value=True),
    )
    assert await advance_system_message_version(directus, chat_id="chat", owner_hash="owner",
        timestamp=100, minimum_version=minimum) == expected
    args = directus.update_item_if_version.call_args
    assert args.args[2] == {"messages_v": expected, "last_edited_overall_timestamp": 200,
                            "last_message_timestamp": 200}
    assert args.args[3] == current
    assert args.kwargs["owner_hash"] == "owner"


# contract-test: supporting surface=rest_api assertions=video-call.chat.transcripts,chats.message.identity-idempotent
@pytest.mark.asyncio
async def test_system_message_revision_retries_racing_canonical_write():
    directus = SimpleNamespace(chat=SimpleNamespace(get_chat_metadata=AsyncMock(side_effect=[
        {"hashed_user_id": "owner", "messages_v": 6},
        {"hashed_user_id": "owner", "messages_v": 8},
    ])), update_item_if_version=AsyncMock(side_effect=[False, True]))
    assert await advance_system_message_version(directus, chat_id="chat", owner_hash="owner", timestamp=100) == 9


# contract-test: supporting surface=rest_api assertions=video-call.chat.transcripts,chats.message.identity-idempotent
@pytest.mark.asyncio
async def test_system_message_revision_rejects_changed_owner():
    directus = SimpleNamespace(chat=SimpleNamespace(get_chat_metadata=AsyncMock(return_value={
        "hashed_user_id": "someone_else", "messages_v": 6,
    })), update_item_if_version=AsyncMock())
    with pytest.raises(RuntimeError, match="authority unavailable"):
        await advance_system_message_version(directus, chat_id="chat", owner_hash="owner", timestamp=100)
    directus.update_item_if_version.assert_not_called()
