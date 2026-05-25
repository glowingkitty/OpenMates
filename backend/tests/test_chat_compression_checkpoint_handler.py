"""
Regression tests for client-encrypted chat compression checkpoint handlers.

Checkpoints are persisted only after the client encrypts the summary with the
chat key; server/Vault ciphertext must be rejected before Directus writes.
"""

import asyncio

import pytest

pytest.importorskip("celery")

from backend.core.api.app.routes.handlers.websocket_handlers.chat_compression_checkpoint_handler import (
    CHECKPOINT_COLLECTION,
    handle_store_chat_compression_checkpoint,
)


class FakeChatMethods:
    async def check_chat_ownership(self, chat_id: str, user_id: str) -> bool:
        return chat_id == "chat-123" and user_id == "user-123"


class FakeDirectusService:
    def __init__(self) -> None:
        self.chat = FakeChatMethods()
        self.created: list[tuple[str, dict, bool]] = []

    async def get_items(self, *args, **kwargs):
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
