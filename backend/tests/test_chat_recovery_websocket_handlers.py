"""
WebSocket contracts for claiming and completing sealed recovery jobs.

Authenticated identity always overrides client owner/device fields. Terminal
persistence sends only client ciphertext and acknowledges after the Directus
transaction commits with the current lease fencing generation.
"""

import asyncio
import json
from types import SimpleNamespace
import pytest

from backend.core.api.app.routes.connection_manager import (
    ConnectionManager, permits_canonical_embed_write,
    should_rediscover_recovery_on_lifecycle,
)
from backend.core.api.app.routes.handlers.websocket_handlers import chat_recovery_job_handlers
from backend.core.api.app.routes import websockets as websocket_routes
from backend.core.api.app.services.chat_recovery_service import ChatRecoveryProtocolError
from backend.core.api.app.services.directus.team_methods import hash_id


class FakeManager:
    def __init__(self, *, typed: bool = False, receipts: bool = False, foreground: bool = True) -> None:
        self.messages: list[dict] = []
        self.typed = typed
        self.receipts = receipts
        self.foreground = foreground

    async def send_personal_message(self, message: dict, user_id: str, device_hash: str) -> None:
        self.messages.append(message)

    def supports_typed_recovery_outputs(self, _user_id: str, _device_hash: str) -> bool:
        return self.foreground and self.typed

    def supports_canonical_embed_receipts(self, _user_id: str, _device_hash: str) -> bool:
        return self.foreground and self.receipts

    def negotiated_typed_recovery_outputs(self, _user_id: str, _device_hash: str) -> bool:
        return self.typed

    def negotiated_canonical_embed_receipts(self, _user_id: str, _device_hash: str) -> bool:
        return self.receipts

    def is_connection_completion_capable(self, _user_id: str, _device_hash: str) -> bool:
        return self.foreground


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
    class PersonalDirectus:
        async def get_items(self, collection: str, *, params: dict, no_cache: bool,
                            admin_required: bool, raise_on_error: bool) -> list[dict]:
            assert collection == "chats" and no_cache and admin_required and raise_on_error
            return [{"id": params["filter[id][_eq]"], "hashed_team_id": None}]

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
        directus_service=PersonalDirectus(),
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


class TerminalRelayDirectus:
    def __init__(self) -> None:
        self.team_id = "team-one"
        self.chat_id = "22222222-2222-4222-8222-222222222222"
        self.job_id = "11111111-1111-4111-8111-111111111111"
        self.message_id = "assistant-1"
        self.actor_hash = hash_id("member")
        self.team_hash = hash_id(self.team_id)
        self.membership_active = True
        self.member_role = "member"
        self.job_chat_id = self.chat_id
        self.job_state = "TERMINAL"
        self.row = {
            "chat_id": self.chat_id, "client_message_id": self.message_id,
            "hashed_user_id": self.actor_hash, "role": "assistant",
            "encrypted_content": "committed-ciphertext",
            "encrypted_sender_name": "sealed-name", "created_at": 100,
            "user_message_id": "human-1", "content": "never relay plaintext",
        }
        self.chat = SimpleNamespace(
            get_chat_metadata=self.get_chat_metadata,
            get_message_for_chat_by_client_id=self.get_message,
        )
        self.team = SimpleNamespace(
            list_teams=self.list_teams,
            require_team_role=self.require_team_role,
            list_active_member_hashes=self.list_active_member_hashes,
        )

    async def get_chat_metadata(self, chat_id: str, *, admin_required: bool) -> dict:
        assert admin_required and chat_id == self.chat_id
        return {"id": self.chat_id, "hashed_team_id": self.team_hash}

    async def get_message(self, chat_id: str, message_id: str) -> dict:
        assert (chat_id, message_id) == (self.chat_id, self.message_id)
        return self.row

    async def list_teams(self, user_id: str) -> list[dict]:
        assert user_id == "member"
        return ([{"team_id": self.team_id, "hashed_team_id": self.team_hash}]
                if self.membership_active else [])

    async def require_team_role(self, team_id: str, user_id: str, roles: set[str]) -> dict:
        assert (team_id, user_id) == (self.team_id, "member")
        if not self.membership_active or self.member_role not in roles:
            raise PermissionError("Team permission denied")
        return {"role": self.member_role}

    async def list_active_member_hashes(self, team_id: str) -> set[str]:
        assert team_id == self.team_id
        return {self.actor_hash, hash_id("owner")} if self.membership_active else set()

    async def get_items(self, collection: str, *, params: dict, no_cache: bool,
                        admin_required: bool, raise_on_error: bool) -> list[dict]:
        assert no_cache and admin_required and raise_on_error
        if collection == "chats":
            assert params["filter[id][_eq]"] == self.chat_id
            return [{"id": self.chat_id, "hashed_team_id": self.team_hash}]
        if collection == "team_memberships":
            assert params["filter[hashed_team_id][_eq]"] == self.team_hash
            assert params["filter[hashed_user_id][_eq]"] == self.actor_hash
            return ([{"role": self.member_role}] if self.membership_active else [])
        if collection == "teams":
            assert params["filter[hashed_team_id][_eq]"] == self.team_hash
            return [{"team_id": self.team_id, "hashed_team_id": self.team_hash}]
        assert collection == "chat_completion_recovery_jobs"
        assert params["filter[id][_eq]"] == self.job_id
        return [{
            "id": self.job_id, "hashed_user_id": self.actor_hash,
            "chat_id": self.job_chat_id, "assistant_message_id": self.message_id,
            "inference_task_id": "trusted-task-1", "state": self.job_state,
        }]


class RelayCache:
    instances: list["RelayCache"] = []
    fail_first_publish = False

    def __init__(self) -> None:
        self.published: list[tuple[str, dict]] = []
        self.closed = False
        self.instances.append(self)

    @property
    async def client(self):
        return self

    async def publish(self, channel: str, body: str) -> None:
        if self.fail_first_publish:
            type(self).fail_first_publish = False
            raise RuntimeError("synthetic Redis interruption")
        self.published.append((channel, json.loads(body)))

    async def close(self) -> None:
        self.closed = True


def _terminal_payload(directus: TerminalRelayDirectus) -> dict:
    return {
        "protocol_version": 1, "job_id": directus.job_id,
        "request_id": "persist-request-1", "lease_generation": 2,
        "lease_token": "lease-token", "expected_messages_v": 4,
        "encrypted_assistant_message": {
            "client_message_id": directus.message_id, "chat_id": directus.chat_id,
            "hashed_user_id": "untrusted-client-owner", "role": "assistant",
            "encrypted_content": "submitted-ciphertext", "created_at": 100,
            "updated_at": 100,
        },
    }


def _install_terminal_relay_fakes(monkeypatch, *, conflict: bool = False) -> None:
    class Recovery:
        calls: list[tuple[str, dict]] = []

        def __init__(self, _directus) -> None:
            pass

        async def execute(self, operation: str, data: dict) -> dict:
            self.calls.append((operation, data))
            assert operation == "persist_terminal"
            if conflict:
                raise ChatRecoveryProtocolError(409, "terminal_identity_mismatch")
            return {"job_id": data["job_id"], "state": "TERMINAL", "committed_messages_v": 5,
                    "idempotent": len(self.calls) > 1}

    async def no_cache_work(**_kwargs) -> None:
        return None

    monkeypatch.setattr(chat_recovery_job_handlers, "ChatRecoveryService", Recovery)
    monkeypatch.setattr(chat_recovery_job_handlers, "_create_cache_service", RelayCache)
    monkeypatch.setattr(chat_recovery_job_handlers, "_refresh_terminal_sync_cache", no_cache_work)
    monkeypatch.setattr(chat_recovery_job_handlers, "_acknowledge_output_cache_if_complete", no_cache_work)
    RelayCache.instances = []
    RelayCache.fail_first_publish = False


async def _persist_terminal_for_relay(directus: TerminalRelayDirectus, manager: FakeManager) -> None:
    await chat_recovery_job_handlers.handle_recovery_job_persist(
        manager=manager, directus_service=directus, user_id="member",
        user_id_hash=directus.actor_hash, device_fingerprint_hash="device-hash",
        payload=_terminal_payload(directus),
    )


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=teams.collaboration.realtime-team-sync,teams.chat.encrypted-until-invoked
async def test_terminal_team_recovery_relays_committed_ciphertext_to_both_members_and_replays(monkeypatch) -> None:
    _install_terminal_relay_fakes(monkeypatch)
    directus = TerminalRelayDirectus()
    manager = FakeManager()

    await _persist_terminal_for_relay(directus, manager)
    await _persist_terminal_for_relay(directus, manager)

    assert [message["type"] for message in manager.messages] == [
        "recovery_job_persisted", "recovery_job_persisted",
    ]
    assert manager.messages[1]["payload"]["idempotent"] is True
    assert len(RelayCache.instances) == 2
    for cache in RelayCache.instances:
        assert cache.closed
        assert {channel for channel, _event in cache.published} == {
            f"websocket:user:{directus.actor_hash}", f"websocket:user:{hash_id('owner')}",
        }
        for _channel, event in cache.published:
            assert event["type"] == "team_ai_response_completed"
            assert event["payload"] == {
                "team_id": directus.team_id, "chat_id": directus.chat_id,
                "message_id": directus.message_id, "ai_task_id": "trusted-task-1",
                "role": "assistant", "status": "synced",
                "encrypted_content": "committed-ciphertext",
                "encrypted_sender_name": "sealed-name", "created_at": 100,
                "user_message_id": "human-1",
            }


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=teams.collaboration.realtime-team-sync
async def test_terminal_team_relay_publish_failure_waits_for_idempotent_client_retry(monkeypatch) -> None:
    _install_terminal_relay_fakes(monkeypatch)
    directus = TerminalRelayDirectus()
    manager = FakeManager()
    RelayCache.fail_first_publish = True

    await _persist_terminal_for_relay(directus, manager)
    assert manager.messages == []
    assert RelayCache.instances[0].closed
    assert RelayCache.instances[0].published == []

    await _persist_terminal_for_relay(directus, manager)
    assert [message["type"] for message in manager.messages] == ["recovery_job_persisted"]
    assert manager.messages[0]["payload"]["idempotent"] is True
    assert len(RelayCache.instances[1].published) == 2
    assert {event["payload"]["message_id"] for _channel, event in RelayCache.instances[1].published} == {
        directus.message_id,
    }


@pytest.mark.anyio
@pytest.mark.parametrize("denial", ["conflict", "removed", "viewer", "cross_team", "job_chat", "job_state", "message_owner", "personal"])
# contract-test: supporting surface=rest_api assertions=teams.collaboration.realtime-team-sync,teams.chat.encrypted-until-invoked
async def test_terminal_recovery_never_relays_without_committed_team_authority(monkeypatch, denial: str) -> None:
    _install_terminal_relay_fakes(monkeypatch, conflict=denial == "conflict")
    directus = TerminalRelayDirectus()
    if denial == "removed":
        directus.membership_active = False
    elif denial == "viewer":
        directus.member_role = "viewer"
    elif denial == "cross_team":
        directus.team_hash = hash_id("other-team")
    elif denial == "job_chat":
        directus.job_chat_id = "other-chat"
    elif denial == "job_state":
        directus.job_state = "AVAILABLE"
    elif denial == "message_owner":
        directus.row["hashed_user_id"] = hash_id("owner")
    elif denial == "personal":
        directus.team_hash = None
    manager = FakeManager()

    await _persist_terminal_for_relay(directus, manager)

    assert RelayCache.instances == []
    expected = ("error" if denial == "conflict" else "recovery_job_persisted"
                if denial in {"removed", "viewer", "cross_team", "personal"} else None)
    assert [message["type"] for message in manager.messages] == ([expected] if expected else [])


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


# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
def test_recovery_negotiation_survives_background_without_weakening_execution_guards() -> None:
    manager = ConnectionManager()
    manager.active_connections["user-1"] = {"device-hash": object()}
    manager.typed_recovery_output_capability[("user-1", "device-hash")] = True
    manager.canonical_embed_receipt_capability[("user-1", "device-hash")] = True
    manager.set_connection_foreground("user-1", "device-hash", False)

    assert manager.negotiated_typed_recovery_outputs("user-1", "device-hash")
    assert manager.negotiated_canonical_embed_receipts("user-1", "device-hash")
    assert not manager.supports_typed_recovery_outputs("user-1", "device-hash")
    assert not manager.supports_canonical_embed_receipts("user-1", "device-hash")
    assert not manager.is_connection_completion_capable("user-1", "device-hash")
    manager.set_connection_foreground("user-1", "device-hash", True)
    assert manager.supports_typed_recovery_outputs("user-1", "device-hash")


@pytest.mark.parametrize(("is_foreground", "was_foreground", "lifecycle_seen", "expected"), [
    (True, True, False, True),   # reconnect default foreground needs ACK-first scan
    (True, True, True, False),   # repeated foreground is quiet
    (False, True, False, False), # blur never discovers
    (True, False, True, True),   # real resume discovers
])
# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
def test_recovery_discovery_lifecycle_transition(
    is_foreground: bool, was_foreground: bool, lifecycle_seen: bool, expected: bool,
) -> None:
    assert should_rediscover_recovery_on_lifecycle(
        is_foreground=is_foreground, was_foreground=was_foreground,
        lifecycle_seen=lifecycle_seen,
    ) is expected


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
async def test_typed_connection_delays_all_initial_recovery_discovery_until_lifecycle(monkeypatch) -> None:
    monkeypatch.setattr(chat_recovery_job_handlers, "ChatRecoveryService", FakeRecoveryService)
    FakeRecoveryService.calls = []
    manager = FakeManager(typed=True)
    epoch_calls = 0

    async def get_epoch() -> int:
        nonlocal epoch_calls
        epoch_calls += 1
        return 1

    tasks = await chat_recovery_job_handlers.begin_initial_recovery_discovery(
        manager=manager, directus_service=object(), user_id="user-1",
        user_id_hash="owner-hash", device_fingerprint_hash="device-hash",
        supports_typed_recovery_outputs=True, get_epoch=get_epoch,
    )
    await asyncio.sleep(0)

    assert tasks == []
    assert epoch_calls == 0
    assert FakeRecoveryService.calls == []
    assert manager.messages == []


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
async def test_legacy_first_foreground_ack_keeps_initial_job_delivery_alive(monkeypatch) -> None:
    gate = asyncio.Event()
    started = asyncio.Event()

    class Recovery:
        def __init__(self, _directus_service) -> None:
            pass

        async def execute(self, operation: str, _data: dict) -> dict:
            assert operation == "list_available_jobs"
            started.set()
            await gate.wait()
            return {"jobs": [{"job_id": "job-1", "chat_id": "chat-1"}]}

    monkeypatch.setattr(chat_recovery_job_handlers, "ChatRecoveryService", Recovery)
    manager = FakeManager()
    tasks = await chat_recovery_job_handlers.begin_initial_recovery_discovery(
        manager=manager, directus_service=object(), user_id="user-1",
        user_id_hash="owner-hash", device_fingerprint_hash="device-hash",
        supports_typed_recovery_outputs=False, get_epoch=lambda: asyncio.sleep(0, result=1),
    )
    await started.wait()
    scheduled = []
    websocket_routes._reconcile_recovery_lifecycle_discovery(
        initial_tasks=tasks, foreground_task=None, is_foreground=True,
        lifecycle_seen_before=False, should_discover=True,
        supports_typed_outputs=False, schedule=lambda: scheduled.append(True),
    )
    gate.set()
    await asyncio.gather(*tasks)

    assert scheduled == []
    assert {message["type"] for message in manager.messages} == {
        "recovery_outputs_discovery_complete", "recovery_jobs_available",
    }
    assert manager.messages[-1]["payload"]["jobs"][0]["job_id"] == "job-1"


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
async def test_legacy_background_cancels_scan_and_resume_rediscovers_jobs_only(monkeypatch) -> None:
    gate = asyncio.Event()
    started = asyncio.Event()
    calls = []

    class Recovery:
        def __init__(self, _directus_service) -> None:
            pass

        async def execute(self, operation: str, _data: dict) -> dict:
            calls.append(operation)
            assert operation == "list_available_jobs"
            started.set()
            await gate.wait()
            return {"jobs": [{"job_id": "job-1", "chat_id": "chat-1"}]}

    monkeypatch.setattr(chat_recovery_job_handlers, "ChatRecoveryService", Recovery)
    manager = FakeManager()
    arguments = dict(manager=manager, directus_service=object(), user_id="user-1",
                     user_id_hash="owner-hash", device_fingerprint_hash="device-hash")
    initial = await chat_recovery_job_handlers.begin_initial_recovery_discovery(
        **arguments, supports_typed_recovery_outputs=False,
        get_epoch=lambda: asyncio.sleep(0, result=1),
    )
    await started.wait()
    manager.foreground = False
    websocket_routes._reconcile_recovery_lifecycle_discovery(
        initial_tasks=initial, foreground_task=None, is_foreground=False,
        lifecycle_seen_before=False, should_discover=False,
        supports_typed_outputs=False, schedule=lambda: pytest.fail("background scheduled recovery"),
    )
    await asyncio.gather(*initial, return_exceptions=True)
    assert initial[0].cancelled()
    assert not any(message["type"] == "recovery_jobs_available" for message in manager.messages)

    manager.foreground = True
    scans = []
    websocket_routes._reconcile_recovery_lifecycle_discovery(
        initial_tasks=initial, foreground_task=None, is_foreground=True,
        lifecycle_seen_before=True, should_discover=True,
        supports_typed_outputs=False,
        schedule=lambda: scans.append(asyncio.create_task(
            chat_recovery_job_handlers.send_available_recovery_jobs(**arguments)
        )),
    )
    gate.set()
    await asyncio.gather(*scans)
    assert calls == ["list_available_jobs", "list_available_jobs"]
    assert manager.messages[-1]["type"] == "recovery_jobs_available"
    assert not any(message["type"] == "recovery_outputs_available" for message in manager.messages)


@pytest.mark.anyio
@pytest.mark.parametrize("typed,epoch", [
    (False, 0), (False, None), (False, 1),
    (True, 0), (True, None), (True, 1),
])
# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
async def test_foreground_scan_gates_v1_jobs_for_both_clients_and_typed_outputs_only(
    monkeypatch, typed: bool, epoch: int | None,
) -> None:
    manager = FakeManager(typed=typed)
    calls = []

    class Cutover:
        def __init__(self, *_args) -> None:
            pass

        async def get_epoch(self, *, authoritative: bool) -> int:
            assert authoritative
            if epoch is None:
                raise RuntimeError("authoritative epoch unavailable")
            return epoch

    async def send_jobs(**_kwargs) -> None:
        calls.append("jobs")
        await manager.send_personal_message(
            {"type": "recovery_jobs_available", "payload": {"jobs": [{"job_id": "v1-job"}]}},
            "user-1", "device-hash",
        )

    async def send_outputs(**_kwargs) -> None:
        calls.append("outputs")
        await manager.send_personal_message(
            {"type": "recovery_outputs_discovery_complete", "payload": {"status": "completed"}},
            "user-1", "device-hash",
        )

    monkeypatch.setattr(websocket_routes, "ChatRecoveryCutoverController", Cutover)
    monkeypatch.setattr(websocket_routes, "send_available_recovery_jobs", send_jobs)
    monkeypatch.setattr(websocket_routes, "send_available_recovery_outputs", send_outputs)

    await websocket_routes._discover_foreground_recovery(
        manager=manager, cache_service=object(), directus_service=object(),
        user_id="user-1", user_id_hash="owner-hash", device_fingerprint_hash="device-hash",
        supports_typed_recovery_outputs=typed, user_otel_attrs={},
    )
    if epoch != 1:
        assert calls == []
        assert manager.messages == [{
            "type": "recovery_outputs_discovery_complete",
            "payload": {"status": "disabled" if epoch == 0 else "failed"},
        }]
    else:
        assert calls == (["jobs", "outputs"] if typed else ["jobs"])
        assert manager.messages[0]["type"] == "recovery_jobs_available"
        assert manager.messages[-1]["type"] == (
            "recovery_outputs_discovery_complete" if typed else "recovery_jobs_available"
        )


@pytest.mark.anyio
@pytest.mark.parametrize("handler_name", [
    "handle_recovery_output_get",
    "handle_recovery_output_persist_message",
    "handle_recovery_output_persist_summary",
    "handle_recovery_output_ack_checkpoint",
    "handle_recovery_output_ack_embed",
])
# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
async def test_background_capable_client_cannot_read_mutate_or_ack_typed_outputs(
    monkeypatch, handler_name: str,
) -> None:
    monkeypatch.setattr(chat_recovery_job_handlers, "ChatRecoveryService", FakeRecoveryService)
    FakeRecoveryService.calls = []
    manager = FakeManager(typed=True, receipts=True, foreground=False)
    arguments = {
        "manager": manager, "directus_service": object(), "user_id": "user-1",
        "user_id_hash": "owner-hash", "device_fingerprint_hash": "device-hash",
        "payload": {"protocol_version": 1, "record_id": "record-1", "request_id": "request-1"},
    }
    if handler_name == "handle_recovery_output_get":
        arguments["s3_service"] = None

    await getattr(chat_recovery_job_handlers, handler_name)(**arguments)

    assert FakeRecoveryService.calls == []
    assert manager.messages[0]["payload"] == {
        "code": "recovery_requires_foreground",
        "message": "Encrypted recovery requires a foreground client.",
        "job_id": "record-1", "request_id": "request-1",
    }


@pytest.mark.anyio
@pytest.mark.parametrize("handler_name", [
    "handle_recovery_job_claim", "handle_recovery_job_renew", "handle_recovery_job_persist",
])
# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover
async def test_background_client_cannot_claim_renew_or_persist_recovery_job(
    monkeypatch, handler_name: str,
) -> None:
    monkeypatch.setattr(chat_recovery_job_handlers, "ChatRecoveryService", FakeRecoveryService)
    FakeRecoveryService.calls = []
    manager = FakeManager(foreground=False)

    await getattr(chat_recovery_job_handlers, handler_name)(
        manager=manager, directus_service=object(), user_id="user-1",
        user_id_hash="owner-hash", device_fingerprint_hash="device-hash",
        payload={"protocol_version": 1, "job_id": "job-1", "request_id": "request-1"},
    )

    assert FakeRecoveryService.calls == []
    assert manager.messages[0]["payload"]["code"] == "recovery_requires_foreground"


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
async def test_foreground_discovery_emits_completion_barrier_for_zero_outputs(monkeypatch) -> None:
    class EmptyRecovery:
        calls = 0

        def __init__(self, _directus_service) -> None:
            pass

        async def execute(self, operation: str, _data: dict) -> dict:
            assert operation == "list_pending_outputs"
            self.calls += 1
            return {"outputs": [], "next_cursor": None}

    monkeypatch.setattr(chat_recovery_job_handlers, "ChatRecoveryService", EmptyRecovery)
    manager = FakeManager(typed=True)

    await chat_recovery_job_handlers.send_available_recovery_outputs(
        manager=manager, directus_service=object(), user_id="user-1",
        user_id_hash="owner-hash", device_fingerprint_hash="device-hash",
    )

    assert manager.messages == [{
        "type": "recovery_outputs_discovery_complete", "payload": {"status": "completed"},
    }]

    manager.foreground = False
    manager.messages.clear()
    await chat_recovery_job_handlers.send_available_recovery_outputs(
        manager=manager, directus_service=object(), user_id="user-1",
        user_id_hash="owner-hash", device_fingerprint_hash="device-hash",
    )
    assert manager.messages == []
