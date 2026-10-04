# backend/tests/test_sync_api.py
"""Regression tests for optional native/desktop offline sync chunks."""

import hashlib

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.core.api.app.routes import sync_api
from backend.core.api.app.routes.sync_api import build_offline_prefetch_chunk


# contract-test: direct surface=rest_api assertions=storage.cold.discoverable-bounded,storage.surface.semantic-parity
@pytest.mark.anyio
async def test_offline_prefetch_starts_after_startup_window_and_excludes_sub_chats(monkeypatch) -> None:
    requested_offsets: list[int] = []

    class FakeDirectusChat:
        async def get_core_chats_and_user_drafts_for_cache_warming(self, user_id, limit=1000, offset=0):
            requested_offsets.append(offset)
            rows = []
            for idx in range(offset, min(offset + limit, 100)):
                is_sub_chat = idx in {10, 12}
                rows.append({
                    "chat_details": {
                        "id": f"{'sub' if is_sub_chat else 'parent'}-{idx}",
                        "parent_id": "parent-0" if is_sub_chat else None,
                        "is_sub_chat": is_sub_chat,
                        "encrypted_title": f"title-{idx}",
                        "encrypted_chat_key": f"key-{idx}",
                        "created_at": "2026-01-01T00:00:00Z",
                    }
                })
            return rows

        async def get_message_count_for_chat(self, chat_id):
            return 1

        async def get_message_window_for_chat(self, **kwargs):
            chat_id = kwargs["chat_id"]
            return {
                "messages": [f'{{"id":"msg-{chat_id}","chat_id":"{chat_id}","role":"user","encrypted_content":"cipher","created_at":1}}'],
                "has_more_before": False,
                "start_cursor": {"created_at": 1, "message_id": f"msg-{chat_id}"},
            }

    class FakeDirectusEmbed:
        async def get_embed_window_by_hashed_chat_id(self, hashed_chat_id, **kwargs):
            return {"embeds": [], "has_more_before": False, "start_cursor": None, "oversized_embed_id": None}

        async def get_sync_embed_key_window_for_page(self, hashed_chat_id, hashed_user_id, hashed_embed_ids):
            return {"embed_keys": [], "has_more_after": False, "end_cursor": None,
                    "oversized_key_id": None, "payload_bytes": 0}

    class FakeDirectusChatKeyWrapper:
        def __init__(self):
            self.calls: list[dict[str, object]] = []

        async def get_sync_wrapper_window_for_chat(self, hashed_chat_id, *, hashed_user_id, before_id=None):
            self.calls.append({"hashed_chat_id": hashed_chat_id, "hashed_user_id": hashed_user_id})
            return {"wrappers": [], "has_more_before": False, "start_cursor": None,
                    "oversized_wrapper_id": None}

    class FakeDirectus:
        def __init__(self):
            self.chat = FakeDirectusChat()
            self.embed = FakeDirectusEmbed()
            self.chat_key_wrapper = FakeDirectusChatKeyWrapper()

    class FakeCache:
        async def get_sync_messages_history(self, user_id, chat_id):
            return []

        async def get_chat_versions(self, user_id, chat_id):
            return SimpleNamespace(messages_v=1)

        async def get_sync_embeds_for_chat(self, chat_id):
            return []

    async def fake_checkpoint(*args, **kwargs):
        return None

    async def fake_code_outputs(*args, **kwargs):
        return [], {}

    monkeypatch.setattr(sync_api, "get_latest_chat_compression_checkpoint", fake_checkpoint)
    monkeypatch.setattr(sync_api, "load_sync_sidecars_for_chats", fake_code_outputs)

    directus = FakeDirectus()
    response = await build_offline_prefetch_chunk(
        user_id="user-1",
        cursor=10,
        limit=3,
        include_embeds=True,
        cache_service=FakeCache(),
        directus_service=directus,
    )

    assert requested_offsets[0] == 10
    assert [chat["id"] for chat in response.chats] == ["parent-11", "parent-13", "parent-14"]
    assert set(response.messages_by_chat_id) == {"parent-11", "parent-13", "parent-14"}
    assert response.chat_key_wrappers == []
    assert directus.chat_key_wrapper.calls == [
        {"hashed_chat_id": hashlib.sha256(chat_id.encode()).hexdigest(),
         "hashed_user_id": hashlib.sha256("user-1".encode()).hexdigest()}
        for chat_id in ["parent-11", "parent-13", "parent-14"]
    ]
    assert response.next_cursor == 15
    assert response.done is False


# contract-test: supporting surface=rest_api assertions=storage.cold.discoverable-bounded
@pytest.mark.anyio
async def test_offline_prefetch_done_after_last_allowed_cursor() -> None:
    response = await build_offline_prefetch_chunk(
        user_id="user-1",
        cursor=100,
        limit=3,
        include_embeds=True,
        cache_service=SimpleNamespace(),
        directus_service=SimpleNamespace(),
    )

    assert response.chats == []
    assert response.next_cursor is None
    assert response.done is True


# contract-test: direct surface=rest_api assertions=storage.cold.independent-message-pages
@pytest.mark.anyio
async def test_offline_prefetch_refetches_directus_when_sync_cache_is_partial(monkeypatch) -> None:
    class FakeDirectusChat:
        async def get_core_chats_and_user_drafts_for_cache_warming(self, user_id, limit=1000, offset=0):
            return [{
                "chat_details": {
                    "id": "parent-10",
                    "parent_id": None,
                    "is_sub_chat": False,
                    "encrypted_title": "title-10",
                    "encrypted_chat_key": "key-10",
                    "created_at": "2026-01-01T00:00:00Z",
                }
            }]

        async def get_message_count_for_chat(self, chat_id):
            return 2

        async def get_message_window_for_chat(self, **kwargs):
            return {
                "messages": ["directus-user-message", "directus-assistant-message"],
                "has_more_before": False,
                "start_cursor": {"created_at": 1, "message_id": "msg-1"},
            }

    class FakeDirectusEmbed:
        async def get_embed_window_by_hashed_chat_id(self, hashed_chat_id, **kwargs):
            return {"embeds": [], "has_more_before": False, "start_cursor": None, "oversized_embed_id": None}

        async def get_sync_embed_key_window_for_page(self, hashed_chat_id, hashed_user_id, hashed_embed_ids):
            return {"embed_keys": [], "has_more_after": False, "end_cursor": None,
                    "oversized_key_id": None, "payload_bytes": 0}

    class FakeDirectusChatKeyWrapper:
        async def get_sync_wrapper_window_for_chat(self, hashed_chat_id, *, hashed_user_id, before_id=None):
            return {"wrappers": [], "has_more_before": False, "start_cursor": None,
                    "oversized_wrapper_id": None}

    class FakeDirectus:
        def __init__(self):
            self.chat = FakeDirectusChat()
            self.embed = FakeDirectusEmbed()
            self.chat_key_wrapper = FakeDirectusChatKeyWrapper()

    class FakeCache:
        async def get_sync_messages_history(self, user_id, chat_id):
            return ["cached-user-message"]

        async def get_chat_versions(self, user_id, chat_id):
            return SimpleNamespace(messages_v=3)

        async def get_sync_embeds_for_chat(self, chat_id):
            return []

    async def fake_checkpoint(*args, **kwargs):
        return None

    async def fake_code_outputs(*args, **kwargs):
        return [], {}

    monkeypatch.setattr(sync_api, "get_latest_chat_compression_checkpoint", fake_checkpoint)
    monkeypatch.setattr(sync_api, "load_sync_sidecars_for_chats", fake_code_outputs)

    response = await build_offline_prefetch_chunk(
        user_id="user-1",
        cursor=10,
        limit=1,
        include_embeds=True,
        cache_service=FakeCache(),
        directus_service=FakeDirectus(),
    )

    assert response.messages_by_chat_id["parent-10"] == [
        "directus-user-message",
        "directus-assistant-message",
    ]
    assert response.versions_by_chat_id["parent-10"] == {
        "messages_v": 3,
        "server_message_count": 2,
    }
    assert response.message_windows_by_chat_id["parent-10"]["has_more_before"] is False


# contract-test: direct surface=rest_api assertions=storage.cold.independent-message-pages,storage.cold.shared-team-authorized
@pytest.mark.anyio
async def test_offline_prefetch_message_continuation_is_owner_scoped_and_cursor_bounded() -> None:
    class FakeChat:
        def __init__(self):
            self.before = None

        async def check_chat_ownership(self, chat_id, user_id):
            return chat_id == "owned" and user_id == "user-1"

        async def get_message_window_for_chat(self, **kwargs):
            self.before = (kwargs["before_timestamp"], kwargs["before_message_id"])
            return {
                "messages": ['{"id":"old","message_id":"old","created_at":1}'],
                "has_more_before": False,
                "start_cursor": {"created_at": 1, "message_id": "old"},
            }

        async def get_message_count_for_chat(self, chat_id):
            return 2

    chat = FakeChat()
    directus = SimpleNamespace(chat=chat)
    response = await build_offline_prefetch_chunk(
        user_id="user-1",
        cursor=10,
        limit=1,
        include_embeds=False,
        cache_service=SimpleNamespace(),
        directus_service=directus,
        message_chat_id="owned",
        before_timestamp=2,
        before_message_id="new",
    )
    assert chat.before == (2, "new")
    assert response.messages_by_chat_id["owned"] == ['{"id":"old","message_id":"old","created_at":1}']
    assert response.message_windows_by_chat_id["owned"]["start_cursor"]["message_id"] == "old"

    with pytest.raises(HTTPException) as denied:
        await build_offline_prefetch_chunk(
            user_id="user-1",
            cursor=10,
            limit=1,
            include_embeds=False,
            cache_service=SimpleNamespace(),
            directus_service=directus,
            message_chat_id="someone-elses-chat",
            before_timestamp=2,
            before_message_id="new",
        )
    assert denied.value.status_code == 404


# contract-test: direct surface=rest_api assertions=storage.cold.discoverable-bounded,storage.privacy.ciphertext-boundary
@pytest.mark.anyio
async def test_offline_prefetch_embed_continuation_scopes_keys_to_selected_page() -> None:
    class FakeChat:
        async def check_chat_ownership(self, chat_id, user_id):
            return chat_id == "owned" and user_id == "user-1"

    class FakeEmbed:
        def __init__(self):
            self.window_call = None
            self.key_call = None

        async def get_embed_window_by_hashed_chat_id(self, hashed_chat_id, **kwargs):
            self.window_call = (hashed_chat_id, kwargs)
            return {
                "embeds": [{"id": "row-1", "embed_id": "embed-1", "created_at": 1}],
                "has_more_before": True,
                "start_cursor": {"created_at": 1, "id": "row-1"},
                "oversized_embed_id": None,
            }

        async def get_sync_embed_key_window_for_page(self, hashed_chat_id, hashed_user_id, hashed_embed_ids):
            self.key_call = (hashed_chat_id, hashed_user_id, hashed_embed_ids)
            return {"embed_keys": [{"id": "key-1"}], "has_more_after": False,
                    "end_cursor": "key-1", "oversized_key_id": None, "payload_bytes": 1}

    embed = FakeEmbed()
    response = await build_offline_prefetch_chunk(
        user_id="user-1",
        cursor=10,
        limit=1,
        include_embeds=True,
        cache_service=SimpleNamespace(),
        directus_service=SimpleNamespace(chat=FakeChat(), embed=embed),
        embed_chat_id="owned",
        before_embed_created_at=2,
        before_embed_id="row-2",
    )
    assert embed.window_call == (
        hashlib.sha256(b"owned").hexdigest(),
        {"before_created_at": 2, "before_id": "row-2"},
    )
    assert embed.key_call[2] == [hashlib.sha256(b"embed-1").hexdigest()]
    assert response.embed_windows_by_chat_id["owned"]["has_more_before"] is True
