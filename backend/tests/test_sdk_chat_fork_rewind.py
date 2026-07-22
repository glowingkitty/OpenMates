"""SDK encrypted chat fork and rewind route contracts.

Purpose: protect API-key chat repair endpoints before CLI/SDK composition.
Architecture: docs/specs/cli-sdk-chat-fork-rewind/spec.yml.
Security: endpoints persist/delete client-encrypted rows only and never plaintext.
Scope: owner-scoped personal saved chats; team/shared/incognito support is out.
"""

import base64
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from backend.core.api.app.routes import sdk


USER_ID = "11111111-1111-4111-8111-111111111111"
CHAT_ID = "22222222-2222-4222-8222-222222222222"
FORK_ID = "33333333-3333-4333-8333-333333333333"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _cipher(label: str) -> str:
    return base64.b64encode((label * 8).encode()).decode()


def _auth(scopes: list[str] | None = None) -> dict:
    return {
        "user_id": USER_ID,
        "device_hash": "device-hash",
        "api_key_metadata": {
            "full_access": False,
            "scopes": {"chat": scopes or ["chat:read_existing", "chat:create_saved", "chat:delete"]},
        },
    }


def _messages(chat_id: str = CHAT_ID) -> list[dict]:
    return [
        {
            "id": "row-1",
            "client_message_id": "msg-1",
            "message_id": "msg-1",
            "chat_id": chat_id,
            "role": "user",
            "encrypted_content": _cipher("user-one"),
            "created_at": 100,
        },
        {
            "id": "row-2",
            "client_message_id": "msg-2",
            "message_id": "msg-2",
            "chat_id": chat_id,
            "role": "assistant",
            "encrypted_content": _cipher("assistant-two"),
            "created_at": 200,
        },
        {
            "id": "row-3",
            "client_message_id": "msg-3",
            "message_id": "msg-3",
            "chat_id": chat_id,
            "role": "user",
            "encrypted_content": _cipher("user-three"),
            "created_at": 300,
        },
    ]


class _FakeChatMethods:
    def __init__(self, directus):
        self.directus = directus
        self.metadata = {
            "id": CHAT_ID,
            "hashed_user_id": hashlib.sha256(USER_ID.encode()).hexdigest(),
            "hashed_team_id": None,
            "encrypted_chat_key": "wrapped-source-key",
            "encrypted_title": "source-title",
            "messages_v": 3,
            "is_shared": False,
            "is_private": True,
        }
        self.messages = _messages()
        self.created_chat = None
        self.created_messages = []

    async def check_chat_ownership(self, chat_id, user_id):
        return chat_id == CHAT_ID and user_id == USER_ID

    async def get_chat_metadata(self, chat_id):
        return self.metadata if chat_id == CHAT_ID else None

    async def get_all_messages_for_chat(self, chat_id, decrypt_content=False):
        assert decrypt_content is False
        return list(self.messages) if chat_id == CHAT_ID else []

    async def create_chat_in_directus(self, chat_metadata):
        self.created_chat = chat_metadata
        return chat_metadata, False

    async def create_message_in_directus(self, message_data):
        assert message_data.get("message_id") == message_data.get("client_message_id")
        self.created_messages.append(message_data)
        return {"id": message_data.get("id") or message_data.get("client_message_id")}


class _FakeDirectus:
    def __init__(self):
        self.chat = _FakeChatMethods(self)
        self.deleted_ids = []
        self.updated = []

    async def bulk_delete_items(self, collection, item_ids):
        assert collection == "messages"
        self.deleted_ids.extend(item_ids)
        return True

    async def update_item(self, collection, item_id, data):
        assert collection == "chats"
        self.updated.append((item_id, data))
        return {"id": item_id, **data}


class _FakeCache:
    def __init__(self):
        self.calls = []

    async def delete_ai_messages_history(self, user_id, chat_id):
        self.calls.append(("ai", user_id, chat_id))
        return True

    async def delete_chat_messages_history(self, user_id, chat_id):
        self.calls.append(("chat", user_id, chat_id))
        return True

    async def delete_sync_messages_history(self, user_id, chat_id):
        self.calls.append(("sync", user_id, chat_id))
        return True

    async def set_chat_version_component(self, user_id, chat_id, component, value):
        self.calls.append(("version", user_id, chat_id, component, value))
        return True


def _request() -> SimpleNamespace:
    return SimpleNamespace(
        headers={"Authorization": "Bearer test-key"},
        app=SimpleNamespace(
            state=SimpleNamespace(
                directus_service=_FakeDirectus(),
                cache_service=_FakeCache(),
            )
        ),
    )


def _fork_payload(message_count: int = 2) -> sdk.SdkChatForkRequest:
    copied = []
    for row in _messages(FORK_ID)[:message_count]:
        copied.append(
            {
                "client_message_id": f"fork-{row['client_message_id']}",
                "chat_id": FORK_ID,
                "role": row["role"],
                "encrypted_content": row["encrypted_content"],
                "created_at": row["created_at"],
            }
        )
    return sdk.SdkChatForkRequest(
        protocol_version=1,
        from_message_id="msg-2",
        new_chat_id=FORK_ID,
        encrypted_chat_metadata={
            "id": FORK_ID,
            "encrypted_chat_key": "wrapped-new-key",
            "encrypted_title": "new-title",
        },
        encrypted_messages=copied,
        expected_source_messages_v=3,
    )


@pytest.mark.anyio
async def test_fork_persists_client_encrypted_chat_and_messages(monkeypatch):
    monkeypatch.setattr(sdk, "_authenticate_sdk_request", AsyncMock(return_value=_auth()))
    request = _request()

    result = await sdk.fork_sdk_chat(request, CHAT_ID, _fork_payload())

    directus = request.app.state.directus_service
    assert result == {"success": True, "source_chat_id": CHAT_ID, "chat_id": FORK_ID, "copied_message_count": 2, "messages_v": 2}
    assert directus.chat.created_chat["hashed_user_id"] == hashlib.sha256(USER_ID.encode()).hexdigest()
    assert directus.chat.created_chat["messages_v"] == 2
    assert len(directus.chat.created_messages) == 2
    assert all("content" not in message for message in directus.chat.created_messages)
    assert all(message["chat_id"] == FORK_ID for message in directus.chat.created_messages)


@pytest.mark.anyio
async def test_fork_rejects_plaintext_or_unsupported_chat(monkeypatch):
    monkeypatch.setattr(sdk, "_authenticate_sdk_request", AsyncMock(return_value=_auth()))
    request = _request()
    request.app.state.directus_service.chat.metadata["hashed_team_id"] = "team-hash"

    with pytest.raises(HTTPException) as exc:
        await sdk.fork_sdk_chat(request, CHAT_ID, _fork_payload())
    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == "unsupported_chat_kind"

    request = _request()
    payload = _fork_payload()
    payload.encrypted_messages[0]["content"] = "plaintext"
    with pytest.raises(HTTPException) as plaintext_exc:
        await sdk.fork_sdk_chat(request, CHAT_ID, payload)
    assert plaintext_exc.value.status_code == 400
    assert plaintext_exc.value.detail["error"] == "encrypted_history_required"


@pytest.mark.anyio
async def test_rewind_requires_confirmation_then_deletes_tail_and_versions(monkeypatch):
    monkeypatch.setattr(sdk, "_authenticate_sdk_request", AsyncMock(return_value=_auth()))
    recovery = AsyncMock(return_value={"deleted_preflights": 1, "deleted_jobs": 1, "deleted_outbox": 1})
    monkeypatch.setattr(sdk, "_execute_sdk_recovery", recovery)
    request = _request()

    with pytest.raises(HTTPException) as exc:
        await sdk.rewind_sdk_chat(
            request,
            CHAT_ID,
            sdk.SdkChatRewindRequest(to_message_id="msg-2", expected_messages_v=3),
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "destructive_confirmation_required"

    result = await sdk.rewind_sdk_chat(
        request,
        CHAT_ID,
        sdk.SdkChatRewindRequest(to_message_id="msg-2", expected_messages_v=3, confirm_destructive=True),
    )

    assert result["deleted_message_count"] == 1
    assert result["messages_v"] == 2
    assert request.app.state.directus_service.deleted_ids == ["row-3"]
    assert request.app.state.directus_service.updated == [(CHAT_ID, {"messages_v": 2, "last_edited_overall_timestamp": 200})]
    assert ("version", USER_ID, CHAT_ID, "messages_v", 2) in request.app.state.cache_service.calls
    recovery.assert_awaited_once()
    assert recovery.await_args.args[1] == "invalidate_deletion"


@pytest.mark.anyio
async def test_rewind_dry_run_and_version_conflict(monkeypatch):
    monkeypatch.setattr(sdk, "_authenticate_sdk_request", AsyncMock(return_value=_auth()))
    request = _request()

    dry_run = await sdk.rewind_sdk_chat(
        request,
        CHAT_ID,
        sdk.SdkChatRewindRequest(to_message_id="msg-2", expected_messages_v=3, dry_run=True),
    )
    assert dry_run["dry_run"] is True
    assert dry_run["planned_deleted_message_ids"] == ["msg-3"]
    assert request.app.state.directus_service.deleted_ids == []

    with pytest.raises(HTTPException) as exc:
        await sdk.rewind_sdk_chat(
            request,
            CHAT_ID,
            sdk.SdkChatRewindRequest(to_message_id="msg-2", expected_messages_v=2, confirm_destructive=True),
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == "version_conflict"


def test_chat_rewind_scope_requires_read_and_delete():
    with pytest.raises(HTTPException) as exc:
        sdk._require_sdk_scope_for_surface(
            {"api_key_metadata": {"full_access": False, "scopes": {"chat": ["chat:read_existing"]}}},
            "chats",
            "POST",
            f"{CHAT_ID}/rewind",
        )
    assert exc.value.detail == {"error": "missing_scope", "missing_scope": "chat:delete"}
