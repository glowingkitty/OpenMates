"""Whole-function startup coverage for ordinary decision preprocessing."""

# contract-test-file: infrastructure

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.processing import agentic_context, context_preselection, jev_preprocessing, preprocessor
from backend.apps.ai.skills.ask_skill import AskSkillRequest
from backend.core.api.app.services import client_context_continuation, project_focus_request_service
from backend.core.api.app.services.billing_service import BillingService
from backend.core.api.app.utils import server_mode
from backend.core.api.app.services.directus.team_methods import TeamPermissionError, hash_id
from backend.core.api.app.services.project_write_authorization_service import ProjectWriteAuthorizationService
from backend.tests.test_teams_lifecycle import FakeDirectus


@pytest.mark.asyncio
async def test_private_focus_empty_discovery_marker_requires_fresh_success(monkeypatch):
    request = SimpleNamespace(user_id="user", chat_id="chat", project_focus_catalog=[])
    get_active = AsyncMock(return_value=None)
    monkeypatch.setattr(ProjectWriteAuthorizationService, "get_active_focus", get_active)
    assert await agentic_context.private_focus_candidates(request, object(), object()) == []
    assert request._private_focus_candidates_discovery_complete is True
    get_active.side_effect = RuntimeError("unavailable")
    assert await agentic_context.private_focus_candidates(request, object(), object()) == []
    assert request._private_focus_candidates_discovery_complete is False


# contract-test: supporting surface=rest_api assertions=teams.chat-billing.team-credit-boundary,teams.membership.role-gated
@pytest.mark.asyncio
async def test_team_chat_member_precheck_uses_spendable_credits(monkeypatch):
    class ReachedRouting(Exception):
        pass

    request = AskSkillRequest(
        chat_id="chat-test", message_id="message-test", user_id="member",
        user_id_hash="member-hash", team_id="team-1",
        message_history=[{"role": "user", "content": "Help", "created_at": 1}],
        current_user_content="Help",
    )
    directus = FakeDirectus()

    async def require_team_role(_team_id, user_id, roles):
        if user_id != "member" or "member" not in roles:
            raise TeamPermissionError("Team permission denied")
        return {"role": "member"}

    directus.team = SimpleNamespace(require_team_role=require_team_role)
    directus.rows["team_credit_accounts"].append({
        "hashed_team_id": hash_id("team-1"), "balance_credits": 2,
    })
    monkeypatch.setattr(server_mode, "is_payment_enabled", lambda: True)
    load_ledger = AsyncMock(side_effect=ReachedRouting)
    monkeypatch.setattr(preprocessor, "load_skill_ledger", load_ledger)
    kwargs = dict(
        request_data=request, base_instructions={}, skill_config=SimpleNamespace(),
        cache_service=SimpleNamespace(get_user_by_id=AsyncMock(return_value={"credits": 0})),
        secrets_manager=None, directus_service=directus, encryption_service=None,
    )

    funded = await preprocessor.handle_preprocessing(**kwargs)
    assert funded.rejection_reason != "team_credit_precheck_failed"
    load_ledger.assert_awaited_once()

    directus.rows["billing_reservations"].append({
        "subject_kind": "team", "subject_hash": hash_id("team-1"),
        "state": "reserved", "quoted_credits": 2,
    })
    insufficient = await preprocessor.handle_preprocessing(**kwargs)
    assert insufficient.rejection_reason == "insufficient_team_credits"
    load_ledger.assert_awaited_once()

    request.user_id = "viewer"
    forbidden = await preprocessor.handle_preprocessing(**kwargs)
    assert forbidden.rejection_reason == "team_credit_precheck_failed"
    load_ledger.assert_awaited_once()


# contract-test: supporting surface=gui.web assertions=ai-model-routing.preprocessing.early-resolution,chat-processing-feedback.selected-mate-identity
@pytest.mark.asyncio
@pytest.mark.parametrize("routing_lane", [False, True])
async def test_normal_account_discovers_rules_only_after_app_selection(monkeypatch, routing_lane):
    """The Jev stage-one boundary sees no Rule catalogue and loads selected apps."""
    class DecisionBoundaryReached(Exception):
        pass

    request = AskSkillRequest(
        chat_id="chat-test", message_id="message-test", user_id="user-test",
        user_id_hash="hash-test",
        message_history=[{"role": "user", "content": "Help me code", "created_at": 1}],
        current_user_content="Help me code",
    )
    cache = SimpleNamespace(
        get_user_by_id=AsyncMock(return_value={"credits": 10, "auto_topup_low_balance_enabled": False}),
        get_mates_configs=AsyncMock(return_value=[SimpleNamespace(
            id="mate-code", category="software_development", description="Code help",
            name="Code Mate",
        )]),
        publish_event=AsyncMock(),
    )
    config = SimpleNamespace(default_llms=SimpleNamespace(
        preprocessing_model="test/preprocessing", decision_model="test/decision",
    ))
    rules = [{"id": "app:code:python", "revision": "revision-test"}]
    workflows = [{"workflow_id": "workflow-test", "current_version_id": "version-test"}]
    discover_rules = AsyncMock(return_value=rules)
    discover_workflows = AsyncMock(return_value=workflows)
    decision_calls = []
    early_decisions = {"complexity": "complex", "task_area": "code", "user_unhappy": False,
                       "china_model_sensitive": False, "topic_area": "software_development",
                       "topic_shift": "noticeable_shift"}
    early = AsyncMock(return_value={"selected_app_ids": ["code"], "early_decisions": early_decisions})
    selection = AsyncMock(return_value={"selected_llm_for_main_id": "test/answer",
                                        "selected_llm_for_main_name": "Answer", "complexity_val": "complex",
                                        "model_override_applied": False})
    notices = []

    async def early_notice(routing):
        discover_rules.assert_not_awaited()
        discover_workflows.assert_not_awaited()
        steps = [call.args[1]["step"] for call in cache.publish_event.await_args_list]
        assert steps == ["mate_selected", "model_selected"]
        notices.append(routing)

    detail_loads = []

    async def context_phase(**kwargs):
        assert kwargs["phase"] == "details"
        assert notices, "Mate publication must precede waiting for private details"
        detail_loads.append(kwargs["phase"])

    from backend.core.api.app.services import client_context_continuation
    monkeypatch.setattr(client_context_continuation, "await_client_context_phase", context_phase)

    async def decision(**kwargs):
        decision_calls.append(kwargs)
        assert detail_loads == ["details"], "Stage two needs the delivered private details"
        assert notices and kwargs["early_decisions"] == early_decisions
        assert await kwargs["available_rules_loader"](["code"]) == rules
        raise RuntimeError("Stop after observing the decision boundary")

    async def stop_before_fallback_inference(**_kwargs):
        raise DecisionBoundaryReached

    monkeypatch.setattr(server_mode, "is_payment_enabled", lambda: True)
    admitted_balance = AsyncMock(return_value=10)
    monkeypatch.setattr(BillingService, "get_authoritative_personal_balance", admitted_balance)
    monkeypatch.setattr(preprocessor, "load_skill_ledger", AsyncMock(return_value=preprocessor.RoutingLedgerSnapshot(
        available=False, prompt_rows=(),
    )))
    monkeypatch.setattr(project_focus_request_service, "validated_project_candidates", AsyncMock(return_value=[]))
    monkeypatch.setattr(agentic_context, "private_focus_candidates", AsyncMock(return_value=[]))
    monkeypatch.setattr(context_preselection, "discover_rule_metadata", discover_rules)
    monkeypatch.setattr(context_preselection, "discover_workflow_metadata", discover_workflows)
    monkeypatch.setattr(jev_preprocessing, "decide_app_and_project_routing_with_jev", early)
    monkeypatch.setattr(preprocessor, "_select_main_model", selection)
    monkeypatch.setattr(preprocessor, "decide_preprocessing_with_jev", decision)
    monkeypatch.setattr(preprocessor, "call_preprocessing_llm", stop_before_fallback_inference)
    monkeypatch.setattr(preprocessor, "utility_model_fallbacks", lambda *_args: [])

    async def run_preprocessor():
        return await preprocessor.handle_preprocessing(
            request_data=request,
            base_instructions={"preprocess_request_tool": {"function": {"parameters": {"required": []}}}},
            skill_config=config, cache_service=cache, secrets_manager=None,
            directus_service=None, encryption_service=None,
            discovered_apps_metadata={"code": SimpleNamespace(skills=[], focuses=[])},
            on_early_routing=early_notice,
            preprocessing_stream_channel="preprocessing_stream::hash-test",
            stage_one_only=routing_lane,
        )

    if routing_lane:
        result = await run_preprocessor()
        assert result.routing_only is True
        assert request._stage_one_routing["early_decisions"] == early_decisions
        assert notices[0]["mate_id"] == "mate-code"
        assert detail_loads == [] and decision_calls == []
        discover_rules.assert_not_awaited()
        discover_workflows.assert_not_awaited()
        return
    with pytest.raises(DecisionBoundaryReached):
        await run_preprocessor()

    admitted_balance.assert_awaited_once_with(user_id="user-test", user_id_hash="hash-test")
    cache.get_user_by_id.assert_not_awaited()
    discover_rules.assert_awaited_once_with(request, None, cache, ["code"])
    discover_workflows.assert_awaited_once_with(request, cache)
    assert notices[0]["model_id"] == "test/answer"
    assert notices[0]["category"] == "software_development"
    assert notices[0]["mate_id"] == "mate-code"
    early.assert_awaited_once()
    assert len(decision_calls) == 1
    assert "available_rules" not in decision_calls[0]
    assert decision_calls[0]["available_workflows"] == workflows


# contract-test: supporting surface=gui.web assertions=ai-model-routing.preprocessing.early-resolution
@pytest.mark.parametrize("missing", [None, "scope_complete", "active_focus_id", "context_revision"])
def test_empty_context_fast_path_requires_complete_server_scope(missing):
    from backend.apps.ai.processing.preprocessor import _simple_context_fast_path
    scope = {"scope_complete": True, "active_project_id": None, "active_project_activation_id": None,
             "active_focus_id": None, "accepted_plan_ref": None, "explicit_related_task_ids": [],
             "context_revision": "revision"}
    if missing:
        scope.pop(missing)
    request = SimpleNamespace(admission_context=scope, is_focus_mode_continuation=False,
                              is_app_settings_memories_continuation=False)
    routing = {"early_decisions": {"public_decisions": {}, "needs_detailed_context": False,
                                   "needs_related_work": False},
               "selected_app_ids": [], "project_target_outcome": "none"}
    assert _simple_context_fast_path(request, routing, None) is (missing is None)

# contract-test: supporting surface=cli assertions=chat-processing-feedback.selected-mate-identity,projects.focus.inferred-consent
@pytest.mark.parametrize("change", [
    "none", "missing_route", "selected_project", "uncertain_route", "named_project",
    "file_request", "active_project", "active_focus", "explicit_dependency", "stale_revision", "missing_scope",
    "selected_app", "detailed_context", "explicit_focus_override",
])
def test_sealed_stage_one_no_project_reuse_keeps_context_boundaries(change):
    request = AskSkillRequest(
        chat_id="chat", message_id="turn", user_id="owner", user_id_hash="hash",
        current_user_content="What's the capital of Spain?",
        message_history=[{"role": "user", "content": "What's the capital of Spain?", "created_at": 1}],
        project_focus_candidates=[{"project_id": "project-1", "name": "OpenMates"}],
        admission_context={"scope_complete": True, "active_project_id": None,
            "active_project_activation_id": None, "active_focus_id": None,
            "accepted_plan_ref": None, "explicit_related_task_ids": [],
            "context_revision": "server-admission-v1"},
    )
    routing = {"project_target_outcome": "none", "selected_app_ids": [],
        "early_decisions": {"needs_detailed_context": False, "needs_related_work": False,
                            "public_decisions": {}}}
    if change == "missing_route":
        routing = None
    elif change == "selected_project":
        routing["project_target_outcome"] = "selected"
    elif change == "uncertain_route":
        routing["project_target_outcome"] = "low_confidence"
    elif change == "named_project":
        request.current_user_content = "Tell me about my OpenMates project"
    elif change == "file_request":
        request.current_user_content = "Read the README in my project"
    elif change == "active_project":
        request.current_project = {"project_id": "project-1"}
    elif change == "active_focus":
        request.active_focus_id = "web-research"
    elif change == "explicit_dependency":
        request.admission_context["explicit_related_task_ids"] = ["TASK-1"]
    elif change == "stale_revision":
        request.admission_context["context_revision"] = "old"
    elif change == "missing_scope":
        request.admission_context["scope_complete"] = False
    elif change == "selected_app":
        routing["selected_app_ids"] = ["projects"]
    elif change == "detailed_context":
        routing["early_decisions"]["needs_detailed_context"] = True
    overrides = SimpleNamespace(has_overrides=True) if change == "explicit_focus_override" else None
    assert preprocessor._reusable_stage_one_project_none(request, routing, overrides) is (change == "none")


# contract-test: supporting surface=cli assertions=projects.focus.inferred-consent,chat-processing-feedback.selected-mate-identity
@pytest.mark.asyncio
async def test_main_reuses_sealed_no_project_route_without_second_candidate_read(monkeypatch):
    import uuid

    class ReachedMainSetup(BaseException):
        pass

    class FakeRedis:
        values = {}

        async def get(self, key):
            return self.values.get(key)

    class FakeVault:
        values = {}

        async def encrypt_with_user_key(self, plaintext, key):
            token = uuid.uuid4().hex
            self.values[token] = (key, plaintext)
            return token, "nonce"

        async def decrypt_with_user_key(self, token, key):
            stored_key, plaintext = self.values[token]
            assert stored_key == key
            return plaintext

    class FakeCache:
        get_user_by_id = AsyncMock(return_value={})
        get_mates_configs = AsyncMock(return_value=[])

        @property
        async def client(self):
            return redis

        async def get_user_vault_key_id(self, user_id):
            return f"vault:{user_id}"

    redis, vault, cache = FakeRedis(), FakeVault(), FakeCache()
    request_id = str(uuid.uuid4())

    request = AskSkillRequest(
        chat_id="chat", message_id="turn", user_id="owner", user_id_hash="hash",
        current_user_content="What's the capital of Spain?", chat_has_title=False,
        message_history=[{"role": "user", "content": "What's the capital of Spain?", "created_at": 1}],
        project_focus_candidates=[{"project_id": "project-1", "name": "OpenMates"}],
        client_capabilities=["project_file_jobs"],
        client_context_pending=True,
        client_context_request_id=request_id, recovery_turn_id="admitted-turn",
        admission_context={"scope_complete": False, "active_project_id": None,
            "active_project_activation_id": None, "active_focus_id": None,
            "accepted_plan_ref": None, "explicit_related_task_ids": [],
            "context_revision": "server-admission-v1"},
    )
    scope = client_context_continuation._scope(
        user_id=request.user_id, chat_id=request.chat_id, turn_id=request.recovery_turn_id,
        message_id=request.message_id, request_id=request_id,
    )
    reference = client_context_continuation._reference(scope)
    request.client_context_binding_ref = reference
    request.__dict__["_client_context_routing_loaded"] = True
    key = client_context_continuation._key(reference)
    redis.values[key] = await client_context_continuation._seal(
        vault, "vault:owner", {"scope": scope, "device": "admitted-device"},
    )
    redis.values[key + ":details"] = await client_context_continuation._seal(
        vault, "vault:owner", {"scope": scope, "phase": "details", "context": {}},
    )
    routing = {"project_target_outcome": "none", "selected_app_ids": [],
        "early_decisions": {"task_area": "general", "complexity": "low",
            "needs_detailed_context": False, "needs_related_work": False,
            "public_decisions": {}}}
    validate = AsyncMock(side_effect=AssertionError("Unrelated Project candidate reread"))
    monkeypatch.setattr(project_focus_request_service, "validated_project_candidates", validate)
    stage_one_jev = AsyncMock(side_effect=AssertionError("Duplicate paid Stage-one Jev"))
    monkeypatch.setattr(jev_preprocessing, "decide_app_and_project_routing_with_jev", stage_one_jev)
    monkeypatch.setattr(server_mode, "is_payment_enabled", lambda: False)
    monkeypatch.setattr(preprocessor, "load_skill_ledger", AsyncMock(return_value=preprocessor.RoutingLedgerSnapshot(
        available=True, prompt_rows=())))
    selected_model = AsyncMock(return_value={
        "selected_llm_for_main_id": "google/test-answer",
        "selected_llm_for_main_name": "Test Answer",
        "complexity_val": "low", "model_override_applied": False,
    })
    monkeypatch.setattr(preprocessor, "_select_main_model", selected_model)
    detailed_decision = AsyncMock(side_effect=ReachedMainSetup)
    monkeypatch.setattr(preprocessor, "decide_preprocessing_with_jev", detailed_decision)
    hydration_calls = []

    hydrate_actual_details = client_context_continuation.await_client_context_phase

    async def hydrate_details(**kwargs):
        assert kwargs["phase"] == "details"
        assert kwargs["request"] is request
        assert validate.await_count == 0 and selected_model.await_count == 0
        assert request.admission_context["scope_complete"] is False
        await hydrate_actual_details(**kwargs)
        assert request.admission_context["scope_complete"] is True
        assert request.client_context_pending is False
        hydration_calls.append("details")

    monkeypatch.setattr(client_context_continuation, "await_client_context_phase", hydrate_details)
    with pytest.raises(ReachedMainSetup):
        await preprocessor.handle_preprocessing(
            request_data=request, base_instructions={"preprocess_request_tool": {}},
            skill_config=SimpleNamespace(default_llms=SimpleNamespace(
                preprocessing_model="test/preprocessing", decision_model="test/jev")),
            cache_service=cache, secrets_manager=None, directus_service=object(),
            encryption_service=vault, discovered_apps_metadata={},
            precomputed_stage_one=routing,
        )
    validate.assert_not_awaited()
    stage_one_jev.assert_not_awaited()
    selected_model.assert_awaited_once()
    detailed_decision.assert_awaited_once()
    assert hydration_calls == ["details"]
    assert request.project_focus_candidates == []


# contract-test: supporting surface=cli assertions=projects.focus.inferred-consent,chat-processing-feedback.selected-mate-identity
@pytest.mark.asyncio
@pytest.mark.parametrize("rejected", [False, True])
async def test_scoped_stage_one_joins_fresh_credit_and_project_eligibility_before_routing(monkeypatch, rejected):
    import asyncio
    from backend.apps.ai.processing import routing_ledger

    request = AskSkillRequest(
        chat_id="chat", message_id="turn", user_id="owner", user_id_hash="owner-hash",
        current_user_content="What is the capital of Spain?",
        message_history=[{"role": "user", "content": "What is the capital of Spain?", "created_at": 1}],
        project_focus_candidates=[{"project_id": "project", "name": "OpenMates"}],
        client_capabilities=["project_file_jobs"],
    )
    entered = set()
    both_entered = asyncio.Event()

    async def enter(name):
        entered.add(name)
        if len(entered) == 2:
            both_entered.set()
        await asyncio.wait_for(both_entered.wait(), timeout=1)

    async def credit(*_args):
        await enter("credit")
        return preprocessor.PreprocessingResult(
            can_proceed=False, rejection_reason="insufficient_credits",
        ) if rejected else None

    async def eligible(*_args, **_kwargs):
        await enter("project")
        return []

    ledger = AsyncMock(return_value=routing_ledger.RoutingLedgerSnapshot(available=False, prompt_rows=()))
    monkeypatch.setattr(preprocessor, "check_preprocessing_credits", credit)
    monkeypatch.setattr(project_focus_request_service, "validated_project_candidates", eligible)
    monkeypatch.setattr(preprocessor, "load_skill_ledger", ledger)
    result = await preprocessor.handle_preprocessing(
        request_data=request, base_instructions={}, skill_config=SimpleNamespace(),
        cache_service=object(), secrets_manager=None, directus_service=object(),
        encryption_service=None, stage_one_only=True, routing_scope_validated=True,
    )
    assert entered == {"credit", "project"}
    assert result.rejection_reason == (
        "insufficient_credits" if rejected else "internal_error_missing_instructions"
    )
    assert ledger.await_count == (0 if rejected else 1)


# contract-test: supporting surface=cli assertions=projects.focus.inferred-consent
@pytest.mark.asyncio
async def test_scoped_stage_one_cancellation_cleans_both_prechecks(monkeypatch):
    import asyncio

    request = AskSkillRequest(
        chat_id="chat", message_id="turn", user_id="owner", user_id_hash="owner-hash",
        current_user_content="What is the capital of Spain?",
        message_history=[{"role": "user", "content": "What is the capital of Spain?", "created_at": 1}],
        project_focus_candidates=[{"project_id": "project", "name": "OpenMates"}],
        client_capabilities=["project_file_jobs"],
    )
    started = asyncio.Event()
    cancelled = set()

    async def wait(name):
        if name == "project":
            started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.add(name)
            raise

    async def credit(*_args):
        return await wait("credit")

    async def eligible(*_args, **_kwargs):
        return await wait("project")

    monkeypatch.setattr(preprocessor, "check_preprocessing_credits", credit)
    monkeypatch.setattr(project_focus_request_service, "validated_project_candidates", eligible)
    task = asyncio.create_task(preprocessor.handle_preprocessing(
        request_data=request, base_instructions={}, skill_config=SimpleNamespace(),
        cache_service=object(), secrets_manager=None, directus_service=object(),
        encryption_service=None, stage_one_only=True, routing_scope_validated=True,
    ))
    await asyncio.wait_for(started.wait(), timeout=1)
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled == {"credit", "project"}


# contract-test: supporting surface=cli assertions=chat-processing-feedback.selected-mate-identity
@pytest.mark.asyncio
@pytest.mark.parametrize("hook_fails", [False, True])
async def test_related_summary_fallback_waits_for_active_summary_hook(monkeypatch, hook_fails):
    import asyncio
    from backend.apps.ai.processing import related_work

    class ReachedDetail(BaseException):
        pass

    request = AskSkillRequest(
        chat_id="chat", message_id="turn", user_id="owner", user_id_hash="owner-hash",
        recovery_task_id="task", current_user_content="What happened earlier?",
        message_history=[{"role": "user", "content": "What happened earlier?", "created_at": 1}],
    )
    config = SimpleNamespace(default_llms=SimpleNamespace(
        preprocessing_model="test/preprocessing", decision_model="test/decision",
    ))
    cache = SimpleNamespace(get_mates_configs=AsyncMock(return_value=[SimpleNamespace(
        id="mate-general", category="general_knowledge", description="General", name="General Mate",
    )]), publish_event=AsyncMock())
    early = {"project_target_outcome": "none", "selected_app_ids": [],
             "early_decisions": {"task_area": "general", "topic_area": "general_knowledge",
                                 "complexity": "low", "needs_related_work": True}}
    order = []

    async def hook():
        order.append("hook_started")
        await asyncio.sleep(0)
        if hook_fails:
            raise RuntimeError("active summary failed")
        order.append("hook_done")

    async def summaries(*_args):
        assert order == ["hook_started", "hook_done"]
        order.append("summary_read")
        return []

    read = AsyncMock(side_effect=summaries)
    monkeypatch.setattr(preprocessor, "check_preprocessing_credits", AsyncMock(return_value=None))
    monkeypatch.setattr(preprocessor, "load_skill_ledger", AsyncMock(return_value=preprocessor.RoutingLedgerSnapshot(
        available=False, prompt_rows=(),
    )))
    monkeypatch.setattr(jev_preprocessing, "decide_app_and_project_routing_with_jev", AsyncMock(return_value=early))
    monkeypatch.setattr(preprocessor, "_select_main_model", AsyncMock(return_value={
        "selected_llm_for_main_id": "test/answer", "selected_llm_for_main_name": "Answer",
        "complexity_val": "low", "model_override_applied": False,
    }))
    monkeypatch.setattr(agentic_context, "private_focus_candidates", AsyncMock(return_value=[]))
    monkeypatch.setattr(context_preselection, "discover_workflow_metadata", AsyncMock(return_value=[]))
    monkeypatch.setattr(related_work, "fetch_related_chat_summaries", read)
    monkeypatch.setattr(related_work, "fetch_related_task_candidates", AsyncMock(return_value=[]))
    monkeypatch.setattr(preprocessor, "decide_preprocessing_with_jev", AsyncMock(side_effect=ReachedDetail))
    monkeypatch.setattr(preprocessor, "utility_model_fallbacks", lambda *_args: [])
    monkeypatch.setattr(server_mode, "is_payment_enabled", lambda: False)
    monkeypatch.setattr(client_context_continuation, "await_client_context_phase", AsyncMock())

    run = preprocessor.handle_preprocessing(
        request_data=request, base_instructions={"preprocess_request_tool": {}}, skill_config=config,
        cache_service=cache, secrets_manager=None, directus_service=None, encryption_service=None,
        discovered_apps_metadata={}, before_related_summary_read=hook,
    )
    if hook_fails:
        with pytest.raises(RuntimeError, match="active summary failed"):
            await run
        read.assert_not_awaited()
        assert order == ["hook_started"]
    else:
        with pytest.raises(ReachedDetail):
            await run
        read.assert_awaited_once()
        assert order == ["hook_started", "hook_done", "summary_read"]


# contract-test: supporting surface=cli assertions=chat-processing-feedback.selected-mate-identity
@pytest.mark.asyncio
@pytest.mark.parametrize("hook_fails", [False, True])
async def test_invalidated_empty_details_join_summary_before_detailed_jev(monkeypatch, hook_fails):
    import asyncio

    class ReachedDetail(BaseException):
        pass

    request = AskSkillRequest(
        chat_id="chat", message_id="turn", user_id="owner", user_id_hash="owner-hash",
        recovery_task_id="task", current_user_content="Hello",
        message_history=[{"role": "user", "content": "Hello", "created_at": 1}],
        admission_context={"scope_complete": True, "active_project_id": None,
            "active_project_activation_id": None, "active_focus_id": None,
            "accepted_plan_ref": None, "explicit_related_task_ids": [],
            "context_revision": "server-admission-v1"},
    )
    early = {"project_target_outcome": "none", "selected_app_ids": [],
             "early_decisions": {"task_area": "general", "topic_area": "general_knowledge",
                                 "complexity": "low", "public_decisions": {},
                                 "needs_detailed_context": False, "needs_related_work": False}}
    assert preprocessor._simple_context_fast_path(request, early, None)
    config = SimpleNamespace(default_llms=SimpleNamespace(
        preprocessing_model="test/preprocessing", decision_model="test/decision",
    ))
    cache = SimpleNamespace(get_mates_configs=AsyncMock(return_value=[SimpleNamespace(
        id="mate-general", category="general_knowledge", description="General", name="General Mate",
    )]), publish_event=AsyncMock())
    order = []

    async def details(**_kwargs):
        order.append("details")
        request.active_focus_id = "focus-after-details"

    async def hook():
        order.append("hook_start")
        await asyncio.sleep(0)
        if hook_fails:
            raise RuntimeError("active summary failed")
        order.append("hook_done")

    async def detailed(**_kwargs):
        assert order == ["details", "hook_start", "hook_done"]
        raise ReachedDetail

    detailed_call = AsyncMock(side_effect=detailed)
    monkeypatch.setattr(preprocessor, "check_preprocessing_credits", AsyncMock(return_value=None))
    monkeypatch.setattr(preprocessor, "load_skill_ledger", AsyncMock(return_value=preprocessor.RoutingLedgerSnapshot(
        available=False, prompt_rows=(),
    )))
    monkeypatch.setattr(jev_preprocessing, "decide_app_and_project_routing_with_jev", AsyncMock(return_value=early))
    monkeypatch.setattr(preprocessor, "_select_main_model", AsyncMock(return_value={
        "selected_llm_for_main_id": "test/answer", "selected_llm_for_main_name": "Answer",
        "complexity_val": "low", "model_override_applied": False,
    }))
    monkeypatch.setattr(agentic_context, "private_focus_candidates", AsyncMock(return_value=[]))
    monkeypatch.setattr(context_preselection, "discover_workflow_metadata", AsyncMock(return_value=[]))
    monkeypatch.setattr(preprocessor, "decide_preprocessing_with_jev", detailed_call)
    monkeypatch.setattr(preprocessor, "utility_model_fallbacks", lambda *_args: [])
    monkeypatch.setattr(client_context_continuation, "await_client_context_phase", details)

    run = preprocessor.handle_preprocessing(
        request_data=request, base_instructions={"preprocess_request_tool": {}}, skill_config=config,
        cache_service=cache, secrets_manager=None, directus_service=None, encryption_service=None,
        discovered_apps_metadata={}, before_related_summary_read=hook,
    )
    if hook_fails:
        with pytest.raises(RuntimeError, match="active summary failed"):
            await run
        detailed_call.assert_not_awaited()
        assert order == ["details", "hook_start"]
    else:
        with pytest.raises(ReachedDetail):
            await run
        detailed_call.assert_awaited_once()
        assert order == ["details", "hook_start", "hook_done"]


# contract-test: supporting surface=cli assertions=chat-processing-feedback.selected-mate-identity
@pytest.mark.asyncio
async def test_empty_fast_path_failure_joins_summary_before_private_fallback(monkeypatch):
    class ReachedDetailedPass(BaseException):
        pass

    request = AskSkillRequest(
        chat_id="chat", message_id="turn", user_id="owner", user_id_hash="owner-hash",
        recovery_task_id="task", current_user_content="Hello",
        message_history=[{"role": "user", "content": "Hello", "created_at": 1}],
        admission_context={"scope_complete": True, "active_project_id": None,
            "active_project_activation_id": None, "active_focus_id": None,
            "accepted_plan_ref": None, "explicit_related_task_ids": [],
            "context_revision": "server-admission-v1"},
    )
    early = {"project_target_outcome": "none", "selected_app_ids": [],
             "early_decisions": {"task_area": "general", "topic_area": "general_knowledge",
                                 "complexity": "low", "public_decisions": {},
                                 "needs_detailed_context": False, "needs_related_work": False}}
    config = SimpleNamespace(default_llms=SimpleNamespace(
        preprocessing_model="test/preprocessing", decision_model="test/decision",
    ))
    cache = SimpleNamespace(get_mates_configs=AsyncMock(return_value=[SimpleNamespace(
        id="mate-general", category="general_knowledge", description="General", name="General Mate",
    )]), publish_event=AsyncMock())
    order = []

    async def hook():
        order.append("summary_join")

    async def private_catalog(*_args):
        assert order == ["summary_join"]
        order.append("private_read")
        return []

    async def jev(**_kwargs):
        if "private_read" not in order:
            raise ValueError("fast decision failed")
        assert order == ["summary_join", "private_read"]
        raise ReachedDetailedPass

    monkeypatch.setattr(preprocessor, "check_preprocessing_credits", AsyncMock(return_value=None))
    monkeypatch.setattr(preprocessor, "load_skill_ledger", AsyncMock(return_value=preprocessor.RoutingLedgerSnapshot(
        available=False, prompt_rows=(),
    )))
    monkeypatch.setattr(jev_preprocessing, "decide_app_and_project_routing_with_jev", AsyncMock(return_value=early))
    monkeypatch.setattr(preprocessor, "_select_main_model", AsyncMock(return_value={
        "selected_llm_for_main_id": "test/answer", "selected_llm_for_main_name": "Answer",
        "complexity_val": "low", "model_override_applied": False,
    }))
    monkeypatch.setattr(agentic_context, "private_focus_candidates", private_catalog)
    monkeypatch.setattr(context_preselection, "discover_workflow_metadata", AsyncMock(return_value=[]))
    monkeypatch.setattr(preprocessor, "decide_preprocessing_with_jev", jev)
    monkeypatch.setattr(preprocessor, "utility_model_fallbacks", lambda *_args: [])
    monkeypatch.setattr(client_context_continuation, "await_client_context_phase", AsyncMock())

    with pytest.raises(ReachedDetailedPass):
        await preprocessor.handle_preprocessing(
            request_data=request, base_instructions={"preprocess_request_tool": {}},
            skill_config=config, cache_service=cache, secrets_manager=None,
            directus_service=None, encryption_service=None,
            discovered_apps_metadata={}, before_related_summary_read=hook,
        )
    assert order == ["summary_join", "private_read"]


# contract-test: supporting surface=cli assertions=ai-model-routing.preprocessing.contextual-compact-assembly
@pytest.mark.asyncio
@pytest.mark.parametrize("complete", [True, False])
async def test_same_chat_complete_route_reuses_full_history_without_detailed_context(monkeypatch, complete):
    class ReachedDecision(BaseException):
        pass

    history = [{"role": "user", "content": "What is the capital of Spain?", "created_at": 1},
               {"role": "assistant", "content": "Madrid.", "created_at": 2},
               {"role": "user", "content": "And France?", "created_at": 3}]
    request = AskSkillRequest(chat_id="chat", message_id="turn", user_id="owner", user_id_hash="owner-hash",
        recovery_task_id="task", current_user_content="And France?", message_history=history,
        chat_has_title=True,
        admission_context={"scope_complete": complete, "active_project_id": None,
            "active_project_activation_id": None, "active_focus_id": None,
            "accepted_plan_ref": None, "explicit_related_task_ids": [],
            "context_revision": "server-admission-v1"})
    early = {"project_target_outcome": "none", "selected_app_ids": [],
             "early_decisions": {"task_area": "general", "topic_area": "general_knowledge",
                "complexity": "low", "public_decisions": {},
                "needs_detailed_context": False, "needs_related_work": False}}
    config = SimpleNamespace(default_llms=SimpleNamespace(preprocessing_model="test/preprocessing",
                                                         decision_model="test/decision"))
    cache = SimpleNamespace(get_mates_configs=AsyncMock(return_value=[SimpleNamespace(
        id="mate-general", category="general_knowledge", description="General", name="General Mate")]),
        get_chat_list_item_data=AsyncMock(return_value=None), publish_event=AsyncMock())
    join, catalog = AsyncMock(), AsyncMock(return_value=[])

    async def decision(**kwargs):
        assert [row["content"] for row in kwargs["message_history"]] == [row["content"] for row in history]
        assert kwargs["is_first_message"] is False
        if complete:
            join.assert_not_awaited()
            catalog.assert_not_awaited()
            assert kwargs["candidate_discovery_complete"] is True
            assert kwargs["related_discovery_complete"] is True
            assert kwargs["available_rules"] == [] and kwargs["available_workflows"] == []
        else:
            join.assert_awaited_once()
            catalog.assert_awaited_once()
        raise ReachedDecision

    monkeypatch.setattr(preprocessor, "check_preprocessing_credits", AsyncMock(return_value=None))
    monkeypatch.setattr(preprocessor, "load_skill_ledger", AsyncMock(return_value=preprocessor.RoutingLedgerSnapshot(
        available=False, prompt_rows=())))
    monkeypatch.setattr(jev_preprocessing, "decide_app_and_project_routing_with_jev", AsyncMock(return_value=early))
    monkeypatch.setattr(preprocessor, "_select_main_model", AsyncMock(return_value={
        "selected_llm_for_main_id": "test/answer", "selected_llm_for_main_name": "Answer",
        "complexity_val": "low", "model_override_applied": False}))
    monkeypatch.setattr(agentic_context, "private_focus_candidates", catalog)
    monkeypatch.setattr(agentic_context, "fresh_project", AsyncMock(return_value=None))
    monkeypatch.setattr(context_preselection, "discover_workflow_metadata", AsyncMock(return_value=[]))
    monkeypatch.setattr(preprocessor, "decide_preprocessing_with_jev", decision)
    monkeypatch.setattr(preprocessor, "utility_model_fallbacks", lambda *_args: [])
    monkeypatch.setattr(client_context_continuation, "await_client_context_phase", AsyncMock())
    with pytest.raises(ReachedDecision):
        await preprocessor.handle_preprocessing(request_data=request, base_instructions={"preprocess_request_tool": {}},
            skill_config=config, cache_service=cache, secrets_manager=None,
            directus_service=None, encryption_service=None, discovered_apps_metadata={},
            before_related_summary_read=join)


# contract-test: supporting surface=rest_api assertions=ai-model-routing.preprocessing.contextual-compact-assembly
@pytest.mark.parametrize("change", ["none", "missing_public", "missing_preview", "artifact", "instruction", "complex", "incomplete_scope"])
def test_positive_plain_prose_proof_comes_only_from_complete_validated_current_routing(change):
    public = {"temperature": "precise", "enable_subchats": False, "ai_model_topics": [],
              "harmful_or_illegal": 0, "misuse_risk": 0, "output_language": "en", "preview": "none", "icon_names": []}
    kwargs = {"is_first_message": False, "context_fast_path": True, "task_area": "general",
              "complexity": "low", "previews": []}
    if change == "missing_public":
        public = {}
    elif change == "missing_preview":
        public.pop("preview")
    elif change == "artifact":
        public["preview"] = "code"
    elif change == "instruction":
        kwargs["task_area"] = "instruction"
    elif change == "complex":
        kwargs["complexity"] = "complex"
    elif change == "incomplete_scope":
        kwargs["context_fast_path"] = False
    assert preprocessor._plain_prose_routing_proof({"early_decisions": {"public_decisions": public}}, **kwargs) is (change == "none")


# contract-test: supporting surface=rest_api assertions=ai-model-routing.preprocessing.contextual-compact-assembly
@pytest.mark.parametrize("tier", ["low", "simple", "medium", "high", "max", "unknown", None])
def test_prose_routing_proof_tracks_current_low_tier_and_safe_legacy_alias(tier):
    public = {"temperature": "precise", "enable_subchats": False, "ai_model_topics": [],
              "harmful_or_illegal": 0, "misuse_risk": 0, "output_language": "en", "preview": "none", "icon_names": []}
    assert preprocessor._plain_prose_routing_proof({"early_decisions": {"public_decisions": public}},
        is_first_message=False, context_fast_path=True, task_area="general", complexity=tier,
        previews=[]) is (tier in {"low", "simple"})
