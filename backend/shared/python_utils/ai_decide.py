"""Bounded public decision contract and server-side token accounting.

No request content is persisted. Provider context ceilings bound reservations;
proxy token estimates alone cannot bound Jev's native token usage.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from backend.shared.providers.typesafe.models import DecisionAnswer
from backend.shared.providers.typesafe.assets import (
    AssetReference, DecisionImageAsset, MAX_ASSETS, validate_asset_references,
)
from backend.shared.python_utils.billing_utils import calculate_total_credits

MAX_REQUEST_BYTES = 16_384
PROVIDER_INPUT_CEILINGS = {"typesafe": 64_000, "openrouter": 262_144}
Text = Annotated[str, Field(min_length=1, max_length=500)]
Label = Annotated[str, Field(min_length=1, max_length=64)]


class NoulQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["noul"]
    instructions: str = Field(min_length=1, max_length=2000)
    criteria: dict[Literal["true", "false"], Text] | None = None

    @model_validator(mode="after")
    def complete_criteria(self) -> NoulQuestion:
        if self.criteria is not None and set(self.criteria) != {"true", "false"}:
            raise ValueError("noul criteria must define true and false")
        return self


class ChoiceQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["choice"]
    instructions: str = Field(min_length=1, max_length=2000)
    criteria: dict[Label, Text] = Field(min_length=2, max_length=16)


class ScoreQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["score"]
    instructions: str = Field(min_length=1, max_length=2000)
    criteria: list[Text] = Field(min_length=2, max_length=10)


Question = Annotated[NoulQuestion | ChoiceQuestion | ScoreQuestion, Field(discriminator="type")]


class DecideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    state: JsonValue
    questions: dict[Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")], Question] = Field(min_length=1, max_length=16)
    assets: dict[AssetReference, DecisionImageAsset] = Field(default_factory=dict, max_length=MAX_ASSETS, repr=False)

    @model_validator(mode="after")
    def bounded_json(self) -> DecideRequest:
        public_text = self.model_dump(exclude_none=True, exclude={"assets"})
        serialized = json.dumps(public_text, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        if len(serialized.encode("utf-8")) > MAX_REQUEST_BYTES:
            raise ValueError("decision request exceeds 16384 UTF-8 bytes")
        validate_asset_references(self.assets, self.state, public_text["questions"])
        return self


class DecideUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    credits: int = Field(ge=1)
    complete: bool = True


class DecideResponse(BaseModel):
    success: bool = True
    model: str
    answers: dict[str, DecisionAnswer]
    usage: DecideUsage


class DecisionExecutionError(HTTPException):
    """Safe public failure plus private, server-produced incurred accounting.

    The attribute is transported only by in-process dispatch. It is never part
    of HTTP detail, response metadata, or caller-controlled request fields.
    """
    def __init__(self, *, incurred_credits: int, status_code: int = 503, code: str = "decision_provider_unavailable") -> None:
        super().__init__(status_code=status_code, detail={"code": code, "message": "The decision provider or its usage accounting is unavailable. Try again later."})
        self.incurred_credits = incurred_credits


def decision_configuration() -> tuple[str, dict[str, Any]]:
    """Read the existing server decision model and its catalog tariff."""
    root = Path(__file__).resolve().parents[2]
    app = yaml.safe_load((root / "apps/ai/app.yml").read_text())
    ask = next(skill for skill in app["skills"] if skill["id"] == "ask")
    model = ask["skill_config"]["default_llms"]["decision_model"]
    # The provider context ceilings below apply only to the reviewed Jev route.
    if model != "typesafe/jev-1.14":
        raise ValueError("decision model has no reviewed public billing envelope")
    provider = yaml.safe_load((root / "providers/typesafe.yml").read_text())
    catalog_model = next(item for item in provider["models"] if item["id"] == "jev-1.14")
    pricing = catalog_model["pricing"]
    tokens = pricing["tokens"]
    unit = tokens["input"]["per_credit_unit"]
    if type(unit) is not int or unit <= 0 or tokens["output"]["per_credit_unit"] != 0:
        raise ValueError("decision tariff has no reviewed public billing envelope")
    return model, pricing


def decision_quote(pricing: dict[str, Any] | None = None, *, has_assets: bool = False) -> int:
    if pricing is None:
        _, pricing = decision_configuration()
    unit = pricing["tokens"]["input"]["per_credit_unit"]
    providers = ("typesafe",) if has_assets else tuple(PROVIDER_INPUT_CEILINGS)
    return sum(math.ceil(PROVIDER_INPUT_CEILINGS[provider] / unit) for provider in providers)


def account_decision_attempts(attempts: list[dict[str, Any]], pricing: dict[str, Any]) -> DecideUsage:
    """Settle known native usage, retaining the ceiling for ambiguous attempts."""
    if not attempts or not attempts[-1]["success"]:
        raise ValueError("decision usage unavailable")
    input_total = output_total = credits = 0
    complete = True
    seen: set[str] = set()
    for attempt in attempts:
        provider = attempt["provider"]
        if provider not in PROVIDER_INPUT_CEILINGS or provider in seen:
            raise ValueError("decision exceeded its attempt envelope")
        seen.add(provider)
        input_tokens, output_tokens = attempt["input_tokens"], attempt["output_tokens"]
        known = type(input_tokens) is int and input_tokens > 0 and type(output_tokens) is int and output_tokens >= 0
        if known and input_tokens > PROVIDER_INPUT_CEILINGS[provider]:
            raise ValueError("decision exceeded its token envelope")
        if not known:
            if attempt["success"]:
                raise ValueError("decision provider omitted valid native usage")
            complete = False
            credits += math.ceil(PROVIDER_INPUT_CEILINGS[provider] / pricing["tokens"]["input"]["per_credit_unit"])
        else:
            input_total += input_tokens
            output_total += output_tokens
            credits += calculate_total_credits(pricing_config=pricing, input_tokens=input_tokens, output_tokens=output_tokens)
    if credits > decision_quote(pricing):
        raise ValueError("decision exceeded its credit envelope")
    return DecideUsage(input_tokens=input_total, output_tokens=output_total, credits=credits, complete=complete)


def failed_decision_credits(attempts: list[dict[str, Any]], pricing: dict[str, Any] | None) -> int:
    """Retain already-incurred spend permanently, beyond reservation expiry."""
    if not attempts:
        return 0
    if pricing is None:
        raise ValueError("decision attempt has no admitted tariff")
    credits = 0
    for attempt in attempts:
        ceiling = PROVIDER_INPUT_CEILINGS[attempt["provider"]]
        input_tokens, output_tokens = attempt["input_tokens"], attempt["output_tokens"]
        if type(input_tokens) is int and 0 < input_tokens <= ceiling and type(output_tokens) is int and output_tokens >= 0:
            credits += calculate_total_credits(pricing_config=pricing, input_tokens=input_tokens, output_tokens=output_tokens)
        else:
            credits += math.ceil(ceiling / pricing["tokens"]["input"]["per_credit_unit"])
    return min(credits, decision_quote(pricing))


def validate_decision_answers(request: DecideRequest, answers: dict[str, DecisionAnswer]) -> None:
    if set(answers) != set(request.questions):
        raise ValueError("decision answer ids do not match the request")
    for question_id, question in request.questions.items():
        answer = answers[question_id]
        if answer.type != question.type:
            raise ValueError("decision answer type does not match the request")
        if question.type == "noul":
            continue
        expected = set(question.criteria) if question.type == "choice" else {str(i) for i in range(len(question.criteria))}
        if set(answer.probabilities) != expected or any(not math.isfinite(p) for p in answer.probabilities.values()):
            raise ValueError("decision answer categories do not match the request")
        if not math.isclose(sum(answer.probabilities.values()), 1.0, abs_tol=1e-3):
            raise ValueError("decision answer probabilities must sum to one")
        if question.type == "score" and (not math.isfinite(answer.score) or not 0 <= answer.score <= len(question.criteria) - 1 or answer.legend != {str(i): text for i, text in enumerate(question.criteria)}):
            raise ValueError("decision score does not match the requested scale")


def decision_result_credits(result: Any, *, has_assets: bool = False) -> int:
    if isinstance(result, list) and len(result) == 1:
        result = result[0]
    response = DecideResponse.model_validate(result)
    if not response.success or response.usage.credits > decision_quote(has_assets=has_assets):
        raise ValueError("decision result has invalid billing")
    return response.usage.credits
