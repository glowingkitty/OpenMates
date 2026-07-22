"""Contract tests for session-authenticated native chat reads.

These tests keep encrypted chat metadata opaque, verify ownership before message
reads, and inspect FastAPI dependencies without requiring a live Directus or
authenticated user account. The same routes serve independent Apple clients.
"""

import json
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.routes.chats import DEFAULT_MESSAGE_WINDOW_LIMIT, get_chat_message_window, list_chat_messages, list_chats, router


def _request(chat_service, chat_key_wrapper_service=None, get_items=None, team_service=None):
    if chat_key_wrapper_service is None:
        chat_key_wrapper_service = SimpleNamespace(get_wrappers_by_hashed_chat_ids_batch=AsyncMock(return_value=[]))
    if get_items is None:
        get_items = AsyncMock(return_value=[])
    if team_service is None:
        team_service = SimpleNamespace(require_team_role=AsyncMock())
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(directus_service=SimpleNamespace(
        chat=chat_service,
        chat_key_wrapper=chat_key_wrapper_service,
        get_items=get_items,
        team=team_service,
    ))))


def test_native_chat_routes_require_session_authentication() -> None:
    routes = {route.path: route for route in router.routes}

    assert routes["/v1/chats"].methods == {"GET"}
    assert routes["/v1/chats/{chat_id}/messages"].methods == {"GET"}
    assert routes["/v1/chats/{chat_id}/messages/window"].methods == {"GET"}
    for path in ("/v1/chats", "/v1/chats/{chat_id}/messages", "/v1/chats/{chat_id}/messages/window"):
        dependency_calls = [dependency.call for dependency in routes[path].dependant.dependencies]
        assert get_current_user in dependency_calls


@pytest.mark.anyio
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
    chat_key_wrapper_service = SimpleNamespace(get_wrappers_by_hashed_chat_ids_batch=AsyncMock(return_value=[]))

    result = await list_chats(
        request=_request(chat_service, chat_key_wrapper_service),
        limit=20,
        team_id=None,
        current_user=SimpleNamespace(id="user-1"),
    )

    assert result == {
        "chats": [
            {
                "id": "chat-owned",
                "encrypted_title": "cipher-title",
                "encrypted_chat_summary": "cipher-summary",
                "encrypted_chat_key": "wrapped-chat-key",
                "chat_key_wrappers": [],
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
        admin_required=True,
        team_id=None,
    )
    chat_key_wrapper_service.get_wrappers_by_hashed_chat_ids_batch.assert_awaited_once_with(
        [hashlib.sha256("chat-owned".encode()).hexdigest()],
        hashed_user_id=hashlib.sha256("user-1".encode()).hexdigest(),
    )
    assert "title" not in result["chats"][0]
    assert "chat_summary" not in result["chats"][0]


@pytest.mark.anyio
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
        team_id=None,
        current_user=SimpleNamespace(id="user-1"),
    )

    assert result[0]["encrypted_content"] == "cipher-message"
    assert "content" not in result[0]
    chat_service.check_chat_ownership.assert_awaited_once_with("chat-owned", "user-1")
    chat_service.get_all_messages_for_chat.assert_awaited_once_with("chat-owned", decrypt_content=False)


@pytest.mark.anyio
async def test_list_chat_messages_hides_cross_user_chat_existence() -> None:
    chat_service = SimpleNamespace(
        check_chat_ownership=AsyncMock(return_value=False),
        get_all_messages_for_chat=AsyncMock(),
    )

    with pytest.raises(HTTPException) as error:
        await list_chat_messages(
            chat_id="chat-other-user",
            request=_request(chat_service),
            team_id=None,
            current_user=SimpleNamespace(id="user-1"),
        )

    assert error.value.status_code == 404
    assert error.value.detail == "Chat not found"
    chat_service.get_all_messages_for_chat.assert_not_awaited()


@pytest.mark.anyio
async def test_chat_message_window_requires_ownership_before_bounded_encrypted_read() -> None:
    messages = [
        json.dumps({
            "id": f"row-{index}",
            "client_message_id": f"message-{index}",
            "chat_id": "chat-owned",
            "role": "assistant",
            "encrypted_content": f"cipher-{index}",
            "content": "plaintext must not leak",
            "created_at": 1000 + index,
        })
        for index in range(DEFAULT_MESSAGE_WINDOW_LIMIT)
    ]
    chat_service = SimpleNamespace(
        check_chat_ownership=AsyncMock(return_value=True),
        get_chat_metadata=AsyncMock(return_value={"id": "chat-owned", "messages_v": 101}),
        get_message_count_for_chat=AsyncMock(return_value=101),
        get_message_window_for_chat=AsyncMock(return_value={
            "messages": messages,
            "has_more_before": True,
            "has_more_after": False,
            "start_cursor": {"created_at": 1000, "message_id": "message-0"},
            "end_cursor": {"created_at": 1029, "message_id": "message-29"},
            "anchor_found": True,
        }),
        get_all_messages_for_chat=AsyncMock(),
    )
    get_items = AsyncMock(return_value=[{"id": "checkpoint-1", "compressed_up_to_timestamp": 900}])

    result = await get_chat_message_window(
        chat_id="chat-owned",
        request=_request(chat_service, get_items=get_items),
        direction="latest",
        limit=DEFAULT_MESSAGE_WINDOW_LIMIT,
        before_timestamp=None,
        before_message_id=None,
        after_timestamp=None,
        after_message_id=None,
        anchor_message_id=None,
        respect_compression_boundary=True,
        team_id=None,
        current_user=SimpleNamespace(id="user-1"),
    )

    assert len(result["messages"]) == DEFAULT_MESSAGE_WINDOW_LIMIT
    assert result["messages"][0]["encrypted_content"] == "cipher-0"
    assert "content" not in result["messages"][0]
    assert result["has_more_before"] is True
    assert result["has_more_after"] is False
    assert result["server_message_count"] == 101
    assert result["compression_boundary_timestamp"] == 900
    assert result["compression_checkpoints"] == [{"id": "checkpoint-1", "compressed_up_to_timestamp": 900}]
    chat_service.check_chat_ownership.assert_awaited_once_with("chat-owned", "user-1")
    chat_service.get_message_window_for_chat.assert_awaited_once_with(
        chat_id="chat-owned",
        direction="latest",
        limit=DEFAULT_MESSAGE_WINDOW_LIMIT,
        before_timestamp=None,
        before_message_id=None,
        after_timestamp=None,
        after_message_id=None,
        anchor_message_id=None,
        lower_bound_timestamp=900,
    )
    chat_service.get_all_messages_for_chat.assert_not_awaited()


@pytest.mark.anyio
async def test_chat_message_window_hides_cross_user_chat_existence() -> None:
    chat_service = SimpleNamespace(
        check_chat_ownership=AsyncMock(return_value=False),
        get_message_window_for_chat=AsyncMock(),
        get_all_messages_for_chat=AsyncMock(),
    )
    get_items = AsyncMock(return_value=[])

    with pytest.raises(HTTPException) as error:
        await get_chat_message_window(
            chat_id="chat-other-user",
            request=_request(chat_service, get_items=get_items),
            direction="latest",
            limit=DEFAULT_MESSAGE_WINDOW_LIMIT,
            before_timestamp=None,
            before_message_id=None,
            after_timestamp=None,
            after_message_id=None,
            anchor_message_id=None,
            respect_compression_boundary=True,
            team_id=None,
            current_user=SimpleNamespace(id="user-1"),
        )

    assert error.value.status_code == 404
    assert error.value.detail == "Chat not found"
    chat_service.get_message_window_for_chat.assert_not_awaited()
    chat_service.get_all_messages_for_chat.assert_not_awaited()
    get_items.assert_not_awaited()


@pytest.mark.anyio
async def test_chat_message_window_around_anchor_passes_anchor_cursor() -> None:
    chat_service = SimpleNamespace(
        check_chat_ownership=AsyncMock(return_value=True),
        get_chat_metadata=AsyncMock(return_value={"id": "chat-owned", "messages_v": 3}),
        get_message_count_for_chat=AsyncMock(return_value=3),
        get_message_window_for_chat=AsyncMock(return_value={
            "messages": [
                json.dumps({"id": "row-1", "client_message_id": "before", "chat_id": "chat-owned", "encrypted_content": "cipher-before", "created_at": 1}),
                json.dumps({"id": "row-2", "client_message_id": "anchor", "chat_id": "chat-owned", "encrypted_content": "cipher-anchor", "created_at": 2}),
                json.dumps({"id": "row-3", "client_message_id": "after", "chat_id": "chat-owned", "encrypted_content": "cipher-after", "created_at": 3}),
            ],
            "has_more_before": False,
            "has_more_after": False,
            "start_cursor": {"created_at": 1, "message_id": "before"},
            "end_cursor": {"created_at": 3, "message_id": "after"},
            "anchor_found": True,
        }),
        get_all_messages_for_chat=AsyncMock(),
    )

    result = await get_chat_message_window(
        chat_id="chat-owned",
        request=_request(chat_service),
        direction="around",
        limit=DEFAULT_MESSAGE_WINDOW_LIMIT,
        before_timestamp=None,
        before_message_id=None,
        after_timestamp=None,
        after_message_id=None,
        anchor_message_id="anchor",
        respect_compression_boundary=True,
        team_id=None,
        current_user=SimpleNamespace(id="user-1"),
    )

    assert [message["message_id"] for message in result["messages"]] == ["before", "anchor", "after"]
    assert result["anchor_found"] is True
    chat_service.get_message_window_for_chat.assert_awaited_once_with(
        chat_id="chat-owned",
        direction="around",
        limit=DEFAULT_MESSAGE_WINDOW_LIMIT,
        before_timestamp=None,
        before_message_id=None,
        after_timestamp=None,
        after_message_id=None,
        anchor_message_id="anchor",
        lower_bound_timestamp=None,
    )
