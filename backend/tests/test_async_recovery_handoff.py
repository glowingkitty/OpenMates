"""Legacy Project callbacks transfer a recovery inference before nested skills."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.skills.ask_skill import AskSkillRequest
from backend.shared.python_utils import recent_work_summary_client as summary

SOURCE = "018f2222-2222-7222-8222-222222222222"
PRODUCER = "018f3333-3333-7333-8333-333333333333"


class Cache:
    def __init__(self):
        self.values = {}
        self.events = []

    @property
    async def client(self):
        return self

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ttl=None, *, nx=False, ex=None):
        import json
        if nx and key in self.values:
            return False
        if isinstance(value, str) and value.startswith("{"):
            value = json.loads(value)
        self.values[key] = value
        return True

    async def delete(self, key):
        return self.values.pop(key, None) is not None

    def _get_active_task_key(self, chat):
        return f"active:{chat}"

    def _get_task_chat_mapping_key(self, task):
        return f"task-chat:{task}"

    async def get_active_ai_task(self, chat):
        return self.values.get(self._get_active_task_key(chat))

    async def clear_active_ai_task_if_matches(self, chat, task):
        if await self.get_active_ai_task(chat) == task:
            await self.delete(self._get_active_task_key(chat))
            return True
        return False

    async def publish_event(self, channel, payload):
        self.events.append((channel, payload))

    async def eval(self, _script, count, *args):
        if count == 1:
            key, expected, replacement, _ttl = args
            if self.values.get(key) != expected:
                return 0
            self.values[key] = replacement
            return 1
        latest_key, active_key, mapping_key, turn, delivery, chat = args
        assert count == 3
        if self.values.get(latest_key) != turn or self.values.get(active_key) not in {None, delivery}:
            return 0
        self.values[active_key] = delivery
        self.values[mapping_key] = chat
        return 1


class Lifecycle:
    """Strict source/step ownership fake; real Directus guard has a Node regression."""
    def __init__(self):
        self.current = SOURCE
        self.step = None
        self.state = "RUNNING"
        self.calls = []

    async def execute(self, operation, data):
        self.calls.append((operation, data))
        if operation == "pause_inference_for_skill":
            if self.state != "RUNNING" or self.current != data["delivery_task_id"]:
                raise RuntimeError("inference_delivery_mismatch")
            if self.step not in {None, data["step_id"]}:
                return {"paused": False}
            self.step = data["step_id"]
            return {"paused": True}
        if operation == "resume_inference_for_skill":
            if self.state != "RUNNING" or self.step != data["step_id"]:
                return {"claimed": False}
            self.current, self.step = data["delivery_task_id"], None
            return {"claimed": True}
        assert operation == "mark_inference_failed"
        if data.get("turn_id") == "recovery-turn" or self.step == data.get("step_id"):
            self.state = "FAILED"
        return {"failed": self.state == "FAILED", "state": self.state}


@pytest.fixture
def subject(monkeypatch):
    # Load the production task types before patching the Directus constructor;
    # lazy task imports must not capture a test replacement globally.
    from backend.apps.ai.tasks import ask_skill_task  # noqa: F401

    path = Path(__file__).resolve().parents[1] / "apps/ai/tasks/async_skill_continuation.py"
    spec = importlib.util.spec_from_file_location("async_project_handoff_subject", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from backend.core.api.app.services import chat_recovery_service
    lifecycle = Lifecycle()
    monkeypatch.setattr(chat_recovery_service, "ChatRecoveryService", lambda _directus: lifecycle)
    from backend.core.api.app.services import directus
    class FakeDirectus:
        def __init__(self, **_kwargs):
            self.close = AsyncMock()

    monkeypatch.setattr(directus, "DirectusService", FakeDirectus)
    queued, timers = [], []
    failure = {"send": False, "timer": False}

    def send_task(name, kwargs, queue, **options):
        if name.endswith("async_recovery_handoff_deadline"):
            if failure["timer"]:
                raise RuntimeError("deadline broker unavailable")
            timers.append((name, kwargs, options))
            return SimpleNamespace(id="deadline")
        assert name == "apps.ai.tasks.skill_ask"
        if failure["send"]:
            failure["send"] = False
            raise RuntimeError("broker unavailable")
        queued.append({"task_id": options["task_id"], **kwargs})
        return SimpleNamespace(id=options["task_id"])

    monkeypatch.setattr(module, "_get_celery_app", lambda: SimpleNamespace(send_task=send_task))
    return module, lifecycle, queued, timers, failure


def request():
    return AskSkillRequest(
        user_id="owner", user_id_hash="hash", chat_id="chat", message_id="user-message",
        message_history=[], recovery_task_id=SOURCE, recovery_preflight_id="preflight",
        recovery_turn_id="recovery-turn", recovery_public_key="public-key", chat_key_version=1,
    )


async def prepare(subject):
    module, lifecycle, queued, timers, _failure = subject
    cache, original = Cache(), request()
    await cache.set(cache._get_active_task_key("chat"), SOURCE)
    await cache.set(module.async_skill_latest_user_turn_key("owner", "chat"), "user-message")
    await module.cache_async_skill_continuation_context(
        cache_service=cache, async_task_id=PRODUCER, request_data=original,
        app_id="system", skill_id="project_focus_catalog", tool_name="project_focus_catalog",
        tool_arguments={}, skill_config_dict={"default_llms": {"preprocessing_model": "configured"}},
        requires_current_turn=True, defer_until_initial_response_complete=True,
        ttl_seconds=300, source_delivery_task_id=SOURCE, directus_service=object(),
    )
    assert original.awaiting_async_skill_continuation is True
    assert original._pending_async_recovery_handoff == PRODUCER
    assert lifecycle.step == f"async:{PRODUCER}"
    assert len(timers) == 1
    assert await module.dispatch_async_skill_continuation(
        cache_service=cache, async_task_id=PRODUCER, completed_results=[{"catalog": []}],
    ) is None
    assert queued == []  # Source still owns the chat; no premature successor.
    await module.dispatch_async_skill_continuation(
        cache_service=cache, async_task_id=PRODUCER, completed_results=[{"catalog": []}],
    )
    assert await cache.get(module.async_skill_deferred_index_key("owner", "chat")) == [PRODUCER]
    await cache.clear_active_ai_task_if_matches("chat", SOURCE)
    return cache, original


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=code-run.assistant.auto-debug-bounded,app-skills.assistant.idempotent-resume,app-skills.assistant.same-turn-completion
async def test_project_callback_claims_delivery_before_nested_code_pause(subject):
    module, lifecycle, queued, _timers, _failure = subject
    cache, original = await prepare(subject)
    ids = await module.dispatch_deferred_async_skill_continuations(cache_service=cache, user_id="owner", chat_id="chat")
    assert ids == [queued[0]["task_id"]]
    successor = AskSkillRequest.model_validate(queued[0]["request_data_dict"])
    assert successor.resolved_recovery_inference_task_id() == SOURCE
    assert successor.continuation_message_id == SOURCE
    assert successor.message_id == original.message_id
    assert not successor.awaiting_async_skill_continuation
    delivery = ids[0]
    assert module.is_async_recovery_handoff_delivery(successor, delivery)
    assert await module.claim_async_recovery_handoff(cache=cache, directus=object(), request=successor, delivery_id=delivery)
    assert summary.recent_work_authority_task_id(successor, delivery) == delivery
    assert not any(key.startswith("_verified") for key in successor.model_dump())
    assert await lifecycle.execute("pause_inference_for_skill", {
        "delivery_task_id": delivery, "step_id": "nested-code-run",
    }) == {"paused": True}
    with pytest.raises(RuntimeError, match="inference_delivery_mismatch"):
        await lifecycle.execute("pause_inference_for_skill", {"delivery_task_id": SOURCE, "step_id": "forged"})
    assert not await module.claim_async_recovery_handoff(cache=cache, directus=object(), request=successor, delivery_id=delivery)
    assert await module.dispatch_deferred_async_skill_continuations(cache_service=cache, user_id="owner", chat_id="chat") == []
    assert len(queued) == 1


@pytest.mark.parametrize("change", ["forged_delivery", "wrong_turn", "cancelled", "expired"])
@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=app-skills.assistant.bounded-private-failure,app-skills.assistant.idempotent-resume
async def test_async_handoff_rejects_forged_stale_cancelled_and_late_claims(subject, monkeypatch, change):
    module, lifecycle, queued, _timers, _failure = subject
    cache, _original = await prepare(subject)
    await module.dispatch_deferred_async_skill_continuations(cache_service=cache, user_id="owner", chat_id="chat")
    row = queued[0]
    successor = AskSkillRequest.model_validate(row["request_data_dict"])
    delivery = row["task_id"]
    if change == "forged_delivery":
        delivery = SOURCE
    elif change == "wrong_turn":
        await cache.set(module.async_skill_latest_user_turn_key("owner", "chat"), "new-user-message")
    elif change == "cancelled":
        lifecycle.state = "FAILED"
    else:
        authority = await cache.get(module._async_handoff_key(PRODUCER))
        monkeypatch.setattr(module.time, "time", lambda: authority["deadline"] + 1)
    object.__setattr__(successor, "_verified_async_handoff_delivery_task_id", delivery)
    object.__setattr__(successor, "_verified_async_handoff_capability", {})
    assert summary.recent_work_authority_task_id(successor, delivery) == SOURCE
    assert not await module.claim_async_recovery_handoff(cache=cache, directus=object(), request=successor, delivery_id=delivery)
    assert summary.recent_work_authority_task_id(successor, delivery) == SOURCE
    assert not hasattr(successor, "_verified_async_handoff_capability")


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=app-skills.assistant.idempotent-resume,app-skills.assistant.bounded-private-failure
async def test_failed_enqueue_retries_same_delivery_and_unclaimed_pause_expires(subject, monkeypatch):
    module, lifecycle, queued, _timers, failure = subject
    cache, _original = await prepare(subject)
    authority = await cache.get(module._async_handoff_key(PRODUCER))
    failure["send"] = True
    with pytest.raises(RuntimeError, match="broker unavailable"):
        await module.dispatch_deferred_async_skill_continuations(cache_service=cache, user_id="owner", chat_id="chat")
    assert await cache.get_active_ai_task("chat") is None
    assert lifecycle.current == SOURCE
    assert await cache.get(module.async_skill_deferred_completion_key(PRODUCER))
    ids = await module.dispatch_deferred_async_skill_continuations(cache_service=cache, user_id="owner", chat_id="chat")
    assert ids == [authority["delivery_id"]]
    assert len(queued) == 1
    monkeypatch.setattr(module.time, "time", lambda: authority["deadline"] + 1)
    await module.expire_async_recovery_handoff(cache=cache, directus=object(), producer_id=PRODUCER)
    assert lifecycle.state == "FAILED"
    assert await cache.get_active_ai_task("chat") is None
    assert await cache.get(module._async_handoff_key(PRODUCER)) is None
    assert cache.events[-1][1]["type"] == "recovery_output_paused"
    assert cache.events[-1][1]["reason_code"] == "durable_output_unavailable"


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=app-skills.assistant.bounded-private-failure,app-skills.assistant.idempotent-resume
async def test_stop_while_source_owner_is_released_fences_delayed_project_callback(subject):
    module, lifecycle, queued, _timers, _failure = subject
    cache, _original = await prepare(subject)
    assert await cache.get_active_ai_task("chat") is None
    assert await module.cancel_same_turn_source(cache, user_id="owner", chat_id="chat", source_task_id=SOURCE)
    assert lifecycle.state == "FAILED"
    assert cache.events[-1][1]["reason_code"] == "user_cancelled"
    assert await cache.get(module.async_skill_latest_user_turn_key("owner", "chat")) == f"cancelled:{SOURCE}"
    assert await module.dispatch_deferred_async_skill_continuations(cache_service=cache, user_id="owner", chat_id="chat") == []
    assert queued == []
    assert not await module.cancel_same_turn_source(cache, user_id="owner", chat_id="chat", source_task_id=SOURCE)
    assert len(cache.events) == 1


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=app-skills.assistant.bounded-private-failure
async def test_expiry_does_not_notify_or_clear_a_different_claimed_pause(subject, monkeypatch):
    module, lifecycle, _queued, _timers, _failure = subject
    cache, _original = await prepare(subject)
    authority = await cache.get(module._async_handoff_key(PRODUCER))
    lifecycle.step = "different-pause"
    monkeypatch.setattr(module.time, "time", lambda: authority["deadline"] + 1)
    await module.expire_async_recovery_handoff(cache=cache, directus=object(), producer_id=PRODUCER)
    assert lifecycle.state == "RUNNING"
    assert not cache.events
    assert await cache.get(module._async_handoff_key(PRODUCER)) == authority


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=app-skills.assistant.complete-result-barrier,app-skills.assistant.bounded-private-failure
async def test_waiting_source_preserves_accepted_followup_queue_handoff(subject, monkeypatch):
    import sys
    from backend.apps.ai.tasks import ask_skill_task
    from backend.apps.ai.processing import queued_steering

    module, lifecycle, _queued, _timers, _failure = subject
    monkeypatch.setitem(sys.modules, "backend.apps.ai.tasks.async_skill_continuation", module)
    cache, original = await prepare(subject)
    await cache.set(cache._get_active_task_key("chat"), SOURCE)
    follower = {"recovery_task_id": "queued-follower", "message_id": "next-user-message"}
    lease = {"messages": [follower], "token": "owned-queue-lease"}
    cache.lease_queued_message_prefix = AsyncMock(return_value=lease)
    monkeypatch.setattr(queued_steering, "reconcile_queued_revision_quarantine", AsyncMock(return_value=True))
    transferred = []

    async def transfer(**kwargs):
        assert lifecycle.state == "FAILED"  # Exact predecessor pause settled first.
        transferred.append(kwargs["queued_lease"])

    monkeypatch.setattr(ask_skill_task, "_start_recovery_queued_follower", transfer)
    assert await ask_skill_task._handoff_queued_after_task_failure(
        original, {}, SOURCE, cache, object(),
    ) is True
    assert transferred == [lease]
    assert cache.lease_queued_message_prefix.await_count == 1


@pytest.mark.parametrize("failure_point", ["deadline", "callback_cache"])
@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=app-skills.assistant.bounded-private-failure
async def test_registration_failure_settles_exact_pause_instead_of_stranding_source(subject, failure_point):
    module, lifecycle, _queued, _timers, failure = subject
    cache, original = Cache(), request()
    await cache.set(cache._get_active_task_key("chat"), SOURCE)
    await cache.set(module.async_skill_latest_user_turn_key("owner", "chat"), "user-message")
    if failure_point == "deadline":
        failure["timer"] = True
    else:
        original_set = cache.set

        async def reject_context(key, *args, **kwargs):
            if key == module.async_skill_continuation_key(PRODUCER):
                return False
            return await original_set(key, *args, **kwargs)

        cache.set = reject_context
    with pytest.raises(RuntimeError):
        await module.cache_async_skill_continuation_context(
            cache_service=cache, async_task_id=PRODUCER, request_data=original,
            app_id="system", skill_id="project_focus_catalog", tool_name="project_focus_catalog",
            tool_arguments={}, requires_current_turn=True, defer_until_initial_response_complete=True,
            source_delivery_task_id=SOURCE, directus_service=object(), ttl_seconds=300,
        )
    assert lifecycle.state == "FAILED"
    assert await cache.get(module._async_handoff_key(PRODUCER)) is None
    assert cache.events[-1][1]["reason_code"] == "durable_output_unavailable"


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=app-skills.assistant.same-turn-completion
async def test_unoffered_project_operation_releases_its_pause_for_the_next_operation(subject):
    """A Project operation that fails before it is offered (invalid path) frees the turn."""
    module, lifecycle, _queued, _timers, _failure = subject
    cache, original = Cache(), request()
    await cache.set(cache._get_active_task_key("chat"), SOURCE)
    await cache.set(module.async_skill_latest_user_turn_key("owner", "chat"), "user-message")
    common = dict(
        cache_service=cache, request_data=original, app_id="system",
        skill_config_dict={"default_llms": {"preprocessing_model": "configured"}},
        requires_current_turn=True, defer_until_initial_response_complete=True,
        ttl_seconds=300, source_delivery_task_id=SOURCE, directus_service=object(),
    )
    await module.cache_async_skill_continuation_context(
        async_task_id=PRODUCER, skill_id="project-list-files", tool_name="project-list-files",
        tool_arguments={}, **common,
    )
    assert lifecycle.step == f"async:{PRODUCER}"
    await module.release_unoffered_async_recovery_handoff(
        cache=cache, directus=object(), request=original, producer_id=PRODUCER, awaiting_before=False,
    )
    assert lifecycle.step is None and lifecycle.current == SOURCE
    assert original.awaiting_async_skill_continuation is False
    assert getattr(original, "_pending_async_recovery_handoff", None) is None
    assert await cache.get(module._async_handoff_key(PRODUCER)) is None

    second = "018f4444-4444-7444-8444-444444444444"
    await module.cache_async_skill_continuation_context(
        async_task_id=second, skill_id="project-create-file", tool_name="project-create-file",
        tool_arguments={}, **common,
    )
    assert lifecycle.step == f"async:{second}"
    assert original._pending_async_recovery_handoff == second
