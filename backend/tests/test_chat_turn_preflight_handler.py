"""
WebSocket contract tests for durable encrypted chat-turn preflight.

The handler must commit encrypted user storage before acknowledging a send,
derive the inference commitment server-side, and avoid forwarding plaintext to
the Directus transaction extension.
"""

import hashlib
import hmac
import json

import pytest

from backend.core.api.app.routes.handlers.websocket_handlers import chat_turn_preflight_handler


class FakeManager:
    def __init__(self) -> None:
        self.messages: list[tuple[dict, str, str]] = []

    async def send_personal_message(self, message: dict, user_id: str, device_hash: str) -> None:
        self.messages.append((message, user_id, device_hash))


class FakeRecoveryService:
    calls: list[tuple[str, dict]] = []

    def __init__(self, directus_service) -> None:
        self.directus_service = directus_service

    async def execute(self, operation: str, data: dict) -> dict:
        self.calls.append((operation, data))
        return {
            "preflight_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "state": "PREPARED",
            "committed_messages_v": 4,
            "chat_key_version": 1,
            "recovery_key_fingerprint": "f" * 64,
            "commitment_version": 1,
            "inference_task_id": None,
            "billing_identity": None,
            "outbox_id": None,
        }


def _payload() -> dict:
    return {
        "protocol_version": 1,
        "chat_id": "11111111-1111-4111-8111-111111111111",
        "turn_id": "22222222-2222-4222-8222-222222222222",
        "message_id": "message-1",
        "chat_key_version": 1,
        "encrypted_chat_key": "wrapped-key",
        "recovery_public_key": "2EFIcBAPeLs5wvSL0p3_4KF4klj--DspH4b6f7MRwSc",
        "expected_messages_v": 3,
        "encrypted_user_message": {
            "client_message_id": "message-1",
            "chat_id": "11111111-1111-4111-8111-111111111111",
            "hashed_user_id": "ignored-client-owner",
            "encrypted_content": "ciphertext",
            "role": "user",
            "created_at": 100,
            "updated_at": 100,
        },
        "inference_request": {
            "message": "private plaintext",
            "model": "best",
            "apps": ["web"],
        },
    }


@pytest.mark.asyncio
async def test_preflight_commits_only_encrypted_data_and_acknowledges(monkeypatch) -> None:
    monkeypatch.setenv("CHAT_RECOVERY_COMMITMENT_KEY", "commitment-secret")
    monkeypatch.setattr(chat_turn_preflight_handler, "ChatRecoveryService", FakeRecoveryService)
    FakeRecoveryService.calls = []
    manager = FakeManager()
    payload = _payload()

    await chat_turn_preflight_handler.handle_chat_turn_preflight(
        manager=manager,
        directus_service=object(),
        user_id="user-1",
        user_id_hash="owner-hash",
        device_fingerprint_hash="device-hash",
        payload=payload,
    )

    operation, transaction_data = FakeRecoveryService.calls[0]
    assert operation == "prepare_preflight"
    assert transaction_data["hashed_user_id"] == "owner-hash"
    assert transaction_data["encrypted_user_message"]["hashed_user_id"] == "owner-hash"
    assert "inference_request" not in transaction_data
    assert "private plaintext" not in json.dumps(transaction_data)
    canonical = json.dumps(payload["inference_request"], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    assert transaction_data["inference_commitment"] == hmac.new(
        b"commitment-secret", canonical, hashlib.sha256
    ).hexdigest()
    assert manager.messages[0][0]["type"] == "chat_turn_preflight_ack"
    assert manager.messages[0][0]["payload"]["preflight_id"] == "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


@pytest.mark.asyncio
async def test_preflight_fails_closed_without_commitment_key(monkeypatch) -> None:
    monkeypatch.delenv("CHAT_RECOVERY_COMMITMENT_KEY", raising=False)
    monkeypatch.delenv("INTERNAL_API_SHARED_TOKEN", raising=False)
    monkeypatch.setattr(chat_turn_preflight_handler, "ChatRecoveryService", FakeRecoveryService)
    manager = FakeManager()

    await chat_turn_preflight_handler.handle_chat_turn_preflight(
        manager=manager,
        directus_service=object(),
        user_id="user-1",
        user_id_hash="owner-hash",
        device_fingerprint_hash="device-hash",
        payload=_payload(),
    )

    assert manager.messages == [
        (
            {
                "type": "error",
                "payload": {
                    "code": "durable_preflight_failed",
                    "message": "Encrypted chat preflight is temporarily unavailable.",
                },
            },
            "user-1",
            "device-hash",
        )
    ]


def test_preflight_derives_a_purpose_bound_commitment_key_from_internal_token(monkeypatch) -> None:
    monkeypatch.delenv("CHAT_RECOVERY_COMMITMENT_KEY", raising=False)
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "internal-token")
    inference_request = _payload()["inference_request"]

    expected_key = hmac.new(
        b"internal-token", b"openmates:chat-recovery-commitment:v1", hashlib.sha256
    ).digest()
    expected = hmac.new(
        expected_key,
        json.dumps(inference_request, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(),
        hashlib.sha256,
    ).hexdigest()

    assert chat_turn_preflight_handler.build_inference_commitment(inference_request) == expected


@pytest.mark.asyncio
async def test_enqueue_uses_stable_identities_and_matching_commitment(monkeypatch) -> None:
    monkeypatch.setenv("CHAT_RECOVERY_COMMITMENT_KEY", "commitment-secret")
    monkeypatch.setattr(chat_turn_preflight_handler, "ChatRecoveryService", FakeRecoveryService)
    FakeRecoveryService.calls = []
    inference_request = _payload()["inference_request"]

    first = await chat_turn_preflight_handler.enqueue_chat_turn(
        directus_service=object(),
        user_id_hash="owner-hash",
        device_fingerprint_hash="device-hash",
        preflight_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        inference_request=inference_request,
    )
    await chat_turn_preflight_handler.enqueue_chat_turn(
        directus_service=object(),
        user_id_hash="owner-hash",
        device_fingerprint_hash="device-hash",
        preflight_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        inference_request=inference_request,
    )

    assert first["state"] == "PREPARED"
    first_data = FakeRecoveryService.calls[0][1]
    second_data = FakeRecoveryService.calls[1][1]
    assert FakeRecoveryService.calls[0][0] == "enqueue_inference"
    assert first_data == second_data
    assert first_data["inference_task_id"] != first_data["billing_identity"]
    assert first_data["billing_identity"] != first_data["outbox_id"]
