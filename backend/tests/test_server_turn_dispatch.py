"""Server-started turns get durable admission before ai.ask dispatch.

Real dev run 18 of the voice orchestration proof: two automatic interpreting turns were
dispatched straight to the Celery task and the worker refused both with "Saved AI task
lacks durable admission authority". These tests pin the admission-then-dispatch order.
"""

import hashlib

import pytest

from backend.core.api.app.services import chat_recovery_cutover, skill_registry
from backend.shared.python_utils import server_turn_dispatch as dispatch

USER, CHAT, MESSAGE = "user-1", "chat-1", "event-message-1"
IDENTITY = hashlib.sha256(f"{USER}:{CHAT}:{MESSAGE}".encode()).hexdigest()


class FakeChat:
    async def get_chat_metadata(self, chat_id, admin_required=False):
        assert chat_id == CHAT and admin_required
        return {"hashed_team_id": "team-hash"}


class FakeDirectus:
    chat = FakeChat()


class FakeController:
    result: dict = {"admitted": True}
    admitted: list = []
    released: list = []

    def __init__(self, cache_service, directus_service):
        pass

    async def admit_legacy_inference(self, identity, **scope):
        FakeController.admitted.append((identity, scope))
        return FakeController.result

    async def release_legacy_inference(self, identity):
        FakeController.released.append(identity)
        return {}


class FakeRegistry:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    async def dispatch_skill(self, app_id, skill_id, body):
        self.calls.append((app_id, skill_id, body))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


@pytest.fixture
def wire(monkeypatch):
    FakeController.result, FakeController.admitted, FakeController.released = {"admitted": True}, [], []
    monkeypatch.setattr(chat_recovery_cutover, "ChatRecoveryCutoverController", FakeController)

    def use(answer):
        registry = FakeRegistry(answer)
        monkeypatch.setattr(skill_registry, "get_global_registry", lambda: registry)
        return registry
    return use


def _request():
    return {"user_id": USER, "chat_id": CHAT, "message_id": MESSAGE, "message_history": []}


async def _run():
    return await dispatch.admit_and_dispatch_server_turn(
        cache_service=object(), directus_service=FakeDirectus(), request=_request())


# contract-test: supporting surface=rest_api assertions=chat-orchestration.events.automatic-interpretation
@pytest.mark.asyncio
async def test_admits_with_owner_and_team_scope_then_dispatches_bound_to_the_admission(wire):
    registry = wire({"task_id": IDENTITY})
    assert await _run() == IDENTITY
    identity, scope = FakeController.admitted[0]
    assert identity == IDENTITY
    assert scope == {"actor_user_id": USER, "hashed_user_id": hashlib.sha256(USER.encode()).hexdigest(),
                     "chat_id": CHAT, "first_message_id": MESSAGE, "hashed_team_id": "team-hash"}
    app_id, skill_id, body = registry.calls[0]
    assert (app_id, skill_id) == ("ai", "ask") and body["legacy_cutover_task_id"] == IDENTITY


# contract-test: supporting surface=rest_api assertions=chat-orchestration.events.automatic-interpretation
@pytest.mark.asyncio
@pytest.mark.parametrize("result", [{"admitted": False, "idempotent": True}, {"admitted": False}])
async def test_refused_or_repeated_admission_dispatches_nothing(wire, result):
    registry = wire({"task_id": IDENTITY})
    FakeController.result = result
    with pytest.raises(dispatch.ServerTurnNotAdmitted):
        await _run()
    assert registry.calls == []


# contract-test: supporting surface=rest_api assertions=chat-orchestration.events.automatic-interpretation
@pytest.mark.asyncio
async def test_failed_dispatch_releases_the_admission(wire):
    wire(RuntimeError("broker down"))
    with pytest.raises(RuntimeError, match="broker down"):
        await _run()
    assert FakeController.released == [IDENTITY]


# contract-test: supporting surface=rest_api assertions=chat-orchestration.events.automatic-interpretation
@pytest.mark.asyncio
async def test_other_task_id_from_the_dispatcher_is_an_error(wire):
    wire({"task_id": "something-else"})
    with pytest.raises(RuntimeError, match="differs"):
        await _run()
