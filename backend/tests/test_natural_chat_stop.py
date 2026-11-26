"""Confirmed terminal stop commands keep other executions live."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fakeredis.aioredis import FakeRedis
from pytest import fixture, mark

from backend.apps.ai.tasks import same_turn_skill_barrier
from backend.apps.code.run_cancellation import code_run_cancel_key
from backend.apps.code.tasks import run_code_task
from backend.core.api.app.routes.code_execution import _execution_key
from backend.core.api.app.routes.handlers.websocket_handlers import cancel_ai_task_handler, natural_chat_stop
from backend.shared.python_utils.active_input_authority import (
    admit_fixed_active_input_reply,
    verified_fixed_active_input_reply,
)
from backend.shared.python_utils.ai_task_cancellation import cancellation_scope_key
from backend.shared.python_utils.explicit_chat_stop import (
    STOP_CLARIFY, STOP_REQUESTED, STOP_RUN_ENDED, STOP_RUN_REQUESTED, STOP_UNCONFIRMED,
    explicit_stop_label,
)

pytestmark = mark.asyncio
OWNER = "owner"
CHAT = "chat"
OWNER_HASH = hashlib.sha256(OWNER.encode()).hexdigest()


class Cache:
    def __init__(self, redis):
        self.redis = redis
        self.get_active_ai_task = AsyncMock(return_value=None)
        self.publish_event = AsyncMock()

    @property
    async def client(self):
        return self.redis

    async def get(self, key):
        value = await self.redis.get(key)
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value.decode() if value else None

    async def set(self, key, value, *, ttl):
        return await self.redis.set(key, json.dumps(value), ex=ttl)


def request(content="cancel the Safari run", *,
            safari="Run the checkout tests in Safari.", firefox="Run the checkout tests in Firefox."):
    rows = [
        SimpleNamespace(role="user", message_id="safari", content=safari),
        SimpleNamespace(role="user", message_id="firefox", content=firefox),
        SimpleNamespace(role="user", message_id="stop", content=content),
    ]
    return SimpleNamespace(
        current_user_content=content, message_history=rows, message_id="stop",
        chat_id=CHAT, user_id=OWNER, recovery_task_id="stop-task", queue_revision=1,
        recovery_preflight_id="stop-preflight", recovery_turn_id="saved-stop",
    )


def paused(source, *execution_ids):
    return {"turn_id": source, "source_delivery_task_id": f"assistant-{source}", "task_ids": execution_ids}


async def write_run(redis, execution_id, status="running", owner_hash=OWNER_HASH):
    await redis.set(_execution_key(execution_id), json.dumps({
        "execution_id": execution_id, "status": status, "user_id_hash": owner_hash, "events": [],
    }))


@fixture
def scopes(monkeypatch):
    scoped_runs = AsyncMock(return_value=[paused("safari", "run-1"), paused("firefox", "run-2")])
    assistant_stop = AsyncMock(return_value="revocation_sent")
    monkeypatch.setattr(same_turn_skill_barrier, "find_paused_code_work", scoped_runs)
    monkeypatch.setattr(cancel_ai_task_handler, "cancel_owned_ai_task", assistant_stop)
    return scoped_runs, assistant_stop


async def resolve(cache, chat_request=None, *, new=True):
    if chat_request is None:
        chat_request = request()
    return await natural_chat_stop.resolve_natural_chat_stop(
        request=chat_request, cache=cache, directus=None, manager=None,
        device_hash="device", newly_enqueued=new,
    )


# contract-test: supporting surface=rest_api assertions=chat-queued-followups.routing.active-work,chat-queued-followups.access.scoped
async def test_cancel_named_code_run_preserves_other_run_and_worker_sees_stop_after_progress_overwrite(scopes, monkeypatch):
    scoped_runs, assistant_stop = scopes
    async with FakeRedis() as redis:
        cache = Cache(redis)
        await write_run(redis, "run-1")
        await write_run(redis, "run-2")

        first = await resolve(cache)
        assert first.reply == STOP_RUN_REQUESTED
        scoped_runs.assert_awaited_once_with(cache, user_id=OWNER, chat_id=CHAT)
        assistant_stop.assert_not_awaited()
        assert json.loads(await redis.get(_execution_key("run-1")))["status"] == "cancelling"
        assert json.loads(await redis.get(_execution_key("run-2")))["status"] == "running"
        cache.publish_event.assert_awaited_once()

        # The selected run's worker writes a progress snapshot fetched just before
        # the cancellation. The independent stop flag must still reach its next check.
        await write_run(redis, "run-1")
        monkeypatch.setattr(run_code_task, "get_worker_cache_service", AsyncMock(return_value=cache))
        assert await run_code_task._is_cancel_requested("run-1")
        assert not await run_code_task._is_cancel_requested("run-2")

        scoped_runs.return_value = [paused("safari", "run-3")]
        await write_run(redis, "run-3")
        assert await resolve(cache, new=False) == first
        assert not await redis.get(code_run_cancel_key("run-3"))
        cache.publish_event.assert_awaited_once()


# contract-test: supporting surface=rest_api assertions=chat-queued-followups.routing.active-work,chat-queued-followups.access.scoped
@mark.parametrize("content", [
    "give me a second", "hold on a minute", "stop for a second", "stop talking please",
    "don’t cancel the Safari run", "“cancel the Safari run”", "What does cancel the Safari run mean?",
])
async def test_ordinary_barge_in_never_resolves_or_mutates_work(scopes, content):
    scoped_runs, assistant_stop = scopes
    assert explicit_stop_label(content) is None
    async with FakeRedis() as redis:
        cache = Cache(redis)
        assert await resolve(cache, request(content)) == natural_chat_stop.StopDecision()
        assert list(await redis.keys()) == []
        scoped_runs.assert_not_awaited()
        assistant_stop.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=chat-queued-followups.routing.active-work,chat-queued-followups.access.scoped
@mark.parametrize("case", ["bare", "same-label", "multiple-executions", "exclusion", "missing-history", "mixed"])
async def test_ambiguous_or_unbound_request_cannot_signal_any_execution(scopes, case):
    scoped_runs, assistant_stop = scopes
    chat_request = request()
    if case == "bare":
        chat_request = request("stop")
    if case == "same-label":
        chat_request = request(firefox="Run the second Safari test.")
    if case == "multiple-executions":
        scoped_runs.return_value = [paused("safari", "run-1", "run-2")]
    if case == "exclusion":
        chat_request = request(safari="Run the Firefox test without Safari.")
    if case == "missing-history":
        chat_request.message_history.pop(1)
    if case == "mixed":
        chat_request = request("cancel the Safari run and the Firefox run")
    async with FakeRedis() as redis:
        cache = Cache(redis)
        await write_run(redis, "run-1")
        await write_run(redis, "run-2")
        assert (await resolve(cache, chat_request)).reply == STOP_CLARIFY
        assert not await redis.keys("code_run_cancel_requested:*")
        assistant_stop.assert_not_awaited()
        cache.publish_event.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=chat-queued-followups.routing.active-work,chat-queued-followups.access.scoped
async def test_live_assistant_stop_uses_verified_bound_user_message_and_not_latest_chat_turn(scopes):
    scoped_runs, assistant_stop = scopes
    scoped_runs.return_value = []
    async with FakeRedis() as redis:
        cache = Cache(redis)
        cache.get_active_ai_task.return_value = "assistant-safari"
        slot = {"user_id": OWNER, "chat_id": CHAT, "task_id": "assistant-firefox"}
        await cache.set(f"independent_chat_reply:{CHAT}", slot, ttl=60)
        for title in ("safari", "firefox"):
            task_id = f"assistant-{title}"
            await cache.set(cancellation_scope_key(CHAT, task_id), {
                "user_id": OWNER, "chat_id": CHAT, "task_id": task_id, "user_message_id": title,
            }, ttl=60)

        assert (await resolve(cache)).reply == STOP_REQUESTED
        assistant_stop.assert_awaited_once_with(
            cache_service=cache, directus_service=None, manager=None, user_id=OWNER,
            device_fingerprint_hash="device", chat_id=CHAT, task_id="assistant-safari",
        )


# contract-test: supporting surface=rest_api assertions=chat-queued-followups.routing.active-work,chat-queued-followups.access.scoped
@mark.parametrize("case", ["foreign-owner", "finished", "exact-retry-no-receipt"])
async def test_rechecks_ownership_and_live_state_and_retries_do_not_pick_a_replacement(scopes, case):
    scoped_runs, assistant_stop = scopes
    async with FakeRedis() as redis:
        cache = Cache(redis)
        await write_run(redis, "run-1", status="finished" if case == "finished" else "running",
                        owner_hash="other" if case == "foreign-owner" else OWNER_HASH)
        decision = await resolve(cache, new=case != "exact-retry-no-receipt")
        if case == "exact-retry-no-receipt":
            assert decision.prior_request_pending
            scoped_runs.assert_not_awaited()
        else:
            assert decision.reply == (STOP_RUN_ENDED if case == "finished" else STOP_UNCONFIRMED)
        assistant_stop.assert_not_awaited()
        cache.publish_event.assert_not_awaited()
        assert not await redis.get(code_run_cancel_key("run-1"))


# contract-test: supporting surface=rest_api assertions=chat-queued-followups.routing.active-work,chat-queued-followups.access.scoped
async def test_only_confirmed_stop_request_can_save_a_fixed_control_reply():
    async with FakeRedis() as redis:
        cache = Cache(redis)
        chat_request = request()
        chat_request.active_input_reply = STOP_RUN_REQUESTED
        cache.get_active_ai_task.return_value = chat_request.recovery_task_id
        assert not await verified_fixed_active_input_reply(cache, chat_request, chat_request.recovery_task_id)
        await admit_fixed_active_input_reply(cache, chat_request)
        assert await verified_fixed_active_input_reply(cache, chat_request, chat_request.recovery_task_id)

        pause = request("give me a second")
        pause.active_input_reply = STOP_RUN_REQUESTED
        await admit_fixed_active_input_reply(cache, pause)
        assert not await verified_fixed_active_input_reply(cache, pause, pause.recovery_task_id)
