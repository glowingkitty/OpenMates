"""
WebSocket contract tests for durable encrypted chat-turn preflight.

The handler must commit encrypted user storage before acknowledging a send,
derive the inference commitment server-side, and avoid forwarding plaintext to
the Directus transaction extension.
"""

import hashlib
import hmac
import json
import base64
from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.core.api.app.routes.handlers.websocket_handlers import chat_turn_preflight_handler
from backend.core.api.app.schemas.chat import AIHistoryMessage
from backend.core.api.app.services.team_chat_ai_service import normalize_team_ai_inference_request


class FakeManager:
    def __init__(self) -> None:
        self.messages: list[tuple[dict, str, str]] = []
        self.task_update_jobs = False

    async def send_personal_message(self, message: dict, user_id: str, device_hash: str) -> None:
        self.messages.append((message, user_id, device_hash))

    def supports_task_update_jobs(self, user_id: str, device_hash: str) -> bool:
        return self.task_update_jobs


class FakeWebSocket:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.messages.append(message)


class FakeRecoveryService:
    calls: list[tuple[str, dict]] = []

    def __init__(self, directus_service) -> None:
        self.directus_service = directus_service

    async def execute(self, operation: str, data: dict) -> dict:
        self.calls.append((operation, data))
        if operation == "get_cutover_state":
            return {"protocol_epoch": 1, "sends_paused": False, "legacy_in_flight": 0}
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
# contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,chats.message.identity-idempotent
async def test_preflight_commits_only_encrypted_data_and_acknowledges(monkeypatch) -> None:
    monkeypatch.setenv("CHAT_RECOVERY_COMMITMENT_KEY", "commitment-secret")
    monkeypatch.setattr(chat_turn_preflight_handler, "ChatRecoveryService", FakeRecoveryService)
    telemetry = []
    monkeypatch.setattr(chat_turn_preflight_handler, "start_recovery_timing", lambda: 1.0)
    monkeypatch.setattr(
        chat_turn_preflight_handler,
        "record_recovery_duration",
        lambda phase, started_at: telemetry.append((phase, started_at)),
    )
    FakeRecoveryService.calls = []
    manager = FakeManager()
    websocket = FakeWebSocket()
    payload = _payload()

    await chat_turn_preflight_handler.handle_chat_turn_preflight(
        websocket=websocket,
        manager=manager,
        directus_service=object(),
        user_id="user-1",
        user_id_hash="owner-hash",
        device_fingerprint_hash="device-hash",
        payload=payload,
    )

    operation, transaction_data = FakeRecoveryService.calls[1]
    assert operation == "prepare_preflight"
    assert transaction_data["hashed_user_id"] == "owner-hash"
    assert transaction_data["device_hash"] == "device-hash"
    assert transaction_data["encrypted_user_message"]["hashed_user_id"] == "owner-hash"
    assert "inference_request" not in transaction_data
    assert "private plaintext" not in json.dumps(transaction_data)
    expected_inference_request = dict(payload["inference_request"])
    expected_inference_request["client_capabilities"] = []
    canonical = json.dumps(expected_inference_request, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    assert transaction_data["inference_commitment"] == hmac.new(
        b"commitment-secret", canonical, hashlib.sha256
    ).hexdigest()
    assert manager.messages == []
    assert websocket.messages[0]["type"] == "chat_turn_preflight_ack"
    assert websocket.messages[0]["payload"]["preflight_id"] == "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    assert websocket.messages[0]["payload"]["turn_id"] == payload["turn_id"]
    assert telemetry == [("durable_preflight", 1.0)]


@pytest.mark.asyncio
# contract-test: supporting surface=gui.web assertions=chats.message.identity-idempotent
async def test_epoch_zero_acknowledges_without_persisting_recovery_state(monkeypatch) -> None:
    class EpochZeroRecoveryService(FakeRecoveryService):
        async def execute(self, operation: str, data: dict) -> dict:
            self.calls.append((operation, data))
            assert operation == "get_cutover_state"
            return {"protocol_epoch": 0, "sends_paused": False, "legacy_in_flight": 0}

    monkeypatch.setattr(
        chat_turn_preflight_handler,
        "ChatRecoveryService",
        EpochZeroRecoveryService,
    )
    EpochZeroRecoveryService.calls = []
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

    assert [call[0] for call in EpochZeroRecoveryService.calls] == ["get_cutover_state"]
    assert manager.messages[0][0] == {
        "type": "chat_turn_preflight_ack",
        "payload": {
            "preflight_id": "2e500b1c-a0e0-5b44-b2d5-820c6eb56697",
            "state": "LEGACY",
            "turn_id": payload["turn_id"],
        },
    }


@pytest.mark.asyncio
# contract-test: direct surface=gui.web assertions=teams.chat.encrypted-until-invoked,chats.persistence.client-encrypted
async def test_epoch_zero_ordinary_team_preflight_commits_before_ack(monkeypatch) -> None:
    class EpochZeroRecoveryService(FakeRecoveryService):
        async def execute(self, operation: str, data: dict) -> dict:
            self.calls.append((operation, data))
            if operation == "get_cutover_state":
                return {"protocol_epoch": 0, "sends_paused": False, "legacy_in_flight": 0}
            return {"preflight_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "state": "PREPARED"}

    async def require_team_role(*_args):
        return None

    monkeypatch.setenv("CHAT_RECOVERY_COMMITMENT_KEY", "commitment-key")
    monkeypatch.setattr(chat_turn_preflight_handler, "ChatRecoveryService", EpochZeroRecoveryService)
    EpochZeroRecoveryService.calls = []
    directus = type("Directus", (), {"team": type("Team", (), {"require_team_role": staticmethod(require_team_role)})()})()
    manager = FakeManager()
    payload = _payload()
    payload["team_id"] = "team-1"
    ciphertext = base64.b64encode(b"x" * 29).decode("ascii")
    payload["encrypted_user_message"]["encrypted_content"] = ciphertext
    payload["inference_request"] = {
        "team_id": "team-1",
        "chat_id": payload["chat_id"],
        "message": {"message_id": payload["message_id"], "encrypted_content": ciphertext},
    }

    await chat_turn_preflight_handler.handle_chat_turn_preflight(
        manager=manager, directus_service=directus, user_id="user-1", user_id_hash="owner-hash",
        device_fingerprint_hash="device-hash", payload=payload,
    )

    assert [operation for operation, _ in EpochZeroRecoveryService.calls] == ["get_cutover_state", "prepare_preflight"]
    committed = EpochZeroRecoveryService.calls[1][1]
    assert committed["hashed_team_id"] == hashlib.sha256(b"team-1").hexdigest()
    assert committed["encrypted_user_message"]["encrypted_content"] == ciphertext
    assert "inference_request" not in committed
    assert manager.messages[0][0]["payload"]["state"] == "PREPARED"


@pytest.mark.asyncio
# contract-test: direct surface=gui.web assertions=teams.chat.encrypted-until-invoked,chats.message.identity-idempotent
async def test_ordinary_team_lost_ack_retry_ignores_live_inference_metadata(monkeypatch) -> None:
    from backend.core.api.app.services import project_write_authorization_service
    from backend.core.api.app.services.chat_recovery_service import ChatRecoveryProtocolError

    class IdempotentRecoveryService:
        committed: dict | None = None
        commit_count = 0

        def __init__(self, _directus_service) -> None:
            pass

        async def execute(self, operation: str, data: dict) -> dict:
            if operation == "get_cutover_state":
                return {"protocol_epoch": 0, "sends_paused": False, "legacy_in_flight": 0}
            assert operation == "prepare_preflight"
            if self.committed is None:
                self.__class__.committed = deepcopy(data)
                self.__class__.commit_count += 1
            elif data != self.committed:
                raise ChatRecoveryProtocolError(409, "preflight_mismatch")
            return {"preflight_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "state": "PREPARED"}

    focus = {"project_id": "project-before"}
    focus_reads = []

    class ChangingFocus:
        def __init__(self, *_args) -> None:
            pass

        async def get_active_focus(self, **_kwargs) -> dict:
            focus_reads.append(focus["project_id"])
            return {"project_id": focus["project_id"]}

    async def require_team_role(*_args):
        return None

    monkeypatch.setenv("CHAT_RECOVERY_COMMITMENT_KEY", "commitment-key")
    monkeypatch.setattr(chat_turn_preflight_handler, "ChatRecoveryService", IdempotentRecoveryService)
    monkeypatch.setattr(project_write_authorization_service, "ProjectWriteAuthorizationService", ChangingFocus)
    directus = SimpleNamespace(team=SimpleNamespace(require_team_role=require_team_role))
    websocket = FakeWebSocket()
    websocket.app = SimpleNamespace(state=SimpleNamespace(cache_service=object(), encryption_service=None))
    manager = FakeManager()
    payload = _payload()
    payload["team_id"] = "team-1"
    ciphertext = base64.b64encode(b"x" * 29).decode("ascii")
    payload["encrypted_user_message"]["encrypted_content"] = ciphertext
    payload["inference_request"] = {
        "team_id": "team-1", "chat_id": payload["chat_id"],
        "message": {"message_id": payload["message_id"], "encrypted_content": ciphertext},
    }

    async def attempt(request: dict, connection_hash: str) -> None:
        await chat_turn_preflight_handler.handle_chat_turn_preflight(
            websocket=websocket, manager=manager, directus_service=directus,
            user_id="user-1", user_id_hash="owner-hash",
            device_fingerprint_hash=connection_hash,
            stable_device_fingerprint_hash="authenticated-device-hash", payload=request,
        )

    await attempt(deepcopy(payload), "connection-before")
    manager.task_update_jobs = True
    focus["project_id"] = "project-after"
    await attempt(deepcopy(payload), "connection-after")

    assert [message["type"] for message in websocket.messages] == [
        "chat_turn_preflight_ack", "chat_turn_preflight_ack"
    ]
    assert websocket.messages[0]["payload"]["preflight_id"] == websocket.messages[1]["payload"]["preflight_id"]
    assert IdempotentRecoveryService.commit_count == 1
    assert focus_reads == []
    assert IdempotentRecoveryService.committed["device_hash"] == "authenticated-device-hash"
    assert IdempotentRecoveryService.committed["inference_commitment"] == (
        chat_turn_preflight_handler.build_inference_commitment(payload["inference_request"])
    )

    changed = deepcopy(payload)
    changed_ciphertext = base64.b64encode(b"y" * 29).decode("ascii")
    changed["encrypted_user_message"]["encrypted_content"] = changed_ciphertext
    changed["inference_request"]["message"]["encrypted_content"] = changed_ciphertext
    await attempt(changed, "connection-after")
    assert websocket.messages[-1]["type"] == "error"
    assert websocket.messages[-1]["payload"]["code"] == "preflight_mismatch"
    assert IdempotentRecoveryService.commit_count == 1


@pytest.mark.asyncio
# contract-test: direct surface=gui.web assertions=teams.chat.encrypted-until-invoked,chats.message.identity-idempotent
async def test_team_ai_preflight_and_enqueue_bind_the_same_typed_history(monkeypatch) -> None:
    from backend.core.api.app.services.chat_recovery_service import ChatRecoveryProtocolError
    from backend.core.api.app.services import project_write_authorization_service

    class BoundRecoveryService(FakeRecoveryService):
        calls: list[tuple[str, dict]] = []
        commitment: str | None = None

        async def execute(self, operation: str, data: dict) -> dict:
            if operation == "prepare_preflight":
                BoundRecoveryService.commitment = data["inference_commitment"]
            elif operation == "enqueue_inference" and data["inference_commitment"] != BoundRecoveryService.commitment:
                raise ChatRecoveryProtocolError(409, "preflight_mismatch")
            return await super().execute(operation, data)

    class NoProjectFocus:
        def __init__(self, *_args) -> None:
            pass

        async def get_active_focus(self, **_kwargs) -> None:
            return None

    async def require_team_role(*_args) -> None:
        return None

    monkeypatch.setenv("CHAT_RECOVERY_COMMITMENT_KEY", "commitment-key")
    monkeypatch.setattr(chat_turn_preflight_handler, "ChatRecoveryService", BoundRecoveryService)
    monkeypatch.setattr(project_write_authorization_service, "ProjectWriteAuthorizationService", NoProjectFocus)
    manager = FakeManager()
    websocket = FakeWebSocket()
    websocket.app = SimpleNamespace(state=SimpleNamespace(cache_service=object(), encryption_service=None))
    directus = SimpleNamespace(team=SimpleNamespace(require_team_role=require_team_role))
    payload = _payload()
    payload["team_id"] = "team-1"
    ciphertext = base64.b64encode(b"x" * 29).decode("ascii")
    payload["encrypted_user_message"]["encrypted_content"] = ciphertext
    history = [
        {"role": "user", "content": "A teammate proposed a venue.", "sender_name": "Owner", "created_at": 99},
        {"role": "user", "content": "@openmates, who proposed the venue?", "sender_name": "Member", "created_at": 100},
    ]
    raw_request = {
        "team_id": "team-1", "chat_id": payload["chat_id"],
        "message": {"message_id": payload["message_id"], "role": "user", "encrypted_content": ciphertext,
                    "created_at": 100},
        "team_ai_invocation": {"history": deepcopy(history)},
        "message_history": deepcopy(history),
    }
    payload["inference_request"] = deepcopy(raw_request)

    # A Team AI commitment must authorize the same row and ciphertext that
    # prepare_preflight persists, even before the history normalization runs.
    for mutation in ("inference_ciphertext", "inference_message_id", "stored_message_id", "stored_chat_id"):
        rejected = deepcopy(payload)
        if mutation == "inference_ciphertext":
            rejected["inference_request"]["message"]["encrypted_content"] = base64.b64encode(b"y" * 29).decode("ascii")
        elif mutation == "inference_message_id":
            rejected["inference_request"]["message"]["message_id"] = "other-message"
        elif mutation == "stored_message_id":
            rejected["encrypted_user_message"]["client_message_id"] = "other-message"
        else:
            rejected["encrypted_user_message"]["chat_id"] = "other-chat"
        rejected_websocket = FakeWebSocket()
        rejected_websocket.app = websocket.app
        BoundRecoveryService.calls = []
        await chat_turn_preflight_handler.handle_chat_turn_preflight(
            websocket=rejected_websocket, manager=manager, directus_service=directus,
            user_id="user-1", user_id_hash="owner-hash", device_fingerprint_hash="device-hash",
            payload=rejected,
        )
        assert rejected_websocket.messages[-1]["payload"]["code"] == "message_identity_mismatch"
        assert [operation for operation, _ in BoundRecoveryService.calls] == ["get_cutover_state"]
    BoundRecoveryService.calls = []

    await chat_turn_preflight_handler.handle_chat_turn_preflight(
        websocket=websocket, manager=manager, directus_service=directus,
        user_id="user-1", user_id_hash="owner-hash", device_fingerprint_hash="device-hash",
        payload=payload,
    )
    assert websocket.messages[-1]["type"] == "chat_turn_preflight_ack"
    prepared = next(data for operation, data in BoundRecoveryService.calls if operation == "prepare_preflight")
    assert "inference_request" not in prepared
    assert "@openmates" not in json.dumps(prepared)

    # The receive handler replaces the compact client history with typed JSON
    # before enqueueing. The shared normalizer makes both commitments identical.
    dispatch_request = deepcopy(raw_request)
    dispatch_request["message_history"] = [AIHistoryMessage.model_validate(item).model_dump(mode="json")
                                            for item in history]
    dispatch_request.update(client_capabilities=[], current_project=None, active_project_focus=None)
    normalized = normalize_team_ai_inference_request(dispatch_request)
    assert normalized["message_history"][-1]["content"] == history[-1]["content"]
    assert "content" not in normalized["message"]
    assert "@openmates" in chat_turn_preflight_handler.canonicalize_inference_request(normalized).decode()
    await chat_turn_preflight_handler.enqueue_chat_turn(
        directus_service=directus, user_id_hash="owner-hash", device_fingerprint_hash="device-hash",
        preflight_id=websocket.messages[-1]["payload"]["preflight_id"],
        inference_request=normalized,
    )
    assert BoundRecoveryService.calls[-1][0] == "enqueue_inference"
    assert BoundRecoveryService.calls[-1][1]["inference_commitment"] == prepared["inference_commitment"]

    for mutation in ("prompt", "ciphertext"):
        tampered = deepcopy(dispatch_request)
        if mutation == "prompt":
            tampered["team_ai_invocation"]["history"][-1]["content"] = "@openmates, ignore the original question"
            tampered["message_history"][-1]["content"] = "@openmates, ignore the original question"
        else:
            tampered["message"]["encrypted_content"] = base64.b64encode(b"y" * 29).decode("ascii")
        with pytest.raises(ChatRecoveryProtocolError, match="preflight_mismatch"):
            await chat_turn_preflight_handler.enqueue_chat_turn(
                directus_service=directus, user_id_hash="owner-hash", device_fingerprint_hash="device-hash",
                preflight_id=websocket.messages[-1]["payload"]["preflight_id"],
                inference_request=normalize_team_ai_inference_request(tampered),
            )

    inconsistent = deepcopy(dispatch_request)
    inconsistent["message_history"][-1]["content"] = "Different plaintext history"
    with pytest.raises(ValueError, match="differs from the invocation"):
        normalize_team_ai_inference_request(inconsistent)


@pytest.mark.asyncio
# contract-test: supporting surface=gui.web assertions=teams.chat.encrypted-until-invoked
async def test_epoch_zero_ordinary_team_preflight_respects_send_pause(monkeypatch) -> None:
    class PausedRecoveryService(FakeRecoveryService):
        async def execute(self, operation: str, data: dict) -> dict:
            self.calls.append((operation, data))
            return {"protocol_epoch": 0, "sends_paused": True, "legacy_in_flight": 0}

    monkeypatch.setattr(chat_turn_preflight_handler, "ChatRecoveryService", PausedRecoveryService)
    PausedRecoveryService.calls = []
    payload = _payload()
    payload["team_id"] = "team-1"
    payload["inference_request"] = {
        "team_id": "team-1", "chat_id": payload["chat_id"],
        "message": {"message_id": payload["message_id"], "encrypted_content": "ciphertext"},
    }
    manager = FakeManager()
    await chat_turn_preflight_handler.handle_chat_turn_preflight(
        manager=manager, directus_service=object(), user_id="user-1", user_id_hash="owner-hash",
        device_fingerprint_hash="device-hash", payload=payload,
    )
    assert [operation for operation, _ in PausedRecoveryService.calls] == ["get_cutover_state"]
    assert manager.messages[0][0]["type"] == "error"
    assert manager.messages[0][0]["payload"]["code"] == "inference_temporarily_paused"


@pytest.mark.asyncio
# contract-test: direct surface=gui.web assertions=teams.chat.encrypted-until-invoked,chats.persistence.client-encrypted
async def test_epoch_zero_ordinary_team_commit_failure_sends_no_ack(monkeypatch) -> None:
    from backend.core.api.app.services.chat_recovery_service import ChatRecoveryProtocolError

    class FailingRecoveryService(FakeRecoveryService):
        async def execute(self, operation: str, data: dict) -> dict:
            self.calls.append((operation, data))
            if operation == "get_cutover_state":
                return {"protocol_epoch": 0, "sends_paused": False, "legacy_in_flight": 0}
            raise ChatRecoveryProtocolError(409, "version_conflict")

    async def require_team_role(*_args):
        return None

    monkeypatch.setenv("CHAT_RECOVERY_COMMITMENT_KEY", "commitment-key")
    monkeypatch.setattr(chat_turn_preflight_handler, "ChatRecoveryService", FailingRecoveryService)
    FailingRecoveryService.calls = []
    directus = type("Directus", (), {"team": type("Team", (), {"require_team_role": staticmethod(require_team_role)})()})()
    payload = _payload()
    payload["team_id"] = "team-1"
    ciphertext = base64.b64encode(b"x" * 29).decode("ascii")
    payload["encrypted_user_message"]["encrypted_content"] = ciphertext
    payload["inference_request"] = {
        "team_id": "team-1", "chat_id": payload["chat_id"],
        "message": {"message_id": payload["message_id"], "encrypted_content": ciphertext},
    }
    manager = FakeManager()
    await chat_turn_preflight_handler.handle_chat_turn_preflight(
        manager=manager, directus_service=directus, user_id="user-1", user_id_hash="owner-hash",
        device_fingerprint_hash="device-hash", payload=payload,
    )
    assert [operation for operation, _ in FailingRecoveryService.calls] == ["get_cutover_state", "prepare_preflight"]
    assert [message[0]["type"] for message in manager.messages] == ["error"]
    assert manager.messages[0][0]["payload"]["code"] == "version_conflict"


@pytest.mark.asyncio
# contract-test: supporting surface=gui.web assertions=teams.chat.encrypted-until-invoked
async def test_epoch_zero_ordinary_team_scope_mismatch_never_commits(monkeypatch) -> None:
    class EpochZeroRecoveryService(FakeRecoveryService):
        async def execute(self, operation: str, data: dict) -> dict:
            self.calls.append((operation, data))
            return {"protocol_epoch": 0, "sends_paused": False, "legacy_in_flight": 0}

    monkeypatch.setattr(chat_turn_preflight_handler, "ChatRecoveryService", EpochZeroRecoveryService)
    EpochZeroRecoveryService.calls = []
    payload = _payload()
    payload["team_id"] = "team-1"
    payload["inference_request"] = {
        "team_id": "team-2", "chat_id": payload["chat_id"],
        "message": {"message_id": payload["message_id"], "encrypted_content": "ciphertext"},
    }
    manager = FakeManager()
    await chat_turn_preflight_handler.handle_chat_turn_preflight(
        manager=manager, directus_service=object(), user_id="user-1", user_id_hash="owner-hash",
        device_fingerprint_hash="device-hash", payload=payload,
    )
    assert [operation for operation, _ in EpochZeroRecoveryService.calls] == ["get_cutover_state"]
    assert manager.messages[0][0]["payload"]["code"] == "team_chat_scope_mismatch"


@pytest.mark.asyncio
# contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
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
                    "turn_id": "22222222-2222-4222-8222-222222222222",
                },
            },
            "user-1",
            "device-hash",
        )
    ]


# contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
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
# contract-test: supporting surface=gui.web assertions=chats.message.identity-idempotent
async def test_enqueue_uses_stable_identities_and_matching_commitment(monkeypatch) -> None:
    monkeypatch.setenv("CHAT_RECOVERY_COMMITMENT_KEY", "commitment-secret")
    monkeypatch.setattr(chat_turn_preflight_handler, "ChatRecoveryService", FakeRecoveryService)
    telemetry = []
    monkeypatch.setattr(chat_turn_preflight_handler, "start_recovery_timing", lambda: 2.0)
    monkeypatch.setattr(
        chat_turn_preflight_handler,
        "record_recovery_duration",
        lambda phase, started_at: telemetry.append((phase, started_at)),
    )
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
    assert telemetry == [("enqueue_inference", 2.0), ("enqueue_inference", 2.0)]


# contract-test: supporting surface=gui.web assertions=projects.focus.mention-activation,chats.message.identity-idempotent
def test_project_activation_after_preflight_preserves_immutable_user_request(monkeypatch) -> None:
    monkeypatch.setenv("CHAT_RECOVERY_COMMITMENT_KEY", "commitment-secret")
    prepared = {**_payload()["inference_request"], "current_project": None, "active_project_focus": None}
    dispatched = deepcopy(prepared)
    dispatched["current_project"] = {"project_id": "project-1"}
    dispatched["active_project_focus"] = {"project_id": "project-1", "instruction": "authorized instructions"}
    assert chat_turn_preflight_handler.build_inference_commitment(prepared) == chat_turn_preflight_handler.build_inference_commitment(dispatched)
    dispatched["message"] = {"content": "a different user request"}
    assert chat_turn_preflight_handler.build_inference_commitment(prepared) != chat_turn_preflight_handler.build_inference_commitment(dispatched)
