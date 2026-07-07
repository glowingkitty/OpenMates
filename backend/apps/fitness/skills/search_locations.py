# backend/apps/fitness/skills/search_locations.py
#
# Fitness location search skill backed by Urban Sports Club public pages.
#
# The skill accepts one or more requests, normalizes address/radius/plan inputs,
# and returns grouped app-skill results that can be rendered by CLI, SDK, web,
# and native embed surfaces without requiring Urban Sports credentials.

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.shared.providers.urban_sports import UrbanSportsClient


class FitnessLocationSearchRequestItem(BaseModel):
    id: Any | None = Field(default=None, description="Optional request correlation ID.")
    query: str | None = Field(default=None, description="Optional text filter such as yoga, pilates, HIIT, or venue name.")
    city: str | None = Field(default="Berlin", description="City name. Defaults to Berlin for Urban Sports city_id=1.")
    city_id: str | None = Field(default=None, description="Urban Sports Club city_id override.")
    address: str | None = Field(default=None, description="Street address used as radius center.")
    lat: float | None = Field(default=None, description="Latitude for radius center.")
    lon: float | None = Field(default=None, description="Longitude for radius center.")
    radius_km: float | None = Field(default=None, description="Radius in kilometers for distance filtering.")
    plan: str | None = Field(default=None, description="Optional plan filter: essential, classic, premium, or max. Omit for all plans.")
    category: str | None = Field(default=None, description="Optional Urban Sports category filter ID.")
    limit: int = Field(default=10, ge=1, le=50, description="Maximum number of locations to return.")
    language: str | None = Field(default="en", description="Urban Sports language path, usually en or de.")


class FitnessLocationSearchRequest(BaseModel):
    requests: list[FitnessLocationSearchRequestItem] = Field(..., description="Location search requests.")


class SearchLocationsSkill(BaseSkill):
    def __init__(
        self,
        app: Any,
        app_id: str,
        skill_id: str,
        skill_name: str,
        skill_description: str,
        full_model_reference: str | None = None,
        pricing_config: dict[str, Any] | None = None,
        celery_producer: Any | None = None,
        skill_operational_defaults: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            app=app,
            app_id=app_id,
            skill_id=skill_id,
            skill_name=skill_name,
            skill_description=skill_description,
            full_model_reference=full_model_reference,
            pricing_config=pricing_config,
            celery_producer=celery_producer,
            skill_operational_defaults=skill_operational_defaults,
        )
        self.client = UrbanSportsClient()

    @classmethod
    def resolve_preview_metadata(cls, request: dict[str, Any]) -> dict[str, Any]:
        normalized_request = _normalize_request_payload(request)
        first_request = (normalized_request.get("requests") or [{}])[0]
        return {
            "provider": "Urban Sports Club",
            "query": first_request.get("query"),
            "location": first_request.get("address") or first_request.get("city"),
            "radius_km": first_request.get("radius_km"),
            "plan": first_request.get("plan") or "all",
        }

    async def execute(self, input_data: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        request = FitnessLocationSearchRequest.model_validate(_normalize_request_payload(input_data or kwargs))
        groups = []
        for index, item in enumerate(request.requests):
            req = item.model_dump(exclude_none=True)
            request_id = req.get("id", index)
            plan = req.get("plan")
            req["plan"] = plan
            filters = _filters(req, plan=plan, attendance_mode=None)
            try:
                results = await self.client.search_locations(**{key: value for key, value in req.items() if key != "id"})
                groups.append(
                    {
                        "id": request_id,
                        "provider": "Urban Sports Club",
                        "result_count": len(results),
                        "filters": filters,
                        "summary": _summary("locations", len(results), plan=plan),
                        "results": results,
                    }
                )
            except Exception as exc:
                groups.append(
                    {
                        "id": request_id,
                        "provider": "Urban Sports Club",
                        "result_count": 0,
                        "filters": filters,
                        "summary": "Urban Sports Club location search failed.",
                        "results": [],
                        "error": f"Urban Sports Club search failed: {exc}",
                    }
                )
        return {
            "provider": "Urban Sports Club",
            "results": groups,
            "ignore_fields_for_inference": ["image_url", "lat", "lon", "venue_lat", "venue_lon"],
        }


def _normalize_request_payload(input_data: dict[str, Any]) -> dict[str, Any]:
    if "requests" in input_data:
        return input_data
    return {"requests": [{key: value for key, value in input_data.items() if not key.startswith("_")}]}


def _filters(req: dict[str, Any], *, plan: str | None, attendance_mode: str | None) -> dict[str, Any]:
    filters = {
        "query": req.get("query"),
        "city": req.get("city") or "Berlin",
        "address": req.get("address"),
        "radius_km": req.get("radius_km"),
        "plan": plan or "all",
    }
    if attendance_mode:
        filters["attendance_mode"] = attendance_mode
    return {key: value for key, value in filters.items() if value is not None}


def _summary(kind: str, count: int, *, plan: str | None) -> str:
    plan_text = f"Filtered to {plan.title()} plan." if plan else "Searched all Urban Sports plans."
    return f"Found {count} Urban Sports {kind}. {plan_text}"
