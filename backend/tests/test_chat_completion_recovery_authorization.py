"""
Authorization contracts for every sealed completion recovery operation.

The authenticated owner and server-derived device identity must be applied to
all operations, and rejected requests must return only a sanitized error code.
"""

import pytest

from backend.core.api.app.routes.handlers.websocket_handlers import chat_recovery_job_handlers
from backend.core.api.app.services.chat_recovery_service import ChatRecoveryProtocolError


class Manager:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_personal_message(self, message: dict, *_args) -> None:
        self.messages.append(message)


class RejectingService:
    def __init__(self, _directus_service) -> None:
        pass

    async def execute(self, _operation: str, _data: dict) -> dict:
        raise ChatRecoveryProtocolError(404, "recovery_job_not_found")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handler_name",
    ["handle_recovery_job_claim", "handle_recovery_job_renew", "handle_recovery_job_persist"],
)
async def test_rejected_job_request_discloses_no_payload_or_chat_metadata(monkeypatch, handler_name: str) -> None:
    monkeypatch.setattr(chat_recovery_job_handlers, "ChatRecoveryService", RejectingService)
    manager = Manager()
    payload = {
        "protocol_version": 1,
        "job_id": "11111111-1111-4111-8111-111111111111",
        "chat_id": "sensitive-chat-id",
        "sealed_payload": "sensitive-sealed-payload",
        "lease_generation": 1,
        "lease_token": "sensitive-lease-token",
        "expected_messages_v": 2,
        "encrypted_assistant_message": {},
    }

    await getattr(chat_recovery_job_handlers, handler_name)(
        manager=manager,
        directus_service=object(),
        user_id="authenticated-user",
        user_id_hash="authenticated-owner-hash",
        device_fingerprint_hash="authenticated-device-hash",
        payload=payload,
    )

    assert manager.messages == [{"type": "error", "payload": {
        "code": "recovery_job_not_found",
        "message": "Encrypted completion recovery was rejected.",
    }}]
    assert "sensitive" not in repr(manager.messages)


@pytest.mark.asyncio
async def test_lease_renewal_uses_authenticated_owner_and_device(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    class RecordingService:
        def __init__(self, _directus_service) -> None:
            pass

        async def execute(self, operation: str, data: dict) -> dict:
            calls.append((operation, data))
            return {"job_id": data["job_id"], "state": "LEASED"}

    monkeypatch.setattr(chat_recovery_job_handlers, "ChatRecoveryService", RecordingService)
    manager = Manager()
    await chat_recovery_job_handlers.handle_recovery_job_renew(
        manager=manager,
        directus_service=object(),
        user_id="authenticated-user",
        user_id_hash="authenticated-owner-hash",
        device_fingerprint_hash="authenticated-device-hash",
        payload={
            "protocol_version": 1,
            "job_id": "11111111-1111-4111-8111-111111111111",
            "hashed_user_id": "attacker-owner",
            "device_hash": "attacker-device",
            "lease_generation": 3,
            "lease_token": "lease-token",
        },
    )

    assert calls == [("renew_lease", {
        "protocol_version": 1,
        "job_id": "11111111-1111-4111-8111-111111111111",
        "hashed_user_id": "authenticated-owner-hash",
        "device_hash": "authenticated-device-hash",
        "lease_generation": 3,
        "lease_token": "lease-token",
    })]
    assert manager.messages[0]["type"] == "recovery_job_renewed"


@pytest.mark.parametrize(
    "handler_name",
    ["handle_recovery_job_renew", "handle_recovery_job_persist"],
)
def test_all_mutating_recovery_operations_have_authenticated_handlers(handler_name: str) -> None:
    assert callable(getattr(chat_recovery_job_handlers, handler_name, None)), (
        f"missing authenticated recovery operation handler: {handler_name}"
    )


@pytest.mark.asyncio
async def test_device_revocation_immediately_invalidates_authenticated_device_lease(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    class RecordingService:
        def __init__(self, _directus_service) -> None:
            pass

        async def execute(self, operation: str, data: dict) -> dict:
            calls.append((operation, data))
            return {"invalidated_leases": 1}

    monkeypatch.setattr(chat_recovery_job_handlers, "ChatRecoveryService", RecordingService)
    result = await chat_recovery_job_handlers.invalidate_recovery_leases_for_device(
        directus_service=object(),
        user_id_hash="authenticated-owner-hash",
        device_fingerprint_hash="revoked-device-hash",
    )

    assert result == {"invalidated_leases": 1}
    assert calls == [("invalidate_deletion", {
        "protocol_version": 1,
        "hashed_user_id": "authenticated-owner-hash",
        "scope": "device",
        "device_hash": "revoked-device-hash",
    })]
