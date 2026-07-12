"""
Behavioral contracts for durable chat-turn preflight and enqueue ordering.

These tests isolate the Python boundary from Directus while proving that no
acknowledgement is emitted before persistence succeeds and retry identities are
stable. Transaction rollback itself remains covered by the extension runtime.
"""

import pytest

from backend.core.api.app.routes.handlers.websocket_handlers import chat_turn_preflight_handler
from backend.core.api.app.services.chat_recovery_service import ChatRecoveryProtocolError


class RecordingManager:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_personal_message(self, message: dict, *_args) -> None:
        self.messages.append(message)


class RecordingRecoveryService:
    calls: list[tuple[str, dict]] = []
    failure: Exception | None = None

    def __init__(self, _directus_service) -> None:
        pass

    async def execute(self, operation: str, data: dict) -> dict:
        self.calls.append((operation, data))
        if self.failure:
            raise self.failure
        return {"preflight_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "state": "PREPARED"}


def preflight_payload() -> dict:
    return {
        "protocol_version": 1,
        "chat_id": "11111111-1111-4111-8111-111111111111",
        "turn_id": "22222222-2222-4222-8222-222222222222",
        "message_id": "user-message-1",
        "chat_key_version": 1,
        "encrypted_chat_key": "wrapped-key",
        "recovery_public_key": "2EFIcBAPeLs5wvSL0p3_4KF4klj--DspH4b6f7MRwSc",
        "expected_messages_v": 0,
        "encrypted_user_message": {
            "client_message_id": "user-message-1",
            "chat_id": "11111111-1111-4111-8111-111111111111",
            "hashed_user_id": "client-controlled",
            "encrypted_content": "ciphertext",
            "role": "user",
            "created_at": 1,
            "updated_at": 1,
        },
        "inference_request": {"message": "plaintext for inference", "model": "best"},
    }


@pytest.mark.asyncio
async def test_preflight_ack_is_emitted_only_after_durable_commit(monkeypatch) -> None:
    monkeypatch.setenv("CHAT_RECOVERY_COMMITMENT_KEY", "commitment-key")
    monkeypatch.setattr(chat_turn_preflight_handler, "ChatRecoveryService", RecordingRecoveryService)
    RecordingRecoveryService.calls = []
    RecordingRecoveryService.failure = ChatRecoveryProtocolError(409, "version_conflict")
    manager = RecordingManager()

    await chat_turn_preflight_handler.handle_chat_turn_preflight(
        manager=manager,
        directus_service=object(),
        user_id="user-id",
        user_id_hash="owner-hash",
        device_fingerprint_hash="device-hash",
        payload=preflight_payload(),
    )

    assert [message["type"] for message in manager.messages] == ["error"]
    assert manager.messages[0]["payload"] == {
        "code": "version_conflict",
        "message": "Encrypted chat preflight was rejected.",
    }


@pytest.mark.asyncio
async def test_preflight_persists_canonical_server_identity_without_plaintext(monkeypatch) -> None:
    monkeypatch.setenv("CHAT_RECOVERY_COMMITMENT_KEY", "commitment-key")
    monkeypatch.setattr(chat_turn_preflight_handler, "ChatRecoveryService", RecordingRecoveryService)
    RecordingRecoveryService.calls = []
    RecordingRecoveryService.failure = None
    manager = RecordingManager()

    await chat_turn_preflight_handler.handle_chat_turn_preflight(
        manager=manager,
        directus_service=object(),
        user_id="user-id",
        user_id_hash="owner-hash",
        device_fingerprint_hash="device-hash",
        payload=preflight_payload(),
    )

    operation, data = RecordingRecoveryService.calls[0]
    assert operation == "prepare_preflight"
    assert data["hashed_user_id"] == "owner-hash"
    assert data["encrypted_user_message"]["hashed_user_id"] == "owner-hash"
    assert "inference_request" not in data
    assert "plaintext for inference" not in repr(data)
    assert manager.messages == [{"type": "chat_turn_preflight_ack", "payload": {
        "preflight_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "state": "PREPARED"
    }}]


@pytest.mark.asyncio
async def test_lost_enqueue_ack_reuses_task_billing_and_outbox_identity(monkeypatch) -> None:
    monkeypatch.setenv("CHAT_RECOVERY_COMMITMENT_KEY", "commitment-key")
    monkeypatch.setattr(chat_turn_preflight_handler, "ChatRecoveryService", RecordingRecoveryService)
    RecordingRecoveryService.calls = []
    RecordingRecoveryService.failure = None
    kwargs = {
        "directus_service": object(),
        "user_id_hash": "owner-hash",
        "device_fingerprint_hash": "device-hash",
        "preflight_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "inference_request": {"message": "hello", "model": "best"},
    }

    await chat_turn_preflight_handler.enqueue_chat_turn(**kwargs)
    await chat_turn_preflight_handler.enqueue_chat_turn(**kwargs)

    assert RecordingRecoveryService.calls[0] == RecordingRecoveryService.calls[1]
    _, data = RecordingRecoveryService.calls[0]
    assert len({data["inference_task_id"], data["billing_identity"], data["outbox_id"]}) == 3
