"""Investor search schemas and the explicit unavailable capability boundary.

The skill ships paused without a built-in provider. Operator-installed providers
serve it through the generic ``skill.requests@1`` flat contract; the flat
delegate fills ``InvestorSearchResponse`` from their results.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    StrictStr,
    StringConstraints,
)

from backend.apps.base_skill import BaseSkill

SEARCH_LIMITATION = (
    "Results are public self-descriptions of investors from the searched sources. "
    "They are not a recommendation, and portfolios, ticket sizes and activity are not verified."
)

REGION_PATTERN = r"^([A-Z]{2}|WORLDWIDE)$"
CURRENCY_PATTERN = r"^[A-Z]{3}$"
RegionCode = Annotated[str, StringConstraints(pattern=REGION_PATTERN)]
InvestorType = Literal["angel", "angel_network", "vc", "family_office", "accelerator", "public_funding"]
InvestorStage = Literal["pre_seed", "seed", "series_a", "later"]


class InvestorSearchRequest(BaseModel):
    """Flat tool input; the whole validated model is sent to every installed provider."""

    model_config = ConfigDict(extra="forbid")
    query: StrictStr = Field(min_length=1, max_length=200)
    regions: list[RegionCode] = Field(min_length=1, max_length=10)
    investor_types: list[InvestorType] = Field(default_factory=list, max_length=6)
    stages: list[InvestorStage] = Field(default_factory=list, max_length=4)
    ticket_min: StrictInt | StrictFloat | None = Field(default=None, ge=0)
    ticket_max: StrictInt | StrictFloat | None = Field(default=None, ge=0)
    currency: StrictStr = Field(default="EUR", pattern=CURRENCY_PATTERN)
    max_results: StrictInt = Field(default=15, ge=1, le=30)


class InvestorSearchResponse(BaseModel):
    """Whole response saved as one embed; investors stay inside it.

    The list is deliberately not named ``results``: a top-level ``results`` array
    is flattened into child embeds by the shared inference pipeline. The flat
    delegate falls back to the first list-of-objects field, which is ``investors``.
    """

    success: bool = False
    app_id: str = "business"
    skill_id: str = "search_investors"
    status: str = "finished"
    query: str = ""
    regions: list[str] = Field(default_factory=list)
    provider: str = ""
    providers: list[str] = Field(default_factory=list)
    result_count: int = 0
    investors: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    partial: bool = False
    limitation: str = SEARCH_LIMITATION
    error: str | None = None
    error_code: str | None = None


class SearchInvestorsSkill(BaseSkill):
    """Preserve the capability path while no provider is installed."""

    async def execute(self, *args: Any, **kwargs: Any) -> InvestorSearchResponse:
        return InvestorSearchResponse(
            error="No permitted provider is available for this capability.",
            error_code="provider_unavailable",
        )
