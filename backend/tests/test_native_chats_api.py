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
from backend.core.api.app.routes.chats import DEFAULT_MESSAGE_WINDOW_LIMIT, _watch_chat_payload, get_chat_message_window, get_chat_wrapper_window, get_exact_chat_message, list_chat_messages, list_chats, router
from backend.core.api.app.services.bounded_message_window import MESSAGE_WINDOW_LIMIT


def _request(chat_service, chat_key_wrapper_service=None, get_items=None, team_service=None):
    if chat_key_wrapper_service is None:
        chat_key_wrapper_service = SimpleNamespace(get_sync_wrapper_window_for_chat=AsyncMock(return_value={
            "wrappers": [], "has_more_before": False, "start_cursor": None, "oversized_wrapper_id": None,
        }))
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


# contract-test: direct surface=rest_api assertions=auth.surface.first-party-boundary,chats.persistence.client-encrypted
def test_native_chat_routes_require_session_authentication() -> None:
    routes = {route.path: route for route in router.routes}

    assert routes["/v1/chats"].methods == {"GET"}
    assert routes["/v1/chats/{chat_id}/messages"].methods == {"GET"}
    assert routes["/v1/chats/{chat_id}/messages/window"].methods == {"GET"}
    assert routes["/v1/chats/{chat_id}/messages/{message_id}"].methods == {"GET"}
    assert routes["/v1/chats/{chat_id}/wrappers/window"].methods == {"GET"}
    for path in ("/v1/chats", "/v1/chats/{chat_id}/messages", "/v1/chats/{chat_id}/messages/window", "/v1/chats/{chat_id}/messages/{message_id}", "/v1/chats/{chat_id}/wrappers/window"):
        dependency_calls = [dependency.call for dependency in routes[path].dependant.dependencies]
        assert get_current_user in dependency_calls


# contract-test: supporting surface=rest_api assertions=focus-modes.restoration
def test_native_chat_payload_preserves_saved_focus_ciphertext() -> None:
    payload = _watch_chat_payload({
        "id": "saved-focus-chat",
        "encrypted_active_focus_id": "opaque-focus-id",
        "encrypted_focus_phase_state": "opaque-phase-state",
    })

    assert payload["encrypted_active_focus_id"] == "opaque-focus-id"
    assert payload["encrypted_focus_phase_state"] == "opaque-phase-state"


# contract-test: direct surface=rest_api assertions=storage.cold.independent-message-pages,auth.surface.first-party-boundary
@pytest.mark.anyio
async def test_exact_message_requires_live_ownership_and_has_two_megabyte_cap() -> None:
    chat_service = SimpleNamespace(
        check_chat_ownership=AsyncMock(return_value=False),
        get_chat_metadata=AsyncMock(return_value={"id": "chat-1", "archived_message_count": 0}),
        get_message_for_chat_by_client_id=AsyncMock(return_value={
            "id": "db-1", "client_message_id": "message-1", "chat_id": "chat-1",
            "encrypted_content": "cipher", "created_at": 100,
        }),
    )
    with pytest.raises(HTTPException) as denied:
        await get_exact_chat_message("chat-1", "message-1", _request(chat_service),
                                     team_id=None, current_user=SimpleNamespace(id="other"), response=None)
    assert denied.value.status_code == 404
    chat_service.get_message_for_chat_by_client_id.assert_not_awaited()

    chat_service.check_chat_ownership.return_value = True
    result = await get_exact_chat_message("chat-1", "message-1", _request(chat_service),
                                          team_id=None, current_user=SimpleNamespace(id="owner"), response=None)
    assert result["message"]["encrypted_content"] == "cipher"
    assert result["storage_tier"] == "hot"
    chat_service.get_message_for_chat_by_client_id.return_value = {
        "id": "db-1", "client_message_id": "message-1", "chat_id": "chat-1",
        "encrypted_content": "A" * (2 * 1024 * 1024), "created_at": 100,
    }
    with pytest.raises(HTTPException) as too_large:
        await get_exact_chat_message("chat-1", "message-1", _request(chat_service),
                                     team_id=None, current_user=SimpleNamespace(id="owner"), response=None)
    assert too_large.value.status_code == 413


# contract-test: direct surface=rest_api assertions=chats.persistence.client-encrypted
@pytest.mark.anyio
async def test_team_wrapper_window_requires_membership_and_matching_chat_team() -> None:
    team_hash = hashlib.sha256(b"team-1").hexdigest()
    wrapper_service = SimpleNamespace(get_sync_wrapper_window_for_chat=AsyncMock(return_value={
        "wrappers": [{"id": "wrapper-1", "encrypted_chat_key": "cipher"}],
        "has_more_before": True, "start_cursor": "wrapper-1", "oversized_wrapper_id": None,
    }))
    chat_service = SimpleNamespace(get_chat_metadata=AsyncMock(return_value={
        "id": "chat-1", "hashed_team_id": team_hash,
    }))
    team_service = SimpleNamespace(require_team_role=AsyncMock())
    result = await get_chat_wrapper_window(
        "chat-1", _request(chat_service, wrapper_service, team_service=team_service),
        team_id="team-1", before_id="wrapper-2", wrapper_id=None,
        current_user=SimpleNamespace(id="user-1"), response=None,
    )
    assert result["start_cursor"] == "wrapper-1"
    wrapper_service.get_sync_wrapper_window_for_chat.assert_awaited_once_with(
        hashlib.sha256(b"chat-1").hexdigest(), before_id="wrapper-2", hashed_team_id=team_hash,
    )
    team_service.require_team_role.assert_awaited_once()

    chat_service.get_chat_metadata.return_value = {"id": "chat-1", "hashed_team_id": "other-team"}
    with pytest.raises(HTTPException) as exc:
        await get_chat_wrapper_window(
            "chat-1", _request(chat_service, wrapper_service, team_service=team_service),
            team_id="team-1", before_id="wrapper-2", wrapper_id=None,
            current_user=SimpleNamespace(id="user-1"), response=None,
        )
    assert exc.value.status_code == 404


# contract-test: direct surface=rest_api assertions=chats.persistence.client-encrypted
@pytest.mark.anyio
async def test_list_chats_returns_bounded_encrypted_metadata() -> None:
    chat_service = SimpleNamespace(
        get_user_chats_metadata=AsyncMock(return_value=[
            {
                "id": "chat-owned",
                "encrypted_title": "cipher-title",
                "encrypted_chat_summary": "cipher-summary",
                "encrypted_chat_key": "wrapped-chat-key",
                "created_at": 150,
                "parent_id": "chat-parent",
                "is_sub_chat": True,
                "pinned": False,
                "updated_at": 200,
                "last_message_timestamp": 190,
            }
        ])
    )
    chat_key_wrapper_service = SimpleNamespace(get_sync_wrapper_window_for_chat=AsyncMock(return_value={
        "wrappers": [], "has_more_before": False, "start_cursor": None, "oversized_wrapper_id": None,
    }))

    result = await list_chats(
        request=_request(chat_service, chat_key_wrapper_service),
        limit=20,
        offset=0,
        team_id=None,
        current_user=SimpleNamespace(id="user-1"),
    )

    assert result == {
        "chats": [
            {
                "id": "chat-owned",
                "created_at": "150",
                "last_edited_overall_timestamp": None,
                "parent_id": "chat-parent",
                "is_sub_chat": True,
                "messages_v": None,
                "title_v": None,
                "metadata_v": None,
                "encrypted_title": "cipher-title",
                "encrypted_category": None,
                "encrypted_icon": None,
                "encrypted_slug": None,
                "slug_lookup_hash": None,
                "encrypted_chat_summary": "cipher-summary",
                "encrypted_active_focus_id": None,
                "encrypted_focus_phase_state": None,
                "encrypted_chat_key": "wrapped-chat-key",
                "chat_key_wrappers": [],
                "chat_key_wrapper_window": {"has_more_before": False, "start_cursor": None, "oversized_wrapper_id": None},
                "encrypted_auto_speak_response": None,
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
    chat_key_wrapper_service.get_sync_wrapper_window_for_chat.assert_awaited_once_with(
        hashlib.sha256("chat-owned".encode()).hexdigest(),
        hashed_user_id=hashlib.sha256("user-1".encode()).hexdigest(),
    )
    assert "title" not in result["chats"][0]
    assert "chat_summary" not in result["chats"][0]


# contract-test: supporting surface=rest_api assertions=apple-watch.offline.recent-cohort,chats.persistence.client-encrypted
@pytest.mark.anyio
@pytest.mark.parametrize("pinned", [False, True])
async def test_native_chat_payload_preserves_recency_and_versions_independent_of_pin(pinned: bool) -> None:
    chat_service = SimpleNamespace(get_user_chats_metadata=AsyncMock(return_value=[{
        "id": "owned-recent", "pinned": pinned, "last_edited_overall_timestamp": 900,
        "last_message_timestamp": 100, "created_at": 50, "messages_v": 7,
        "title_v": 2, "metadata_v": 3, "parent_id": None, "is_sub_chat": False,
        "encrypted_title": "opaque-title", "encrypted_chat_key": "opaque-wrapped-key",
    }]))
    result = await list_chats(request=_request(chat_service), limit=20, offset=0,
                             team_id=None, current_user=SimpleNamespace(id="owner"))
    row = result["chats"][0]
    assert row["pinned"] is pinned
    assert row["last_edited_overall_timestamp"] == "900"
    assert row["last_message_at"] == "100"
    assert row["created_at"] == "50"
    assert (row["messages_v"], row["title_v"], row["metadata_v"]) == (7, 2, 3)
    assert row["parent_id"] is None and row["is_sub_chat"] is False
    assert "title" not in row and "chat_summary" not in row
    assert chat_service.get_user_chats_metadata.await_args.kwargs["sort"] == "-pinned,-last_edited_overall_timestamp"


# contract-test: supporting surface=rest_api assertions=teams.membership.role-gated,teams.workspace.surface-parity,chats.persistence.client-encrypted
@pytest.mark.anyio
async def test_list_team_chats_fetches_team_key_wrappers_after_role_check() -> None:
    team_hash = hashlib.sha256("team-1".encode()).hexdigest()
    chat_hash = hashlib.sha256("team-chat".encode()).hexdigest()
    wrapper = {
        "id": "team-wrapper",
        "hashed_chat_id": chat_hash,
        "hashed_team_id": team_hash,
        "key_type": "team",
        "encrypted_chat_key": "team-cipher",
    }
    chat_service = SimpleNamespace(
        get_user_chats_metadata=AsyncMock(return_value=[
            {
                "id": "team-chat",
                "encrypted_title": "cipher-title",
                "encrypted_chat_summary": "cipher-summary",
                "encrypted_chat_key": "team-wrapped-key",
                "pinned": False,
                "updated_at": 200,
                "last_message_timestamp": 190,
            }
        ])
    )
    chat_key_wrapper_service = SimpleNamespace(get_sync_wrapper_window_for_chat=AsyncMock(return_value={
        "wrappers": [wrapper], "has_more_before": False, "start_cursor": "team-wrapper", "oversized_wrapper_id": None,
    }))
    team_service = SimpleNamespace(require_team_role=AsyncMock())

    result = await list_chats(
        request=_request(chat_service, chat_key_wrapper_service, team_service=team_service),
        limit=20,
        offset=25,
        team_id="team-1",
        current_user=SimpleNamespace(id="user-1"),
    )

    assert result["chats"][0]["chat_key_wrappers"] == [wrapper]
    team_service.require_team_role.assert_awaited_once_with(
        "team-1",
        "user-1",
        {"owner", "admin", "member", "viewer"},
    )
    chat_service.get_user_chats_metadata.assert_awaited_once_with(
        "user-1",
        limit=20,
        offset=25,
        sort="-pinned,-last_edited_overall_timestamp",
        admin_required=True,
        team_id="team-1",
    )
    chat_key_wrapper_service.get_sync_wrapper_window_for_chat.assert_awaited_once_with(
        chat_hash,
        hashed_team_id=team_hash,
    )


# contract-test: direct surface=rest_api assertions=chats.persistence.client-encrypted
@pytest.mark.anyio
async def test_list_chat_messages_requires_ownership_before_encrypted_read() -> None:
    chat_service = SimpleNamespace(
        check_chat_ownership=AsyncMock(return_value=True),
        get_chat_metadata=AsyncMock(return_value={"id": "chat-owned", "archived_message_count": 0}),
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
    chat_service.get_chat_metadata.assert_awaited_once_with("chat-owned", admin_required=True)
    chat_service.get_all_messages_for_chat.assert_awaited_once_with("chat-owned", decrypt_content=False)


# contract-test: direct surface=rest_api assertions=chats.persistence.client-encrypted
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


# contract-test: direct surface=rest_api assertions=chats.persistence.client-encrypted,chats.message.identity-idempotent
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
        for index in range(MESSAGE_WINDOW_LIMIT)
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
            "end_cursor": {"created_at": 1019, "message_id": "message-19"},
            "anchor_found": True,
        }),
        get_all_messages_for_chat=AsyncMock(),
    )
    checkpoint = {"id": "checkpoint-1", "compressed_up_to_timestamp": 900, "created_at": 901}
    get_items = AsyncMock(return_value=[checkpoint])

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

    assert len(result["messages"]) == MESSAGE_WINDOW_LIMIT
    assert result["messages"][0]["encrypted_content"] == "cipher-0"
    assert "content" not in result["messages"][0]
    assert result["has_more_before"] is True
    assert result["has_more_after"] is False
    assert result["server_message_count"] == 101
    assert result["compression_boundary_timestamp"] == 900
    assert result["compression_checkpoints"] == [checkpoint]
    chat_service.check_chat_ownership.assert_awaited_once_with("chat-owned", "user-1")
    chat_service.get_message_window_for_chat.assert_awaited_once_with(
        chat_id="chat-owned",
        direction="latest",
        limit=MESSAGE_WINDOW_LIMIT,
        before_timestamp=None,
        before_message_id=None,
        after_timestamp=None,
        after_message_id=None,
        anchor_message_id=None,
        lower_bound_timestamp=900,
    )
    chat_service.get_all_messages_for_chat.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=chats.persistence.client-encrypted
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


# contract-test: direct surface=rest_api assertions=chats.message.identity-idempotent
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
        limit=MESSAGE_WINDOW_LIMIT,
        before_timestamp=None,
        before_message_id=None,
        after_timestamp=None,
        after_message_id=None,
        anchor_message_id="anchor",
        lower_bound_timestamp=None,
    )


# contract-test: supporting surface=rest_api assertions=chats.fork.non-destructive-boundary,chats.persistence.client-encrypted
@pytest.mark.parametrize("title_version", ["missing", None, 0, 4])
@pytest.mark.parametrize("encrypted_title", [None, "cipher-title"])
def test_fork_initializes_missing_title_version_without_rewriting_ciphertext(title_version, encrypted_title):
    from backend.core.api.app.routes.sdk import SdkChatForkRequest, _validate_encrypted_fork_payload

    metadata = {"encrypted_chat_key": "wrapped-key", "encrypted_title": encrypted_title}
    if title_version != "missing":
        metadata["title_v"] = title_version
    payload = SdkChatForkRequest(
        from_message_id="message-2", new_chat_id="fork-chat",
        encrypted_chat_metadata=metadata, encrypted_messages=[{}, {}],
    )
    normalized = _validate_encrypted_fork_payload(payload, 2, "owner-hash")
    assert normalized["title_v"] == (int(bool(encrypted_title)) if title_version in ("missing", None) else title_version)
    assert normalized["encrypted_title"] == encrypted_title
    assert payload.encrypted_chat_metadata == metadata


# contract-test: direct surface=rest_api assertions=teams.context.full-switch-local,teams.membership.role-gated
@pytest.mark.anyio
async def test_personal_chat_read_rejects_team_chat_even_for_its_creator() -> None:
    chat_service = SimpleNamespace(
        check_chat_ownership=AsyncMock(return_value=True),
        get_chat_metadata=AsyncMock(return_value={
            "id": "team-chat", "hashed_team_id": hashlib.sha256(b"team-1").hexdigest(),
            "hashed_user_id": hashlib.sha256(b"creator").hexdigest(),
        }),
        get_all_messages_for_chat=AsyncMock(),
    )
    with pytest.raises(HTTPException) as denied:
        await list_chat_messages(
            chat_id="team-chat", request=_request(chat_service), team_id=None,
            current_user=SimpleNamespace(id="creator"),
        )
    assert denied.value.status_code == 404
    chat_service.get_all_messages_for_chat.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=teams.context.full-switch-local,teams.membership.role-gated
@pytest.mark.anyio
async def test_team_chat_read_rejects_other_team_context_before_reading_messages() -> None:
    chat_service = SimpleNamespace(
        get_chat_metadata=AsyncMock(return_value={
            "id": "team-chat", "hashed_team_id": hashlib.sha256(b"team-1").hexdigest(),
        }),
        get_all_messages_for_chat=AsyncMock(),
    )
    with pytest.raises(HTTPException) as denied:
        await list_chat_messages(
            chat_id="team-chat", request=_request(chat_service), team_id="team-2",
            current_user=SimpleNamespace(id="creator"),
        )
    assert denied.value.status_code == 404
    chat_service.get_all_messages_for_chat.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=teams.chat.sender-identity-layout,teams.context.full-switch-local,chats.persistence.client-encrypted
@pytest.mark.anyio
async def test_team_message_read_preserves_author_hash_without_plaintext_and_checks_membership_first() -> None:
    team_hash = hashlib.sha256(b"team-1").hexdigest()
    author_hash = hashlib.sha256(b"author-1").hexdigest()
    chat_service = SimpleNamespace(
        get_chat_metadata=AsyncMock(return_value={"id": "team-chat", "hashed_team_id": team_hash}),
        get_all_messages_for_chat=AsyncMock(return_value=[{
            "id": "message-1", "chat_id": "team-chat", "role": "user",
            "hashed_user_id": author_hash, "encrypted_content": "cipher-human-message",
            "encrypted_sender_name": "cipher-author", "content": "private text", "sender_name": "Alice",
        }]),
    )
    membership = SimpleNamespace(require_team_role=AsyncMock())
    request = _request(chat_service, team_service=membership)
    result = await list_chat_messages("team-chat", request, team_id="team-1",
                                      current_user=SimpleNamespace(id="member-1"))
    assert result[0]["hashed_user_id"] == author_hash
    assert result[0]["encrypted_content"] == "cipher-human-message"
    assert result[0]["encrypted_sender_name"] == "cipher-author"
    assert "content" not in result[0]
    assert "sender_name" not in result[0]
    membership.require_team_role.assert_awaited_once()
    chat_service.get_all_messages_for_chat.reset_mock()
    chat_service.get_chat_metadata.reset_mock()
    membership.require_team_role.side_effect = HTTPException(status_code=403, detail="Membership required")
    with pytest.raises(HTTPException) as error:
        await list_chat_messages("team-chat", request, team_id="team-1",
                                current_user=SimpleNamespace(id="outsider"))
    assert error.value.status_code == 403
    chat_service.get_chat_metadata.assert_not_awaited()
    chat_service.get_all_messages_for_chat.assert_not_awaited()
