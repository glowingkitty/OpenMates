"""The active-input decision gets bounded, owner-scoped reference data only."""

from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.processing import jev_decisions
from backend.core.api.app.schemas.chat import AIHistoryMessage
from backend.core.api.app.services.active_chat_input import ActiveWork, decide_active_chat_input
from backend.shared.providers.typesafe.models import ChoiceAnswer, DecisionResponse


def _choice(choice: str, confidence: float = 0.98) -> ChoiceAnswer:
    return ChoiceAnswer(type="choice", choice=choice, probabilities={choice: 1.0}, confidence=confidence)


@pytest.mark.asyncio
@pytest.mark.parametrize("target,confidence,editable,intent", [
    ("work_1", 0.9, True, "steer"),
    ("work_99", 0.9, True, "clarify"),
    ("work_1", 0.4, True, "clarify"),
    ("work_1", 0.9, False, "clarify"),
])
# contract-test: supporting surface=rest_api assertions=chat-queued-followups.routing.active-work
async def test_jev_can_only_choose_a_verified_candidate(monkeypatch, target, confidence, editable, intent):
    evaluate = AsyncMock(return_value=DecisionResponse(
        model="jev", answers={"intent": _choice("steer"), "target": _choice(target, confidence)},
    ))
    monkeypatch.setattr(jev_decisions, "evaluate_jev_decisions", evaluate)
    work = ActiveWork(task_id="private-task-id", turn_id="prior-request", artifact=editable)
    history = [
        AIHistoryMessage(message_id="other-request", role="user", sender_name="user", created_at=1,
                         content="Unrelated confidential history"),
        AIHistoryMessage(message_id="prior-request", role="user", sender_name="user", created_at=2,
                         content="Build a recipe site. ```json\nSECRET ATTACHMENT\n```"),
    ]
    decision = await decide_active_chat_input(
        content="Change the header to red.", message_history=history,
        candidates=[work], message_id="private-new-message-id",
    )
    assert decision.intent == intent
    assert decision.target == (work if intent == "steer" else None)
    evaluate.assert_awaited_once()
    state = evaluate.await_args.kwargs["state"]
    assert state == {
        "new_user_message": "Change the header to red.",
        "active_work": {"work_1": {
            "phase": "answer_in_progress", "editable_artifact": editable,
            "original_request": "Build a recipe site.", "assistant_excerpt": "",
        }},
    }


# contract-test: supporting surface=rest_api assertions=chat-queued-followups.routing.active-work,chat-queued-followups.access.scoped
@pytest.mark.asyncio
async def test_standalone_question_can_use_only_completed_turns_as_context(monkeypatch):
    evaluate = AsyncMock(return_value=DecisionResponse(
        model="jev", answers={"intent": _choice("standalone_answer"), "target": _choice("unresolved")},
    ))
    monkeypatch.setattr(jev_decisions, "evaluate_jev_decisions", evaluate)
    history = [
        AIHistoryMessage(message_id="definition", role="assistant", sender_name="assistant", created_at=1,
                         content="The cache flag reuses completed build output."),
        AIHistoryMessage(message_id="foreground-user", role="user", sender_name="user", created_at=2,
                         content="Build the new app."),
        AIHistoryMessage(message_id="foreground-assistant", role="assistant", sender_name="assistant", created_at=3,
                         content="Unfinished code preview."),
    ]
    decision = await decide_active_chat_input(
        content="What does the cache flag do?", message_history=history,
        candidates=[ActiveWork("foreground-assistant", "foreground-user", artifact=True)],
        message_id="question", include_completed_context=True,
    )
    assert decision.intent == "independent" and decision.standalone_answer
    assert evaluate.await_args.kwargs["state"]["recent_completed_conversation"] == [{
        "role": "assistant", "excerpt": "The cache flag reuses completed build output.",
    }]


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=chat-queued-followups.routing.active-work
async def test_unavailable_classifier_defers_without_proposing_an_action(monkeypatch):
    evaluate = AsyncMock(side_effect=TimeoutError())
    monkeypatch.setattr(jev_decisions, "evaluate_jev_decisions", evaluate)
    decision = await decide_active_chat_input(
        content="Change it", message_history=[], candidates=[ActiveWork("id", None)], message_id="new",
    )
    assert decision.intent == "defer"
    assert decision.target is None
    assert evaluate.await_args.kwargs["max_retries"] == 0


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=chat-queued-followups.steering.safe-boundary
async def test_parked_steer_waits_for_its_exact_resumed_worker():
    import json
    from fakeredis.aioredis import FakeRedis
    from backend.core.api.app.services.cache_chat_mixin import ChatCacheMixin

    class Cache(ChatCacheMixin):
        def __init__(self, redis):
            self.redis = redis

        @property
        async def client(self):
            return self.redis

    async with FakeRedis() as redis:
        cache = Cache(redis)
        key = "same_turn_skill:long-running-batch"
        await redis.set(f"{key}:batch", json.dumps({
            "user_id": "owner", "chat_id": "chat", "turn_id": "source-turn",
            "logical_task_id": "producer", "code_work": True,
        }))
        await redis.set(f"{key}:armed", "armed")
        await cache.set_active_ai_task("chat", "independent-turn")
        member = {
            "user_id": "owner", "chat_id": "chat", "message_id": "steer-message",
            "queue_mode": "steer", "active_input_steer_task_id": "producer",
            "active_input_steer_batch_id": "long-running-batch",
        }
        assert not await cache.queue_message(
            "chat", member | {"user_id": "another-owner"}, expected_paused_turn_id="source-turn",
        )
        assert await cache.queue_message("chat", member, expected_paused_turn_id="source-turn")
        assert await redis.ttl(cache._get_chat_queue_key("chat")) > 600
        assert not await cache.lease_queued_message_prefix("chat", worker_task_id="independent-turn")
        assert await cache.complete_active_ai_task_if_queue_empty("chat", "independent-turn") == 1
        assert await cache.queue_waits_for_parked_steer("chat", "owner")
        assert not await cache.queue_waits_for_parked_steer("chat", "another-owner")

        await redis.set(f"{key}:resume_claim", "expected-resume")
        await cache.set_active_ai_task("chat", "expected-resume")
        assert not await cache.lease_queued_message_prefix("chat", worker_task_id="wrong-resume")
        assert (await cache.lease_queued_message_prefix("chat", worker_task_id="expected-resume"))["messages"] == [member]
        await redis.set(f"{key}:stopping", "1")
        assert not await cache.queue_message(
            "chat", member | {"message_id": "late-steer"}, expected_paused_turn_id="source-turn",
        )


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=chat-queued-followups.access.scoped
async def test_hidden_candidates_cannot_become_inferred_steer_targets(monkeypatch):
    evaluate = AsyncMock(return_value=DecisionResponse(
        model="jev", answers={"intent": _choice("steer"), "target": _choice("work_1")},
    ))
    monkeypatch.setattr(jev_decisions, "evaluate_jev_decisions", evaluate)
    candidates = [ActiveWork(f"task-{number}", None, artifact=True) for number in range(5)]
    decision = await decide_active_chat_input(
        content="Change its color", message_history=[], candidates=candidates, message_id="new",
    )
    assert decision.intent == "clarify"
    assert len(evaluate.await_args.kwargs["state"]["active_work"]) == 4


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=chat-queued-followups.steering.safe-boundary
async def test_retirement_pauses_only_exact_parked_revisions_before_removal(monkeypatch):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from backend.apps.ai.processing.parked_steering import retire_parked_steers
    from backend.core.api.app.services import directus

    effects = []

    @asynccontextmanager
    async def queue_lock(chat_id):
        assert chat_id == "chat"
        yield

    async def pause(*args, **kwargs):
        effects.append(("durably_paused", args, kwargs))
        return {"status": "paused"}

    async def remove(*args):
        effects.append(("removed", args))
        return True

    directus_client = SimpleNamespace(
        chat=SimpleNamespace(mark_queued_message_paused=AsyncMock(side_effect=pause)),
        close=AsyncMock(),
    )
    monkeypatch.setattr(directus, "DirectusService", lambda **_: directus_client)
    cache = SimpleNamespace(
        get=AsyncMock(return_value={"user_id": "owner", "chat_id": "chat", "code_work": True}),
        queued_message_edit_lock=queue_lock,
        get_parked_steer_members=AsyncMock(return_value=[{
            "raw": b"exact-revision",
            "member": {"message_id": "correction", "queue_revision": 3, "queue_mode": "steer"},
        }]),
        publish_event=AsyncMock(),
        delete=AsyncMock(),
        remove_parked_steer_member=AsyncMock(side_effect=remove),
    )

    async def get_client(_):
        return SimpleNamespace(set=AsyncMock())

    cache_type = type("Cache", (), {"client": property(get_client)})
    instance = cache_type()
    instance.__dict__.update(vars(cache))
    await retire_parked_steers(instance, user_id="owner", chat_id="chat", batch_id="selected")
    cache.get_parked_steer_members.assert_awaited_once_with("chat", "owner", "selected")
    assert effects == [
        ("durably_paused", ("chat", "owner", "correction", 3, "dispatch_failed"), {"queue_mode": "steer"}),
        ("removed", ("chat", b"exact-revision")),
    ]
    assert cache.publish_event.await_args.args[1]["payload"]["message_id"] == "correction"


# contract-test: supporting surface=rest_api assertions=chat-queued-followups.access.scoped
def test_active_input_fields_are_internal_to_the_exact_websocket_dispatch():
    from backend.apps.ai.skills.ask_skill import AskSkillRequest
    from backend.shared.python_utils.active_input_authority import (
        authorize_active_input_dispatch, remove_untrusted_active_input,
    )

    spoofed = AskSkillRequest(
        user_id="owner", user_id_hash="owner-hash", chat_id="chat", message_id="message",
        message_history=[], active_input_reply="injected status",
        active_input_steer_task_id="injected-task", active_input_steer_batch_id="injected-batch",
        active_input_parallel_source="injected-source", active_input_parallel_source_message="injected-source-message",
    )
    fields = ("active_input_reply", "active_input_steer_task_id", "active_input_steer_batch_id",
              "active_input_parallel_source", "active_input_parallel_source_message")
    assert all(getattr(remove_untrusted_active_input(spoofed), name) is None for name in fields)
    with authorize_active_input_dispatch("owner", "chat", "different-message"):
        assert all(getattr(remove_untrusted_active_input(spoofed), name) is None for name in fields)
    with authorize_active_input_dispatch("owner", "chat", "message"):
        assert remove_untrusted_active_input(spoofed) is spoofed
    assert all(getattr(remove_untrusted_active_input(spoofed), name) is None for name in fields)


# contract-test: supporting surface=rest_api assertions=chat-queued-followups.routing.active-work,chat-queued-followups.access.scoped
@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", [
    "status", "clarify", "credit_balance_unavailable", "missing_admission", "edited",
    "other_foreground", "not_neutral", "fake_reply", "empty_reply", "duplicate_delivery",
])
async def test_canonical_worker_limits_provider_free_reply_to_exact_admission(monkeypatch, scenario):
    from types import SimpleNamespace
    from backend.apps.ai.processing import answer_safety, main_processor, preprocessor
    from backend.apps.ai.skills.ask_skill import AskSkillDefaultConfig, AskSkillRequest
    from backend.apps.ai.tasks import ask_skill_task, stream_consumer
    from backend.apps.ai.tasks import async_skill_continuation
    from backend.apps.ai.tasks.stage_one_task import eligible_for_routing_lane
    from backend.core.api.app.services import client_context_continuation
    from backend.core.api.app.tasks import celery_config
    from backend.shared.python_utils import recent_work_summary_client, voice_call_admission
    from backend.shared.python_utils.active_input_authority import (
        ACTIVE_INPUT_CLARIFICATION, active_input_progress_text, admit_fixed_active_input_reply,
    )

    task_id = "11111111-1111-4111-8111-111111111111"
    reply = active_input_progress_text(1, 2)
    content = "How is the build going?"
    if scenario == "clarify":
        reply = ACTIVE_INPUT_CLARIFICATION
        content = "Which one?"
    denied = scenario == "credit_balance_unavailable"
    public_credit_notice = "Your credit balance could not be verified. Please try again later."
    request = AskSkillRequest(
        user_id="owner", user_id_hash="owner-hash", chat_id="chat", message_id="source-message",
        message_history=[
            AIHistoryMessage(role="assistant", message_id="old", content="A build is starting.",
                             sender_name="assistant", category="software_development", created_at=1),
            AIHistoryMessage(role="user", message_id="source-message", content=content,
                             sender_name="user", created_at=2),
        ],
        current_user_content=content, active_input_reply=reply, chat_has_title=True,
        recovery_task_id=task_id, recovery_preflight_id="preflight", recovery_turn_id="new-turn",
        recovery_public_key="public", chat_key_version=1,
    )
    receipts = {}

    async def store(key, value, **_kwargs):
        receipts[key] = value
        return True

    async def read(key):
        return receipts.get(key)

    cache = SimpleNamespace(
        set=AsyncMock(side_effect=store), get=AsyncMock(side_effect=read),
        get_active_ai_task=AsyncMock(return_value=task_id),
        get_user_by_id=AsyncMock(return_value={"vault_key_id": "vault", "encrypted_credit_balance": "encrypted"}),
        get_discovered_apps_metadata=AsyncMock(return_value={"ai": SimpleNamespace(skills=[])}),
        get_chat_list_item_data=AsyncMock(return_value=None),
        cache_debug_request_entry=AsyncMock(), publish_event=AsyncMock(),
        complete_active_ai_task_if_queue_empty=AsyncMock(return_value=1),
        lease_queued_message_prefix=AsyncMock(return_value=None),
    )
    if scenario == "not_neutral":
        request.current_user_content = "How is the build going? Also change a file."
    if scenario == "fake_reply":
        request.active_input_reply = "Invented status with a private value."
    if scenario == "empty_reply":
        request.active_input_reply = ""
    if scenario != "missing_admission":
        await admit_fixed_active_input_reply(cache, request)
    if scenario == "edited":
        request.queue_revision += 1
    if scenario == "other_foreground":
        cache.get_active_ai_task.return_value = "another-task"

    durable = AsyncMock(return_value={"claimed": scenario != "duplicate_delivery", "state": "RUNNING"})
    prefix_ack = AsyncMock()
    credit_gate = AsyncMock(return_value=preprocessor.PreprocessingResult(
        can_proceed=False, rejection_reason=scenario, error_message=public_credit_notice,
    ) if denied else None)
    paid_preprocessing = AsyncMock(side_effect=RuntimeError("ordinary preprocessing selected"))
    paid_postprocessing = AsyncMock(side_effect=AssertionError("Unexpected postprocessing"))
    paid_final_safety = AsyncMock(side_effect=AssertionError("Unexpected final safety inference"))
    paid_model_billing = AsyncMock(side_effect=AssertionError("Unexpected model billing"))
    recover = AsyncMock(return_value={"job_id": "sealed-status"})
    update_history = AsyncMock()
    actual_consumer = stream_consumer._consume_main_processing_stream

    async def consume(**kwargs):
        durable.assert_awaited_once_with("claim_inference", {"protocol_version": 1, "inference_task_id": task_id})
        prefix_ack.assert_awaited_once()
        assert kwargs["request_data"] is request
        assert kwargs["preprocessing_result"].can_proceed is (not denied)
        assert kwargs["preprocessing_result"].selected_main_llm_model_id is None
        if not denied:
            assert kwargs["preprocessing_result"].selected_mate_id == "programmer"
        return await actual_consumer(**kwargs)

    consumer = AsyncMock(side_effect=consume)
    monkeypatch.setattr(celery_config, "get_worker_cache_service", AsyncMock(return_value=cache))
    monkeypatch.setattr(celery_config.app, "AsyncResult", lambda _: SimpleNamespace(state="STARTED"))
    monkeypatch.setattr(ask_skill_task, "SecretsManager", lambda: SimpleNamespace(initialize=AsyncMock()))
    monkeypatch.setattr(ask_skill_task, "EncryptionService", lambda **_: object())
    monkeypatch.setattr(ask_skill_task, "DirectusService", lambda **_: object())
    monkeypatch.setattr(ask_skill_task, "ChatRecoveryService", lambda _: SimpleNamespace(execute=durable))
    monkeypatch.setattr(ask_skill_task, "_ack_running_recovery_queue_prefix", prefix_ack)
    monkeypatch.setattr(ask_skill_task, "load_validated_base_instructions", AsyncMock(return_value={}))
    monkeypatch.setattr(ask_skill_task, "_load_available_mates", AsyncMock(return_value=[
        SimpleNamespace(
            id="programmer", category="software_development",
            voice_profile=SimpleNamespace(key="programmer", version=1),
        ),
    ]))
    monkeypatch.setattr(ask_skill_task, "_prepare_artifact_context", AsyncMock())
    monkeypatch.setattr(ask_skill_task, "handle_preprocessing", paid_preprocessing)
    monkeypatch.setattr(ask_skill_task, "handle_postprocessing", paid_postprocessing)
    monkeypatch.setattr(ask_skill_task, "_consume_main_processing_stream", consumer)
    monkeypatch.setattr(ask_skill_task, "_publish_project_authoring_availability", AsyncMock())
    monkeypatch.setattr(main_processor, "validate_required_answer_instructions", lambda _: None)
    monkeypatch.setattr(stream_consumer, "_persist_sealed_recovery_job", recover)
    monkeypatch.setattr(stream_consumer, "_update_chat_metadata", update_history)
    monkeypatch.setattr(stream_consumer, "_handle_normal_billing", paid_model_billing)
    zero_cost_notice = AsyncMock(return_value={})
    monkeypatch.setattr(stream_consumer, "_charge_credits", zero_cost_notice)
    monkeypatch.setattr(stream_consumer, "mint_response_summary_completion", AsyncMock())
    monkeypatch.setattr(preprocessor, "check_preprocessing_credits", credit_gate)
    monkeypatch.setattr(answer_safety, "decide_finished_answer", paid_final_safety)
    monkeypatch.setattr(voice_call_admission, "require_active_voice_dispatch", AsyncMock())
    monkeypatch.setattr(client_context_continuation, "await_client_context_phase", AsyncMock())
    monkeypatch.setattr(recent_work_summary_client, "mark_response_summary_active", AsyncMock())
    monkeypatch.setattr(async_skill_continuation, "dispatch_deferred_async_skill_continuations", AsyncMock())
    from backend.apps.ai.processing import queued_steering
    monkeypatch.setattr(queued_steering, "reconcile_queued_revision_quarantine", AsyncMock(return_value=True))

    assert eligible_for_routing_lane(request.model_dump()) is (scenario == "empty_reply")
    if scenario == "duplicate_delivery":
        result = await ask_skill_task._async_process_ai_skill_ask_task(task_id, request, AskSkillDefaultConfig())
        assert result["main_processing_output"] is None
        paid_preprocessing.assert_not_awaited()
        credit_gate.assert_not_awaited()
        consumer.assert_not_awaited()
        prefix_ack.assert_not_awaited()
    elif scenario not in {"status", "clarify", "credit_balance_unavailable"}:
        with pytest.raises(RuntimeError, match="ordinary preprocessing selected"):
            await ask_skill_task._async_process_ai_skill_ask_task(task_id, request, AskSkillDefaultConfig())
        paid_preprocessing.assert_awaited_once()
        credit_gate.assert_not_awaited()
        consumer.assert_not_awaited()
    else:
        result = await ask_skill_task._async_process_ai_skill_ask_task(task_id, request, AskSkillDefaultConfig())
        expected = public_credit_notice if denied else reply
        assert result["main_processing_output"] == expected
        assert result["status"] == "completed"
        credit_gate.assert_awaited_once()
        consumer.assert_awaited_once()
        paid_preprocessing.assert_not_awaited()
        paid_postprocessing.assert_not_awaited()
        paid_final_safety.assert_not_awaited()
        paid_model_billing.assert_not_awaited()
        recover.assert_awaited_once()
        assert recover.await_args.kwargs["task_id"] == task_id
        assert recover.await_args.kwargs["content"] == expected
        update_history.assert_awaited_once()
        if denied:
            zero_cost_notice.assert_awaited_once()
            assert zero_cost_notice.await_args.args[2] == 0
        else:
            zero_cost_notice.assert_not_awaited()
        sealed_frames = [
            call.args[1] for call in cache.publish_event.await_args_list
            if len(call.args) == 2 and call.args[1].get("recovery_job_id") == "sealed-status"
        ]
        assert len(sealed_frames) == 1
        assert sealed_frames[0]["is_final_chunk"] is True
        assert sealed_frames[0]["user_message_id"] == request.message_id

@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=chat-queued-followups.routing.active-work,chat-queued-followups.access.scoped
async def test_linked_sub_chat_projection_reads_only_the_scoped_parent_batch_and_outcomes():
    import json
    from fakeredis.aioredis import FakeRedis
    from backend.core.api.app.services.active_chat_input import linked_sub_chat_work

    class Cache:
        def __init__(self, redis):
            self.redis = redis

        @property
        async def client(self):
            return self.redis

    key = "sub_chat_pending:parent"
    parent = {
        "chat_id": "parent", "user_id": "owner", "user_id_hash": "owner-hash", "message_id": "original-turn",
        "root_chat_id": "parent", "root_turn_id": "original-turn", "orchestration_id": "original-work",
        "message_history": [{"content": "private history is never returned"}],
    }
    child = {
        "chat_id": "one", "parent_id": "parent", "owner_hash": "owner-hash",
        "root_chat_id": "parent", "root_turn_id": "original-turn", "orchestration_id": "original-work",
        "completed_at": 41, "failed": True, "summary": "private report is never returned",
    }
    pending = {
        "parent_task_id": "original-task", "parent_request_data": parent,
        "expected_sub_chat_ids": ["one", "two", "three"],
        "completed": {
            "one": child,
            "unrelated": {**child, "chat_id": "unrelated"},
        },
    }
    scope = {"user_id": "owner", "user_hash": "owner-hash", "chat_id": "parent"}
    async with FakeRedis() as redis:
        cache = Cache(redis)
        exact = json.dumps(pending)
        await redis.set(key, exact)
        assert await linked_sub_chat_work(cache, **scope) == ActiveWork(
            "original-task", "original-turn", linked_sub_chat=True, completed_count=1, task_count=3,
        )
        assert await redis.get(key) == exact.encode()
        assert await linked_sub_chat_work(cache, **{**scope, "user_hash": "unrelated"}) is None
        assert await linked_sub_chat_work(cache, **{**scope, "chat_id": "unrelated"}) is None

        for field, value in (("owner_hash", "foreign-owner-hash"), ("root_turn_id", "previous-run")):
            invalid_result = {**child, "chat_id": "two", field: value}
            await redis.set(key, json.dumps({**pending, "completed": pending["completed"] | {"two": invalid_result}}))
            assert await linked_sub_chat_work(cache, **scope) is None
        for field in ("team_id", "team_id_hash", "team_workspace_type", "team_object_id_hash", "parent_id"):
            altered = {**pending, "parent_request_data": {**parent, field: "foreign-scope"}}
            await redis.set(key, json.dumps(altered))
            assert await linked_sub_chat_work(cache, **scope) is None
        await redis.set(key, json.dumps({**pending, "expected_sub_chat_ids": ["one", "one"]}))
        assert await linked_sub_chat_work(cache, **scope) is None
