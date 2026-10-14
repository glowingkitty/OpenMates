"""
Tests for windowed shared-chat loading endpoints.

Large shared-chat fixtures are synthetic Directus rows. These tests must never
trigger AI inference to create or exercise long chats.
"""

import json
import hashlib
import importlib
import inspect
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
direct_chat_stub = types.ModuleType("backend.core.api.app.services.direct_chat_access")
direct_chat_stub.is_direct_chat = lambda chat: bool(chat.get("is_direct_chat"))

_STUB_MODULES = {
    "backend.core.api.app.services.directus": directus_stub,
    "backend.core.api.app.utils.encryption": encryption_stub,
    "backend.core.api.app.services.cache": cache_stub,
    "backend.core.api.app.services.limiter": limiter_stub,
    "backend.core.api.app.routes.auth_routes.auth_dependencies": auth_deps_stub,
    "backend.core.api.app.models.user": user_stub,
    "backend.core.api.app.services.direct_chat_access": direct_chat_stub,
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
get_shared_chat_embed_by_id = getattr(
    share_routes.get_shared_chat_embed_by_id,
    "__wrapped__",
    share_routes.get_shared_chat_embed_by_id,
)
get_shared_chat_embed_window = getattr(
    share_routes.get_shared_chat_embed_window,
    "__wrapped__", share_routes.get_shared_chat_embed_window,
)
get_shared_chat_embed_keys_window = getattr(
    share_routes.get_shared_chat_embed_keys_window,
    "__wrapped__", share_routes.get_shared_chat_embed_keys_window,
)
get_shared_chat_message_by_id = getattr(
    share_routes.get_shared_chat_message_by_id,
    "__wrapped__",
    share_routes.get_shared_chat_message_by_id,
)
get_shared_chat_auxiliary_window = getattr(
    share_routes.get_shared_chat_auxiliary_window,
    "__wrapped__", share_routes.get_shared_chat_auxiliary_window,
)
get_shared_chat_auxiliary_by_id = getattr(
    share_routes.get_shared_chat_auxiliary_by_id,
    "__wrapped__", share_routes.get_shared_chat_auxiliary_by_id,
)
get_shared_plan_task_key_window = getattr(
    share_routes.get_shared_plan_task_key_window,
    "__wrapped__", share_routes.get_shared_plan_task_key_window,
)
get_shared_chat = getattr(
    share_routes.get_shared_chat,
    "__wrapped__",
    share_routes.get_shared_chat,
)
get_shared_chat_message_window = getattr(
    share_routes.get_shared_chat_message_window,
    "__wrapped__",
    share_routes.get_shared_chat_message_window,
)
get_shared_sub_chats = share_routes.get_shared_sub_chats
DEFAULT_SHARED_MESSAGE_WINDOW_LIMIT = share_routes.DEFAULT_SHARED_MESSAGE_WINDOW_LIMIT


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

    async def get_embed_window_by_hashed_chat_id(
        self, hashed_chat_id: str, *, before_created_at=None, before_id=None,
    ):
        rows = [dict(row, hashed_chat_id=row.get("hashed_chat_id") or hashed_chat_id,
                     id=row.get("id") or row["embed_id"],
                     created_at=row.get("created_at", 1)) for row in self.chat_embeds]
        rows = [row for row in rows if row["hashed_chat_id"] == hashed_chat_id]
        rows.sort(key=lambda row: (row["created_at"], row["id"]), reverse=True)
        if before_created_at is not None:
            rows = [row for row in rows if (row["created_at"], row["id"])
                    < (before_created_at, before_id)]
        page = rows[:30]
        oldest = page[-1] if page else None
        return {"embeds": page, "has_more_before": len(rows) > 30,
                "start_cursor": {"created_at": oldest["created_at"], "id": oldest["id"]} if oldest else None,
                "oversized_embed_id": None, "oversized_embed_cursor": None}

    async def get_sync_embed_key_window_for_page(self, hashed_chat_id: str, hashed_user_id: str,
                                                 hashes: list[str], *, include_master_keys: bool = True,
                                                 after_key_id: str | None = None):
        assert include_master_keys is False
        keys = self.embed_keys or [{"id": "key-1", "hashed_chat_id": hashed_chat_id,
                                    "key_type": "chat", "hashed_embed_id": value} for value in hashes]
        selected = [key for key in keys if key.get("hashed_embed_id") in hashes
                    and key.get("hashed_chat_id") == hashed_chat_id and key.get("key_type") == "chat"]
        selected.sort(key=lambda key: key.get("id") or "")
        if after_key_id:
            selected = [key for key in selected if key.get("id", "") > after_key_id]
        page = selected[:30]
        return {"embed_keys": page, "has_more_after": len(selected) > 30,
                "end_cursor": page[-1].get("id") if page else None,
                "oversized_key_id": None}

    async def validate_embed_ids_in_chat(self, hashed_chat_id: str, embed_ids: list[str]):
        by_id = {row["embed_id"]: row for row in self.chat_embeds
                 if (row.get("hashed_chat_id") or hashed_chat_id) == hashed_chat_id}
        if any(embed_id not in by_id for embed_id in embed_ids):
            raise ValueError("Embed id is not in the shared chat")
        return [by_id[embed_id].get("hashed_embed_id") or hashlib.sha256(embed_id.encode()).hexdigest()
                for embed_id in embed_ids]

    async def get_sync_embed_key_by_id(
        self, hashed_chat_id: str, _hashed_user_id: str, hashes: list[str], key_id: str,
        *, include_master_keys: bool = True,
    ):
        assert include_master_keys is False
        return next((key for key in self.embed_keys if key.get("id") == key_id
                     and key.get("hashed_chat_id") == hashed_chat_id
                     and key.get("key_type") == "chat"
                     and key.get("hashed_embed_id") in hashes), None)

    async def get_embed_by_id(self, embed_id: str):
        return next((embed for embed in [*self.chat_embeds, *self.key_embeds]
                     if embed.get("embed_id") == embed_id), None)

    get_sync_embed_by_id = get_embed_by_id


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

    async def get_all_messages_for_chat(self, chat_id: str, decrypt_content: bool = False):
        assert decrypt_content is False
        return [
            json.dumps({**row, "message_id": row["client_message_id"]})
            for row in self.messages
            if row["chat_id"] == chat_id
        ]

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
        no_cache: bool = False,
        raise_on_error: bool = False,
    ):
        if collection == "message_highlights":
            return [{"id": "highlight-1", "chat_id": "chat-shared", "message_id": "msg-1",
                     "author_user_id": "author", "encrypted_payload": "cipher-highlight",
                     "created_at": 1, "updated_at": 1}]
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


# contract-test: supporting surface=rest_api assertions=storage.warm.bounded-chat-tail,storage.cold.shared-team-authorized
@pytest.mark.anyio
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
    assert payload["sub_chat_window"]["has_more_before"] is False
    assert payload["message_highlight_window"]["payload_bytes"] > 0


# contract-test: direct surface=rest_api assertions=storage.cold.discoverable-bounded,storage.cold.shared-team-authorized
@pytest.mark.anyio
async def test_public_embed_windows_complete_beyond_manifest_tail_with_chat_only_wrappers():
    directus = FakeDirectusService()
    chat_hash = hashlib.sha256(b"chat-shared").hexdigest()
    directus.embed.chat_embeds = [
        {"id": f"row-{index:03d}", "embed_id": f"embed-{index:03d}",
         "created_at": index, "hashed_chat_id": chat_hash,
         "hashed_embed_id": hashlib.sha256(f"embed-{index:03d}".encode()).hexdigest(),
         "encrypted_content": f"cipher-{index}", "is_private": True}
        for index in range(67)
    ]
    directus.embed.embed_keys = [
        {"id": f"key-{index:03d}", "key_type": "chat", "hashed_chat_id": chat_hash,
         "hashed_embed_id": row["hashed_embed_id"], "encrypted_embed_key": "wrapped"}
        for index, row in enumerate(directus.embed.chat_embeds)
    ] + [{"id": "master", "key_type": "master", "hashed_chat_id": chat_hash,
          "hashed_embed_id": directus.embed.chat_embeds[0]["hashed_embed_id"]}]

    seen: list[str] = []
    cursor = None
    while True:
        page = await get_shared_chat_embed_window(
            request=None, chat_id="chat-shared", directus_service=directus,
            before_created_at=cursor["created_at"] if cursor else None,
            before_id=cursor["id"] if cursor else None,
        )
        assert len(page["embeds"]) <= 30
        assert all(key["key_type"] == "chat" and key["hashed_chat_id"] == chat_hash
                   for key in page["embed_keys"])
        seen.extend(row["embed_id"] for row in page["embeds"])
        if not page["has_more_before"]:
            break
        cursor = page["start_cursor"]
        assert cursor
    assert len(seen) == 67
    assert len(set(seen)) == 67
    assert "embed-000" in seen and "embed-066" in seen


# contract-test: direct surface=rest_api assertions=storage.cold.shared-team-authorized,storage.privacy.ciphertext-boundary
@pytest.mark.anyio
async def test_public_embed_window_denies_missing_private_chat_and_invalid_cursor():
    directus = FakeDirectusService()
    for chat_id in ("missing-chat", "private-chat"):
        if chat_id == "private-chat":
            original = directus.chat.get_chat_metadata

            async def private_metadata(value, admin_required=False):
                row = await original(value, admin_required=admin_required)
                return {**row, "is_private": True} if row else None

            directus.chat.get_chat_metadata = private_metadata
        with pytest.raises(share_routes.HTTPException) as error:
            await get_shared_chat_embed_window(request=None, chat_id=chat_id,
                                               directus_service=directus)
        assert error.value.status_code == 404
    for before_created_at, before_id in ((1, None), (None, "row"), (-1, "row"), (1, "x" * 129)):
        with pytest.raises(share_routes.HTTPException) as error:
            await get_shared_chat_embed_window(
                request=None, chat_id="chat-shared", directus_service=directus,
                before_created_at=before_created_at, before_id=before_id,
            )
        assert error.value.status_code == 400


# contract-test: direct surface=rest_api assertions=storage.cold.shared-team-authorized,storage.privacy.ciphertext-boundary
@pytest.mark.anyio
async def test_public_embed_key_window_rechecks_private_and_missing_chat():
    directus = FakeDirectusService()
    directus.embed.chat_embeds = [{"embed_id": "selected", "hashed_chat_id": hashlib.sha256(b"chat-shared").hexdigest()}]
    with pytest.raises(share_routes.HTTPException) as missing:
        await get_shared_chat_embed_keys_window(
            request=None, chat_id="missing-chat", embed_ids="selected", directus_service=directus,
        )
    assert missing.value.status_code == 404

    original = directus.chat.get_chat_metadata

    async def private_metadata(chat_id, admin_required=False):
        row = await original(chat_id, admin_required=admin_required)
        return {**row, "is_private": True} if row else None

    directus.chat.get_chat_metadata = private_metadata
    with pytest.raises(share_routes.HTTPException) as private:
        await get_shared_chat_embed_keys_window(
            request=None, chat_id="chat-shared", embed_ids="selected", directus_service=directus,
        )
    assert private.value.status_code == 404


# contract-test: direct surface=rest_api assertions=storage.cold.shared-team-authorized,storage.privacy.ciphertext-boundary
@pytest.mark.anyio
async def test_public_page_key_continuation_rejects_foreign_ids_master_and_forged_key():
    directus = FakeDirectusService()
    chat_hash = hashlib.sha256(b"chat-shared").hexdigest()
    own_id = "own-embed"
    own_hash = hashlib.sha256(own_id.encode()).hexdigest()
    directus.embed.chat_embeds = [{"embed_id": own_id, "hashed_chat_id": chat_hash,
                                   "hashed_embed_id": own_hash, "is_private": True}]
    directus.embed.key_embeds = [{"embed_id": "foreign", "hashed_chat_id": "foreign-chat",
                                  "hashed_embed_id": "foreign-hash"}]
    directus.embed.embed_keys = [
        {"id": "key-1", "key_type": "chat", "hashed_chat_id": chat_hash,
         "hashed_embed_id": own_hash, "encrypted_embed_key": "wrapped"},
        {"id": "key-2", "key_type": "master", "hashed_chat_id": chat_hash,
         "hashed_embed_id": own_hash, "encrypted_embed_key": "master"},
        {"id": "key-3", "key_type": "chat", "hashed_chat_id": "foreign-chat",
         "hashed_embed_id": own_hash, "encrypted_embed_key": "foreign"},
    ]
    page = await get_shared_chat_embed_keys_window(
        request=None, chat_id="chat-shared", embed_ids=own_id, directus_service=directus,
    )
    assert [key["id"] for key in page["embed_keys"]] == ["key-1"]
    exact = await get_shared_chat_embed_keys_window(
        request=None, chat_id="chat-shared", embed_ids=own_id,
        key_id="key-1", directus_service=directus,
    )
    assert [key["id"] for key in exact["embed_keys"]] == ["key-1"]
    for selected_id, key_id in (("foreign", None), (own_id, "key-2"), (own_id, "key-3")):
        with pytest.raises(share_routes.HTTPException) as error:
            await get_shared_chat_embed_keys_window(
                request=None, chat_id="chat-shared", embed_ids=selected_id,
                key_id=key_id, directus_service=directus,
            )
        assert error.value.status_code == 404
    for ids, after_key_id, key_id in (("", None, None), ("a,a", None, None),
                                      (",".join(str(i) for i in range(31)), None, None),
                                      (own_id, "key-1", "key-1"), (own_id, "x" * 129, None)):
        with pytest.raises(share_routes.HTTPException) as error:
            await get_shared_chat_embed_keys_window(
                request=None, chat_id="chat-shared", embed_ids=ids,
                after_key_id=after_key_id, key_id=key_id, directus_service=directus,
            )
        assert error.value.status_code == 400


# contract-test: direct surface=rest_api assertions=storage.cold.discoverable-bounded,storage.cold.shared-team-authorized
@pytest.mark.anyio
async def test_public_embed_key_cursor_completes_and_rejects_storage_scope_widening(monkeypatch):
    directus = FakeDirectusService()
    chat_hash = hashlib.sha256(b"chat-shared").hexdigest()
    embed_id = "many-wrappers"
    embed_hash = hashlib.sha256(embed_id.encode()).hexdigest()
    directus.embed.chat_embeds = [{"embed_id": embed_id, "hashed_chat_id": chat_hash,
                                   "hashed_embed_id": embed_hash}]
    directus.embed.embed_keys = [
        {"id": f"key-{index:03d}", "key_type": "chat", "hashed_chat_id": chat_hash,
         "hashed_embed_id": embed_hash, "encrypted_embed_key": f"cipher-{index}"}
        for index in range(35)
    ]
    first = await get_shared_chat_embed_keys_window(
        request=None, chat_id="chat-shared", embed_ids=embed_id, directus_service=directus,
    )
    assert len(first["embed_keys"]) == 30
    assert first["has_more_after"] is True
    second = await get_shared_chat_embed_keys_window(
        request=None, chat_id="chat-shared", embed_ids=embed_id,
        after_key_id=first["end_cursor"], directus_service=directus,
    )
    assert len(second["embed_keys"]) == 5
    assert second["has_more_after"] is False
    assert {row["id"] for row in first["embed_keys"] + second["embed_keys"]} == {
        f"key-{index:03d}" for index in range(35)
    }

    async def forged_page(*_args, **_kwargs):
        return {"embed_keys": [{"id": "forged", "key_type": "master",
                                 "hashed_chat_id": chat_hash, "hashed_embed_id": embed_hash}],
                "has_more_after": False, "end_cursor": "forged", "oversized_key_id": None}

    monkeypatch.setattr(directus.embed, "get_sync_embed_key_window_for_page", forged_page)
    with pytest.raises(share_routes.HTTPException) as error:
        await get_shared_chat_embed_keys_window(
            request=None, chat_id="chat-shared", embed_ids=embed_id, directus_service=directus,
        )
    assert error.value.status_code == 503


# contract-test: supporting surface=rest_api assertions=storage.cold.discoverable-bounded,storage.cold.shared-team-authorized
def test_public_embed_window_routes_precede_selected_embed_route():
    paths = [route.path for route in share_routes.router.routes]
    selected = paths.index("/v1/share/chat/{chat_id}/embeds/{embed_id}")
    assert paths.index("/v1/share/chat/{chat_id}/embeds/window") < selected
    assert paths.index("/v1/share/chat/{chat_id}/embeds/keys/window") < selected


# contract-test: direct surface=rest_api assertions=storage.cold.discoverable-bounded,storage.cold.shared-team-authorized
@pytest.mark.anyio
async def test_shared_manifest_reports_authorized_auxiliary_failure(monkeypatch):
    directus = FakeDirectusService()

    async def unavailable(*_args, **_kwargs):
        raise RuntimeError("ciphertext page unavailable")

    monkeypatch.setattr(share_routes, "get_shared_chat_auxiliary_payload", unavailable)
    with pytest.raises(share_routes.HTTPException) as error:
        await get_shared_chat_manifest(request=None, chat_id="chat-shared", directus_service=directus)
    assert error.value.status_code == 503
    assert error.value.detail == "SHARED_MANIFEST_UNAVAILABLE"


# contract-test: direct surface=rest_api assertions=storage.cold.shared-team-authorized,storage.cold.independent-message-pages
@pytest.mark.anyio
async def test_shared_legacy_read_reports_authorized_storage_failure(monkeypatch):
    directus = FakeDirectusService()

    async def unavailable(*_args, **_kwargs):
        raise RuntimeError("ciphertext unavailable")

    monkeypatch.setattr(directus.chat, "get_all_messages_for_chat", unavailable)
    with pytest.raises(share_routes.HTTPException) as error:
        await get_shared_chat(request=None, chat_id="chat-shared", directus_service=directus)
    assert error.value.status_code == 503
    assert error.value.detail == "SHARED_CHAT_UNAVAILABLE"


# contract-test: direct surface=rest_api assertions=storage.cold.shared-team-authorized,storage.cold.discoverable-bounded
@pytest.mark.anyio
async def test_shared_chat_manifest_resolves_key_addressable_embeds_on_demand():
    directus = FakeDirectusService()
    directus.embed.chat_embeds = [{"embed_id": "image-embed", "hashed_embed_id": "image-hash"}]
    directus.embed.key_embeds = [
        {"embed_id": "image-embed", "hashed_embed_id": "image-hash"},
        {"embed_id": "pdf-embed", "hashed_embed_id": "pdf-hash", "encrypted_content": "cipher-pdf", "is_private": False},
    ]
    directus.embed.embed_keys = [
        {"hashed_chat_id": hashlib.sha256(b"chat-shared").hexdigest(), "key_type": "chat", "hashed_embed_id": "image-hash"},
        {"hashed_chat_id": hashlib.sha256(b"chat-shared").hexdigest(), "key_type": "chat", "hashed_embed_id": "pdf-hash"},
        {"hashed_chat_id": hashlib.sha256(b"chat-shared").hexdigest(), "key_type": "master", "hashed_embed_id": "pdf-hash"},
    ]

    payload = await get_shared_chat_manifest(
        request=None,
        chat_id="chat-shared",
        directus_service=directus,
    )

    assert [embed["embed_id"] for embed in payload["embeds"]] == ["image-embed"]
    exact = await get_shared_chat_embed_by_id(request=None, chat_id="chat-shared",
                                              embed_id="pdf-embed", directus_service=directus)
    assert exact["embed"]["embed_id"] == "pdf-embed"
    assert all(key["key_type"] == "chat" for key in exact["embed_keys"])


# contract-test: direct surface=rest_api assertions=storage.cold.shared-team-authorized,storage.privacy.ciphertext-boundary
@pytest.mark.anyio
async def test_shared_exact_embed_denies_foreign_chat_without_scoped_key():
    directus = FakeDirectusService()
    directus.embed.chat_embeds = []
    directus.embed.key_embeds = [{"embed_id": "foreign", "hashed_chat_id": "other-chat",
                                  "hashed_embed_id": "foreign-hash", "is_private": False}]
    directus.embed.embed_keys = [{"id": "master-key", "key_type": "master",
                                  "hashed_embed_id": "foreign-hash"}]
    with pytest.raises(share_routes.HTTPException) as error:
        await get_shared_chat_embed_by_id(request=None, chat_id="chat-shared",
                                          embed_id="foreign", directus_service=directus)
    assert error.value.status_code == 404


# contract-test: supporting surface=rest_api assertions=storage.cold.shared-team-authorized
@pytest.mark.anyio
async def test_shared_chat_manifest_includes_compression_checkpoints():
    directus = FakeDirectusService()

    payload = await get_shared_chat_manifest(
        request=None,
        chat_id="chat-shared",
        directus_service=directus,
    )

    assert payload["compression_checkpoints"] == directus.checkpoints
    assert payload["compression_checkpoint_window"]["has_more_before"] is False


# contract-test: direct surface=rest_api assertions=storage.cold.discoverable-bounded,storage.cold.shared-team-authorized
@pytest.mark.anyio
async def test_shared_manifest_exposes_exact_cursor_for_oversized_checkpoint():
    directus = FakeDirectusService()
    directus.checkpoints[0]["encrypted_summary"] = "x" * 140_000

    payload = await get_shared_chat_manifest(
        request=None, chat_id="chat-shared", directus_service=directus,
    )

    assert payload["compression_checkpoints"] == []
    assert payload["compression_checkpoint_window"]["oversized_checkpoint_id"] == "checkpoint-1"
    assert payload["compression_checkpoint_window"]["has_more_before"] is True


# contract-test: supporting surface=rest_api assertions=storage.cold.shared-team-authorized
@pytest.mark.anyio
async def test_shared_chat_legacy_payload_includes_compression_checkpoints():
    directus = FakeDirectusService()

    payload = await get_shared_chat(
        request=None,
        chat_id="chat-shared",
        directus_service=directus,
    )

    assert payload["compression_checkpoints"] == directus.checkpoints


# contract-test: supporting surface=rest_api assertions=storage.warm.bounded-chat-tail
@pytest.mark.anyio
async def test_shared_chat_message_window_default_limit_is_thirty():
    limit_default = inspect.signature(share_routes.get_shared_chat_message_window).parameters["limit"].default

    assert limit_default.default == DEFAULT_SHARED_MESSAGE_WINDOW_LIMIT
    assert DEFAULT_SHARED_MESSAGE_WINDOW_LIMIT == 30


# contract-test: direct surface=rest_api assertions=storage.warm.bounded-chat-tail,storage.cold.shared-team-authorized
@pytest.mark.anyio
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


# contract-test: supporting surface=rest_api assertions=storage.warm.bounded-chat-tail
@pytest.mark.anyio
async def test_shared_chat_message_window_uses_durable_rows_when_messages_v_is_stale():
    directus = FakeDirectusService()

    payload = await get_shared_chat_message_window(
        request=None,
        chat_id="chat-shared",
        before_timestamp=2147483647,
        limit=DEFAULT_SHARED_MESSAGE_WINDOW_LIMIT,
        directus_service=directus,
    )

    assert directus.chat.requested_limits == [21]
    assert len(payload["messages"]) == 20
    assert payload["has_more"] is True
    assert payload["messages_v"] == 82


# contract-test: direct surface=rest_api assertions=storage.cold.independent-message-pages,storage.cold.shared-team-authorized
@pytest.mark.anyio
async def test_shared_large_message_uses_exact_cursor_without_full_replay():
    directus = FakeDirectusService()
    large = {"id": "db-large", "client_message_id": "msg-large", "chat_id": "chat-shared",
             "role": "user", "created_at": 1000, "encrypted_content": "x" * 500_000,
             "encrypted_pii_mappings": "private-pii"}
    directus.chat.messages.append(large)
    page = await get_shared_chat_message_window(
        request=None, chat_id="chat-shared", before_timestamp=2000, limit=20,
        directus_service=directus,
    )
    assert page["messages"] == []
    assert page["oversized_message_cursor"] == {"created_at": 1000, "message_id": "msg-large"}
    selected = await get_shared_chat_message_by_id(
        request=None, chat_id="chat-shared", message_id="msg-large", directus_service=directus,
    )
    assert selected["message"]["message_id"] == "msg-large"
    assert "encrypted_pii_mappings" not in selected["message"]


# contract-test: direct surface=rest_api assertions=storage.cold.shared-team-authorized
@pytest.mark.anyio
async def test_shared_exact_message_denies_nonshared_chat():
    directus = FakeDirectusService()
    with pytest.raises(share_routes.HTTPException) as error:
        await get_shared_chat_message_by_id(
            request=None, chat_id="missing-chat", message_id="msg-1", directus_service=directus,
        )
    assert error.value.status_code == 404


# contract-test: direct surface=rest_api assertions=storage.cold.discoverable-bounded,storage.cold.shared-team-authorized,storage.privacy.ciphertext-boundary
@pytest.mark.anyio
async def test_shared_plan_page_exact_and_keys_are_chat_scoped():
    chat_hash = hashlib.sha256(b"chat-shared").hexdigest()
    plan_hash = hashlib.sha256(b"plan-1").hexdigest()

    class PlanDirectus(FakeDirectusService):
        async def get_items(self, collection, params, **kwargs):
            if collection == "user_plans":
                assert params["filter"]["hashed_primary_chat_id"]["_eq"] == chat_hash
                return [{"plan_id": "plan-1", "primary_chat_id": "chat-shared", "status": "active",
                         "created_at": 1, "updated_at": 2, "encrypted_title": "cipher-plan"}]
            if collection == "user_plan_key_wrappers":
                assert params["filter"]["hashed_chat_id"]["_eq"] == chat_hash
                assert params["filter"]["key_type"]["_eq"] == "chat"
                assert plan_hash in params["filter"]["hashed_plan_id"]["_in"]
                return [{"id": "wrapper-1", "hashed_plan_id": plan_hash, "hashed_chat_id": chat_hash,
                         "key_type": "chat", "encrypted_plan_key": "cipher-key"}]
            return await super().get_items(collection, params, **kwargs)

    directus = PlanDirectus()
    page = await get_shared_chat_auxiliary_window(
        request=None, chat_id="chat-shared", kind="plans", before_timestamp=None,
        before_id=None, directus_service=directus,
    )
    assert [item["plan_id"] for item in page["items"]] == ["plan-1"]
    assert page["key_wrappers"][0]["key_type"] == "chat"
    exact = await get_shared_chat_auxiliary_by_id(
        request=None, chat_id="chat-shared", kind="plans", record_id="plan-1",
        directus_service=directus,
    )
    assert exact["item"]["plan_id"] == "plan-1"
    keys = await get_shared_plan_task_key_window(
        request=None, chat_id="chat-shared", kind="plans", item_ids="plan-1",
        after_key_id=None, key_id="wrapper-1", directus_service=directus,
    )
    assert [key["id"] for key in keys["key_wrappers"]] == ["wrapper-1"]


# contract-test: direct surface=rest_api assertions=storage.cold.shared-team-authorized
@pytest.mark.anyio
async def test_shared_auxiliary_denies_missing_chat_before_plan_lookup():
    directus = FakeDirectusService()
    with pytest.raises(share_routes.HTTPException) as error:
        await get_shared_chat_auxiliary_window(
            request=None, chat_id="missing-chat", kind="tasks", before_timestamp=None,
            before_id=None, directus_service=directus,
        )
    assert error.value.status_code == 404


# contract-test: supporting surface=rest_api assertions=storage.cold.independent-message-pages
@pytest.mark.anyio
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


# contract-test: supporting surface=rest_api assertions=storage.cold.independent-message-pages
@pytest.mark.anyio
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


# contract-test: supporting surface=rest_api assertions=storage.cold.independent-message-pages
@pytest.mark.anyio
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


# contract-test: supporting surface=rest_api assertions=storage.cold.shared-team-authorized
@pytest.mark.anyio
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


# contract-test: supporting surface=rest_api assertions=storage.cold.shared-team-authorized
@pytest.mark.anyio
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
