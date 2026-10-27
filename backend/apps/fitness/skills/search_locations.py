"""Search schemas and explicit unavailable capability boundary."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill


class FitnessLocationSearchRequestItem(BaseModel):
    id: Any | None = Field(default=None, description="Optional request correlation ID.")
    query: str | None = Field(
        default=None,
        description="Optional text filter such as yoga, pilates, HIIT, or venue name.",
    )
    city: str | None = Field(
        default="Berlin",
        description="City name. Defaults to Berlin for Fitness city_id=1.",
    )
    city_id: str | None = Field(default=None, description="Fitness city_id override.")
    address: str | None = Field(
        default=None, description="Street address used as radius center."
    )
    lat: float | None = Field(default=None, description="Latitude for radius center.")
    lon: float | None = Field(default=None, description="Longitude for radius center.")
    radius_km: float | None = Field(
        default=None, description="Radius in kilometers for distance filtering."
    )
    plan: str | None = Field(
        default=None,
        description="Optional plan filter: essential, classic, premium, or max. Omit for all plans.",
    )
    category: str | None = Field(
        default=None, description="Optional Fitness category filter ID."
    )
    limit: int = Field(
        default=10, ge=1, le=50, description="Maximum number of locations to return."
    )
    relevance_criteria: str | None = Field(
        default=None,
        max_length=1_000,
        description="Optional natural-language activity goal used only to rank matching locations.",
    )
    language: str | None = Field(
        default="en", description="Fitness language path, usually en or de."
    )


class FitnessLocationSearchRequest(BaseModel):
    requests: list[FitnessLocationSearchRequestItem] = Field(
        ..., description="Location search requests."
    )


class SearchLocationsSkill(BaseSkill):
    """Preserve the capability path while no permitted provider is configured."""

    async def execute(self, *args: Any, **kwargs: Any):
        return {
            "success": False,
            "app_id": "fitness",
            "skill_id": "search_locations",
            "results": [],
            "result_count": 0,
            "error": "No permitted provider is available for this capability.",
            "error_code": "provider_unavailable",
        }
