"""Request-safety confirmation and fixed-corpus regression tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.apps.ai.processing import chat_request_safety as safety
from backend.apps.ai.testing.chat_request_safety_cases import CHAT_REQUEST_SAFETY_CASES


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
