"""Inline typed decisions; never creates chat, embed, file, or account state."""
from typing import Any

from backend.apps.base_skill import BaseSkill
from backend.shared.providers.typesafe.client import (
    DecisionProviderError, DecisionRequestTooLarge, JevDecisionClient,
)
from backend.shared.python_utils.ai_decide import (
    DecideRequest, DecideResponse, DecisionExecutionError, account_decision_attempts,
    decision_configuration, decision_quote, failed_decision_credits, validate_decision_answers,
)


class DecideSkill(BaseSkill):
    async def execute(self, request: DecideRequest, secrets_manager: Any = None, **kwargs: Any) -> DecideResponse:
        attempts: list[dict[str, Any]] = []
        pricing = None
        try:
            model, pricing = decision_configuration()
            response = await JevDecisionClient(
                secrets_manager=secrets_manager, model=model, max_retries=0,
                accounting=attempts, provider="typesafe" if request.assets else None,
            ).evaluate(state=request.state, questions={key: value.model_dump(exclude_none=True) for key, value in request.questions.items()},
                       **({"assets": {key: value.model_dump() for key, value in request.assets.items()}} if request.assets else {}))
            validate_decision_answers(request, response.answers)
            usage = account_decision_attempts(attempts, pricing)
            if usage.credits > decision_quote(pricing, has_assets=bool(request.assets)):
                raise ValueError("decision exceeded its admitted credit envelope")
            return DecideResponse(model=response.model, answers=response.answers, usage=usage)
        except DecisionRequestTooLarge as exc:
            raise DecisionExecutionError(status_code=422, code="decision_input_too_large", incurred_credits=failed_decision_credits(attempts, pricing)) from exc
        except (DecisionProviderError, ValueError) as exc:
            # Never disclose provider response text or private request content.
            raise DecisionExecutionError(incurred_credits=failed_decision_credits(attempts, pricing)) from exc
