"""The explicit Stop control cannot signal an unrelated execution."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from backend.apps.ai.tasks import async_skill_continuation
from backend.core.api.app.routes.handlers.websocket_handlers import cancel_ai_task_handler
from backend.core.api.app.services.directus.team_methods import TeamPermissionError, hash_id
from backend.shared.python_utils import focus_continuation_history
from backend.shared.python_utils.ai_task_cancellation import cancellation_scope_key


@pytest.fixture
def harness(monkeypatch):
    cache = SimpleNamespace(
        get_chat_id_for_task=AsyncMock(return_value="chat"),
        get_active_ai_task=AsyncMock(return_value="task"),
        complete_active_ai_task_if_queue_empty=AsyncMock(return_value=0),
        get=AsyncMock(return_value=None),
        set=AsyncMock(return_value=True),
    )
    metadata = {"id": "chat", "hashed_team_id": None, "hashed_user_id": hash_id("owner")}
    directus = SimpleNamespace(
        chat=SimpleNamespace(get_chat_metadata=AsyncMock(return_value=metadata)),
        team=SimpleNamespace(require_team_role=AsyncMock()),
    )
    manager = SimpleNamespace(
        send_personal_message=AsyncMock(), get_volatile_session_nonce=Mock(return_value=None),
    )

    def revoke(task_id, **kwargs):
        cache.set.assert_awaited_once_with("ai_task_cancel_requested:owner:chat:task", "1", ttl=3600)
        assert (task_id, kwargs) == ("task", {"terminate": True, "signal": "SIGUSR1"})

    signal = Mock(side_effect=revoke)
    parked = AsyncMock(return_value=False)
    focus = AsyncMock(return_value=None)
    monkeypatch.setattr(cancel_ai_task_handler.celery_app.control, "revoke", signal)
    monkeypatch.setattr(async_skill_continuation, "cancel_same_turn_source", parked)
    monkeypatch.setattr(focus_continuation_history, "find_cancellable_focus_execution", focus)
    monkeypatch.setattr(focus_continuation_history, "cancel_focus_execution", AsyncMock(return_value=False))
    return SimpleNamespace(cache=cache, directus=directus, manager=manager, metadata=metadata,
                           signal=signal, parked=parked, focus=focus)


async def stop(harness, *, user_id="owner", chat_id="chat", task_id="task"):
    payload = {"task_id": task_id}
    if chat_id is not None:
        payload["chat_id"] = chat_id
    await cancel_ai_task_handler.handle_cancel_ai_task(
        websocket=None, manager=harness.manager, user_id=user_id, device_fingerprint_hash="device",
        payload=payload, cache_service=harness.cache, directus_service=harness.directus,
    )
    return harness.manager.send_personal_message.await_args.kwargs["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["wrong_owner", "wrong_chat", "stale_task", "missing_chat", "removed_team_member"])
# contract-test: supporting surface=rest_api assertions=chat-queued-followups.access.scoped
async def test_unverified_stop_never_signals_or_writes_intent(harness, case):
    args = {}
    if case == "wrong_owner":
        args["user_id"] = "another-owner"
    if case == "wrong_chat":
        args["chat_id"] = "another-chat"
    if case == "stale_task":
        harness.cache.get_active_ai_task.return_value = "newer-task"
    if case == "missing_chat":
        harness.cache.get_chat_id_for_task.return_value = None
        args["chat_id"] = None
    if case == "removed_team_member":
        harness.metadata["hashed_team_id"] = hash_id("team")
        harness.cache.get.return_value = {
            "user_id": "owner", "chat_id": "chat", "task_id": "task", "team_id": "team",
        }
        harness.directus.team.require_team_role.side_effect = TeamPermissionError("removed")
    result = await stop(harness, **args)
    assert result["type"] == "error"
    assert result["payload"]["code"] == "ai_task_cancel_unavailable"
    harness.signal.assert_not_called()
    harness.cache.set.assert_not_awaited()
    harness.cache.complete_active_ai_task_if_queue_empty.assert_not_awaited()


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=chat-queued-followups.access.scoped
async def test_authenticated_owner_can_stop_exact_foreground_using_reverse_binding(harness):
    result = await stop(harness, chat_id=None)
    assert result == {"type": "ai_task_cancel_requested", "payload": {
        "task_id": "task", "status": "revocation_sent",
    }}
    harness.signal.assert_called_once()
    harness.directus.chat.get_chat_metadata.assert_awaited_once_with("chat", admin_required=True)
    harness.cache.complete_active_ai_task_if_queue_empty.assert_awaited_once_with("chat", "task")


# contract-test: supporting surface=rest_api assertions=chat-queued-followups.routing.active-work,chat-queued-followups.access.scoped
@pytest.mark.asyncio
@pytest.mark.parametrize("owner_matches", [True, False])
async def test_named_stop_of_independent_reply_leaves_foreground_and_continuations(harness, owner_matches):
    harness.cache.get_active_ai_task.return_value = "foreground"
    slot = {"user_id": "owner" if owner_matches else "other", "chat_id": "chat", "task_id": "task"}

    async def cache_get(key):
        return slot if key == "independent_chat_reply:chat" else None

    harness.cache.get.side_effect = cache_get
    result = await stop(harness)
    if owner_matches:
        assert result["payload"]["status"] == "revocation_sent"
        harness.signal.assert_called_once()
        harness.parked.assert_not_awaited()
        harness.focus.assert_not_awaited()
    else:
        assert result["payload"]["code"] == "ai_task_cancel_unavailable"
        harness.signal.assert_not_called()
    harness.cache.complete_active_ai_task_if_queue_empty.assert_not_awaited()


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=chat-queued-followups.access.scoped
async def test_verified_paused_source_uses_its_scoped_handler(harness):
    harness.cache.get_chat_id_for_task.return_value = None
    harness.cache.get_active_ai_task.return_value = "newer-task"
    harness.parked.return_value = True
    result = await stop(harness)
    assert result == {"type": "ai_task_cancel_requested", "payload": {
        "task_id": "task", "status": "paused_turn_cancelled",
    }}
    harness.parked.assert_awaited_once_with(
        harness.cache, user_id="owner", chat_id="chat", source_task_id="task",
    )
    harness.signal.assert_not_called()
    harness.cache.set.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("device_nonce", ["original-session", "different-session"])
# contract-test: supporting surface=rest_api assertions=chat-queued-followups.access.scoped
async def test_incognito_stop_requires_the_live_origin_session(harness, device_nonce):
    async def cache_get(key):
        if key == cancellation_scope_key("chat", "task"):
            return {"user_id": "owner", "chat_id": "chat", "task_id": "task", "session_nonce": "original-session"}
        if key == "volatile_ai_live:v1:original-session":
            return hash_id("owner")
        return None

    harness.cache.get.side_effect = cache_get
    harness.manager.get_volatile_session_nonce.return_value = device_nonce
    harness.directus.chat.get_chat_metadata.return_value = None
    result = await stop(harness)
    verified = device_nonce == "original-session"
    assert result["type"] == ("ai_task_cancel_requested" if verified else "error")
    assert harness.signal.call_count == int(verified)


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=chat-queued-followups.access.scoped
async def test_late_cancel_never_invalidates_a_new_foreground_turn():
    from fakeredis.aioredis import FakeRedis
    from backend.core.api.app.services.cache_chat_mixin import ChatCacheMixin
    from backend.shared.python_utils.ai_task_cancellation import fence_cancelled_turn_if_idle

    class Cache(ChatCacheMixin):
        def __init__(self, redis):
            self.redis = redis

        @property
        async def client(self):
            return self.redis

    async with FakeRedis() as redis:
        cache = Cache(redis)
        latest = "root-turn"
        await redis.set(latest, "older-turn")
        await cache.set_active_ai_task("chat", "newer-task")
        await fence_cancelled_turn_if_idle(
            cache, chat_id="chat", latest_key=latest, expected_latest="older-turn", task_id="stopped", ttl=900,
        )
        assert await redis.get(latest) == b"older-turn"
        await cache.clear_active_ai_task_if_matches("chat", "newer-task")
        await redis.set(latest, "newer-turn")
        await fence_cancelled_turn_if_idle(
            cache, chat_id="chat", latest_key=latest, expected_latest="older-turn", task_id="stopped", ttl=900,
        )
        assert await redis.get(latest) == b"newer-turn"
        await fence_cancelled_turn_if_idle(
            cache, chat_id="chat", latest_key=latest, expected_latest="newer-turn", task_id="stopped", ttl=900,
        )
        assert await redis.get(latest) == b"cancelled:stopped"
