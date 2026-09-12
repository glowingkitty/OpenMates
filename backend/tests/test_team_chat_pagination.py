"""Team-scoped WebSocket chat pagination tests.

These tests keep older-chat and metadata pagination out of the Personal Redis
index when a Team context is active. Responses must echo the client context so
the browser can reject stale work after an atomic context switch.
"""

import sys
import types
from types import SimpleNamespace

if "redis.asyncio" not in sys.modules:
    redis_module = types.ModuleType("redis")
    redis_asyncio_module = types.ModuleType("redis.asyncio")
    redis_asyncio_module.Redis = object
    redis_module.asyncio = redis_asyncio_module
    redis_module.exceptions = SimpleNamespace(
        RedisError=Exception,
        ConnectionError=Exception,
        TimeoutError=Exception,
    )
    sys.modules["redis"] = redis_module
    sys.modules["redis.asyncio"] = redis_asyncio_module

directus_module = types.ModuleType("backend.core.api.app.services.directus")
directus_module.DirectusService = object
sys.modules["backend.core.api.app.services.directus"] = directus_module

import pytest  # noqa: E402

from backend.core.api.app.routes.handlers.websocket_handlers.load_more_chats_handler import (  # noqa: E402
    handle_load_more_chats,
    _fetch_chats_from_directus_paginated,
)
from backend.core.api.app.routes.handlers.websocket_handlers.sync_metadata_chats_handler import (  # noqa: E402
    handle_sync_metadata_chats,
)


class FakeManager:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_personal_message(self, message, user_id, device_fingerprint_hash) -> None:
        self.sent.append(message)


class FakeTeam:
    def __init__(self) -> None:
        self.required: list[tuple[str, str, set[str]]] = []

    async def require_team_role(self, team_id, user_id, roles) -> None:
        self.required.append((team_id, user_id, roles))


class FakeChat:
    def __init__(self, count: int) -> None:
        self.count = count
        self.scopes: list[str | None] = []

    async def get_user_chat_count(self, user_id, team_id=None) -> int:
        self.scopes.append(team_id)
        return self.count

    async def get_core_chats_and_user_drafts_for_cache_warming(
        self, user_id, *, limit, offset, team_id=None
    ) -> list[dict]:
        self.scopes.append(team_id)
        return [{"chat_details": {"id": "team-chat", "encrypted_chat_key": "cipher"}}]


class NoPersonalCache:
    async def get_user_draft_from_cache(self, **kwargs):
        return None

    async def get_chat_ids_versions(self, *args, **kwargs):
        raise AssertionError("Team pagination must not read the Personal chat cache")


def directus(count: int):
    return SimpleNamespace(team=FakeTeam(), chat=FakeChat(count))


# contract-test: direct surface=rest_api assertions=teams.context.full-switch-local,teams.collaboration.realtime-team-sync
@pytest.mark.anyio
async def test_load_more_chats_uses_exact_team_scope_and_echoes_context() -> None:
    manager = FakeManager()
    service = directus(101)

    await handle_load_more_chats(
        websocket=None,
        manager=manager,
        cache_service=NoPersonalCache(),
        directus_service=service,
        encryption_service=None,
        user_id="user-1",
        device_fingerprint_hash="device-1",
        payload={"offset": 100, "limit": 20, "team_id": "team-1", "context_epoch": 4},
    )

    assert service.chat.scopes == ["team-1", "team-1"]
    assert service.team.required[0][:2] == ("team-1", "user-1")
    assert manager.sent[-1]["payload"]["team_id"] == "team-1"
    assert manager.sent[-1]["payload"]["context_epoch"] == 4


# contract-test: direct surface=rest_api assertions=teams.context.full-switch-local,teams.collaboration.realtime-team-sync
@pytest.mark.anyio
async def test_metadata_chat_sync_uses_exact_team_scope_and_echoes_context() -> None:
    manager = FakeManager()
    service = directus(102)

    await handle_sync_metadata_chats(
        websocket=None,
        manager=manager,
        cache_service=NoPersonalCache(),
        directus_service=service,
        encryption_service=None,
        user_id="user-1",
        device_fingerprint_hash="device-1",
        payload={"team_id": "team-1", "context_epoch": 5, "existing_chat_ids": []},
    )

    assert service.chat.scopes == ["team-1", "team-1"]
    assert service.team.required[0][:2] == ("team-1", "user-1")
    assert manager.sent[-1]["payload"]["team_id"] == "team-1"
    assert manager.sent[-1]["payload"]["context_epoch"] == 5


# contract-test: direct surface=rest_api assertions=sync.surface.semantic-parity
@pytest.mark.anyio
async def test_personal_pagination_ignores_sparse_draft_only_cache() -> None:
    class SparseCache:
        async def get_user_draft_from_cache(self, **kwargs):
            return None

        async def get_chat_ids_versions(self, *args, **kwargs):
            return ["draft-without-persisted-chat"]

        async def get_batch_chat_list_item_data(self, *args):
            return {}

        async def get_batch_chat_versions(self, *args):
            return {}

    class PersistedChatPage(FakeChat):
        async def get_chat_metadata(self, chat_id):
            return None  # Draft-only cache IDs do not own a persisted chat row.

        async def get_core_chats_and_user_drafts_for_cache_warming(
            self, user_id, *, limit, offset, team_id=None
        ):
            self.scopes.append(team_id)
            assert offset == 0 and limit == 20
            return [{"chat_details": {"id": "persisted-personal-chat"}}]

    manager = FakeManager()
    service = SimpleNamespace(team=FakeTeam(), chat=PersistedChatPage(425))
    await handle_load_more_chats(
        websocket=None, manager=manager, cache_service=SparseCache(),
        directus_service=service, encryption_service=None,
        user_id="user-1", device_fingerprint_hash="device-1",
        payload={"offset": 0, "limit": 20, "context_epoch": 0},
    )
    payload = manager.sent[-1]["payload"]
    assert [item["chat_details"]["id"] for item in payload["chats"]] == ["persisted-personal-chat"]
    assert payload["total_count"] == 425
    assert payload["has_more"] is True
    assert payload["context_epoch"] == 0
    assert payload["team_id"] is None
    assert service.chat.scopes == [None, None]


# contract-test: supporting surface=rest_api assertions=sync.surface.semantic-parity,drafts.sync.version-authoritative
@pytest.mark.anyio
async def test_paginated_draft_metadata_preserves_scoped_ciphertext_without_mutating_source() -> None:
    source = [{
        "chat_details": {"id": "older-chat", "encrypted_title": "title", "messages_v": 6},
        "user_encrypted_draft_content": "encrypted-draft", "user_draft_version_db": 4,
    }]
    calls = []

    class ChatPage:
        async def get_core_chats_and_user_drafts_for_cache_warming(self, user_id, **kwargs):
            calls.append((user_id, kwargs)); return source

    result = await _fetch_chats_from_directus_paginated(SimpleNamespace(chat=ChatPage()), "owner",
        100, 50, team_id="team", cache_service=NoPersonalCache())
    assert calls == [("owner", {"limit": 50, "offset": 100, "team_id": "team"})]
    assert result[0]["chat_details"] == {
        "id": "older-chat", "encrypted_title": "title", "messages_v": 6,
        "encrypted_draft_md": "encrypted-draft", "encrypted_draft_preview": None, "draft_v": 4,
    }
    assert result[0]["messages"] is None and result[0]["server_message_count"] is None
    assert "user_encrypted_draft_content" not in result[0]
    assert "draft_v" not in source[0]["chat_details"]


# contract-test: supporting surface=rest_api assertions=sync.surface.semantic-parity,drafts.sync.version-authoritative
@pytest.mark.anyio
@pytest.mark.parametrize("content,version", [(None, 9), ("", 3), ("null", 5), ("encrypted", 0)])
async def test_paginated_empty_or_deleted_draft_is_authoritatively_cleared(content, version) -> None:
    class ChatPage:
        async def get_core_chats_and_user_drafts_for_cache_warming(self, user_id, **kwargs):
            return [{"chat_details": {"id": "chat", "draft_v": 12, "encrypted_draft_md": "stale"},
                     "user_encrypted_draft_content": content, "user_draft_version_db": version}]
    result = await _fetch_chats_from_directus_paginated(SimpleNamespace(chat=ChatPage()), "owner", 100, 20)
    assert result[0]["chat_details"]["draft_v"] == 0
    assert result[0]["chat_details"]["encrypted_draft_md"] is None
    assert result[0]["chat_details"]["encrypted_draft_preview"] is None


# contract-test: supporting surface=rest_api assertions=sync.surface.semantic-parity,drafts.sync.version-authoritative
@pytest.mark.anyio
@pytest.mark.parametrize("cached,tombstone,expected_md,expected_v,cleared_v", [
    (("new", 6, "preview"), False, "new", 6, None),
    ((None, 7, None), True, None, 0, 7),
    (("old", 2, "old-preview"), False, "database", 4, None),
])
async def test_paginated_draft_uses_newer_scoped_cache_and_deletion_tombstone(cached, tombstone, expected_md, expected_v, cleared_v) -> None:
    class ChatPage:
        async def get_core_chats_and_user_drafts_for_cache_warming(self, user_id, **kwargs):
            return [{"chat_details": {"id": "chat"}, "user_encrypted_draft_content": "database", "user_draft_version_db": 4}]
    class DraftCache:
        async def get_user_draft_from_cache(self, *, user_id, chat_id):
            assert (user_id, chat_id) == ("owner", "chat"); return cached
        async def is_user_draft_tombstoned(self, user_id, chat_id):
            assert (user_id, chat_id) == ("owner", "chat"); return tombstone
    result = await _fetch_chats_from_directus_paginated(SimpleNamespace(chat=ChatPage()), "owner", 100, 20, cache_service=DraftCache())
    details = result[0]["chat_details"]
    assert details["encrypted_draft_md"] == expected_md
    assert details["draft_v"] == expected_v
    assert details.get("cleared_draft_v") == cleared_v


# contract-test: supporting surface=rest_api assertions=sync.surface.semantic-parity
@pytest.mark.anyio
async def test_paginated_draft_cache_failure_is_reported_instead_of_returning_stale_priority() -> None:
    class ChatPage:
        async def get_core_chats_and_user_drafts_for_cache_warming(self, user_id, **kwargs):
            return [{"chat_details": {"id": "chat"}, "user_encrypted_draft_content": "old", "user_draft_version_db": 1}]
    class BrokenCache:
        async def get_user_draft_from_cache(self, **kwargs):
            raise RuntimeError("fixture cache unavailable")
    with pytest.raises(RuntimeError, match="fixture cache unavailable"):
        await _fetch_chats_from_directus_paginated(SimpleNamespace(chat=ChatPage()), "owner", 100, 20, cache_service=BrokenCache())
