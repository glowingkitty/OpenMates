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


# contract-test: supporting surface=cli assertions=chat-processing-feedback.selected-mate-identity
@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["published", "stale", "failed_before_publish"])
async def test_stage_one_prefetches_chat_key_and_rechecks_authority_before_mate(monkeypatch, outcome):
    import asyncio
    from types import SimpleNamespace
    from backend.apps.ai.skills import ask_skill
    from backend.core.api.app.services import client_context_continuation, directus as directus_module
    from backend.core.api.app.utils import encryption as encryption_module, secrets_manager as secrets_module
    from backend.shared.python_utils import recent_work_summary_client
    from backend.apps.ai.processing import preprocessor

    request = ask_skill.AskSkillRequest(
        chat_id="chat", message_id="turn", user_id="owner", user_id_hash="owner-hash",
        recovery_task_id="task", recovery_preflight_id="preflight",
        current_user_content="Hello", message_history=[],
    )
    config = SimpleNamespace(model_dump=lambda **_kwargs: {})
    monkeypatch.setattr(ask_skill.AskSkillRequest, "model_validate", lambda _value: request)
    monkeypatch.setattr(ask_skill.AskSkillDefaultConfig, "model_validate", lambda _value: config)
    cache = SimpleNamespace(
        get_base_instructions=AsyncMock(return_value={"preprocess_request_tool": {}}),
        get_discovered_apps_metadata=AsyncMock(return_value={"ai": object()}),
        get_chat_list_item_data=AsyncMock(), publish_event=AsyncMock(),
    )
    key_started = asyncio.Event()
    release_key = asyncio.Event()
    key_cancelled = asyncio.Event()

    async def chat_key(*_args):
        key_started.set()
        try:
            await release_key.wait()
        except asyncio.CancelledError:
            key_cancelled.set()
            raise
        return SimpleNamespace(encrypted_chat_key="sealed-chat-key")

    cache.get_chat_list_item_data.side_effect = chat_key
    directus = SimpleNamespace(get_items=AsyncMock(), close=AsyncMock())
    monkeypatch.setattr(stage_one_task.celery_config, "get_worker_cache_service", AsyncMock(return_value=cache))
    monkeypatch.setattr(secrets_module, "SecretsManager", lambda: SimpleNamespace(initialize=AsyncMock()))
    monkeypatch.setattr(encryption_module, "EncryptionService", lambda **_kwargs: object())
    monkeypatch.setattr(directus_module, "DirectusService", lambda **_kwargs: directus)
    monkeypatch.setattr(recent_work_summary_client, "restore_private_context_payload", AsyncMock(return_value={}))
    monkeypatch.setattr(recent_work_summary_client, "bind_restored_context_turn", lambda *_args: None)
    monkeypatch.setattr(client_context_continuation, "await_client_context_phase", AsyncMock())
    current = AsyncMock(side_effect=[True, outcome != "stale"])
    admitted = AsyncMock(return_value=True)
    monkeypatch.setattr(stage_one_task, "routing_turn_is_current", current)
    monkeypatch.setattr(stage_one_task, "routing_admission_is_current", admitted)
    handoff = AsyncMock(return_value="sealed-routing-ref")
    monkeypatch.setattr(stage_one_task, "store_stage_one", handoff)

    async def decision(**kwargs):
        await asyncio.wait_for(key_started.wait(), timeout=1)
        if outcome == "failed_before_publish":
            raise RuntimeError("Jev unavailable")
        release_key.set()
        await kwargs["on_early_routing"]({
            "category": "general_knowledge", "mate_id": "mate-general",
            "model_id": "google/answer", "model_name": "Answer",
        })
        request._stage_one_routing = {"early_decisions": {"task_area": "general"}}

    monkeypatch.setattr(preprocessor, "handle_preprocessing", decision)
    envelope = request.model_dump(mode="json")
    if outcome != "published":
        with pytest.raises(RuntimeError, match=(
            "no longer current" if outcome == "stale" else "Jev unavailable"
        )):
            await stage_one_task.route_stage_one(envelope, {}, "task")
        cache.publish_event.assert_not_awaited()
        handoff.assert_not_awaited()
    else:
        assert await stage_one_task.route_stage_one(envelope, {}, "task") == "sealed-routing-ref"
        cache.publish_event.assert_awaited_once()
        assert cache.publish_event.await_args.args[1]["encrypted_chat_key"] == "sealed-chat-key"
        handoff.assert_awaited_once()
        assert handoff.await_args.kwargs["typing_started"] is True
    assert current.await_count == (1 if outcome == "failed_before_publish" else 2)
    assert key_cancelled.is_set() is (outcome == "failed_before_publish")
    directus.get_items.assert_not_awaited()
