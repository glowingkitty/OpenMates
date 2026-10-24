"""Search schemas and explicit unavailable capability boundary."""

from __future__ import annotations


from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from backend.apps.base_skill import BaseSkill


SEARCH_LIMITATION = "Preliminary name search only. No results do not establish legal availability; unregistered rights and other jurisdictions may still matter. Spelling similarity is not a complete phonetic, visual or legal similarity assessment."


class TrademarkSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    queries: list[StrictStr] = Field(min_length=1, max_length=3)
    regions: list[Literal["US", "EU", "DE", "WORLDWIDE"]] = Field(
        min_length=1, max_length=4
    )
    nice_classes: list[StrictInt] = Field(default_factory=list, max_length=10)
    status: Literal["active", "all"] = "active"
    match: Literal["exact", "similar"] = "similar"
    max_results: StrictInt = Field(default=10, ge=1, le=20)


class TrademarkSearchResponse(BaseModel):
    success: bool = False
    app_id: str = "business"
    skill_id: str = "search_trademarks"
    status: str = "finished"
    query: str = ""
    regions: list[str] = Field(default_factory=list)
    nice_classes: list[int] = Field(default_factory=list)
    status_filter: Literal["active", "all"] = "active"
    match: Literal["exact", "similar"] = "similar"
    provider: str = ""
    result_count: int = 0
    # Keep the entire response as one saved embed, including zero-match coverage.
    # A top-level results array would be flattened by the shared inference pipeline.
    matches: list[dict[str, Any]] = Field(default_factory=list)
    coverage: list[dict[str, Any]] = Field(default_factory=list)
    partial: bool = False
    limitation: str = SEARCH_LIMITATION
    summary: str | None = None
    error: str | None = None
    error_code: str | None = None


class SearchTrademarksSkill(BaseSkill):
    """Preserve the capability path while no permitted provider is configured."""

    async def execute(self, *args: Any, **kwargs: Any):
        return TrademarkSearchResponse(
            error="No permitted provider is available for this capability.",
            error_code="provider_unavailable",
        )
