"""Bound Ask AI inference and settlement inside a signed For-each allowance."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.apps.ai.processing import main_processor
from backend.apps.ai.tasks.stream_consumer import _enforce_workflow_credit_allowance
from backend.core.api.app.services.workflow_app_skill_adapter import (
    sign_workflow_ai_budget,
    verify_workflow_ai_budget,
)


def _request(monkeypatch: pytest.MonkeyPatch, *, credits: int = 3) -> SimpleNamespace:
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "test-workflow-budget-secret")
    budget = sign_workflow_ai_budget("alice", {
        "workflow_id": "workflow-1", "run_id": "run-1", "node_id": "loop:0:ask:body",
    }, credits)
    return SimpleNamespace(user_id="alice", user_preferences={
        "workflow_ai": True, "workflow_budget": budget, "workflow_credit_allowance": credits,
    })


# contract-test: direct surface=rest_api assertions=workflows.control.for-each
def test_signed_workflow_budget_is_owner_and_occurrence_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    request = _request(monkeypatch)
    budget = request.user_preferences["workflow_budget"]
    assert verify_workflow_ai_budget("alice", budget) == 3
    assert verify_workflow_ai_budget("bob", budget) is None
    assert verify_workflow_ai_budget("alice", {**budget, "max_credits": 4}) is None
    assert verify_workflow_ai_budget("alice", {**budget, "node_id": "loop:1:ask:body"}) is None


# contract-test: direct surface=rest_api assertions=workflows.control.for-each
def test_workflow_ask_limits_provider_tokens_before_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    request = _request(monkeypatch)
    quoted: list[dict] = []

    def quote(**kwargs):
        quoted.append(kwargs)
        return 120

    monkeypatch.setattr(main_processor, "_max_affordable_ai_output_tokens", quote)
    result = main_processor._fit_workflow_output_token_limit(
        model_id="openai/test", system_prompt="system", message_history=[], tools=None,
        requested_output_token_limit=500, request_data=request,
    )
    assert result == 120
    assert quoted[0]["available_credits"] == 3
    assert quoted[0]["requested_output_token_limit"] == 500


# contract-test: direct surface=rest_api assertions=workflows.control.for-each
def test_workflow_ask_rejects_unaffordable_input_before_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    request = _request(monkeypatch)
    monkeypatch.setattr(main_processor, "_max_affordable_ai_output_tokens", lambda **_kwargs: None)
    with pytest.raises(RuntimeError, match="input exceeds its credit allowance"):
        main_processor._fit_workflow_output_token_limit(
            model_id="openai/test", system_prompt="system", message_history=[], tools=None,
            requested_output_token_limit=500, request_data=request,
        )


# contract-test: direct surface=rest_api assertions=workflows.control.for-each
def test_workflow_ask_settlement_never_exceeds_signed_allowance(monkeypatch: pytest.MonkeyPatch) -> None:
    request = _request(monkeypatch)
    assert _enforce_workflow_credit_allowance(request, 10) == 3
    assert _enforce_workflow_credit_allowance(request, 2) == 2
    request.user_preferences["workflow_credit_allowance"] = 4
    with pytest.raises(RuntimeError, match="invalid"):
        _enforce_workflow_credit_allowance(request, 10)
