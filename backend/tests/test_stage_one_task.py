"""Stage-one broker handoff keeps the signed main invocation and task identity."""
# contract-test-file: infrastructure
from unittest.mock import AsyncMock, Mock
import pytest

from backend.apps.ai.tasks import stage_one_task
from backend.apps.ai.tasks import ask_skill_task


@pytest.mark.parametrize("routing_failure", [False, True])
def test_routing_finishes_before_main_dispatch_and_never_reserializes_private_context(monkeypatch, routing_failure):
    envelope = {"user_id": "owner", "recovery_task_id": "main-id", "recovery_preflight_id": "preflight",
                "current_user_content": "Hello", "agentic_context_ref": "private-opaque-ref"}
    route = AsyncMock(side_effect=RuntimeError("unavailable") if routing_failure else None,
                      return_value="encrypted-routing-ref")
    dispatch = Mock()
    monkeypatch.setattr(stage_one_task, "route_stage_one", route)
    monkeypatch.setattr(ask_skill_task.process_ai_skill_ask_task, "apply_async", dispatch)
    task = stage_one_task.process_ai_stage_one_task
    task.push_request(id="main-id:routing", retries=0, headers={"x-openmates-stage-one-ref": "forged"})
    try:
        result = task.run(envelope, {"default": "model"}, "main-id")
    finally:
        task.pop_request()
    route.assert_awaited_once()
    assert result["status"] == "main_dispatched"
    options = dispatch.call_args.kwargs
    assert options["task_id"] == "main-id" and options["queue"] == "app_ai"
    assert options["kwargs"] == {"request_data_dict": envelope, "skill_config_dict": {"default": "model"}}
    assert options["kwargs"]["request_data_dict"] is envelope
    assert options["headers"] == ({} if routing_failure else {"x-openmates-stage-one-ref": "encrypted-routing-ref"})


def test_publication_retry_reuses_snapshot_without_paid_routing(monkeypatch):
    route = AsyncMock()
    dispatch = Mock()
    monkeypatch.setattr(stage_one_task, "route_stage_one", route)
    monkeypatch.setattr(ask_skill_task.process_ai_skill_ask_task, "apply_async", dispatch)
    task = stage_one_task.process_ai_stage_one_task
    task.push_request(id="main:routing", retries=1, headers={})
    try:
        task.run({"user_id": "owner"}, {}, "main", routing_snapshot_ref="sealed-ref")
    finally:
        task.pop_request()
    route.assert_not_awaited()
    assert dispatch.call_args.kwargs["headers"] == {"x-openmates-stage-one-ref": "sealed-ref"}


@pytest.mark.parametrize("field", ["is_incognito", "is_external", "is_anonymous", "is_sub_chat", "is_focus_mode_continuation"])
def test_special_authority_paths_stay_on_main(field):
    request = {"user_id": "owner", "recovery_task_id": "task", "recovery_preflight_id": "preflight"}
    assert stage_one_task.eligible_for_routing_lane(request)
    assert not stage_one_task.eligible_for_routing_lane({**request, field: True})
    assert not stage_one_task.eligible_for_routing_lane({**request,
        "message_history": [{"role": "user", "content": "<<<TEST_LIVE_MOCK:fixture>>>"}]})


def test_concurrent_original_deliveries_acquire_one_paid_routing_slot(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Lock
    from celery.exceptions import Ignore
    from backend.core.api.app.tasks import base_task
    task = stage_one_task.process_ai_stage_one_task
    assert isinstance(task, base_task.DedupedTask)
    ready, mutex, acquired = Barrier(2), Lock(), set()
    def acquire(identifier, **kwargs):
        ready.wait(timeout=5)
        with mutex:
            if identifier in acquired:
                return False
            acquired.add(identifier)
            return True
    monkeypatch.setattr(base_task, "acquire_celery_task_dedup_lock", acquire)
    body = Mock(return_value="routed")
    monkeypatch.setattr(task, "run", body)
    def deliver():
        task.push_request(id="same-main:routing", retries=0)
        try:
            return task({}, {}, "same-main")
        except Ignore:
            return "duplicate"
        finally:
            task.pop_request()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: deliver(), range(2)))
    assert sorted(results) == ["duplicate", "routed"]
    body.assert_called_once()


def test_publication_retry_retains_original_lock_and_reference(monkeypatch):
    from celery.exceptions import Ignore, Retry
    from backend.core.api.app.tasks import base_task
    task = stage_one_task.process_ai_stage_one_task
    acquired = set()
    def acquire(identifier, **kwargs):
        if identifier in acquired:
            return False
        acquired.add(identifier)
        return True
    release = Mock(side_effect=lambda identifier, **kwargs: acquired.discard(identifier))
    monkeypatch.setattr(base_task, "acquire_celery_task_dedup_lock", acquire)
    monkeypatch.setattr(base_task, "release_celery_task_dedup_lock", release)
    route = AsyncMock(return_value="sealed-ref")
    monkeypatch.setattr(stage_one_task, "route_stage_one", route)
    dispatch = Mock(side_effect=[RuntimeError("broker unavailable"), None])
    monkeypatch.setattr(ask_skill_task.process_ai_skill_ask_task, "apply_async", dispatch)
    retries = []
    def retry(**kwargs):
        retries.append(kwargs)
        raise Retry()
    monkeypatch.setattr(task, "retry", retry)
    envelope = {"user_id": "owner", "recovery_task_id": "main", "recovery_preflight_id": "preflight"}
    task.push_request(id="main:routing", retries=0, headers={})
    try:
        with pytest.raises(Retry):
            task(envelope, {}, "main")
        task.on_retry(None, "main:routing", (), {}, None)
        with pytest.raises(Ignore):
            task(envelope, {}, "main")
    finally:
        task.pop_request()
    release.assert_not_called()
    assert retries[0]["kwargs"]["routing_snapshot_ref"] == "sealed-ref"
    task.push_request(id="main:routing", retries=1, headers={})
    try:
        task(**retries[0]["kwargs"])
    finally:
        task.pop_request()
    route.assert_awaited_once()
    assert dispatch.call_count == 2
    assert all(call.kwargs["task_id"] == "main" for call in dispatch.call_args_list)
    assert dispatch.call_args.kwargs["headers"]["x-openmates-stage-one-ref"] == "sealed-ref"


def test_main_snapshot_load_precedes_recovery_claim():
    import ast
    from pathlib import Path
    source = Path(ask_skill_task.__file__).read_text()
    function = next(node for node in ast.parse(source).body
                    if isinstance(node, ast.AsyncFunctionDef) and node.name == "_async_process_ai_skill_ask_task")
    load = next(node for node in ast.walk(function) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name) and node.func.id == "load_stage_one")
    claim = next(node for node in ast.walk(function) if isinstance(node, ast.Call)
                 and any(isinstance(arg, ast.Constant) and arg.value == "claim_inference" for arg in node.args))
    assert load.lineno < claim.lineno
