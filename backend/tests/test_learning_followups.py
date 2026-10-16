# contract-test-file: supporting surface=rest_api assertions=focus-modes.learning.progress-and-suggestions
"""Exercise-aware chip validation retains hints and drops answer leaks/uncertainty."""

from unittest.mock import AsyncMock
import pytest
from backend.apps.ai.processing import learning_followups as guard
from backend.shared.providers.typesafe.models import DecisionResponse, ChoiceAnswer


def response(choices):
    return DecisionResponse(
        model="test",
        answers={
            f"suggestion_{i}": ChoiceAnswer(
                type="choice", choice=c, confidence=0.9, probabilities={c: 1}
            )
            for i, c in enumerate(choices)
        },
    )


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=focus-modes.learning.progress-and-suggestions
async def test_fraction_spoiler_removed_but_hint_retained(monkeypatch):
    decide = AsyncMock(return_value=response(["safe"]))
    monkeypatch.setattr(guard, "evaluate_jev_decisions", decide)
    got = await guard.filter_learning_followups(
        [
            "Convert 7/10 to a decimal",
            "Give me a small hint",
            "Explain why 0.7 is the answer",
        ],
        assistant_response="Try 1/5 + 1/2. What do you think?",
        user_message="Give me a practice problem.",
        message_history=[],
        teaching_context={"phase": "guided_practice"},
        secrets_manager=None,
        model_id="test",
    )
    assert got == ["Give me a small hint"]
    state = decide.call_args.kwargs["state"]
    assert "1/5 + 1/2" in state["assistant_response"]
    assert state["teaching_context"]["phase"] == "guided_practice"


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=focus-modes.learning.progress-and-suggestions
async def test_new_question_number_words_withheld_even_if_classifier_would_approve(
    monkeypatch,
):
    decide = AsyncMock(return_value=response(["safe"]))
    monkeypatch.setattr(guard, "evaluate_jev_decisions", decide)
    got = await guard.filter_learning_followups(
        [
            "Calculate the decimal value of thirteen twentieths using division",
            "Give me a small hint",
        ],
        assistant_response="Your previous 7/10 is correct. Now try 1/4 + 2/5. What do you think?",
        user_message="I solved the previous problem.",
        message_history=[],
        teaching_context={},
        secrets_manager=None,
        model_id="test",
    )
    assert got == ["Give me a small hint"]
    assert decide.call_args.kwargs["state"]["suggestions"] == ["Give me a small hint"]


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=focus-modes.learning.progress-and-suggestions
async def test_unavailable_decision_does_not_publish_unverified_chips(monkeypatch):
    monkeypatch.setattr(
        guard, "evaluate_jev_decisions", AsyncMock(side_effect=RuntimeError("offline"))
    )
    assert (
        await guard.filter_learning_followups(
            ["Give me a small hint"],
            assistant_response="Try 1/5 + 1/2.",
            user_message="Practice",
            message_history=[],
            teaching_context={},
            secrets_manager=None,
            model_id="test",
        )
        == []
    )
