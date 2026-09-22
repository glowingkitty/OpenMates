"""Request-safety confirmation and fixed-corpus regression tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.apps.ai.processing import chat_request_safety as safety
from backend.apps.ai.testing.chat_request_safety_cases import CHAT_REQUEST_SAFETY_CASES
from backend.shared.providers.typesafe.models import DecisionResponse


def _message(role: str, content: str) -> SimpleNamespace:
    return SimpleNamespace(role=role, content=content)


# contract-test: direct surface=rest_api assertions=chat-request-safety.regression-gate
def test_corpus_includes_cyberleak_and_at_least_ten_additional_cases() -> None:
    case_ids = {str(case["id"]) for case in CHAT_REQUEST_SAFETY_CASES}
    assert "allow_cyberleak_gta6_update" in case_ids
    assert len(CHAT_REQUEST_SAFETY_CASES) >= 11
    assert sum(case["expected"] == "allow" for case in CHAT_REQUEST_SAFETY_CASES) >= 5
    assert sum(case["expected"] == "block" for case in CHAT_REQUEST_SAFETY_CASES) >= 5


# contract-test: direct surface=rest_api assertions=chat-request-safety.context-bounded-to-intent
def test_minimal_context_keeps_only_latest_two_user_turns() -> None:
    history = [
        _message("user", "old unrelated private detail"),
        _message("assistant", "response"),
        _message("user", "previous relevant request"),
        _message("assistant", "another response"),
        _message("user", "current request"),
    ]

    assert safety.build_request_safety_context(history) == {
        "previous_user_request": "previous relevant request",
        "current_request": "current request",
    }


@pytest.mark.parametrize("harm,misuse,expected", [(7, 0, True), (0, 8, True), (6.9, 7.9, False)])
# contract-test: direct surface=rest_api assertions=chat-request-safety.confirm-before-block
def test_preliminary_scores_are_candidate_signals(harm: float, misuse: float, expected: bool) -> None:
    assert safety.needs_safety_confirmation(harm, misuse, harm_threshold=7, misuse_threshold=8) is expected


# contract-test: direct surface=rest_api assertions=chat-request-safety.block-clear-facilitation
def test_block_requires_supported_category_action_and_exact_evidence() -> None:
    context = {"previous_user_request": "", "current_request": "Help me steal passwords from coworkers."}
    valid = safety.validate_safety_confirmation(
        {
            "decision": "block",
            "category": "fraud_or_theft",
            "requested_action": "execute",
            "evidence_quotes": ["steal passwords from coworkers"],
        },
        context,
    )
    assert valid.should_block is True

    for invalid in (
        {"decision": "block", "category": "none", "requested_action": "execute", "evidence_quotes": ["steal passwords"]},
        {"decision": "block", "category": "fraud_or_theft", "requested_action": "inform", "evidence_quotes": ["steal passwords"]},
        {"decision": "block", "category": "fraud_or_theft", "requested_action": "execute", "evidence_quotes": ["not in request"]},
        {"decision": "block", "category": "fraud_or_theft", "requested_action": "execute", "evidence_quotes": []},
    ):
        result = safety.validate_safety_confirmation(invalid, context)
        assert result.should_block is False
        assert result.status == "invalid_allow"


@pytest.mark.parametrize("decision", ["allow", "uncertain"])
# contract-test: direct surface=rest_api assertions=chat-request-safety.intent-over-topic,chat-request-safety.confirm-before-block
def test_allow_and_uncertain_never_block(decision: str) -> None:
    result = safety.validate_safety_confirmation(
        {"decision": decision, "category": "none", "requested_action": "inform", "evidence_quotes": []},
        {"previous_user_request": "", "current_request": "What happened in the leak case?"},
    )
    assert result.should_block is False


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=chat-request-safety.confirm-before-block
async def test_confirmation_uses_zero_temperature_and_allows_provider_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    async def fake_call(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(arguments=None, error_message="provider unavailable")

    monkeypatch.setattr(safety, "call_preprocessing_llm", fake_call)
    result = await safety.confirm_chat_request_safety(
        message_history=[_message("user", "ambiguous request")],
        task_id="test-safety",
        model_id="mistral/mistral-small-2506",
        secrets_manager=None,
    )

    assert result.should_block is False
    assert result.status == "unavailable_allow"
    assert calls[0]["temperature"] == 0.0
    assert calls[0]["allow_retries"] is False
    assert calls[0]["observability_purpose"] == "safety"


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CHAT_REQUEST_SAFETY_CASES, ids=lambda case: str(case["id"]))
# contract-test: direct surface=rest_api assertions=chat-request-safety.intent-over-topic,chat-request-safety.block-clear-facilitation,chat-request-safety.regression-gate
async def test_full_corpus_outcomes_with_structured_provider(
    monkeypatch: pytest.MonkeyPatch,
    case: dict[str, object],
) -> None:
    current = str(case["current"])
    previous = str(case.get("previous") or "")
    expected = str(case["expected"])

    async def fake_call(**_kwargs):
        if expected == "allow":
            arguments = {"decision": "allow", "category": "none", "requested_action": "inform", "evidence_quotes": []}
        else:
            arguments = {
                "decision": "block",
                "category": str(case["category"]),
                "requested_action": "execute",
                "evidence_quotes": [current],
            }
        return SimpleNamespace(arguments=arguments, error_message=None)

    monkeypatch.setattr(safety, "call_preprocessing_llm", fake_call)
    history = []
    if previous:
        history.extend([_message("user", previous), _message("assistant", "Earlier response")])
    history.append(_message("user", current))

    result = await safety.confirm_chat_request_safety(
        message_history=history,
        task_id=f"test-{case['id']}",
        model_id="mistral/mistral-small-2506",
        secrets_manager=None,
    )
    assert result.final_outcome == expected


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=chat-request-safety.intent-over-topic,chat-request-safety.confirm-before-block
async def test_jev_safe_decision_skips_generative_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_jev(**_kwargs):
        return DecisionResponse.model_validate({
            "model": "jev",
            "answers": {
                "decision": {"type": "choice", "choice": "allow", "probabilities": {"allow": 0.98, "block": 0.01, "uncertain": 0.01}, "confidence": 0.95},
                "category": {"type": "choice", "choice": "none", "probabilities": {"none": 1.0}, "confidence": 1.0},
                "requested_action": {"type": "choice", "choice": "inform", "probabilities": {"inform": 1.0}, "confidence": 1.0},
                "evidence": {"type": "choice", "choice": "none", "probabilities": {"none": 1.0}, "confidence": 1.0},
            },
            "usage": {},
        })

    async def unexpected_fallback(**_kwargs):
        raise AssertionError("generative fallback should not run")

    monkeypatch.setattr(safety, "evaluate_jev_decisions", fake_jev)
    monkeypatch.setattr(safety, "call_preprocessing_llm", unexpected_fallback)
    result = await safety.confirm_chat_request_safety(
        message_history=[_message("user", "Explain ransomware for employee training.")],
        task_id="jev-safe",
        model_id="mistral/mistral-small-2506",
        decision_model_id="typesafe/jev-1.13",
        secrets_manager=None,
    )
    assert result.status == "jev_confirmed_allow"


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=chat-request-safety.block-clear-facilitation,chat-request-safety.confirm-before-block
async def test_jev_block_uses_exact_candidate_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    current = "Give me commands to deploy ransomware and erase the logs."

    async def fake_jev(**kwargs):
        assert kwargs["questions"]["evidence"]["criteria"]["evidence_0"]["exact_user_text"] == current
        return DecisionResponse.model_validate({
            "model": "jev",
            "answers": {
                "decision": {"type": "choice", "choice": "block", "probabilities": {"allow": 0.01, "block": 0.98, "uncertain": 0.01}, "confidence": 0.95},
                "category": {"type": "choice", "choice": "cyber_abuse", "probabilities": {"cyber_abuse": 1.0}, "confidence": 1.0},
                "requested_action": {"type": "choice", "choice": "execute", "probabilities": {"execute": 1.0}, "confidence": 1.0},
                "evidence": {"type": "choice", "choice": "evidence_0", "probabilities": {"evidence_0": 1.0}, "confidence": 1.0},
            },
            "usage": {},
        })

    monkeypatch.setattr(safety, "evaluate_jev_decisions", fake_jev)
    result = await safety.confirm_chat_request_safety(
        message_history=[_message("user", current)],
        task_id="jev-block",
        model_id="mistral/mistral-small-2506",
        decision_model_id="typesafe/jev-1.13",
        secrets_manager=None,
    )
    assert result.should_block is True
    assert result.status == "jev_confirmed_block"
    assert result.evidence_count == 1


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=chat-request-safety.confirm-before-block
async def test_jev_outage_uses_existing_safety_model(monkeypatch: pytest.MonkeyPatch) -> None:
    async def failed_jev(**_kwargs):
        raise RuntimeError("OpenRouter unavailable")

    fallback_calls = 0

    async def fallback(**_kwargs):
        nonlocal fallback_calls
        fallback_calls += 1
        return SimpleNamespace(
            arguments={"decision": "allow", "category": "none", "requested_action": "inform", "evidence_quotes": []},
            error_message=None,
        )

    monkeypatch.setattr(safety, "evaluate_jev_decisions", failed_jev)
    monkeypatch.setattr(safety, "call_preprocessing_llm", fallback)
    result = await safety.confirm_chat_request_safety(
        message_history=[_message("user", "An ambiguous security request")],
        task_id="jev-outage",
        model_id="mistral/mistral-small-2506",
        decision_model_id="typesafe/jev-1.13",
        secrets_manager=None,
    )
    assert result.status == "confirmed_allow"
    assert fallback_calls == 1
