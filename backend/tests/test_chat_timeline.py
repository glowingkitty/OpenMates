"""Bounded identity discovery and the existing first-party/share boundaries."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, Response

from backend.core.api.app.services.chat_timeline import timeline_page
from backend.core.api.app.services.directus.chat_methods import ChatMethods
from backend.core.api.app.routes import chats, share


def row(identity, timestamp, role="user", **extra):
    return {"id": f"db-{identity}", "client_message_id": identity, "chat_id": "chat-1",
            "created_at": timestamp, "role": role, **extra}

def reader(rows):
    return SimpleNamespace(chat=SimpleNamespace(get_message_timeline_metadata=AsyncMock(return_value=rows)))


# contract-test: supporting surface=gui.web assertions=chat-message-timeline.full-history-loading,chat-message-timeline.access-and-lifecycle
@pytest.mark.anyio
async def test_internal_metadata_reader_preserves_legacy_ids_and_uses_the_fixed_projection(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "isolated-unit-token")
    response = SimpleNamespace(status_code=200, json=lambda: {"data": {"messages": [
        {"id": "legacy-id", "client_message_id": None, "chat_id": "chat-1", "created_at": 10, "role": "user"}]}})
    directus = SimpleNamespace(base_url="http://isolated.invalid", _make_api_request=AsyncMock(return_value=response))
    result = await ChatMethods(directus).get_message_timeline_metadata(
        "chat-1", before_timestamp=10, before_message_id="same-time-user", limit=999)
    assert result[0]["message_id"] == "legacy-id"
    directus._make_api_request.assert_awaited_once_with(
        "POST", "http://isolated.invalid/chat-archive-transaction", headers={"X-Internal-Service-Token": "isolated-unit-token"},
        json={"operation": "hot_message_timeline", "data": {"chat_id": "chat-1", "direction": "before", "limit": 201,
            "cursor_timestamp": 10, "cursor_message_id": "same-time-user", "lower_bound_timestamp": None}})


# contract-test: supporting surface=gui.web assertions=chat-message-timeline.full-history-loading,chat-message-timeline.access-and-lifecycle
@pytest.mark.anyio
async def test_catalogue_uses_metadata_only_and_keeps_a_stable_tie_cursor():
    directus = reader([
        row("d", 10, encrypted_content="must-not-leak"), row("c", 10, "assistant", user_message_id="b"), row("b", 10),
    ])
    result = await timeline_page(directus=directus, s3=None, chat_id="chat-1", archived=False,
                                 before_timestamp=11, before_message_id="a", limit=2)
    assert [item["message_id"] for item in result["entries"]] == ["c", "d"]
    assert result["before"] == {"created_at": 10, "message_id": "c"}
    assert result["has_more"] is True
    assert "encrypted_content" not in str(result)
    directus.chat.get_message_timeline_metadata.assert_awaited_once_with(
        "chat-1", before_timestamp=11, before_message_id="a", limit=3)


# contract-test: supporting surface=gui.web assertions=chat-message-timeline.full-history-loading,chat-message-timeline.compression-history
@pytest.mark.anyio
async def test_cold_and_hot_overlap_is_deduplicated_without_a_full_history_read(monkeypatch):
    archive = SimpleNamespace(read_before=AsyncMock(return_value={
        "messages": [row("a", 1), row("b", 2, "assistant")], "has_more_before": False,
    }), hydrate_records=AsyncMock())
    monkeypatch.setattr("backend.core.api.app.services.chat_timeline.ChatMessageArchiveService", lambda **kwargs: archive)
    directus = reader([row("b", 2, "assistant"), row("c", 3)])
    result = await timeline_page(directus=directus, s3=None, chat_id="chat-1", archived=True,
                                 before_timestamp=None, before_message_id=None)
    assert [item["message_id"] for item in result["entries"]] == ["a", "b", "c"]
    assert result["has_more"] is False
    archive.read_before.assert_awaited_once_with(chat_id="chat-1", before=None, limit=20)
    archive.hydrate_records.assert_not_awaited()


# contract-test: supporting surface=gui.web assertions=chat-message-timeline.full-history-loading,chat-message-timeline.compression-history
@pytest.mark.anyio
async def test_legacy_archive_catalogue_has_a_fixed_metadata_page_budget(monkeypatch):
    pages = [{"messages": [row(str(value), value) for value in range(200 - i * 20, 220 - i * 20)],
              "has_more_before": True} for i in range(10)]
    archive = SimpleNamespace(read_before=AsyncMock(side_effect=pages), hydrate_records=AsyncMock())
    monkeypatch.setattr("backend.core.api.app.services.chat_timeline.ChatMessageArchiveService", lambda **kwargs: archive)
    directus = reader([])
    result = await timeline_page(directus=directus, s3=None, chat_id="chat-1", archived=True,
                                 before_timestamp=None, before_message_id=None)
    assert len(result["entries"]) == 200 and result["has_more"] is True
    assert archive.read_before.await_count == 10
    assert all(call.kwargs["limit"] == 20 for call in archive.read_before.await_args_list)


# contract-test: supporting surface=gui.web assertions=chat-message-timeline.full-history-loading,chat-message-timeline.compression-history
@pytest.mark.anyio
async def test_multiple_large_archived_messages_advance_without_exceeding_the_byte_budget(monkeypatch):
    def stub(identity, timestamp):
        return {"id": f"db-{identity}", "client_message_id": identity, "chat_id": "chat-1", "created_at": timestamp,
                "large_payload": {"size_bytes": 1500000}}
    oldest, newest = stub("a", 1), stub("c", 3)
    archive = SimpleNamespace(read_before=AsyncMock(side_effect=[
        {"messages": [oldest, row("b", 2), newest, row("d", 4)], "has_more_before": False},
        {"messages": [oldest], "has_more_before": False},
    ]), hydrate_records=AsyncMock(side_effect=lambda rows: [{**value, "role": "user"} for value in rows]))
    monkeypatch.setattr("backend.core.api.app.services.chat_timeline.ChatMessageArchiveService", lambda **kwargs: archive)
    directus = reader([])
    first = await timeline_page(directus=directus, s3=None, chat_id="chat-1", archived=True,
                                before_timestamp=None, before_message_id=None)
    assert [value["message_id"] for value in first["entries"]] == ["b", "c", "d"]
    assert first["has_more"] and first["before"] == {"created_at": 2, "message_id": "b"}
    second = await timeline_page(directus=directus, s3=None, chat_id="chat-1", archived=True,
                                 before_timestamp=2, before_message_id="b")
    assert [value["message_id"] for value in second["entries"]] == ["a"]
    assert second["has_more"] is False
    assert archive.hydrate_records.await_count == 2
    assert all(len(call.args[0]) == 1 for call in archive.hydrate_records.await_args_list)


# contract-test: supporting surface=gui.web assertions=chat-message-timeline.access-and-lifecycle
@pytest.mark.anyio
async def test_foreign_catalogue_rows_fail_closed():
    directus = reader([row("a", 1, chat_id="foreign-chat")])
    with pytest.raises(ValueError, match="TIMELINE_IDENTITY_UNAVAILABLE"):
        await timeline_page(directus=directus, s3=None, chat_id="chat-1", archived=False,
                            before_timestamp=None, before_message_id=None)


# contract-test: supporting surface=gui.web assertions=chat-message-timeline.access-and-lifecycle
@pytest.mark.anyio
async def test_private_route_checks_access_before_catalogue(monkeypatch):
    denied = AsyncMock(side_effect=HTTPException(status_code=404, detail="Chat not found"))
    catalogue = AsyncMock()
    monkeypatch.setattr(chats, "_require_chat_read_access", denied)
    monkeypatch.setattr(chats, "timeline_page", catalogue)
    with pytest.raises(HTTPException) as error:
        await chats.get_chat_timeline.__wrapped__(request=SimpleNamespace(), chat_id="chat-1", response=Response(),
            before_timestamp=None, before_message_id=None, team_id="team-1", current_user=SimpleNamespace(id="viewer"))
    assert error.value.status_code == 404
    denied.assert_awaited_once()
    catalogue.assert_not_awaited()


# contract-test: supporting surface=gui.web assertions=chat-message-timeline.access-and-lifecycle
@pytest.mark.anyio
async def test_revoked_share_never_reads_catalogue_or_section(monkeypatch):
    monkeypatch.setattr(share, "get_shared_chat_or_dummy", AsyncMock(return_value=(None, {"messages": []})))
    directus = SimpleNamespace(chat=SimpleNamespace(get_message_timeline_metadata=AsyncMock(), get_message_window_for_chat=AsyncMock()))
    kwargs = dict(request=SimpleNamespace(), chat_id="chat-1", response=Response(), directus_service=directus)
    page = await share.get_shared_chat_timeline.__wrapped__(**kwargs, before_timestamp=None, before_message_id=None)
    section = await share.get_shared_chat_section.__wrapped__(**kwargs, message_id="message-1")
    assert page["entries"] == [] and page["has_more"] is False
    assert section["messages"] == [] and section["anchor_found"] is False
    directus.chat.get_message_timeline_metadata.assert_not_awaited()
    directus.chat.get_message_window_for_chat.assert_not_awaited()
