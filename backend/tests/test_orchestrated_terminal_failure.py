# contract-test-file: infrastructure
"""A bounded research failure is a failed child and worker, never usable evidence."""
import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from backend.apps.ai.processing.preprocessor import PreprocessingResult
from backend.apps.ai.skills.ask_skill import AskSkillRequest
from backend.apps.ai.tasks import ask_skill_task, stream_consumer
from backend.apps.ai.utils.main_processing_failure import main_processing_failure
from backend.tests.test_chat_failure_notifications import _stub_wrapper_terminal_cleanup


def _id(n):
    return str(uuid.UUID(int=n, version=4))


class _Cache:
    def __init__(self, pending):
        self.rows = pending
        self.close = AsyncMock()

    @property
    async def client(self):
        return object()

    async def get(self, key):
        return self.rows.get(key)

    async def set(self, key, value, **_kwargs):
        self.rows[key] = value
        return True


# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,operational-monitoring.chat-failures.email-trigger,focus-modes.full-instruction,app-skills.assistant.bounded-private-failure
@pytest.mark.parametrize("failure_reason", ["orchestration_budget_limit", "orchestration_output_limit"])
def test_budget_marker_fails_child_and_worker_without_paid_retry(monkeypatch, failure_reason):
    child, parent, task_id = _id(10), _id(1), _id(20)
    request = AskSkillRequest(chat_id=child, message_id=_id(11), user_id="owner",
        user_id_hash="a" * 64, parent_id=parent, is_sub_chat=True, orchestration_id=_id(3),
        root_chat_id=parent, root_turn_id=_id(2), active_focus_id="web-research",
        recovery_inference_task_id=task_id, recovery_preflight_id=_id(4),
        recovery_turn_id=_id(2), recovery_public_key="A" * 43, chat_key_version=1,
        sub_chat_depth=1, orchestration_dispatch_token="test-dispatch-token", message_history=[])
    pending_key = stream_consumer._sub_chat_pending_key(parent)
    cache = _Cache({pending_key: {"expected_sub_chat_ids": [child], "completed": {},
        "parent_request_data": {"chat_id": parent, "user_id_hash": request.user_id_hash}}})
    transitions = []

    class Transactions:
        def __init__(self, _directus):
            pass

        async def execute(self, operation, payload):
            assert operation == "transition_child"
            transitions.append(payload["state"])
            return {"batch_complete": False, "batch_id": _id(31)}

    async def failure_stream(**_kwargs):
        yield "A provisional claim that is not a verified research report."
        yield main_processing_failure(failure_reason)

    publish = AsyncMock()
    monkeypatch.setattr(stream_consumer, "handle_main_processing", failure_stream)
    monkeypatch.setattr(stream_consumer, "_publish_to_redis", publish)
    monkeypatch.setattr(stream_consumer, "_update_chat_metadata", AsyncMock(return_value={}))
    monkeypatch.setattr(stream_consumer, "_persist_sealed_recovery_job", AsyncMock(return_value={"output_id": _id(40)}))
    monkeypatch.setattr(stream_consumer, "_persist_sealed_typed_output", AsyncMock(return_value={"output_id": _id(41)}))
    monkeypatch.setattr(stream_consumer, "DirectusService", lambda: SimpleNamespace(close=AsyncMock()))
    monkeypatch.setattr(stream_consumer, "SubChatOrchestrationService", Transactions)
    monkeypatch.setattr(stream_consumer, "_scoped_child_source_urls", AsyncMock(side_effect=AssertionError("Failed report source read")))
    broker = Mock(side_effect=AssertionError("Paid automatic redispatch"))
    monkeypatch.setattr(stream_consumer.celery_config.app, "send_task", broker)
    monkeypatch.setattr(stream_consumer.celery_config.app, "AsyncResult", lambda _: SimpleNamespace(state="STARTED"))

    result = asyncio.run(stream_consumer._consume_main_processing_stream(
        task_id=task_id, request_data=request, preprocessing_result=PreprocessingResult(can_proceed=True),
        base_instructions={}, directus_service=None, encryption_service=None, user_vault_key_id=None,
        all_mates_configs=[], discovered_apps_metadata={}, cache_service=cache,
    ))
    assert result[4]["main_processing_failure_reason"] == failure_reason
    assert cache.rows[pending_key]["completed"] == {}  # Worker failure callback owns settlement.
    finals = [call.args[2] for call in publish.await_args_list if call.args[2].get("is_final_chunk")]
    assert len(finals) == 1 and finals[0]["error"] is True
    assert "failure_reason" not in finals[0]  # The private budget code stays server-side.

    real_failure_callback = ask_skill_task._mark_sub_chat_terminal_failure
    _stub_wrapper_terminal_cleanup(monkeypatch, ask_skill_task)
    monkeypatch.setattr(ask_skill_task, "_mark_sub_chat_terminal_failure", real_failure_callback)
    monkeypatch.setattr(ask_skill_task, "CacheService", lambda: cache)
    monkeypatch.setattr(ask_skill_task, "notify_chat_failure", AsyncMock())
    retry = Mock(side_effect=AssertionError("Paid automatic retry"))
    monkeypatch.setattr(ask_skill_task.process_ai_skill_ask_task, "retry", retry)
    entered = []

    async def after_stream(*_args, **_kwargs):
        entered.append(True)
        failure = ask_skill_task._orchestration_budget_failure_result(result[4])
        assert failure is not None
        return failure

    monkeypatch.setattr(ask_skill_task, "_async_process_ai_skill_ask_task", after_stream)
    task = ask_skill_task.process_ai_skill_ask_task
    task.push_request(id=task_id)
    try:
        failed_result = task.run(request.model_dump(mode="json"), {})
    finally:
        task.pop_request()
    assert entered == [True]
    assert failed_result["_celery_task_state"] == "FAILURE"
    assert failed_result["failure_reason"] == failure_reason
    assert transitions == ["failed"]
    entry = cache.rows[pending_key]["completed"][child]
    assert entry["failed"] is True and entry["cancelled"] is False
    assert entry["source_refs"] == [] and entry["source_bindings"] == {} and entry["source_urls"] == {}
    assert not stream_consumer._successful_research_reports(cache.rows[pending_key])
    assert any(call.kwargs.get("state") == "FAILURE" for call in task.update_state.call_args_list)
    broker.assert_not_called()
    retry.assert_not_called()


@pytest.mark.parametrize("metadata", [{"main_processing_failure_reason": "untrusted-detail"},
    {"main_processing_failure_reason": "provider_exhausted"}, {}])
# contract-test: supporting surface=rest_api assertions=operational-monitoring.chat-failures.safe-delivery
def test_worker_failure_reason_uses_only_bounded_internal_marker(metadata):
    assert ask_skill_task._orchestration_budget_failure_result(metadata) is None


def _worker_post_consume_decision():
    """Run the production decision statements without unrelated worker setup."""
    import ast
    from pathlib import Path
    module = ast.parse(Path(ask_skill_task.__file__).read_text())
    worker = next(node for node in module.body if isinstance(node, ast.AsyncFunctionDef)
                  and node.name == "_async_process_ai_skill_ask_task")
    budget = next(node for node in ast.walk(worker) if isinstance(node, ast.If)
                  and isinstance(node.test, ast.BoolOp)
                  and ast.unparse(node.test) == "not revoked_in_consumer and (not soft_limited_in_consumer)")
    pause = next(node for node in ast.walk(worker) if isinstance(node, ast.If)
                 and isinstance(node.test, ast.Call) and isinstance(node.test.func, ast.Attribute)
                 and node.test.func.attr == "get" and node.test.args
                 and isinstance(node.test.args[0], ast.Constant)
                 and node.test.args[0].value == "same_turn_skill_paused")
    fn = ast.AsyncFunctionDef(name="decision", args=ast.arguments(posonlyargs=[], args=[ast.arg(arg="debug_cache_task")],
        kwonlyargs=[], kw_defaults=[], defaults=[ast.Constant(value=None)]), body=[budget, pause,
        ast.Return(value=ast.Constant(value="continue-existing-worker-flow"))], decorator_list=[])
    namespace = dict(vars(ask_skill_task))
    tree = ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))
    exec(compile(tree, ask_skill_task.__file__, "exec"), namespace)
    return namespace


# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,operational-monitoring.chat-failures.safe-delivery,app-skills.assistant.bounded-private-failure
@pytest.mark.parametrize("metadata,revoked,soft_limited,expected", [
    (None, False, False, "continue-existing-worker-flow"),
    ({}, False, False, "continue-existing-worker-flow"),
    ({"same_turn_skill_paused": False}, False, False, "continue-existing-worker-flow"),
    (None, True, False, "continue-existing-worker-flow"),
    (None, False, True, "continue-existing-worker-flow"),
    ({"main_processing_failure_reason": "orchestration_budget_limit"}, False, False, "failure"),
    ({"main_processing_failure_reason": "orchestration_output_limit"}, False, False, "failure"),
    ({"same_turn_skill_paused": True, "same_turn_batch_id": "batch"}, False, False, "pause"),
])
def test_optional_debug_metadata_preserves_post_consume_worker_decisions(monkeypatch, metadata, revoked, soft_limited, expected):
    from backend.apps.ai.tasks import async_skill_continuation
    dispatch = AsyncMock()
    monkeypatch.setattr(async_skill_continuation, "dispatch_same_turn_barrier", dispatch)
    cache = SimpleNamespace(clear_active_ai_task_if_matches=AsyncMock(return_value=True))
    namespace = _worker_post_consume_decision()
    namespace.update(main_processor_debug_metadata=metadata, revoked_in_consumer=revoked,
        soft_limited_in_consumer=soft_limited, debug_cache_task=None, cache_service_instance=cache,
        request_data=SimpleNamespace(chat_id="chat", same_turn_batch_id=None, orchestration_id=None), task_id="task")
    result = asyncio.run(namespace["decision"]())
    if expected == "failure":
        assert result == ask_skill_task._orchestration_budget_failure_result(metadata)
        assert result["_celery_task_state"] == "FAILURE"
        assert result["main_processing_output"] is None
    elif expected == "pause":
        assert result["status"] == "waiting_for_skill_completion"
        assert result["main_processing_output"] is None
        dispatch.assert_awaited_once_with(cache_service=cache, batch_id="batch")
    else:
        assert result == "continue-existing-worker-flow"
    if expected != "pause":
        cache.clear_active_ai_task_if_matches.assert_not_awaited()
        dispatch.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,app-skills.assistant.bounded-private-failure
def test_real_revoked_consumer_optional_metadata_does_not_become_paused_or_success(monkeypatch):
    monkeypatch.setattr(stream_consumer.celery_config.app, "AsyncResult", lambda _: SimpleNamespace(state="REVOKED"))
    request = AskSkillRequest(chat_id="chat", message_id="turn", user_id="owner", user_id_hash="owner-hash",
        message_history=[])
    result = asyncio.run(stream_consumer._consume_main_processing_stream(task_id="task", request_data=request,
        preprocessing_result=PreprocessingResult(can_proceed=True), base_instructions={}, directus_service=None,
        encryption_service=None, user_vault_key_id=None, all_mates_configs=[], discovered_apps_metadata={},
        cache_service=None))
    assert result == ("", True, False, [], None)
    namespace = _worker_post_consume_decision()
    namespace.update(main_processor_debug_metadata=result[4], revoked_in_consumer=result[1],
        soft_limited_in_consumer=result[2])
    assert asyncio.run(namespace["decision"]()) == "continue-existing-worker-flow"
    assert result[1] is True and result[0] == ""


# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,focus-modes.full-instruction,app-skills.assistant.bounded-private-failure
@pytest.mark.parametrize("orchestrated", [False, True])
def test_real_insufficient_credit_notice_none_metadata_is_failed_only_for_orchestration(monkeypatch, orchestrated):
    notice = "You do not have enough credits to complete this request."
    request = AskSkillRequest(chat_id="chat", message_id="turn", user_id="owner", user_id_hash="owner-hash",
        message_history=[], recovery_task_id="task", orchestration_id="orchestration" if orchestrated else None,
        active_focus_id="web-research" if orchestrated else None)
    preprocessing = PreprocessingResult(can_proceed=False, rejection_reason="insufficient_credits", error_message=notice)
    publish = AsyncMock()
    persist = AsyncMock(return_value={"output_id": "sealed-notice"})
    charge = AsyncMock(return_value={"total_credits": 0})
    monkeypatch.setattr(stream_consumer.celery_config.app, "AsyncResult", lambda _: SimpleNamespace(state="STARTED"))
    monkeypatch.setattr(stream_consumer, "_publish_to_redis", publish)
    monkeypatch.setattr(stream_consumer, "_persist_sealed_recovery_job", persist)
    monkeypatch.setattr(stream_consumer, "_charge_credits", charge)
    monkeypatch.setattr(stream_consumer, "_update_chat_metadata", AsyncMock())
    monkeypatch.setattr(stream_consumer, "log_main_llm_stream_aggregated_output", Mock())
    main = AsyncMock(side_effect=AssertionError("Rejected request must not start inference"))
    monkeypatch.setattr(stream_consumer, "handle_main_processing", main)
    report = AsyncMock(side_effect=AssertionError("Notice must not become a successful child report"))
    monkeypatch.setattr(stream_consumer, "_record_sub_chat_completion_and_maybe_continue_parent", report)
    result = asyncio.run(stream_consumer._consume_main_processing_stream(task_id="task", request_data=request,
        preprocessing_result=preprocessing, base_instructions={}, directus_service=object(),
        encryption_service=object(), user_vault_key_id="vault-key", all_mates_configs=[],
        discovered_apps_metadata={}, cache_service=object()))
    assert result == (notice, False, False, [], None)
    persist.assert_awaited_once()
    assert persist.await_args.kwargs["content"] == notice
    assert charge.await_args.args[2] == 0
    assert publish.await_args.args[2]["is_final_chunk"] is True
    assert publish.await_args.args[2]["rejection_reason"] == "insufficient_credits"
    main.assert_not_called()
    report.assert_not_awaited()
    namespace = _worker_post_consume_decision()
    namespace.update(main_processor_debug_metadata=result[4], revoked_in_consumer=result[1],
        soft_limited_in_consumer=result[2], request_data=request, preprocessing_result=preprocessing,
        aggregated_final_response=result[0], task_id="task", user_vault_key_id="vault-key",
        cache_service_instance=object(), directus_service_instance=object(), encryption_service_instance=object(),
        skill_config_dict={}, _cleanup_on_task_failure=AsyncMock())
    decision = asyncio.run(namespace["decision"]())
    if orchestrated:
        assert decision["_celery_task_state"] == "FAILURE"
        assert decision["failure_reason"] == "insufficient_credits"
        assert decision["main_processing_output"] == notice
        assert decision["preprocessing_summary"] == {"can_proceed": False, "rejection_reason": "insufficient_credits"}
    else:
        assert decision == "continue-existing-worker-flow"


# contract-test: supporting surface=rest_api assertions=operational-monitoring.chat-failures.safe-delivery,app-skills.assistant.bounded-private-failure
def test_orchestrated_preprocessing_failure_reason_is_bounded():
    namespace = _worker_post_consume_decision()
    namespace.update(main_processor_debug_metadata=None, revoked_in_consumer=False, soft_limited_in_consumer=False,
        request_data=AskSkillRequest(chat_id="chat", message_id="turn", user_id="owner", user_id_hash="owner-hash",
            orchestration_id="orchestration", message_history=[]), task_id="task", user_vault_key_id="vault-key",
        cache_service_instance=object(), directus_service_instance=object(), encryption_service_instance=object(),
        skill_config_dict={}, _cleanup_on_task_failure=AsyncMock(),
        preprocessing_result=PreprocessingResult(can_proceed=False, rejection_reason="private provider diagnostic"),
        aggregated_final_response="The request could not be completed.")
    result = asyncio.run(namespace["decision"]())
    assert result["_celery_task_state"] == "FAILURE"
    assert result["failure_reason"] == "preprocessing_rejected"
    assert "private provider diagnostic" not in str(result)


# contract-test: supporting surface=rest_api assertions=chat-queued-followups.steering.safe-boundary,chats.completion.recovery-takeover,app-skills.assistant.bounded-private-failure
@pytest.mark.parametrize("ownership", ["owned-empty", "owned-follower", "newer-owner"])
def test_rejected_orchestration_reuses_fenced_failure_cleanup_before_return(monkeypatch, ownership):
    from backend.apps.ai.tasks import async_skill_continuation
    from backend.apps.ai.processing import queued_steering
    request = AskSkillRequest(chat_id="chat", message_id="turn", user_id="owner", user_id_hash="owner-hash",
        orchestration_id="orchestration", recovery_task_id="task", message_history=[])
    marker = ["newer-task" if ownership == "newer-owner" else "task"]
    lease = {"messages": [{"recovery_task_id": "follower-task"}]} if ownership == "owned-follower" else None
    async def clear_owned(chat_id, task_id):
        if marker[0] != task_id:
            return False
        marker[0] = None
        return True
    async def finish_empty(chat_id, task_id):
        assert lease is None
        return 1 if await clear_owned(chat_id, task_id) else 2
    cache = SimpleNamespace(get_active_ai_task=AsyncMock(side_effect=lambda _: marker[0]),
        lease_queued_message_prefix=AsyncMock(return_value=lease),
        complete_active_ai_task_if_queue_empty=AsyncMock(side_effect=finish_empty),
        clear_active_ai_task_if_matches=AsyncMock(side_effect=clear_owned), publish_event=AsyncMock())
    async def start_follower(**kwargs):
        assert kwargs["prior_task_id"] == "task" and marker[0] == "task"
        assert kwargs["assistant_response"] == ""
        marker[0] = "follower-task"
    follower = AsyncMock(side_effect=start_follower)
    monkeypatch.setattr(ask_skill_task, "_start_recovery_queued_follower", follower)
    monkeypatch.setattr(ask_skill_task, "_pause_consumed_steers_after_failure", AsyncMock())
    monkeypatch.setattr(queued_steering, "reconcile_queued_revision_quarantine", AsyncMock(return_value=True))
    monkeypatch.setattr(ask_skill_task, "_cleanup_processing_embeds_on_task_failure", AsyncMock(return_value=0))
    deferred = AsyncMock()
    monkeypatch.setattr(async_skill_continuation, "dispatch_deferred_async_skill_continuations", deferred)
    child_failure = AsyncMock()
    monkeypatch.setattr(ask_skill_task, "_mark_sub_chat_terminal_failure", child_failure)
    namespace = _worker_post_consume_decision()
    namespace.update(main_processor_debug_metadata=None, revoked_in_consumer=False, soft_limited_in_consumer=False,
        request_data=request, task_id="task", preprocessing_result=PreprocessingResult(can_proceed=False,
            rejection_reason="insufficient_credits"), aggregated_final_response="Original sealed credit notice.",
        user_vault_key_id="vault-key", cache_service_instance=cache, directus_service_instance=object(),
        encryption_service_instance=object(), skill_config_dict={})
    result = asyncio.run(namespace["decision"]())
    assert result["_celery_task_state"] == "FAILURE"
    assert result["main_processing_output"] == "Original sealed credit notice."
    child_failure.assert_not_awaited()  # The existing wrapper owns this callback exactly once.
    assert all(call.args[1]["event_for_client"] == "ai_typing_ended" for call in cache.publish_event.await_args_list)
    if ownership == "owned-empty":
        assert marker[0] is None
        cache.complete_active_ai_task_if_queue_empty.assert_awaited_once_with("chat", "task")
        cache.clear_active_ai_task_if_matches.assert_not_awaited()
        deferred.assert_awaited_once()
        follower.assert_not_awaited()
    elif ownership == "owned-follower":
        assert marker[0] == "follower-task"
        follower.assert_awaited_once()
        cache.clear_active_ai_task_if_matches.assert_not_awaited()
        deferred.assert_not_awaited()
    else:
        assert marker[0] == "newer-task"
        cache.lease_queued_message_prefix.assert_not_awaited()
        cache.clear_active_ai_task_if_matches.assert_awaited_once_with("chat", "task")
        follower.assert_not_awaited()
        deferred.assert_not_awaited()
