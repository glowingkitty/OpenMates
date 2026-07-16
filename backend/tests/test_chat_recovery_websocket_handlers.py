"""
WebSocket contracts for claiming and completing sealed recovery jobs.

Authenticated identity always overrides client owner/device fields. Terminal
persistence sends only client ciphertext and acknowledges after the Directus
transaction commits with the current lease fencing generation.
"""

import pytest

from backend.core.api.app.routes.handlers.websocket_handlers import chat_recovery_job_handlers


class FakeManager:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_personal_message(self, message: dict, user_id: str, device_hash: str) -> None:
        self.messages.append(message)


class FakeRecoveryService:
    calls: list[tuple[str, dict]] = []

    def __init__(self, directus_service) -> None:
        pass

    async def execute(self, operation: str, data: dict) -> dict:
        self.calls.append((operation, data))
        if operation == "lease_job":
            return {"job_id": data["job_id"], "state": "LEASED", "sealed_payload": "{}"}
        return {"job_id": data["job_id"], "state": "TERMINAL", "committed_messages_v": 5}


class FakeCacheService:
    instances: list["FakeCacheService"] = []

    def __init__(self) -> None:
        self.deleted_sync_messages: list[tuple[str, str]] = []
        self.version_updates: list[tuple[str, str, str, int]] = []
        self.closed = False
        self.instances.append(self)

    async def delete_sync_messages_history(self, user_id: str, chat_id: str) -> bool:
        self.deleted_sync_messages.append((user_id, chat_id))
        return True

    async def set_chat_version_component(
        self,
        user_id: str,
        chat_id: str,
        component: str,
        value: int,
    ) -> bool:
        self.version_updates.append((user_id, chat_id, component, value))
        return True

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_claim_binds_authenticated_owner_and_device(monkeypatch) -> None:
    monkeypatch.setattr(chat_recovery_job_handlers, "ChatRecoveryService", FakeRecoveryService)
    FakeRecoveryService.calls = []
    manager = FakeManager()

    await chat_recovery_job_handlers.handle_recovery_job_claim(
        manager=manager,
        directus_service=object(),
        user_id="user-1",
        user_id_hash="owner-hash",
        device_fingerprint_hash="device-hash",
        payload={
            "protocol_version": 1,
            "job_id": "11111111-1111-4111-8111-111111111111",
            "request_id": "claim-request-1",
        },
    )

    assert FakeRecoveryService.calls == [("lease_job", {
        "protocol_version": 1,
        "job_id": "11111111-1111-4111-8111-111111111111",
        "hashed_user_id": "owner-hash",
        "device_hash": "device-hash",
    })]
    assert manager.messages[0]["type"] == "recovery_job_claimed"
    assert manager.messages[0]["payload"]["request_id"] == "claim-request-1"


@pytest.mark.asyncio
async def test_terminal_persistence_overrides_encrypted_message_owner(monkeypatch) -> None:
    monkeypatch.setattr(chat_recovery_job_handlers, "ChatRecoveryService", FakeRecoveryService)
    monkeypatch.setattr(chat_recovery_job_handlers, "_create_cache_service", FakeCacheService)
    FakeRecoveryService.calls = []
    FakeCacheService.instances = []
    manager = FakeManager()
    encrypted_message = {
        "client_message_id": "assistant-1",
        "chat_id": "22222222-2222-4222-8222-222222222222",
        "hashed_user_id": "untrusted-client-owner",
        "encrypted_content": "ciphertext",
        "role": "assistant",
        "created_at": 100,
        "updated_at": 100,
    }

    await chat_recovery_job_handlers.handle_recovery_job_persist(
        manager=manager,
        directus_service=object(),
        user_id="user-1",
        user_id_hash="owner-hash",
        device_fingerprint_hash="device-hash",
        payload={
            "protocol_version": 1,
            "job_id": "11111111-1111-4111-8111-111111111111",
            "request_id": "persist-request-1",
            "lease_generation": 2,
            "lease_token": "lease-token",
            "expected_messages_v": 4,
            "encrypted_assistant_message": encrypted_message,
        },
    )

    operation, data = FakeRecoveryService.calls[0]
    assert operation == "persist_terminal"
    assert data["hashed_user_id"] == "owner-hash"
    assert data["device_hash"] == "device-hash"
    assert data["encrypted_assistant_message"]["hashed_user_id"] == "owner-hash"
    cache = FakeCacheService.instances[0]
    assert cache.deleted_sync_messages == [("user-1", "22222222-2222-4222-8222-222222222222")]
    assert cache.version_updates == [
        ("user-1", "22222222-2222-4222-8222-222222222222", "messages_v", 5)
    ]
    assert cache.closed is True
    assert manager.messages[0]["type"] == "recovery_job_persisted"
    assert manager.messages[0]["payload"]["request_id"] == "persist-request-1"
