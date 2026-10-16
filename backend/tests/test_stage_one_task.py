"""Stage-one broker handoff keeps the signed main invocation and task identity."""
# contract-test-file: infrastructure
from builtins import ExceptionGroup
from unittest.mock import AsyncMock, Mock
import asyncio
import pytest

from backend.apps.ai.tasks import stage_one_task
from backend.apps.ai.tasks import ask_skill_task


def test_grouped_routing_failure_logs_only_bounded_signature_and_dispatches_main(monkeypatch):
    private = "PRIVATE routing text and owner identifier"
    failures = [RuntimeError(private), ValueError(private)]
    grouped = ExceptionGroup(private, failures)
    monkeypatch.setattr(stage_one_task, "route_stage_one", AsyncMock(side_effect=grouped))
    dispatch = Mock()
    warning = Mock()
    monkeypatch.setattr(ask_skill_task.process_ai_skill_ask_task, "apply_async", dispatch)
    monkeypatch.setattr(stage_one_task.logger, "warning", warning)
    task = stage_one_task.process_ai_stage_one_task
    task.push_request(id="main:routing", retries=0, headers={})
    try:
        result = task.run({"user_id": "owner", "recovery_task_id": "main",
                           "recovery_preflight_id": "preflight"}, {}, "main")
    finally:
        task.pop_request()
    assert result == {"status": "main_dispatched", "stage_one_reusable": False}
    assert dispatch.call_args.kwargs["headers"] == {}
    warning.assert_called_once()
    message = warning.call_args.args[0] % warning.call_args.args[1:]
    assert "RuntimeError" in message and "ValueError" in message
    assert private not in message and "ExceptionGroup" not in message


def test_routing_failure_signature_bounds_nested_and_non_group_exceptions():
    private = "PRIVATE exception text"
    try:
        raise RuntimeError(private)
    except RuntimeError as error:
        types, frames = stage_one_task._routing_failure_signature(error)
    assert types == ("RuntimeError",)
    assert 1 <= len(frames) <= 6
    assert all(frame.startswith("backend/") and ":" in frame for frame in frames)
    assert all(private not in frame for frame in frames)

    class PrivateException(Exception):
        pass

    nested: Exception = PrivateException(private)
    for _ in range(12):
        nested = ExceptionGroup(private, [nested])
    group = ExceptionGroup(private, [nested, *(RuntimeError(private) for _ in range(100))])
    types, frames = stage_one_task._routing_failure_signature(group)
    assert len(types) <= 8 and len(frames) <= 6
    assert set(types) <= {"RuntimeError", "OtherException"}
    assert private not in repr((types, frames))


def test_routing_diagnostic_failure_does_not_change_main_fallback(monkeypatch):
    monkeypatch.setattr(stage_one_task, "route_stage_one", AsyncMock(side_effect=RuntimeError("PRIVATE")))
    monkeypatch.setattr(stage_one_task, "_routing_failure_signature", Mock(side_effect=RuntimeError("PRIVATE")))
    dispatch = Mock()
    warning = Mock()
    monkeypatch.setattr(ask_skill_task.process_ai_skill_ask_task, "apply_async", dispatch)
    monkeypatch.setattr(stage_one_task.logger, "warning", warning)
    task = stage_one_task.process_ai_stage_one_task
    task.push_request(id="main:routing", retries=0, headers={})
    try:
        result = task.run({"user_id": "owner", "recovery_task_id": "main",
                           "recovery_preflight_id": "preflight"}, {}, "main")
    finally:
        task.pop_request()
    assert result["status"] == "main_dispatched"
    dispatch.assert_called_once()
    warning.assert_called_once()
    message = warning.call_args.args[0] % warning.call_args.args[1:]
    assert "PRIVATE" not in message
    assert "diagnostic_failed" in message


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


def test_legacy_handoff_does_not_prewrite_active_summary(monkeypatch):
    route = AsyncMock(return_value="sealed-ref")
    monkeypatch.setattr(stage_one_task, "route_stage_one", route)
    monkeypatch.setattr(ask_skill_task.process_ai_skill_ask_task, "apply_async", Mock())
    task = stage_one_task.process_ai_stage_one_task
    task.push_request(id="main:routing", retries=0, headers={})
    try:
        task.run({"user_id": "owner", "recovery_task_id": "main",
                  "recovery_preflight_id": "preflight"}, {}, "main",
                 legacy_batch_proof={"legacy": True})
    finally:
        task.pop_request()
    assert route.await_args.kwargs["allow_early_summary"] is False


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
@pytest.mark.parametrize("outcome", ["published", "stale", "stale_before_handoff", "failed_before_publish"])
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
        current_user_content="Hello", message_history=[
            {"role": "user", "message_id": "turn", "content": "Hello", "created_at": 1},
        ],
        admission_context={"scope_complete": True, "context_revision": "server-admission-v1",
            "active_project_id": None, "active_project_activation_id": None,
            "active_focus_id": None, "accepted_plan_ref": None,
            "explicit_related_task_ids": []},
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
    private_descriptor = {"same_turn_request": {"private": "internal checkpoint"}}
    monkeypatch.setattr(recent_work_summary_client, "restore_private_context_payload",
                        AsyncMock(return_value=private_descriptor))
    monkeypatch.setattr(recent_work_summary_client, "bind_restored_context_turn", lambda *_args: None)
    context_ready = asyncio.Event()

    async def load_context(**_kwargs):
        context_ready.set()

    monkeypatch.setattr(client_context_continuation, "await_client_context_phase", load_context)
    current = AsyncMock(side_effect=[True, outcome != "stale", outcome != "stale_before_handoff"])
    admitted = AsyncMock(return_value=True)
    monkeypatch.setattr(stage_one_task, "routing_turn_is_current", current)
    monkeypatch.setattr(stage_one_task, "routing_admission_is_current", admitted)
    handoff = AsyncMock(return_value="sealed-routing-ref")
    monkeypatch.setattr(stage_one_task, "store_stage_one", handoff)
    active_started = asyncio.Event()
    active_cancelled = asyncio.Event()

    async def active(_request, task_id, _cache, _encryption, _overrides):
        assert task_id == "task" and context_ready.is_set() and current.await_count >= 1
        assert admitted.await_count >= 1
        active_started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            active_cancelled.set()
            raise

    monkeypatch.setattr(stage_one_task, "_publish_early_active_summary", active)

    async def decision(**kwargs):
        await asyncio.wait_for(asyncio.gather(key_started.wait(), active_started.wait()), timeout=1)
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
    if outcome in {"stale", "failed_before_publish"}:
        with pytest.raises(RuntimeError, match=(
            "no longer current" if outcome == "stale" else "Jev unavailable"
        )):
            await stage_one_task.route_stage_one(envelope, {}, "task")
        cache.publish_event.assert_not_awaited()
        handoff.assert_not_awaited()
    elif outcome == "stale_before_handoff":
        assert await stage_one_task.route_stage_one(envelope, {}, "task") is None
        cache.publish_event.assert_awaited_once()
        handoff.assert_not_awaited()
    else:
        assert await stage_one_task.route_stage_one(envelope, {}, "task") == "sealed-routing-ref"
        cache.publish_event.assert_awaited_once()
        assert cache.publish_event.await_args.args[1]["encrypted_chat_key"] == "sealed-chat-key"
        handoff.assert_awaited_once()
        assert handoff.await_args.kwargs["typing_started"] is True
    assert current.await_count == (1 if outcome == "failed_before_publish"
                                   else 2 if outcome == "stale" else 3)
    assert key_cancelled.is_set() is (outcome == "failed_before_publish")
    assert active_started.is_set() and active_cancelled.is_set()
    directus.get_items.assert_not_awaited()
    assert not hasattr(request, "same_turn_request")


@pytest.mark.parametrize("change", [
    {"chat_has_title": True}, {"team_id": "team"}, {"current_chat_summary": "prior"},
    {"current_project": {"id": "project"}}, {"is_sub_chat": True},
    {"current_user_content": "@tool:search"}, {"client_context_pending": True},
    {"admission_context": None},
    {"admission_context": {"scope_complete": False, "context_revision": "server-admission-v1"}},
    {"admission_context": {"scope_complete": True, "context_revision": "supplied-client"}},
])
def test_early_active_summary_requires_one_message_and_complete_personal_scope(change):
    from types import SimpleNamespace

    fields = {"chat_has_title": False, "message_id": "turn", "current_user_content": "Hello",
              "message_history": [SimpleNamespace(role="user", message_id="turn", content="Hello")],
              "admission_context": {"scope_complete": True,
                  "context_revision": "server-admission-v1", "active_project_id": None,
                  "active_project_activation_id": None, "active_focus_id": None,
                  "accepted_plan_ref": None, "explicit_related_task_ids": []}}
    assert stage_one_task._eligible_for_early_active_summary(SimpleNamespace(**fields), None)
    assert not stage_one_task._eligible_for_early_active_summary(
        SimpleNamespace(**{**fields, **change}), None)


@pytest.mark.asyncio
async def test_early_active_summary_timeout_is_optional_and_cancels_ipc(monkeypatch):
    from backend.apps.ai.skills.ask_skill import AskSkillRequest
    from backend.shared.python_utils import recent_work_summary_client

    cancelled = asyncio.Event()

    async def hanging(_request, _task_id):
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(recent_work_summary_client, "mark_response_summary_active", hanging)
    monkeypatch.setattr(stage_one_task, "EARLY_ACTIVE_SUMMARY_BUDGET_SECONDS", 0.01)
    request = AskSkillRequest(
        chat_id="chat", message_id="turn", user_id="owner", user_id_hash="hash",
        current_user_content="Hello", message_history=[
            {"role": "user", "message_id": "turn", "content": "Hello", "created_at": 1},
        ], admission_context={"scope_complete": True, "context_revision": "server-admission-v1",
            "active_project_id": None, "active_project_activation_id": None,
            "active_focus_id": None, "accepted_plan_ref": None,
            "explicit_related_task_ids": []},
    )
    await stage_one_task._publish_early_active_summary(request, "task", None, None, None)
    assert cancelled.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("private_details", [False, True])
async def test_early_summary_clone_reads_real_details_without_consuming_main_phase(
    monkeypatch, private_details,
):
    import uuid
    from backend.apps.ai.skills.ask_skill import AskSkillRequest
    from backend.core.api.app.services import client_context_continuation as context
    from backend.shared.python_utils import recent_work_summary_client
    from backend.tests.test_client_context_continuation import Redis, Vault

    redis, vault = Redis(), Vault()

    class Cache:
        @property
        async def client(self):
            return redis

        async def get_user_vault_key_id(self, owner):
            return "key:" + owner

    cache = Cache()
    scope = {"user_id": "owner", "chat_id": "chat", "turn_id": "turn",
             "message_id": "turn", "request_id": str(uuid.uuid4()), "team_id": None}
    reference = await context.register_client_context(
        cache_service=cache, encryption_service=vault, device_fingerprint_hash="device", **scope,
    )
    details = ({"custom_rule_documents": [{"id": "rule", "source": "project",
                "project_id": "project", "document": "private body", "item_revision": "v1"}]}
               if private_details else {})
    for phase, payload in (("routing", {}), ("details", details)):
        assert await context.receive_client_context(
            cache_service=cache, encryption_service=vault, device_fingerprint_hash="device",
            phase=phase, context=payload, **scope,
        ) == "accepted"
    request = AskSkillRequest(
        chat_id="chat", message_id="turn", user_id="owner", user_id_hash="hash",
        recovery_turn_id="turn", current_user_content="Hello",
        message_history=[{"role": "user", "message_id": "turn", "content": "Hello",
                          "created_at": 1}],
        client_context_pending=True, client_context_request_id=scope["request_id"],
        client_context_binding_ref=reference, client_context_turn_id="turn",
        admission_context={"scope_complete": False, "context_revision": "server-admission-v1",
            "active_project_id": None, "active_project_activation_id": None,
            "active_focus_id": None, "accepted_plan_ref": None,
            "explicit_related_task_ids": []},
    )
    await context.await_client_context_phase(
        cache_service=cache, request=request, phase="routing", encryption_service=vault,
    )
    assert stage_one_task._eligible_for_early_active_summary(
        request, None, allow_pending_details=True,
    )
    initial_keys = set(redis.values)
    mark = AsyncMock(return_value=True)
    monkeypatch.setattr(recent_work_summary_client, "mark_response_summary_active", mark)
    await stage_one_task._publish_early_active_summary(request, "task", cache, vault, None)
    assert mark.await_count == (0 if private_details else 1)
    if not private_details:
        clone = mark.await_args.args[0]
        assert clone is not request and clone.client_context_pending is False
        assert clone.admission_context["scope_complete"] is True
    assert request.client_context_pending is True
    assert request.admission_context["scope_complete"] is False
    assert set(redis.values) == initial_keys
    await context.await_client_context_phase(
        cache_service=cache, request=request, phase="details", encryption_service=vault,
    )
    assert request.client_context_pending is False
    assert request.admission_context["scope_complete"] is (not private_details)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["slow", "unavailable"])
async def test_early_summary_details_failure_is_optional_and_leaves_original_pending(
    monkeypatch, failure,
):
    from backend.apps.ai.skills.ask_skill import AskSkillRequest
    from backend.core.api.app.services import client_context_continuation as context
    from backend.shared.python_utils import recent_work_summary_client

    request = AskSkillRequest(
        chat_id="chat", message_id="turn", user_id="owner", user_id_hash="hash",
        current_user_content="Hello", message_history=[
            {"role": "user", "message_id": "turn", "content": "Hello", "created_at": 1},
        ], client_context_pending=True, admission_context={
            "scope_complete": False, "context_revision": "server-admission-v1",
            "active_project_id": None, "active_project_activation_id": None,
            "active_focus_id": None, "accepted_plan_ref": None,
            "explicit_related_task_ids": [],
        },
    )
    cancelled = asyncio.Event()

    async def read_details(**_kwargs):
        if failure == "unavailable":
            raise RuntimeError("details unavailable")
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    mark = AsyncMock()
    monkeypatch.setattr(context, "await_client_context_phase", read_details)
    monkeypatch.setattr(recent_work_summary_client, "mark_response_summary_active", mark)
    monkeypatch.setattr(stage_one_task, "EARLY_ACTIVE_SUMMARY_BUDGET_SECONDS", 0.01)
    await stage_one_task._publish_early_active_summary(request, "task", object(), object(), None)
    assert cancelled.is_set() is (failure == "slow")
    mark.assert_not_awaited()
    assert request.client_context_pending is True
    assert request.admission_context["scope_complete"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("turn_ok, admission_ok", [(True, True), (False, True), (True, False)])
async def test_routing_authority_joins_fresh_checks_before_result(monkeypatch, turn_ok, admission_ok):
    entered = [asyncio.Event(), asyncio.Event()]
    release = asyncio.Event()
    calls = []

    async def turn(*args):
        calls.append("turn")
        entered[0].set()
        await release.wait()
        return turn_ok

    async def admission(*args):
        calls.append("admission")
        entered[1].set()
        await release.wait()
        return admission_ok

    monkeypatch.setattr(stage_one_task, "routing_turn_is_current", turn)
    monkeypatch.setattr(stage_one_task, "routing_admission_is_current", admission)
    check = asyncio.create_task(stage_one_task._routing_authority_is_current(
        Mock(), Mock(), Mock(), "task"))
    await asyncio.gather(*(event.wait() for event in entered))
    assert not check.done()
    release.set()
    assert await check is (turn_ok and admission_ok)
    assert calls == ["turn", "admission"]


@pytest.mark.asyncio
async def test_routing_authority_cancels_peer_on_error(monkeypatch):
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def waiting(*args):
        entered.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    async def failing(*args):
        await entered.wait()
        raise RuntimeError("authority unavailable")

    monkeypatch.setattr(stage_one_task, "routing_turn_is_current", waiting)
    monkeypatch.setattr(stage_one_task, "routing_admission_is_current", failing)
    with pytest.raises(RuntimeError, match="authority unavailable"):
        await stage_one_task._routing_authority_is_current(Mock(), Mock(), Mock(), "task")
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_routing_authority_drains_checks_on_caller_cancel(monkeypatch):
    entered = [asyncio.Event(), asyncio.Event()]
    cancelled = [asyncio.Event(), asyncio.Event()]

    def checker(index):
        async def wait(*args):
            entered[index].set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                cancelled[index].set()
                raise
        return wait

    monkeypatch.setattr(stage_one_task, "routing_turn_is_current", checker(0))
    monkeypatch.setattr(stage_one_task, "routing_admission_is_current", checker(1))
    check = asyncio.create_task(stage_one_task._routing_authority_is_current(
        Mock(), Mock(), Mock(), "task"))
    await asyncio.gather(*(event.wait() for event in entered))
    check.cancel()
    with pytest.raises(asyncio.CancelledError):
        await check
    assert all(event.is_set() for event in cancelled)
