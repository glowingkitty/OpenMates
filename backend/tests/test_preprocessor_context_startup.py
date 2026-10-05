"""Whole-function startup coverage for ordinary decision preprocessing."""

# contract-test-file: infrastructure

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.processing import agentic_context, context_preselection, preprocessor
from backend.apps.ai.skills.ask_skill import AskSkillRequest
from backend.core.api.app.services import project_focus_request_service
from backend.core.api.app.utils import server_mode


@pytest.mark.asyncio
async def test_normal_account_discovers_rules_and_workflows_before_decision(monkeypatch):
    """A normal paid account reaches the first decision with both catalogs."""
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
            category="general_knowledge", description="General help",
        )]),
    )
    config = SimpleNamespace(default_llms=SimpleNamespace(
        preprocessing_model="test/preprocessing", decision_model="test/decision",
    ))
    rules = [{"id": "app:code:python", "revision": "revision-test"}]
    workflows = [{"workflow_id": "workflow-test", "current_version_id": "version-test"}]
    discover_rules = AsyncMock(return_value=rules)
    discover_workflows = AsyncMock(return_value=workflows)
    decision_calls = []

    async def decision(**kwargs):
        decision_calls.append(kwargs)
        raise RuntimeError("Stop after observing the decision boundary")

    async def stop_before_fallback_inference(**_kwargs):
        raise DecisionBoundaryReached

    monkeypatch.setattr(server_mode, "is_payment_enabled", lambda: True)
    monkeypatch.setattr(preprocessor, "load_skill_ledger", AsyncMock(return_value=preprocessor.RoutingLedgerSnapshot(
        available=False, prompt_rows=(),
    )))
    monkeypatch.setattr(project_focus_request_service, "validated_project_candidates", AsyncMock(return_value=[]))
    monkeypatch.setattr(agentic_context, "private_focus_candidates", AsyncMock(return_value=[]))
    monkeypatch.setattr(context_preselection, "discover_rule_metadata", discover_rules)
    monkeypatch.setattr(context_preselection, "discover_workflow_metadata", discover_workflows)
    monkeypatch.setattr(preprocessor, "decide_preprocessing_with_jev", decision)
    monkeypatch.setattr(preprocessor, "call_preprocessing_llm", stop_before_fallback_inference)
    monkeypatch.setattr(preprocessor, "utility_model_fallbacks", lambda *_args: [])

    with pytest.raises(DecisionBoundaryReached):
        await preprocessor.handle_preprocessing(
            request_data=request,
            base_instructions={"preprocess_request_tool": {"function": {"parameters": {"required": []}}}},
            skill_config=config, cache_service=cache, secrets_manager=None,
            directus_service=None, encryption_service=None,
        )

    cache.get_user_by_id.assert_awaited_once_with("user-test")
    discover_rules.assert_awaited_once_with(request, None, cache, [])
    discover_workflows.assert_awaited_once_with(request, cache)
    assert len(decision_calls) == 1
    assert decision_calls[0]["available_rules"] == rules
    assert decision_calls[0]["available_workflows"] == workflows
