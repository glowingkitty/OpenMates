"""Application helpers for Jev-backed bounded decisions."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.typesafe.client import JevDecisionClient
from backend.shared.providers.typesafe.models import ChoiceAnswer, DecisionResponse, NoulAnswer, ScoreAnswer


async def evaluate_jev_decisions(
    *,
    state: Any,
    questions: Mapping[str, Mapping[str, Any]],
    secrets_manager: Optional[SecretsManager],
    model_id: str,
) -> DecisionResponse:
    client = JevDecisionClient(secrets_manager=secrets_manager, model=model_id)
    return await client.evaluate(state=state, questions=questions)


def choice_value(response: DecisionResponse, question_id: str, *, min_confidence: float = 0.0) -> str:
    answer = response.answers.get(question_id)
    if not isinstance(answer, ChoiceAnswer) or answer.confidence < min_confidence:
        raise ValueError(f"unreliable choice decision: {question_id}")
    return answer.choice


def noul_value(response: DecisionResponse, question_id: str) -> float:
    answer = response.answers.get(question_id)
    if not isinstance(answer, NoulAnswer):
        raise ValueError(f"missing Noul decision: {question_id}")
    return answer.noul


def score_value(response: DecisionResponse, question_id: str, *, min_confidence: float = 0.0) -> float:
    answer = response.answers.get(question_id)
    if not isinstance(answer, ScoreAnswer) or answer.confidence < min_confidence:
        raise ValueError(f"unreliable score decision: {question_id}")
    return answer.score
