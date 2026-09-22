"""Pydantic models for TypeSafe/System One decision responses."""

from __future__ import annotations

from typing import Dict, Literal, Union

from pydantic import BaseModel, Field, model_validator


class NoulAnswer(BaseModel):
    type: Literal["noul"]
    noul: float = Field(ge=0.0, le=1.0)

    @property
    def confidence(self) -> float:
        """Distance from an undecided 0.5, normalized to 0..1."""

        return abs(self.noul - 0.5) * 2.0


class ChoiceAnswer(BaseModel):
    type: Literal["choice"]
    choice: str
    probabilities: Dict[str, float]
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_choice(self) -> "ChoiceAnswer":
        if self.choice not in self.probabilities:
            raise ValueError("choice is missing from probabilities")
        if any(value < 0.0 or value > 1.0 for value in self.probabilities.values()):
            raise ValueError("choice probabilities must be within 0..1")
        return self


class ScoreAnswer(BaseModel):
    type: Literal["score"]
    score: float
    legend: Dict[str, str]
    probabilities: Dict[str, float]
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_score(self) -> "ScoreAnswer":
        if not self.legend or set(self.legend) != set(self.probabilities):
            raise ValueError("score legend and probabilities must have identical levels")
        if any(value < 0.0 or value > 1.0 for value in self.probabilities.values()):
            raise ValueError("score probabilities must be within 0..1")
        return self


DecisionAnswer = Union[NoulAnswer, ChoiceAnswer, ScoreAnswer]


class DecisionUsage(BaseModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class DecisionResponse(BaseModel):
    model: str
    answers: Dict[str, DecisionAnswer]
    usage: DecisionUsage = Field(default_factory=DecisionUsage)

