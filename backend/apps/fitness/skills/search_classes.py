"""Search schemas and explicit unavailable capability boundary."""

from __future__ import annotations


from typing import Any

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill


MAX_CONCURRENT_GROUPS = 3


class FitnessClassSearchRequestItem(BaseModel):
    id: Any | None = Field(default=None, description="Optional request correlation ID.")
    query: str | None = Field(
        default=None, description="Optional class/category/venue text filter."
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
    start_date: str | None = Field(
        default=None, description="Start date as YYYY-MM-DD. Defaults to today."
    )
    end_date: str | None = Field(default=None, description="End date as YYYY-MM-DD.")
    days: int | None = Field(
        default=1, ge=1, le=14, description="Days to search when end_date is omitted."
    )
    plan: str | None = Field(
        default=None,
        description="Optional plan filter: essential, classic, premium, or max. Omit for all plans.",
    )
    attendance_mode: str | None = Field(
        default=None,
        description="onsite, online, or all. Address/radius searches default to onsite.",
    )
    min_spots: int = Field(default=1, ge=0, description="Minimum available spots.")
    category: str | None = Field(
        default=None,
        description="Optional Fitness activity name or numeric category ID.",
    )
    venue_id: str | None = Field(
        default=None, description="Optional Fitness venue filter ID."
    )
    limit: int = Field(
        default=10, ge=1, le=50, description="Maximum number of classes to return."
    )
    relevance_criteria: str | None = Field(
        default=None,
        max_length=1_000,
        description="Optional natural-language activity goal used only to rank matching classes.",
    )
    language: str | None = Field(
        default="en", description="Fitness language path, usually en or de."
    )


class FitnessClassSearchRequest(BaseModel):
    requests: list[FitnessClassSearchRequestItem] = Field(
        ..., description="Class search requests."
    )


class SearchClassesSkill(BaseSkill):
    """Preserve the capability path while no permitted provider is configured."""

    async def execute(self, *args: Any, **kwargs: Any):
        return {
            "success": False,
            "app_id": "fitness",
            "skill_id": "search_classes",
            "results": [],
            "result_count": 0,
            "error": "No permitted provider is available for this capability.",
            "error_code": "provider_unavailable",
        }
