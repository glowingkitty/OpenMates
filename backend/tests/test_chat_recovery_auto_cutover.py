"""
Automatic chat-recovery epoch activation on production startup.

Directus is modelled with the same gate rules as the transaction extension
(sends paused, no running legacy turn, never lower the epoch), so these tests
prove that the startup task reaches epoch 1, never leaves sends paused and
never touches a server that already runs epoch 1.
"""

from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services import chat_recovery_auto_cutover as auto
from backend.core.api.app.services.chat_recovery_cutover import ChatRecoveryCutoverController
from backend.core.api.app.services.chat_recovery_service import ChatRecoveryProtocolError


class FakeCache:
    def __init__(self) -> None:
        self.value = None

    async def get(self, key: str):
        return self.value

    async def set(self, key: str, value: object, ttl=None) -> bool:
        self.value = value
        return True


class GatedDirectus:
    """Applies the activate_protocol_epoch gate of the Directus extension."""

    def __init__(self, epoch: int = 0, in_flight: list[int] | None = None, paused: bool = False) -> None:
        self.state = {"protocol_epoch": epoch, "sends_paused": paused, "legacy_in_flight": 0}
        self.in_flight = list(in_flight or [0])
        self.calls: list[str] = []

    async def execute(self, operation: str, data: dict[str, object]):
        self.calls.append(operation)
        if operation == "get_cutover_state":
            if self.in_flight:
                self.state["legacy_in_flight"] = self.in_flight.pop(0)
        elif operation == "set_sends_paused":
            self.state["sends_paused"] = data["sends_paused"]
        elif operation == "activate_protocol_epoch":
            if data["target_epoch"] == self.state["protocol_epoch"]:
                return {**self.state, "activated": False}
            if not self.state["sends_paused"]:
                raise ChatRecoveryProtocolError(409, "sends_not_paused")
            if self.state["legacy_in_flight"]:
                raise ChatRecoveryProtocolError(409, "legacy_in_flight")
            self.state["protocol_epoch"] = data["target_epoch"]
            return {**self.state, "activated": True}
        return dict(self.state)


class NoConnections:
    active_connections: dict = {}


def make(directus: GatedDirectus) -> ChatRecoveryCutoverController:
    controller = ChatRecoveryCutoverController(FakeCache(), AsyncMock())
    controller.recovery_service = directus
    return controller


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


# contract-test: supporting surface=rest_api assertions=chats.completion.independent-metadata
@pytest.mark.anyio
async def test_idle_epoch_zero_server_activates_epoch_one_and_resumes_sends() -> None:
    directus = GatedDirectus(epoch=0)
    clock = Clock()
    result = await auto.ensure_recovery_epoch_one(make(directus), NoConnections(), sleep=clock.sleep, clock=clock)
    assert result == "activated"
    assert directus.state["protocol_epoch"] == 1
    assert directus.state["sends_paused"] is False


# contract-test: supporting surface=rest_api assertions=chats.completion.independent-metadata
@pytest.mark.anyio
async def test_waits_for_running_legacy_turns_without_pausing_sends() -> None:
    directus = GatedDirectus(epoch=0, in_flight=[2, 1, 0])
    clock = Clock()
    result = await auto.ensure_recovery_epoch_one(make(directus), NoConnections(), sleep=clock.sleep, clock=clock)
    assert result == "activated"
    # Sends were paused only once, immediately before the activation.
    assert directus.calls.count("set_sends_paused") == 2
    first_pause = directus.calls.index("set_sends_paused")
    assert directus.calls[:first_pause].count("get_cutover_state") == 3
    assert directus.state == {"protocol_epoch": 1, "sends_paused": False, "legacy_in_flight": 0}


# contract-test: supporting surface=rest_api assertions=chats.completion.independent-metadata
@pytest.mark.anyio
async def test_epoch_one_server_is_left_untouched_even_when_an_operator_paused_sends() -> None:
    directus = GatedDirectus(epoch=1, paused=True)
    clock = Clock()
    result = await auto.ensure_recovery_epoch_one(make(directus), NoConnections(), sleep=clock.sleep, clock=clock)
    assert result == "already_active"
    assert directus.calls == ["get_cutover_state"]
    assert directus.state["sends_paused"] is True


# contract-test: supporting surface=rest_api assertions=chats.completion.independent-metadata
@pytest.mark.anyio
async def test_undrained_legacy_work_times_out_with_sends_open_and_epoch_zero() -> None:
    directus = GatedDirectus(epoch=0, in_flight=[1] * 1000)
    clock = Clock()
    result = await auto.ensure_recovery_epoch_one(
        make(directus), NoConnections(), sleep=clock.sleep, clock=clock,
        poll_seconds=15, max_wait_seconds=60,
    )
    assert result == "timed_out"
    assert directus.state["protocol_epoch"] == 0
    assert directus.state["sends_paused"] is False
    assert "set_sends_paused" not in directus.calls


@pytest.mark.parametrize(
    ("environment", "expected"),
    [("production", True), ("prod", True), (" Production ", True), ("development", False), ("", False)],
)
# contract-test: supporting surface=rest_api assertions=chats.completion.independent-metadata
def test_only_production_servers_run_the_cutover(environment: str, expected: bool) -> None:
    assert auto.auto_cutover_enabled(environment) is expected


# contract-test: supporting surface=rest_api assertions=chats.completion.independent-metadata
@pytest.mark.anyio
async def test_development_startup_never_reads_or_changes_the_epoch(monkeypatch) -> None:
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    directus = AsyncMock()
    await auto.run_auto_cutover(FakeCache(), directus, NoConnections())
    directus.assert_not_called()
