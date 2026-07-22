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
auth_deps_stub.get_current_user_optional = lambda: None
auth_deps_stub.get_current_user_or_api_key = lambda: None
auth_deps_stub.get_directus_service = lambda: None
auth_deps_stub.get_cache_service = lambda: None
auth_deps_stub.get_compliance_service = lambda: None
auth_deps_stub.get_encryption_service = lambda: None
user_stub = types.ModuleType("backend.core.api.app.models.user")
user_stub.User = object

_STUB_MODULES = {
    "backend.core.api.app.services.directus": directus_stub,
    "backend.core.api.app.utils.encryption": encryption_stub,
    "backend.core.api.app.services.cache": cache_stub,
    "backend.core.api.app.services.limiter": limiter_stub,
    "backend.core.api.app.routes.auth_routes.auth_dependencies": auth_deps_stub,
    "backend.core.api.app.models.user": user_stub,
}
_previous_modules = {name: sys.modules.get(name) for name in _STUB_MODULES}
try:
    sys.modules.update(_STUB_MODULES)
    share_routes = importlib.import_module("backend.core.api.app.routes.share")
finally:
    sys.modules.pop("backend.core.api.app.routes.share", None)
    for name, previous_module in _previous_modules.items():
        if previous_module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous_module

get_shared_chat_manifest = getattr(
    share_routes.get_shared_chat_manifest,
    "__wrapped__",
    share_routes.get_shared_chat_manifest,
)
get_shared_chat_message_window = getattr(
    share_routes.get_shared_chat_message_window,
    "__wrapped__",
    share_routes.get_shared_chat_message_window,
)
get_shared_sub_chats = share_routes.get_shared_sub_chats


class FakeEmbedMethods:
    def __init__(self) -> None:
        self.chat_embeds = [{"embed_id": "parent-1", "hashed_chat_id": ""}]
        self.key_embeds = []
        self.embed_keys = []

    async def get_embeds_by_hashed_chat_id(self, hashed_chat_id: str):
        return [dict(embed, hashed_chat_id=embed.get("hashed_chat_id") or hashed_chat_id) for embed in self.chat_embeds]

    async def get_embed_keys_by_hashed_chat_id(self, hashed_chat_id: str, include_master_keys: bool = False):
        assert include_master_keys is False
        if self.embed_keys:
            return self.embed_keys
        return [{"hashed_chat_id": hashed_chat_id, "key_type": "chat", "hashed_embed_id": "parent-hash"}]

    async def get_embeds_by_hashed_embed_ids(self, hashed_embed_ids: list[str]):
        requested = set(hashed_embed_ids)
        return [embed for embed in self.key_embeds if embed.get("hashed_embed_id") in requested]


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
            "messages_v": 82,
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
        self.checkpoints = [
            {
                "id": "checkpoint-1",
                "chat_id": "chat-shared",
                "encrypted_summary": "encrypted-checkpoint-summary",
                "compressed_up_to_timestamp": 80,
                "compressed_message_count": 80,
                "summary_token_estimate": 123,
                "key_version": 1,
                "created_at": 1000,
                "updated_at": 1001,
            }
        ]

    async def get_items(
        self,
        collection: str,
        params: dict,
        admin_required: bool = False,
        return_none_on_403: bool = False,
    ):
        if collection == "message_highlights":
            return [{"id": "highlight-1", "chat_id": "chat-shared"}]
        if collection == "code_run_outputs":
            return []
        if collection == "chats":
            return []
        if collection == "chat_compression_checkpoints":
            checkpoint_filter = params.get("filter") or {}
            chat_id_filter = checkpoint_filter.get("chat_id") or {}
            checkpoint_id_filter = checkpoint_filter.get("id") or {}
            rows = [
                row
                for row in self.checkpoints
                if not chat_id_filter or row["chat_id"] == chat_id_filter.get("_eq")
            ]
            if checkpoint_id_filter:
                rows = [row for row in rows if row["id"] == checkpoint_id_filter.get("_eq")]
            return rows
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
async def test_shared_chat_manifest_includes_key_addressable_embeds():
    directus = FakeDirectusService()
    directus.embed.chat_embeds = [{"embed_id": "image-embed", "hashed_embed_id": "image-hash"}]
    directus.embed.key_embeds = [
        {"embed_id": "image-embed", "hashed_embed_id": "image-hash"},
        {"embed_id": "pdf-embed", "hashed_embed_id": "pdf-hash", "encrypted_content": "cipher-pdf"},
    ]
    directus.embed.embed_keys = [
        {"hashed_chat_id": "hashed-chat", "key_type": "chat", "hashed_embed_id": "image-hash"},
        {"hashed_chat_id": "hashed-chat", "key_type": "chat", "hashed_embed_id": "pdf-hash"},
    ]

    payload = await get_shared_chat_manifest(
        request=None,
        chat_id="chat-shared",
        directus_service=directus,
    )

    assert [embed["embed_id"] for embed in payload["embeds"]] == ["image-embed", "pdf-embed"]


@pytest.mark.asyncio
async def test_shared_chat_manifest_includes_compression_checkpoints():
    directus = FakeDirectusService()

    payload = await get_shared_chat_manifest(
        request=None,
        chat_id="chat-shared",
        directus_service=directus,
    )

    assert payload["compression_checkpoints"] == directus.checkpoints


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
async def test_shared_chat_message_window_uses_durable_rows_when_messages_v_is_stale():
    directus = FakeDirectusService()

    payload = await get_shared_chat_message_window(
        request=None,
        chat_id="chat-shared",
        before_timestamp=2147483647,
        limit=40,
        directus_service=directus,
    )

    assert directus.chat.requested_limits == [41]
    assert len(payload["messages"]) == 40
    assert payload["has_more"] is True
    assert payload["messages_v"] == 82


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
async def test_shared_chat_message_window_can_page_forgotten_checkpoint_messages():
    directus = FakeDirectusService()

    payload = await get_shared_chat_message_window(
        request=None,
        chat_id="chat-shared",
        before_timestamp=100,
        checkpoint_id="checkpoint-1",
        limit=10,
        directus_service=directus,
    )

    assert payload["checkpoint_id"] == "checkpoint-1"
    assert payload["checkpoint_boundary_timestamp"] == 80
    assert payload["is_forgotten_page"] is True
    assert len(payload["messages"]) == 10
    assert json.loads(payload["messages"][-1])["message_id"] == "msg-80"


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


@pytest.mark.asyncio
async def test_shared_sub_chats_retry_without_metadata_v_on_directus_permission_denial():
    class MetadataDeniedDirectus(FakeDirectusService):
        def __init__(self) -> None:
            super().__init__()
            self.requested_fields: list[str] = []

        async def get_items(
            self,
            collection: str,
            params: dict,
            admin_required: bool = False,
            return_none_on_403: bool = False,
        ):
            if collection != "chats":
                return await super().get_items(
                    collection, params, admin_required, return_none_on_403
                )
            self.requested_fields.append(params["fields"])
            if "metadata_v" in params["fields"]:
                assert return_none_on_403 is True
                return None
            return [{"id": "sub-chat-1", "title_v": 1}]

    directus = MetadataDeniedDirectus()

    sub_chats = await get_shared_sub_chats("chat-shared", directus)

    assert sub_chats == [{"id": "sub-chat-1", "title_v": 1}]
    assert len(directus.requested_fields) == 2
    assert "metadata_v" in directus.requested_fields[0]
    assert "metadata_v" not in directus.requested_fields[1]
