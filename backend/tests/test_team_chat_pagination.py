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
sys.modules.setdefault("backend.core.api.app.services.directus", directus_module)

import pytest  # noqa: E402

from backend.core.api.app.routes.handlers.websocket_handlers.load_more_chats_handler import (  # noqa: E402
    handle_load_more_chats,
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
