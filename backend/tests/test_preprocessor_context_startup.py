"""Whole-function startup coverage for ordinary decision preprocessing."""

# contract-test-file: infrastructure

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.processing import agentic_context, context_preselection, jev_preprocessing, preprocessor
from backend.apps.ai.skills.ask_skill import AskSkillRequest
from backend.core.api.app.services import project_focus_request_service
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
async def test_normal_account_discovers_rules_only_after_app_selection(monkeypatch):
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

    async def decision(**kwargs):
        decision_calls.append(kwargs)
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

    with pytest.raises(DecisionBoundaryReached):
        await preprocessor.handle_preprocessing(
            request_data=request,
            base_instructions={"preprocess_request_tool": {"function": {"parameters": {"required": []}}}},
            skill_config=config, cache_service=cache, secrets_manager=None,
            directus_service=None, encryption_service=None,
            discovered_apps_metadata={"code": SimpleNamespace(skills=[], focuses=[])},
            on_early_routing=early_notice,
            preprocessing_stream_channel="preprocessing_stream::hash-test",
        )

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
