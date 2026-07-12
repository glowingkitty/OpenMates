"""
Durable protocol cutover contracts for saved-chat completion recovery.

The tests model Directus as the authority and Redis as a disposable snapshot;
no content-bearing values cross this coordination boundary.
"""

from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.chat_recovery_cutover import (
    ChatRecoveryCutoverController,
    CutoverBlockedError,
)
from backend.core.api.app.services.chat_recovery_service import ChatRecoveryProtocolError


class FakeCache:
    def __init__(self, value=None) -> None:
        self.value = value

    async def get(self, key: str):
        return self.value

    async def set(self, key: str, value: object, ttl=None) -> bool:
        self.value = value
        return True


class FakeRecoveryService:
    def __init__(self, state: dict[str, object]) -> None:
        self.state = state
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.failure: Exception | None = None
        self.fail_operation: str | None = None

    async def execute(self, operation: str, data: dict[str, object]):
        self.calls.append((operation, data))
        if self.failure and (self.fail_operation is None or self.fail_operation == operation):
            raise self.failure
        if operation == "get_cutover_state":
            return dict(self.state)
        if operation == "activate_protocol_epoch":
            self.state["protocol_epoch"] = data["target_epoch"]
            return {**self.state, "activated": True}
        return dict(self.state)


class FakeWebSocket:
    def __init__(self, events: list[object], fail: bool = False) -> None:
        self.events = events
        self.fail = fail

    async def send_json(self, message: dict) -> None:
        self.events.append(message)
        if self.fail:
            raise RuntimeError("socket write failed")

    async def close(self, code: int, reason: str) -> None:
        self.events.append(("close", code, reason))


class FakeConnectionManager:
    def __init__(self, events: list[object], fail: bool = False) -> None:
        self.active_connections = {"user": {"device": FakeWebSocket(events, fail)}}


def controller(cache: FakeCache, state: dict[str, object]) -> tuple[ChatRecoveryCutoverController, FakeRecoveryService]:
    instance = ChatRecoveryCutoverController(cache, AsyncMock())
    service = FakeRecoveryService(state)
    instance.recovery_service = service
    return instance, service


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_cache_loss_reads_durable_state_and_repopulates_snapshot() -> None:
    cache = FakeCache()
    instance, service = controller(cache, {
        "protocol_epoch": 1, "sends_paused": True, "legacy_in_flight": 0,
    })

    assert await instance.get_epoch(authoritative=True) == 1
    assert service.calls[0][0] == "get_cutover_state"
    assert cache.value["protocol_epoch"] == 1


@pytest.mark.anyio
async def test_authoritative_read_failure_fails_closed() -> None:
    instance, service = controller(FakeCache(), {
        "protocol_epoch": 0, "sends_paused": False, "legacy_in_flight": 0,
    })
    service.failure = RuntimeError("directus unavailable")

    with pytest.raises(RuntimeError, match="directus unavailable"):
        await instance.get_state(authoritative=True)


@pytest.mark.anyio
async def test_activation_refuses_nonzero_durable_legacy_count() -> None:
    instance, service = controller(FakeCache(), {
        "protocol_epoch": 0, "sends_paused": True, "legacy_in_flight": 2,
    })

    with pytest.raises(CutoverBlockedError):
        await instance.activate_epoch_one(FakeConnectionManager([]))
    assert all(call[0] != "activate_protocol_epoch" for call in service.calls)


@pytest.mark.anyio
async def test_socket_failure_cannot_partially_activate() -> None:
    instance, service = controller(FakeCache(), {
        "protocol_epoch": 0, "sends_paused": True, "legacy_in_flight": 0,
    })

    with pytest.raises(RuntimeError, match="socket write failed"):
        await instance.activate_epoch_one(FakeConnectionManager([], fail=True))
    assert service.state["protocol_epoch"] == 0
    assert all(call[0] != "activate_protocol_epoch" for call in service.calls)


@pytest.mark.anyio
async def test_all_old_sockets_close_before_atomic_activation() -> None:
    events: list[object] = []
    instance, service = controller(FakeCache(), {
        "protocol_epoch": 0, "sends_paused": True, "legacy_in_flight": 0,
    })

    await instance.activate_epoch_one(FakeConnectionManager(events))

    assert events[-1] == ("close", 1012, "Client update required")
    assert service.calls[-1][0] == "activate_protocol_epoch"
    assert service.state["protocol_epoch"] == 1


@pytest.mark.anyio
async def test_activation_rejection_does_not_publish_epoch_one_to_cache() -> None:
    cache = FakeCache()
    instance, service = controller(cache, {
        "protocol_epoch": 0, "sends_paused": True, "legacy_in_flight": 0,
    })
    service.failure = ChatRecoveryProtocolError(409, "legacy_in_flight")
    service.fail_operation = "activate_protocol_epoch"

    with pytest.raises(CutoverBlockedError):
        await instance.activate_epoch_one(FakeConnectionManager([]))
    assert cache.value["protocol_epoch"] == 0
