"""
Tests for windowed shared-chat loading endpoints.

Large shared-chat fixtures are synthetic Directus rows. These tests must never
trigger AI inference to create or exercise long chats.
"""

import json
import importlib
import sys
import types

import pytest


class _StubLimiter:
    def limit(self, _rule: str):
        def decorator(func):
            return func
        return decorator


directus_stub = types.ModuleType("backend.core.api.app.services.directus")
directus_stub.DirectusService = object
encryption_stub = types.ModuleType("backend.core.api.app.utils.encryption")
encryption_stub.EncryptionService = object
cache_stub = types.ModuleType("backend.core.api.app.services.cache")
cache_stub.CacheService = object
limiter_stub = types.ModuleType("backend.core.api.app.services.limiter")
limiter_stub.limiter = _StubLimiter()
auth_deps_stub = types.ModuleType("backend.core.api.app.routes.auth_routes.auth_dependencies")
auth_deps_stub.get_current_user = lambda: None
user_stub = types.ModuleType("backend.core.api.app.models.user")
user_stub.User = object

sys.modules.setdefault("backend.core.api.app.services.directus", directus_stub)
sys.modules.setdefault("backend.core.api.app.utils.encryption", encryption_stub)
sys.modules.setdefault("backend.core.api.app.services.cache", cache_stub)
sys.modules.setdefault("backend.core.api.app.services.limiter", limiter_stub)
sys.modules.setdefault("backend.core.api.app.routes.auth_routes.auth_dependencies", auth_deps_stub)
sys.modules.setdefault("backend.core.api.app.models.user", user_stub)

share_routes = importlib.import_module("backend.core.api.app.routes.share")
get_shared_chat_manifest = share_routes.get_shared_chat_manifest
get_shared_chat_message_window = share_routes.get_shared_chat_message_window


class FakeEmbedMethods:
    async def get_embeds_by_hashed_chat_id(self, hashed_chat_id: str):
        return [{"embed_id": "parent-1", "hashed_chat_id": hashed_chat_id}]

    async def get_embed_keys_by_hashed_chat_id(self, hashed_chat_id: str, include_master_keys: bool = False):
        assert include_master_keys is False
        return [{"hashed_chat_id": hashed_chat_id, "key_type": "chat"}]


class FakeChatMethods:
    def __init__(self) -> None:
        self.messages = [
            {
                "id": f"db-{index}",
                "client_message_id": f"msg-{index}",
                "chat_id": "chat-shared",
                "role": "assistant" if index % 2 == 0 else "user",
                "created_at": index,
                "encrypted_content": f"cipher-{index}",
                "encrypted_pii_mappings": "private-pii",
            }
            for index in range(1, 121)
        ]
        self.requested_limits: list[int] = []

    async def get_chat_metadata(self, chat_id: str, admin_required: bool = False):
        if chat_id == "missing-chat":
            return None
        return {
            "id": chat_id,
            "encrypted_title": "encrypted-title",
            "encrypted_chat_summary": "encrypted-summary",
            "encrypted_icon": "encrypted-icon",
            "encrypted_category": "encrypted-category",
            "is_private": False,
            "share_pii": False,
            "share_highlights": True,
        }

    async def get_messages_for_chat_before_timestamp(
        self,
        chat_id: str,
        before_timestamp: int,
        before_message_id: str | None = None,
        limit: int = 100,
    ):
        self.requested_limits.append(limit)
        rows = [
            row
            for row in self.messages
            if row["chat_id"] == chat_id and row["created_at"] <= before_timestamp
        ]
        if before_message_id:
            rows = [
                row
                for row in rows
                if row["created_at"] < before_timestamp
                or (
                    row["created_at"] == before_timestamp
                    and row["client_message_id"] < before_message_id
                )
            ]
        rows = sorted(rows, key=lambda row: (row["created_at"], row["client_message_id"]), reverse=True)[:limit]
        rows.reverse()
        return [json.dumps({**row, "message_id": row["client_message_id"]}) for row in rows]

    async def get_message_for_chat_by_client_id(self, chat_id: str, message_id: str):
        return next(
            (
                row
                for row in self.messages
                if row["chat_id"] == chat_id
                and (row["client_message_id"] == message_id or row["id"] == message_id)
            ),
            None,
        )


class FakeDirectusService:
    def __init__(self) -> None:
        self.chat = FakeChatMethods()
        self.embed = FakeEmbedMethods()

    async def get_items(self, collection: str, params: dict, admin_required: bool = False):
        if collection == "message_highlights":
            return [{"id": "highlight-1", "chat_id": "chat-shared"}]
        if collection == "code_run_outputs":
            return []
        if collection == "chats":
            return []
        return []


@pytest.mark.asyncio
async def test_shared_chat_manifest_omits_full_messages():
    directus = FakeDirectusService()

    payload = await get_shared_chat_manifest(
        request=None,
        chat_id="chat-shared",
        directus_service=directus,
    )

    assert payload["chat_id"] == "chat-shared"
    assert payload["messages"] == []
    assert payload["embeds"]
    assert payload["embed_keys"]
    assert payload["message_highlights"]


@pytest.mark.asyncio
async def test_shared_chat_message_window_is_bounded_and_sanitized():
    directus = FakeDirectusService()

    payload = await get_shared_chat_message_window(
        request=None,
        chat_id="chat-shared",
        before_timestamp=100,
        limit=10,
        directus_service=directus,
    )

    assert directus.chat.requested_limits == [11]
    assert len(payload["messages"]) == 10
    assert payload["has_more"] is True
    assert payload["next_before_timestamp"] == 91
    assert payload["next_before_message_id"] == "msg-91"
    assert "encrypted_pii_mappings" not in payload["messages"][0]


@pytest.mark.asyncio
async def test_shared_chat_message_window_can_anchor_target_message():
    directus = FakeDirectusService()

    payload = await get_shared_chat_message_window(
        request=None,
        chat_id="chat-shared",
        before_timestamp=2147483647,
        target_message_id="msg-42",
        limit=10,
        directus_service=directus,
    )

    assert payload["target_message_id"] == "msg-42"
    assert json.loads(payload["messages"][-1])["message_id"] == "msg-42"


@pytest.mark.asyncio
async def test_shared_chat_message_window_compound_cursor_preserves_duplicate_timestamps():
    directus = FakeDirectusService()
    directus.chat.messages = [
        {**directus.chat.messages[0], "id": "db-a", "client_message_id": "msg-a", "created_at": 10},
        {**directus.chat.messages[1], "id": "db-b", "client_message_id": "msg-b", "created_at": 10},
        {**directus.chat.messages[2], "id": "db-c", "client_message_id": "msg-c", "created_at": 10},
        {**directus.chat.messages[3], "id": "db-d", "client_message_id": "msg-d", "created_at": 11},
    ]

    payload = await get_shared_chat_message_window(
        request=None,
        chat_id="chat-shared",
        before_timestamp=10,
        before_message_id="msg-c",
        limit=10,
        directus_service=directus,
    )

    assert [json.loads(message)["message_id"] for message in payload["messages"]] == ["msg-a", "msg-b"]


@pytest.mark.asyncio
async def test_shared_chat_window_preserves_non_enumeration_dummy_response():
    directus = FakeDirectusService()

    manifest = await get_shared_chat_manifest(
        request=None,
        chat_id="missing-chat",
        directus_service=directus,
    )
    messages = await get_shared_chat_message_window(
        request=None,
        chat_id="missing-chat",
        directus_service=directus,
    )

    assert manifest["chat_id"] == "missing-chat"
    assert messages["chat_id"] == "missing-chat"
    assert messages["messages"]
    assert messages["has_more"] is False
