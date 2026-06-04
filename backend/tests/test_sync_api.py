# backend/tests/test_sync_api.py
"""Regression tests for optional native/desktop offline sync chunks."""

from types import SimpleNamespace

import pytest

from backend.core.api.app.routes import sync_api
from backend.core.api.app.routes.sync_api import build_offline_prefetch_chunk


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

        async def get_all_messages_for_chat(self, chat_id, decrypt_content=False):
            return [f'{{"id":"msg-{chat_id}","chat_id":"{chat_id}","role":"user","encrypted_content":"cipher","created_at":"2026-01-01T00:00:00Z"}}']

    class FakeDirectusEmbed:
        async def get_embeds_by_hashed_chat_id(self, hashed_chat_id):
            return []

        async def get_embed_keys_by_hashed_chat_ids_batch(self, hashed_chat_ids):
            return []

    class FakeDirectus:
        def __init__(self):
            self.chat = FakeDirectusChat()
            self.embed = FakeDirectusEmbed()

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
        return []

    monkeypatch.setattr(sync_api, "get_latest_chat_compression_checkpoint", fake_checkpoint)
    monkeypatch.setattr(sync_api, "_fetch_code_run_outputs_for_chats", fake_code_outputs)

    response = await build_offline_prefetch_chunk(
        user_id="user-1",
        cursor=10,
        limit=3,
        include_embeds=True,
        cache_service=FakeCache(),
        directus_service=FakeDirectus(),
    )

    assert requested_offsets[0] == 10
    assert [chat["id"] for chat in response.chats] == ["parent-11", "parent-13", "parent-14"]
    assert set(response.messages_by_chat_id) == {"parent-11", "parent-13", "parent-14"}
    assert response.next_cursor == 15
    assert response.done is False


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
