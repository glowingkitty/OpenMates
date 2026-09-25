"""Focused regressions for on-demand chat content hydration."""

import pytest

from backend.core.api.app.routes.handlers.websocket_handlers.chat_content_batch_handler import (
    _fetch_complete_embeds_for_chat,
)


# contract-test: supporting surface=gui.apple assertions=videos.transcript.surface-parity
@pytest.mark.anyio
async def test_partial_embed_cache_merges_authoritative_parent_and_child() -> None:
    class FakeCache:
        async def get_sync_embeds_for_chat(self, chat_id):
            assert chat_id == "chat-1"
            return [
                {
                    "embed_id": "parent-1",
                    "status": "processing",
                    "embed_ids": None,
                    "encrypted_content": "stale-parent",
                },
                {
                    "embed_id": "live-cache-only",
                    "status": "processing",
                    "encrypted_content": "pending-persistence",
                },
            ]

    class FakeDirectusEmbed:
        async def get_embeds_by_hashed_chat_id(self, hashed_chat_id):
            assert hashed_chat_id == "hashed-chat-1"
            return [
                {
                    "embed_id": "parent-1",
                    "status": "finished",
                    "embed_ids": ["child-1"],
                    "encrypted_content": "final-parent",
                },
                {
                    "embed_id": "child-1",
                    "status": "finished",
                    "parent_embed_id": "parent-1",
                    "encrypted_content": "transcript-child",
                },
            ]

    class FakeDirectus:
        embed = FakeDirectusEmbed()

    embeds = await _fetch_complete_embeds_for_chat(
        FakeCache(),
        FakeDirectus(),
        "chat-1",
        "hashed-chat-1",
    )
    by_id = {embed["embed_id"]: embed for embed in embeds}

    assert set(by_id) == {"parent-1", "child-1", "live-cache-only"}
    assert by_id["parent-1"]["status"] == "finished"
    assert by_id["parent-1"]["embed_ids"] == ["child-1"]
    assert by_id["child-1"]["parent_embed_id"] == "parent-1"


# contract-test: supporting surface=gui.apple assertions=videos.transcript.surface-parity
@pytest.mark.anyio
async def test_cached_embeds_remain_available_when_persisted_read_fails() -> None:
    cached = {"embed_id": "cached-1", "status": "finished"}

    class FakeCache:
        async def get_sync_embeds_for_chat(self, chat_id):
            return [cached]

    class FailingDirectusEmbed:
        async def get_embeds_by_hashed_chat_id(self, hashed_chat_id):
            raise RuntimeError("unavailable")

    class FakeDirectus:
        embed = FailingDirectusEmbed()

    embeds = await _fetch_complete_embeds_for_chat(
        FakeCache(),
        FakeDirectus(),
        "chat-1",
        "hashed-chat-1",
    )

    assert embeds == [cached]
