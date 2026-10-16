"""WebSocket contracts for Workflow pending chat delivery.

The backend binds delivery claims to the authenticated owner/device and accepts
only client ciphertext under the current fence. Raw regular chat keys are never
part of the protocol.

Spec: docs/specs/workflows-cli-runtime/spec.yml
"""

from __future__ import annotations

import pytest
import asyncio
import threading
from types import SimpleNamespace
import json
import httpx

from backend.core.api.app.routes.handlers.websocket_handlers import workflow_chat_delivery_handlers
from backend.core.api.app.services.workflow_chat_delivery_service import WorkflowChatDeliveryService
from backend.core.api.app.services.workflow_delivery_history import WorkflowDeliveryHistoryError


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
@pytest.mark.parametrize("status_code,code,expected_status", [
    (400, "selected_embeds_required", "failed"),
    (400, "unknown_validation", "claimed"),
    (409, "delivery_conflict", "claimed"),
])
# contract-test: supporting surface=rest_api assertions=workflows.chat-delivery.claim-fenced,workflows.chat-delivery.client-encrypted
async def test_permanent_client_ciphertext_rejection_fails_only_current_claim(
    monkeypatch, status_code: int, code: str, expected_status: str,
) -> None:
    service = WorkflowChatDeliveryService(cipher=FakeVaultCipher(), clock=lambda: 100)
    delivery = service.create_delivery(owner_id="alice", title="Title", message="Message", expires_at=200,
                                       workflow_id="workflow-1", run_id="run-1", node_id="send")
    claim = service.claim_new_chat_delivery(delivery_id=delivery.delivery_id, owner_id="alice", device_id="device-hash")
    request = httpx.Request("POST", "http://directus.example/workflow-runtime-transaction")
    response = httpx.Response(status_code, request=request, json={"error": {"code": code}})

    def reject(**kwargs):
        del kwargs
        raise WorkflowDeliveryHistoryError("Workflow delivery transaction was rejected") from httpx.HTTPStatusError(
            "Rejected", request=request, response=response,
        )

    monkeypatch.setattr(service, "persist_client_ciphertext", reject)
    monkeypatch.setattr(workflow_chat_delivery_handlers, "_service", lambda directus_service: service)
    manager = FakeManager()
    await workflow_chat_delivery_handlers.handle_workflow_chat_delivery_persist(
        manager=manager, directus_service=object(), user_id="alice", device_fingerprint_hash="device-hash",
        payload={"delivery_id": delivery.delivery_id, "claim_token": claim.token,
                 "claim_generation": claim.generation, "claim_issued_at": claim.issued_at,
                 "claim_expires_at": claim.expires_at, "encrypted_chat_metadata": "ciphertext",
                 "encrypted_message": "ciphertext"},
    )
    assert service.get_delivery(delivery_id=delivery.delivery_id, owner_id="alice").status == expected_status
    assert manager.messages[-1]["message"]["payload"]["code"] == "workflow_chat_delivery_rejected"


# contract-test: supporting surface=rest_api assertions=workflows.chat-delivery.pending-private
@pytest.mark.asyncio
async def test_reconnect_advertises_owner_authorized_pending_deliveries(monkeypatch) -> None:
    service = WorkflowChatDeliveryService(cipher=FakeVaultCipher(), clock=lambda: 100)
    service.create_delivery(owner_id="alice", title="Title", message="Message", expires_at=200)
    service.create_delivery(owner_id="bob", title="Other owner", message="Private", expires_at=200)
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
    assert len(message["payload"]["deliveries"]) == 1
    assert message["payload"]["deliveries"][0]["encrypted_payload"].startswith("vault:")


# contract-test: supporting surface=rest_api assertions=workflows.chat-delivery.claim-fenced,workflows.chat-delivery.client-encrypted
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


# contract-test: supporting surface=rest_api assertions=workflows.chat-delivery.pending-private
@pytest.mark.asyncio
async def test_pending_delivery_discovery_keeps_loop_responsive_and_repository_lifecycle_on_one_thread(monkeypatch):
    loop = asyncio.get_running_loop()
    loop_thread = threading.get_ident()
    started = asyncio.Event()
    release = threading.Event()
    events = []
    delivery = SimpleNamespace()
    manager = FakeManager()
    original_send = manager.send_personal_message

    async def send(*args):
        events.append(("dispatch", threading.get_ident()))
        await original_send(*args)

    def close():
        events.append(("close", threading.get_ident()))

    def list_pending(*, owner_id):
        assert owner_id == "alice"
        events.append(("list", threading.get_ident()))
        loop.call_soon_threadsafe(started.set)
        if not release.wait(timeout=2):
            raise RuntimeError("event loop did not release blocked discovery")
        return [delivery]

    def construct(directus):
        assert directus is directus_service
        events.append(("construct", threading.get_ident()))
        return SimpleNamespace(list_pending_for_owner=list_pending,
                               _repository=SimpleNamespace(_client=SimpleNamespace(close=close)))

    directus_service = object()
    monkeypatch.setattr(workflow_chat_delivery_handlers, "_service", construct)
    monkeypatch.setattr(workflow_chat_delivery_handlers, "_delivery_payload", lambda value: {"safe": value is delivery})
    monkeypatch.setattr(manager, "send_personal_message", send)
    task = asyncio.create_task(workflow_chat_delivery_handlers.send_available_workflow_chat_deliveries(
        manager=manager, directus_service=directus_service, user_id="alice", device_fingerprint_hash="device"))
    try:
        await asyncio.wait_for(started.wait(), timeout=3)
        # Reaching here while discovery remains blocked proves another socket's
        # receive/lifecycle callback can run; no timing-sensitive sleep is needed.
        assert not task.done()
        assert manager.messages == []
    finally:
        release.set()
        await task
    assert [name for name, _thread in events] == ["construct", "list", "close", "dispatch"]
    worker_threads = {thread for name, thread in events if name != "dispatch"}
    assert len(worker_threads) == 1 and loop_thread not in worker_threads
    assert events[-1][1] == loop_thread
    assert manager.messages == [{"message": {"type": "workflow_chat_deliveries_available",
        "payload": {"deliveries": [{"safe": True}]}}, "user_id": "alice", "device_hash": "device"}]


# contract-test: supporting surface=rest_api assertions=workflows.chat-delivery.pending-private,workflows.chat-delivery.claim-fenced
@pytest.mark.asyncio
@pytest.mark.parametrize("close_fails", [False, True])
async def test_pending_delivery_discovery_reports_authority_failure_and_closes_owned_client(monkeypatch, caplog, close_fails):
    events = []
    manager = FakeManager()

    def list_pending(*, owner_id):
        assert owner_id == "alice"
        events.append(("list", threading.get_ident()))
        raise PermissionError("current owner authority denied")

    def close():
        events.append(("close", threading.get_ident()))
        if close_fails:
            raise RuntimeError("cleanup failed")

    monkeypatch.setattr(workflow_chat_delivery_handlers, "_service", lambda _directus: SimpleNamespace(
        list_pending_for_owner=list_pending, _repository=SimpleNamespace(_client=SimpleNamespace(close=close))))
    monkeypatch.setattr(workflow_chat_delivery_handlers.logger, "handlers", [caplog.handler])
    monkeypatch.setattr(workflow_chat_delivery_handlers.logger, "propagate", False)
    await workflow_chat_delivery_handlers.send_available_workflow_chat_deliveries(
        manager=manager, directus_service=object(), user_id="alice", device_fingerprint_hash="device")
    assert [name for name, _thread in events] == ["list", "close"]
    assert events[0][1] == events[1][1] != threading.get_ident()
    assert manager.messages == []
    errors = [record for record in caplog.records if record.exc_info]
    assert any(isinstance(record.exc_info[1], PermissionError) for record in errors)
    assert "Workflow chat delivery discovery failed" in caplog.text
    assert ("Workflow chat delivery discovery client cleanup failed" in caplog.text) is close_fails
