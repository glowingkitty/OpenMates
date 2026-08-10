"""WebSocket contracts for Workflow pending chat delivery.

The backend binds delivery claims to the authenticated owner/device and accepts
only client ciphertext under the current fence. Raw regular chat keys are never
part of the protocol.

Spec: docs/specs/workflows-cli-runtime/spec.yml
"""

from __future__ import annotations

import pytest
import json

from backend.core.api.app.routes.handlers.websocket_handlers import workflow_chat_delivery_handlers
from backend.core.api.app.services.workflow_chat_delivery_service import WorkflowChatDeliveryService


class FakeManager:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_personal_message(self, message: dict, user_id: str, device_hash: str) -> None:
        self.messages.append({"message": message, "user_id": user_id, "device_hash": device_hash})


class FakeVaultCipher:
    def encrypt_delivery(self, *, owner_id: str, delivery_id: str, payload: dict[str, str]) -> str:
        del owner_id, payload
        return f"vault:{delivery_id}"


class FakeCache:
    def __init__(self) -> None:
        self.redis = FakeRedis()

    @property
    async def client(self):
        return self.redis

    async def get_user_vault_key_id(self, user_id: str) -> str:
        del user_id
        return "vault-key"


class FakeRedis:
    def __init__(self) -> None:
        self.keys: set[str] = set()

    async def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool:
        del value, ex
        if nx and key in self.keys:
            return False
        self.keys.add(key)
        return True

    async def delete(self, key: str) -> None:
        self.keys.discard(key)


class FakeDirectus:
    async def get_user_fields_direct(self, user_id: str, fields: list[str]) -> dict:
        del user_id, fields
        return {"vault_key_id": "vault-key"}


class FakeEncryption:
    async def decrypt_with_user_key(self, ciphertext: str, key_id: str) -> str:
        assert ciphertext == "ciphertext"
        assert key_id == "vault-key"
        return json.dumps({"title": "Title", "message": "Message"})


class FakeVaultEnvelopeCipher:
    def encrypt_delivery(self, *, owner_id: str, delivery_id: str, payload: dict[str, str]) -> str:
        del owner_id, delivery_id, payload
        return json.dumps({"ciphertext": "ciphertext", "vault_key_id": "vault-key"})


@pytest.mark.asyncio
async def test_reconnect_advertises_owner_authorized_pending_deliveries(monkeypatch) -> None:
    service = WorkflowChatDeliveryService(cipher=FakeVaultCipher(), clock=lambda: 100)
    service.create_delivery(owner_id="alice", title="Title", message="Message", expires_at=200)
    manager = FakeManager()

    monkeypatch.setattr(workflow_chat_delivery_handlers, "_service", lambda directus_service: service)

    await workflow_chat_delivery_handlers.send_available_workflow_chat_deliveries(
        manager=manager,
        directus_service=object(),
        user_id="alice",
        device_fingerprint_hash="device-hash",
    )

    assert manager.messages[0]["user_id"] == "alice"
    assert manager.messages[0]["device_hash"] == "device-hash"
    message = manager.messages[0]["message"]
    assert message["type"] == "workflow_chat_deliveries_available"
    assert message["payload"]["deliveries"][0]["encrypted_payload"].startswith("vault:")


@pytest.mark.asyncio
async def test_claim_persist_and_ack_use_authenticated_device(monkeypatch) -> None:
    service = WorkflowChatDeliveryService(cipher=FakeVaultEnvelopeCipher(), clock=lambda: 100)
    delivery = service.create_delivery(owner_id="alice", title="Title", message="Message", expires_at=200)
    manager = FakeManager()

    monkeypatch.setattr(workflow_chat_delivery_handlers, "_service", lambda directus_service: service)

    await workflow_chat_delivery_handlers.handle_workflow_chat_delivery_claim(
        manager=manager,
        cache_service=FakeCache(),
        directus_service=FakeDirectus(),
        encryption_service=FakeEncryption(),
        user_id="alice",
        device_fingerprint_hash="trusted-device-hash",
        payload={"delivery_id": delivery.delivery_id, "device_id": "untrusted", "request_id": "claim-1"},
    )

    claim_payload = manager.messages[-1]["message"]["payload"]
    assert manager.messages[-1]["message"]["type"] == "workflow_chat_delivery_claimed"
    assert claim_payload["request_id"] == "claim-1"
    assert claim_payload["title"] == "Title"
    assert claim_payload["message"] == "Message"
    assert service.get_delivery(delivery_id=delivery.delivery_id, owner_id="alice").claim_device_id == "trusted-device-hash"

    await workflow_chat_delivery_handlers.handle_workflow_chat_delivery_persist(
        manager=manager,
        directus_service=object(),
        user_id="alice",
        device_fingerprint_hash="trusted-device-hash",
        payload={
            "delivery_id": delivery.delivery_id,
            "claim_token": claim_payload["claim_token"],
            "claim_generation": claim_payload["claim_generation"],
            "claim_issued_at": claim_payload["claim_issued_at"],
            "claim_expires_at": claim_payload["claim_expires_at"],
            "encrypted_chat_metadata": "encrypted-chat-metadata",
            "encrypted_message": "encrypted-message",
            "chat_key": "client-must-not-send-this",
            "request_id": "persist-1",
        },
    )

    assert manager.messages[-1]["message"]["type"] == "workflow_chat_delivery_persisted"
    persisted = service.get_delivery(delivery_id=delivery.delivery_id, owner_id="alice")
    assert persisted.client_persistence is not None
    assert not hasattr(persisted, "chat_key")

    await workflow_chat_delivery_handlers.handle_workflow_chat_delivery_ack(
        manager=manager,
        directus_service=object(),
        user_id="alice",
        device_fingerprint_hash="trusted-device-hash",
        payload={
            "delivery_id": delivery.delivery_id,
            "claim_token": claim_payload["claim_token"],
            "claim_generation": claim_payload["claim_generation"],
            "claim_issued_at": claim_payload["claim_issued_at"],
            "claim_expires_at": claim_payload["claim_expires_at"],
            "request_id": "ack-1",
        },
    )

    assert manager.messages[-1]["message"]["type"] == "workflow_chat_delivery_acknowledged"
    assert service.get_delivery(delivery_id=delivery.delivery_id, owner_id="alice").status == "acknowledged"
