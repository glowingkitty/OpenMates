"""
Regression tests for client-encrypted chat compression checkpoint handlers.

Checkpoints are persisted only after the client encrypts the summary with the
chat key; server/Vault ciphertext must be rejected before Directus writes.
"""

import asyncio
import base64
import binascii
import importlib
import json
import sys
import types

import pytest

cache_stub = types.ModuleType("backend.core.api.app.services.cache")
cache_stub.CacheService = object
directus_stub = types.ModuleType("backend.core.api.app.services.directus")
directus_stub.DirectusService = object
persistence_tasks_stub = types.ModuleType("backend.core.api.app.tasks.persistence_tasks")
tracing_stub = types.ModuleType("backend.shared.python_utils.tracing.ws_span_helper")


def _validate_client_encrypted_chat_payload(message_id: str, encrypted_content: str) -> None:
    try:
        decoded = base64.b64decode(encrypted_content, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(
            f"Message {message_id} must contain client-encrypted base64 content."
        ) from exc
    if len(decoded) < 29:
        raise ValueError(
            f"Message {message_id} client-encrypted base64 content is too short."
        )


persistence_tasks_stub._validate_client_encrypted_chat_payload = _validate_client_encrypted_chat_payload
tracing_stub.start_ws_handler_span = lambda *args, **kwargs: (None, None)
tracing_stub.end_ws_handler_span = lambda *args, **kwargs: None

sys.modules.setdefault("backend.core.api.app.services.cache", cache_stub)
sys.modules.setdefault("backend.core.api.app.services.directus", directus_stub)
sys.modules.setdefault("backend.core.api.app.tasks.persistence_tasks", persistence_tasks_stub)
sys.modules.setdefault("backend.shared.python_utils.tracing.ws_span_helper", tracing_stub)

checkpoint_handler = importlib.import_module(
    "backend.core.api.app.routes.handlers.websocket_handlers.chat_compression_checkpoint_handler"
)
CHECKPOINT_COLLECTION = checkpoint_handler.CHECKPOINT_COLLECTION
handle_get_compressed_chat_old_messages = checkpoint_handler.handle_get_compressed_chat_old_messages
handle_store_chat_compression_checkpoint = checkpoint_handler.handle_store_chat_compression_checkpoint


class FakeChatMethods:
    def __init__(self) -> None:
        self.requested_old_message_limits: list[int] = []
        self.messages = [
            {"id": f"db-{index}", "client_message_id": f"msg-{index}", "chat_id": "chat-123", "created_at": index}
            for index in range(1, 121)
        ]

    async def check_chat_ownership(self, chat_id: str, user_id: str) -> bool:
        return chat_id == "chat-123" and user_id == "user-123"

    async def get_messages_for_chat_before_timestamp(self, chat_id: str, before_timestamp: int, limit: int):
        self.requested_old_message_limits.append(limit)
        rows = [
            message
            for message in self.messages
            if message["chat_id"] == chat_id and message["created_at"] <= before_timestamp
        ]
        rows = sorted(rows, key=lambda message: message["created_at"], reverse=True)[:limit]
        rows.reverse()
        return [json.dumps({**row, "message_id": row["client_message_id"]}) for row in rows]

    async def get_message_for_chat_by_client_id(self, chat_id: str, message_id: str):
        return next(
            (
                message
                for message in self.messages
                if message["chat_id"] == chat_id
                and (message["client_message_id"] == message_id or message["id"] == message_id)
            ),
            None,
        )


class FakeDirectusService:
    def __init__(self) -> None:
        self.chat = FakeChatMethods()
        self.created: list[tuple[str, dict, bool]] = []

    async def get_items(self, collection: str, *args, **kwargs):
        params = kwargs.get("params") or (args[0] if args else {}) or {}
        checkpoint_filter = params.get("filter") or {}
        if collection == CHECKPOINT_COLLECTION and "hashed_user_id" in checkpoint_filter:
            return [{"id": "compression_ok", "chat_id": "chat-123", "hashed_user_id": "user-hash"}]
        return []

    async def create_item(self, collection: str, payload: dict, admin_required: bool = False):
        self.created.append((collection, payload, admin_required))
        return True, payload


class FakeManager:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_personal_message(self, message: dict, user_id: str, device_fingerprint_hash: str):
        self.messages.append(message)


def test_store_checkpoint_rejects_vault_ciphertext_before_directus_write():
    directus = FakeDirectusService()
    manager = FakeManager()

    with pytest.raises(ValueError, match="client-encrypted base64"):
        asyncio.run(
            handle_store_chat_compression_checkpoint(
                cache_service=None,
                directus_service=directus,
                manager=manager,
                user_id="user-123",
                user_id_hash="user-hash",
                device_fingerprint_hash="device-123",
                payload={
                    "chat_id": "chat-123",
                    "checkpoint_id": "compression_bad",
                    "encrypted_summary": "vault:v1:not-client-ciphertext",
                },
            )
        )

    assert directus.created == []


def test_store_checkpoint_persists_client_encrypted_summary():
    directus = FakeDirectusService()
    manager = FakeManager()

    asyncio.run(
        handle_store_chat_compression_checkpoint(
            cache_service=None,
            directus_service=directus,
            manager=manager,
            user_id="user-123",
            user_id_hash="user-hash",
            device_fingerprint_hash="device-123",
            payload={
                "chat_id": "chat-123",
                "checkpoint_id": "compression_ok",
                "encrypted_summary": "T00xYTViM2I3YzAwMDAwMDAwMDAwMGNpcGhlcnRleHQtb2s=",
                "compressed_up_to_timestamp": 100,
                "compressed_message_count": 12,
                "summary_token_estimate": 50,
            },
        )
    )

    assert directus.created[0][0] == CHECKPOINT_COLLECTION
    assert directus.created[0][1]["id"] == "compression_ok"
    assert manager.messages[0]["type"] == "chat_compression_checkpoint_stored"


def test_get_old_messages_returns_bounded_page_with_cursor_metadata():
    directus = FakeDirectusService()
    manager = FakeManager()

    asyncio.run(
        handle_get_compressed_chat_old_messages(
            cache_service=None,
            directus_service=directus,
            manager=manager,
            user_id="user-123",
            user_id_hash="user-hash",
            device_fingerprint_hash="device-123",
            payload={
                "chat_id": "chat-123",
                "checkpoint_id": "compression_ok",
                "before_timestamp": 100,
                "limit": 10,
            },
        )
    )

    payload = manager.messages[0]["payload"]
    assert directus.chat.requested_old_message_limits == [11]
    assert len(payload["messages"]) == 10
    assert payload["has_more"] is True
    assert payload["next_before_timestamp"] == 90


def test_get_old_messages_can_target_a_forgotten_message():
    directus = FakeDirectusService()
    manager = FakeManager()

    asyncio.run(
        handle_get_compressed_chat_old_messages(
            cache_service=None,
            directus_service=directus,
            manager=manager,
            user_id="user-123",
            user_id_hash="user-hash",
            device_fingerprint_hash="device-123",
            payload={
                "chat_id": "chat-123",
                "checkpoint_id": "compression_ok",
                "before_timestamp": 100,
                "target_message_id": "msg-42",
                "limit": 10,
            },
        )
    )

    payload = manager.messages[0]["payload"]
    assert payload["target_message_id"] == "msg-42"
    assert payload["messages"][-1].find('"message_id": "msg-42"') != -1


def test_get_old_messages_enforces_checkpoint_ownership():
    directus = FakeDirectusService()
    manager = FakeManager()

    asyncio.run(
        handle_get_compressed_chat_old_messages(
            cache_service=None,
            directus_service=directus,
            manager=manager,
            user_id="user-456",
            user_id_hash="other-hash",
            device_fingerprint_hash="device-123",
            payload={
                "chat_id": "chat-123",
                "checkpoint_id": "compression_ok",
                "before_timestamp": 100,
                "limit": 10,
            },
        )
    )

    assert manager.messages[0]["type"] == "error"
