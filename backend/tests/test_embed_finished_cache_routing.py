# contract-test-file: infrastructure
"""Finished-embed cache keeps live routing identity for replays (issue BMKRJ).

Pending-embed replays rebuild send_embed_data from the finished cache. Without
app_id/skill_id there, a replayed child fell back to its parent's skill_id and
the web client rejected it as a canonical revision conflict.
"""
from types import SimpleNamespace

import pytest

from backend.core.api.app.services.embed_service import EmbedService


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("live_routing", "cached_routing", "expected"),
    [
        ({"app_id": "news", "skill_id": "website"}, {}, {"app_id": "news", "skill_id": "website"}),
        ({}, {}, {}),
        # An explicit cache value is never overwritten by the published payload.
        ({"app_id": "news", "skill_id": "website"}, {"skill_id": "custom"}, {"app_id": "news", "skill_id": "custom"}),
    ],
)
async def test_finished_cache_records_live_routing_identity(live_routing, cached_routing, expected) -> None:
    service = EmbedService.__new__(EmbedService)
    cached: dict = {}
    published: list = []

    async def cache_embed(embed_id, data, chat_id, user_id_hash, vault_key_id, user_id):
        cached.update(data)

    async def allow(_user_id_hash):
        return None

    async def track(*_args):
        return None

    class Client:
        async def publish(self, channel, message):
            published.append(channel)

    async def client():
        return Client()

    service._cache_embed = cache_embed
    service._require_finished_publication_authority = allow
    service._track_pending_embed = track
    service._volatile_incognito_publication_required = lambda: False
    service.cache_service = SimpleNamespace(client=client())

    finished = {"embed_id": "child-1", "status": "finished", "chat_id": "chat-1",
                "message_id": "message-1", "type": "website", "parent_embed_id": "parent-1", **cached_routing}
    payload = {"payload": {"embed_id": "child-1", "chat_id": "chat-1", "message_id": "message-1",
                           "user_id": "owner-1", "status": "finished", "type": "website", **live_routing}}

    assert await service._publish_prepared_embed(
        payload, user_id_hash="hash-1", finished_cache_data=finished,
        finished_cache_vault_key_id="vault-1", log_prefix="[test]", required_delivery=True,
    )
    assert {key: cached[key] for key in ("app_id", "skill_id") if key in cached} == expected
    assert cached["parent_embed_id"] == "parent-1"
    assert published == ["websocket:user:hash-1"]
