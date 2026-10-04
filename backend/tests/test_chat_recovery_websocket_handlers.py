"""
WebSocket contracts for claiming and completing sealed recovery jobs.

Authenticated identity always overrides client owner/device fields. Terminal
persistence sends only client ciphertext and acknowledges after the Directus
transaction commits with the current lease fencing generation.
"""

import pytest

from backend.core.api.app.routes.connection_manager import permits_canonical_embed_write
from backend.core.api.app.routes.handlers.websocket_handlers import chat_recovery_job_handlers


class FakeManager:
    def __init__(self, *, typed: bool = False, receipts: bool = False) -> None:
        self.messages: list[dict] = []
        self.typed = typed
        self.receipts = receipts

    async def send_personal_message(self, message: dict, user_id: str, device_hash: str) -> None:
        self.messages.append(message)

    def supports_typed_recovery_outputs(self, _user_id: str, _device_hash: str) -> bool:
        return self.typed

    def supports_canonical_embed_receipts(self, _user_id: str, _device_hash: str) -> bool:
        return self.receipts


@pytest.mark.parametrize(("receipts", "typed", "record_id", "allowed"), [
    (False, False, None, False),
    (False, True, None, False),
    (True, False, None, True),
    (True, False, "recovery-1", False),
    (True, True, "recovery-1", True),
])
# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
def test_canonical_embed_ws_write_requires_explicit_capabilities(
    receipts: bool, typed: bool, record_id: str | None, allowed: bool,
) -> None:
    assert permits_canonical_embed_write(
        supports_receipts=receipts,
        supports_typed_outputs=typed,
        recovery_record_id=record_id,
    ) is allowed


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


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
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


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
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


@pytest.mark.anyio
@pytest.mark.parametrize("handler_name", [
    "handle_recovery_output_get",
    "handle_recovery_output_persist_message",
    "handle_recovery_output_persist_summary",
    "handle_recovery_output_ack_checkpoint",
    "handle_recovery_output_ack_embed",
])
# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
async def test_legacy_connection_cannot_read_or_mutate_typed_outputs(
    monkeypatch, handler_name: str,
) -> None:
    monkeypatch.setattr(chat_recovery_job_handlers, "ChatRecoveryService", FakeRecoveryService)
    FakeRecoveryService.calls = []
    manager = FakeManager()
    handler = getattr(chat_recovery_job_handlers, handler_name)
    arguments = {
        "manager": manager,
        "directus_service": object(),
        "user_id": "user-1",
        "user_id_hash": "owner-hash",
        "device_fingerprint_hash": "device-hash",
        "payload": {"protocol_version": 1, "record_id": "record-1", "request_id": "request-1"},
    }
    if handler_name == "handle_recovery_output_get":
        arguments["s3_service"] = None

    await handler(**arguments)

    assert FakeRecoveryService.calls == []
    assert manager.messages == [{
        "type": "error",
        "payload": {
            "code": "client_capability_required",
            "message": "This encrypted recovery operation requires an updated client.",
            "job_id": "record-1",
            "request_id": "request-1",
        },
    }]


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
async def test_typed_embed_ack_requires_both_explicit_capabilities(monkeypatch) -> None:
    monkeypatch.setattr(chat_recovery_job_handlers, "ChatRecoveryService", FakeRecoveryService)
    FakeRecoveryService.calls = []
    manager = FakeManager(typed=True, receipts=False)

    await chat_recovery_job_handlers.handle_recovery_output_ack_embed(
        manager=manager, directus_service=object(), user_id="user-1",
        user_id_hash="owner-hash", device_fingerprint_hash="device-hash",
        payload={"protocol_version": 1, "record_id": "record-1", "request_id": "request-1"},
    )

    assert FakeRecoveryService.calls == []
    assert manager.messages[0]["payload"]["code"] == "client_capability_required"
