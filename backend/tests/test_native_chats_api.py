"""Contract tests for session-authenticated native chat reads.

These tests keep encrypted chat metadata opaque, verify ownership before message
reads, and inspect FastAPI dependencies without requiring a live Directus or
authenticated user account. The same routes serve independent Apple clients.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.routes.chats import list_chat_messages, list_chats, router


def _request(chat_service):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(directus_service=SimpleNamespace(chat=chat_service))))


def test_native_chat_routes_require_session_authentication() -> None:
    routes = {route.path: route for route in router.routes}

    assert routes["/v1/chats"].methods == {"GET"}
    assert routes["/v1/chats/{chat_id}/messages"].methods == {"GET"}
    for path in ("/v1/chats", "/v1/chats/{chat_id}/messages"):
        dependency_calls = [dependency.call for dependency in routes[path].dependant.dependencies]
        assert get_current_user in dependency_calls


@pytest.mark.asyncio
async def test_list_chats_returns_bounded_encrypted_metadata() -> None:
    chat_service = SimpleNamespace(
        get_user_chats_metadata=AsyncMock(return_value=[
            {
                "id": "chat-owned",
                "encrypted_title": "cipher-title",
                "encrypted_chat_summary": "cipher-summary",
                "encrypted_chat_key": "wrapped-chat-key",
                "pinned": False,
                "updated_at": 200,
                "last_message_timestamp": 190,
            }
        ])
    )

    result = await list_chats(
        request=_request(chat_service),
        limit=20,
        current_user=SimpleNamespace(id="user-1"),
    )

    assert result == {
        "chats": [
            {
                "id": "chat-owned",
                "encrypted_title": "cipher-title",
                "encrypted_chat_summary": "cipher-summary",
                "encrypted_chat_key": "wrapped-chat-key",
                "pinned": False,
                "updated_at": "200",
                "last_message_at": "190",
            }
        ],
        "limit": 20,
    }
    chat_service.get_user_chats_metadata.assert_awaited_once_with(
        "user-1",
        limit=20,
        offset=0,
        sort="-pinned,-last_edited_overall_timestamp",
    )
    assert "title" not in result["chats"][0]
    assert "chat_summary" not in result["chats"][0]


@pytest.mark.asyncio
async def test_list_chat_messages_requires_ownership_before_encrypted_read() -> None:
    chat_service = SimpleNamespace(
        check_chat_ownership=AsyncMock(return_value=True),
        get_all_messages_for_chat=AsyncMock(return_value=[
            json.dumps({
                "id": "message-1",
                "chat_id": "chat-owned",
                "role": "assistant",
                "encrypted_content": "cipher-message",
                "created_at": 201,
            })
        ]),
    )

    result = await list_chat_messages(
        chat_id="chat-owned",
        request=_request(chat_service),
        current_user=SimpleNamespace(id="user-1"),
    )

    assert result[0]["encrypted_content"] == "cipher-message"
    assert "content" not in result[0]
    chat_service.check_chat_ownership.assert_awaited_once_with("chat-owned", "user-1")
    chat_service.get_all_messages_for_chat.assert_awaited_once_with("chat-owned", decrypt_content=False)


@pytest.mark.asyncio
async def test_list_chat_messages_hides_cross_user_chat_existence() -> None:
    chat_service = SimpleNamespace(
        check_chat_ownership=AsyncMock(return_value=False),
        get_all_messages_for_chat=AsyncMock(),
    )

    with pytest.raises(HTTPException) as error:
        await list_chat_messages(
            chat_id="chat-other-user",
            request=_request(chat_service),
            current_user=SimpleNamespace(id="user-1"),
        )

    assert error.value.status_code == 404
    assert error.value.detail == "Chat not found"
    chat_service.get_all_messages_for_chat.assert_not_awaited()
