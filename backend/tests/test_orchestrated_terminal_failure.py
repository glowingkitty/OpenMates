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


# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,operational-monitoring.chat-failures.email-trigger,focus-modes.full-instruction
def test_budget_marker_fails_child_and_worker_without_paid_retry(monkeypatch):
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
        yield main_processing_failure("orchestration_budget_limit")

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
    assert result[4]["main_processing_failure_reason"] == "orchestration_budget_limit"
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
    assert failed_result["failure_reason"] == "orchestration_budget_limit"
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
