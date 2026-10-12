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
        "early_decisions": {"task_area": "general", "complexity": "simple",
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
        "complexity_val": "simple", "model_override_applied": False,
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
