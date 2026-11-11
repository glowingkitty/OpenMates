"""Assistant-inferred Project creation: decision gating, payload contract, completion."""
import sys
import time
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.shared.providers.typesafe.models import ChoiceAnswer, DecisionResponse

pytest_plugins = ["backend.tests.test_async_skill_continuation"]

PROJECT = "11111111-1111-4111-8111-111111111111"
FOCUS = "22222222-2222-4222-8222-222222222222"
REQUEST = "project-create-request-33333333-3333-4333-8333-333333333333"
EARLY = {"task_area": "code", "public_decisions": {"harmful_or_illegal": 0.0, "misuse_risk": 0}}


def _request(**overrides):
    values = dict(
        user_id="owner", chat_id="chat", message_id="turn", team_id=None,
        client_capabilities=["project_file_jobs", "project_create_requests"],
        current_user_content="build me a simple recipe web app",
        is_incognito=False, is_external=False, is_sub_chat=False,
        is_async_skill_continuation=False, is_focus_mode_continuation=False,
        is_app_settings_memories_continuation=False, is_connected_account_permission_continuation=False,
        is_sub_chat_continuation=False, active_project_focus=None, current_project=None,
        project_routing_focus_id=None, project_access_declined=False, user_preferences={},
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _answer(choice, confidence=0.9):
    return DecisionResponse(model="jev", answers={"project_creation": ChoiceAnswer(
        type="choice", choice=choice, confidence=confidence, probabilities={choice: confidence})})


class _Cache:
    def __init__(self, values=None):
        self.values = dict(values or {})

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ttl=None):
        self.values[key] = value
        return True

    async def delete(self, key):
        self.values.pop(key, None)
        return True


async def _decide(monkeypatch, request, choice="web_app", confidence=0.9, cache=None, early=EARLY):
    from backend.apps.ai.processing import project_creation_routing as routing
    jev = AsyncMock(return_value=_answer(choice, confidence))
    monkeypatch.setattr(routing, "evaluate_jev_decisions", jev)
    namer = AsyncMock(return_value="Recipe Manager")
    proposal = await routing.decide_project_creation(
        request_data=request, user_overrides=None, cache_service=cache or _Cache(), secrets_manager=None,
        model_id="jev", message_history=[{"role": "user", "content": request.current_user_content}],
        telemetry_task_id="t", log_prefix="test", early_decisions=early,
        harm_threshold=7.0, misuse_threshold=7.0, name_proposer=namer,
    )
    return proposal, jev, namer


# contract-test: supporting surface=rest_api assertions=projects.creation.assistant-inferred
@pytest.mark.asyncio
async def test_recipe_web_app_creates_project_outcome(monkeypatch):
    proposal, jev, namer = await _decide(monkeypatch, _request())
    assert proposal is not None
    assert proposal.as_dict() == {"kind": "web_app", "subfolder": "web-app", "proposed_name": "Recipe Manager",
                                  "confidence": 0.9, "outcome": "create_project"}
    jev.assert_awaited_once()
    namer.assert_awaited_once()


# contract-test: supporting surface=rest_api assertions=projects.creation.assistant-inferred
@pytest.mark.asyncio
@pytest.mark.parametrize("choice,confidence", [("single_file", 0.95), ("none", 0.9), ("web_app", 0.5)])
async def test_single_script_or_uncertain_creates_no_project(monkeypatch, choice, confidence):
    request = _request(current_user_content="write me a Python script that renames my photos by date")
    proposal, jev, namer = await _decide(monkeypatch, request, choice, confidence)
    assert proposal is None
    jev.assert_awaited_once()
    namer.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=projects.creation.assistant-inferred
@pytest.mark.asyncio
@pytest.mark.parametrize("overrides", [
    {"client_capabilities": ["project_file_jobs"]},
    {"active_project_focus": {"project_id": PROJECT}},
    {"current_project": {"project_id": PROJECT}},
    {"project_routing_focus_id": f"project-{PROJECT}"},
    {"is_incognito": True},
    {"is_sub_chat": True},
    {"is_async_skill_continuation": True},
    {"project_access_declined": True},
    {"user_preferences": {"apps_enabled": False}},
    {"current_user_content": "build me a recipe web app, but don't touch any project files"},
])
# contract-test: supporting surface=rest_api assertions=projects.creation.assistant-inferred
async def test_gate_closed_runs_no_decision(monkeypatch, overrides):
    proposal, jev, _ = await _decide(monkeypatch, _request(**overrides))
    assert proposal is None
    jev.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=projects.creation.assistant-inferred
@pytest.mark.asyncio
@pytest.mark.parametrize("early", [
    None,
    {**EARLY, "task_area": "general"},
    {**EARLY, "public_decisions": {"harmful_or_illegal": 8.0, "misuse_risk": 0}},
])
async def test_stage_one_must_be_safe_code_work(monkeypatch, early):
    proposal, jev, _ = await _decide(monkeypatch, _request(), early=early)
    assert proposal is None
    jev.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=projects.creation.assistant-inferred
@pytest.mark.asyncio
@pytest.mark.parametrize("pending", ["focus", "create"])
async def test_pending_project_focus_or_creation_blocks_new_request(monkeypatch, pending):
    from backend.core.api.app.services.project_create_request_service import ProjectCreateRequestService
    from backend.core.api.app.services.project_focus_request_service import ProjectFocusRequestService
    key = (ProjectFocusRequestService.key("owner", "chat") if pending == "focus"
           else ProjectCreateRequestService.key("owner", "chat"))
    cache = _Cache({key: {"request_id": "r", "expires_at": time.time() + 60}})
    proposal, jev, _ = await _decide(monkeypatch, _request(), cache=cache)
    assert proposal is None
    jev.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=projects.creation.assistant-inferred
@pytest.mark.asyncio
async def test_unavailable_decision_or_name_keeps_todays_behaviour(monkeypatch):
    from backend.apps.ai.processing import project_creation_routing as routing
    from backend.apps.ai.processing.workspace_ask_planner import WorkspaceAskPlanningError
    from backend.shared.providers.typesafe.client import DecisionProviderUnavailable
    monkeypatch.setattr(routing, "evaluate_jev_decisions", AsyncMock(side_effect=DecisionProviderUnavailable("x")))
    common = dict(request_data=_request(), user_overrides=None, cache_service=_Cache(), secrets_manager=None,
                  model_id="jev", message_history=[], telemetry_task_id="t", log_prefix="test",
                  early_decisions=EARLY, harm_threshold=7.0, misuse_threshold=7.0)
    assert await routing.decide_project_creation(**common, name_proposer=AsyncMock(return_value="X")) is None
    monkeypatch.setattr(routing, "evaluate_jev_decisions", AsyncMock(return_value=_answer("web_app")))
    failing = AsyncMock(side_effect=WorkspaceAskPlanningError("no name"))
    assert await routing.decide_project_creation(**common, name_proposer=failing) is None


# contract-test: supporting surface=rest_api assertions=projects.creation.assistant-inferred
def test_create_action_contract_shape():
    from backend.core.api.app.services.project_create_request_service import (
        build_project_create_action, new_project_create_request_id, outbound_create_event,
    )
    request_id = new_project_create_request_id()
    action = build_project_create_action(request_id=request_id, name="  Recipe   Manager ", chat_id="chat",
                                         message_id="turn", team_id=None, origin="preprocessor",
                                         kind="web_app", created_at=1000)
    assert action == {
        "contract": "openmates.project_create_request", "version": 1, "request_id": request_id,
        "action": "create", "origin": "preprocessor", "chat_id": "chat", "message_id": "turn", "team_id": None,
        "name": "Recipe Manager", "description": "", "kind": "web_app", "subfolder": "web-app",
        "write_mode": "apply_and_show", "focus": {"activate": "immediate", "countdown_seconds": 0},
        "undo": {"available": True}, "created_at": 1000, "expires_at": 1600, "notification_queued": False,
    }
    event = {"chat_id": "chat", "request_id": request_id, "pending_client_action": action}
    assert outbound_create_event(event) == event
    assert outbound_create_event({**event, "chat_id": "other"}) is None
    assert outbound_create_event({**event, "request_id": "project-create-request-bad"}) is None
    skill = build_project_create_action(request_id=request_id, name="Notes", chat_id=None, message_id=None,
                                        team_id=None, origin="skill")
    assert skill["focus"] == {"activate": "none", "countdown_seconds": 0}
    assert skill["kind"] is None and skill["subfolder"] is None
    with pytest.raises(ValueError):
        build_project_create_action(request_id=request_id, name=" ", chat_id="c", message_id="m",
                                    team_id=None, origin="preprocessor", kind="web_app")


# contract-test: supporting surface=rest_api assertions=projects.creation.assistant-inferred
def test_completion_report_validation_and_model_message_has_no_name():
    from backend.core.api.app.services.project_create_request_service import (
        continuation_result, parse_project_create_result,
    )
    from backend.core.api.app.services.project_write_authorization_service import ProjectWriteAuthorizationError
    created = parse_project_create_result({"chat_id": "chat", "request_id": REQUEST, "status": "created",
                                           "project_id": PROJECT.upper(), "focus_id": FOCUS})
    assert created == {"chat_id": "chat", "request_id": REQUEST, "status": "created",
                       "project_id": PROJECT, "focus_id": FOCUS}
    assert parse_project_create_result({"chat_id": "chat", "request_id": REQUEST, "status": "failed",
                                        "error_code": "PROJECT_KEY_WRAP_FAILED"})["error_code"] == "PROJECT_KEY_WRAP_FAILED"
    for bad in ({"chat_id": "chat", "request_id": REQUEST, "status": "created", "project_id": "x", "focus_id": FOCUS},
                {"chat_id": "chat", "request_id": REQUEST, "status": "maybe"},
                {"chat_id": "chat", "request_id": "other", "status": "failed"}):
        with pytest.raises(ProjectWriteAuthorizationError):
            parse_project_create_result(bad)
    row = continuation_result({"subfolder": "web-app"}, created)
    assert row["access_granted"] is True and row["project_created"] is True and "web-app/" in row["message"]
    undone = continuation_result({"subfolder": "web-app"}, {"status": "undone"})
    assert undone["access_granted"] is False and undone["project_created"] is False


def _handler(monkeypatch, async_skill_continuation):
    tasks = ModuleType("backend.apps.ai.tasks")
    tasks.__path__ = []
    monkeypatch.setitem(sys.modules, "backend.apps.ai.tasks", tasks)
    monkeypatch.setitem(sys.modules, "backend.apps.ai.tasks.async_skill_continuation", async_skill_continuation)
    sys.modules.pop("backend.core.api.app.routes.handlers.websocket_handlers.project_create_result_handler", None)
    from backend.core.api.app.routes.handlers.websocket_handlers import project_create_result_handler as handler
    return handler


async def _report(monkeypatch, async_skill_continuation, payload, *, focus_project=PROJECT, write_mode="apply_and_show",
                  claim=True, created_at=None, publish=None, on_dispatch=None):
    from backend.core.api.app.services.project_create_request_service import ProjectCreateRequestService
    handler = _handler(monkeypatch, async_skill_continuation)
    now = int(time.time())
    pending = {"request_id": REQUEST, "user_id": "owner", "chat_id": "chat", "message_id": "turn",
               "team_id": None, "kind": "web_app", "subfolder": "web-app", "name": "Recipe Manager",
               "created_at": now, "expires_at": now + 600}
    key = ProjectCreateRequestService.key("owner", "chat")
    redis = SimpleNamespace(set=AsyncMock(return_value=claim), publish=publish or AsyncMock())

    async def client():
        return redis

    class _RedisCache(_Cache):
        # Awaited once per use, like CacheService.client.
        client = property(lambda _self: client())

    cache = _RedisCache({key: pending, key + ":" + REQUEST: pending,
                         async_skill_continuation.async_skill_latest_user_turn_key("owner", "chat"): "turn"})
    from backend.core.api.app.services.project_write_authorization_service import focus_id_hash
    auth = SimpleNamespace(
        _require_chat_access=AsyncMock(),
        _require_project_access=AsyncMock(return_value=({"created_at": created_at or now}, None)),
        directus_service=SimpleNamespace(project=SimpleNamespace(
            get_project_settings=AsyncMock(return_value={"write_mode": write_mode}))),
        get_active_focus=AsyncMock(return_value={"project_id": focus_project, "team_id": None,
                                                 "focus_id_hash": focus_id_hash(FOCUS)}),
    )
    monkeypatch.setattr(handler, "ProjectWriteAuthorizationService", lambda *_: auth)
    dispatch = AsyncMock(side_effect=(lambda **_: on_dispatch()) if on_dispatch else None)
    monkeypatch.setattr(handler, "dispatch_async_skill_continuation", dispatch)
    websocket = SimpleNamespace(send_json=AsyncMock())
    await handler.handle_project_create_result(
        websocket=websocket, manager=SimpleNamespace(can_execute_project_create=lambda *_: True),
        cache_service=cache, directus_service=None, user_id="owner", device_fingerprint_hash="device",
        payload=payload,
    )
    return dispatch, websocket.send_json.await_args.args[0], cache, key


CREATED = {"chat_id": "chat", "request_id": REQUEST, "status": "created", "project_id": PROJECT, "focus_id": FOCUS}


# contract-test: supporting surface=rest_api assertions=projects.creation.assistant-inferred
@pytest.mark.asyncio
async def test_created_report_resumes_turn_with_project_focus(monkeypatch, async_skill_continuation):
    dispatch, sent, cache, key = await _report(monkeypatch, async_skill_continuation, CREATED)
    dispatch.assert_awaited_once()
    assert dispatch.await_args.kwargs["async_task_id"] == REQUEST
    row = dispatch.await_args.kwargs["completed_results"][0]
    assert row["project_id"] == PROJECT and row["access_granted"] is True
    assert sent == {"type": "project_create_confirmed",
                    "payload": {"chat_id": "chat", "request_id": REQUEST, "status": "created"}}
    assert key not in cache.values


# contract-test: supporting surface=rest_api assertions=projects.creation.assistant-inferred
@pytest.mark.asyncio
@pytest.mark.parametrize("variant,code", [
    ({"focus_project": "44444444-4444-4444-8444-444444444444"}, "PROJECT_FOCUS_REQUIRED"),
    ({"write_mode": "always_ask"}, "PROJECT_CREATE_WRITE_MODE_MISMATCH"),
    ({"claim": False}, "PROJECT_CREATE_REQUEST_STALE"),
    ({"created_at": 1}, "PROJECT_CREATE_NOT_NEW"),
])
async def test_created_report_is_verified_before_resuming(monkeypatch, async_skill_continuation, variant, code):
    dispatch, sent, _, _ = await _report(monkeypatch, async_skill_continuation, CREATED, **variant)
    dispatch.assert_not_awaited()
    assert sent["type"] == "project_create_error" and sent["payload"]["code"] == code


# contract-test: supporting surface=rest_api assertions=projects.creation.assistant-inferred
@pytest.mark.asyncio
async def test_undone_report_resumes_turn_without_project(monkeypatch, async_skill_continuation):
    dispatch, sent, _, _ = await _report(monkeypatch, async_skill_continuation,
                                         {"chat_id": "chat", "request_id": REQUEST, "status": "undone"})
    row = dispatch.await_args.kwargs["completed_results"][0]
    assert row["access_granted"] is False and row["project_created"] is False
    assert sent["type"] == "project_create_confirmed"


# contract-test: supporting surface=rest_api assertions=projects.creation.assistant-inferred
@pytest.mark.asyncio
@pytest.mark.parametrize("created", [True, False])
async def test_continuation_activates_created_project_or_declines(monkeypatch, async_skill_continuation, created):
    from backend.tests.test_async_skill_continuation import _FakeCache, _FakeCeleryApp, _request as ask_request, _skill_config_dict
    cache = _FakeCache()
    celery = _FakeCeleryApp()
    monkeypatch.setattr(async_skill_continuation, "celery_app", celery)
    request = ask_request()
    request.active_focus_id = "jobs-career_insights"
    await async_skill_continuation.cache_async_skill_continuation_context(
        cache_service=cache, async_task_id=REQUEST, request_data=request, skill_config_dict=_skill_config_dict(),
        app_id="system", skill_id="project_create_request", tool_name="create_project_request",
        tool_arguments={"kind": "web_app", "subfolder": "web-app"},
    )
    await async_skill_continuation.dispatch_async_skill_continuation(
        cache_service=cache, async_task_id=REQUEST, completed_results=[{"access_granted": created}],
    )
    payload = celery.sent[0]["kwargs"]["request_data_dict"]
    assert payload["active_focus_id"] == (None if created else "jobs-career_insights")
    assert payload["project_access_declined"] is (not created)
