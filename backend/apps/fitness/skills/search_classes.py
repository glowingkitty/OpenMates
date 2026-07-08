# backend/apps/fitness/skills/search_classes.py
#
# Fitness class search skill backed by Urban Sports Club public pages.
#
# Address/radius searches default to on-site classes because online class
# distance is not meaningful. Plan filters are opt-in; omitting plan searches all
# public plans and preserves each class's required-plan labels.

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.shared.providers.urban_sports import UrbanSportsClient


class FitnessClassSearchRequestItem(BaseModel):
    id: Any | None = Field(default=None, description="Optional request correlation ID.")
    query: str | None = Field(default=None, description="Optional class/category/venue text filter.")
    city: str | None = Field(default="Berlin", description="City name. Defaults to Berlin for Urban Sports city_id=1.")
    city_id: str | None = Field(default=None, description="Urban Sports Club city_id override.")
    address: str | None = Field(default=None, description="Street address used as radius center.")
    lat: float | None = Field(default=None, description="Latitude for radius center.")
    lon: float | None = Field(default=None, description="Longitude for radius center.")
    radius_km: float | None = Field(default=None, description="Radius in kilometers for distance filtering.")
    start_date: str | None = Field(default=None, description="Start date as YYYY-MM-DD. Defaults to today.")
    end_date: str | None = Field(default=None, description="End date as YYYY-MM-DD.")
    days: int | None = Field(default=1, ge=1, le=14, description="Days to search when end_date is omitted.")
    plan: str | None = Field(default=None, description="Optional plan filter: essential, classic, premium, or max. Omit for all plans.")
    attendance_mode: str | None = Field(default=None, description="onsite, online, or all. Address/radius searches default to onsite.")
    min_spots: int = Field(default=1, ge=0, description="Minimum available spots.")
    category: str | None = Field(default=None, description="Optional Urban Sports category filter ID.")
    venue_id: str | None = Field(default=None, description="Optional Urban Sports venue filter ID.")
    limit: int = Field(default=10, ge=1, le=50, description="Maximum number of classes to return.")
    language: str | None = Field(default="en", description="Urban Sports language path, usually en or de.")


class FitnessClassSearchRequest(BaseModel):
    requests: list[FitnessClassSearchRequestItem] = Field(..., description="Class search requests.")


class SearchClassesSkill(BaseSkill):
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
        attendance_mode = _default_attendance_mode(first_request)
        return {
            "provider": "Urban Sports Club",
            "query": first_request.get("query"),
            "location": first_request.get("address") or first_request.get("city"),
            "radius_km": first_request.get("radius_km"),
            "date": first_request.get("start_date"),
            "plan": first_request.get("plan") or "all",
            "attendance_mode": attendance_mode,
        }

    async def execute(self, input_data: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        request = FitnessClassSearchRequest.model_validate(_normalize_request_payload(input_data or kwargs))
        groups = []
        for index, item in enumerate(request.requests):
            req = item.model_dump(exclude_none=True)
            request_id = req.pop("id", index)
            req["attendance_mode"] = _default_attendance_mode(req)
            plan = req.get("plan")
            req["plan"] = plan
            filters = _filters(req, plan=plan, attendance_mode=req["attendance_mode"])
            try:
                results = await self.client.search_classes(**req)
                groups.append(
                    {
                        "id": request_id,
                        "provider": "Urban Sports Club",
                        "result_count": len(results),
                        "filters": filters,
                        "summary": _summary(len(results), plan=plan, attendance_mode=req["attendance_mode"]),
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
                        "summary": "Urban Sports Club class search failed.",
                        "results": [],
                        "error": f"Urban Sports Club search failed: {exc}",
                    }
                )
        return {
            "provider": "Urban Sports Club",
            "results": groups,
            "ignore_fields_for_inference": ["image_url", "venue_lat", "venue_lon", "lat", "lon"],
        }


def _normalize_request_payload(input_data: dict[str, Any]) -> dict[str, Any]:
    if "requests" in input_data:
        return input_data
    return {"requests": [{key: value for key, value in input_data.items() if not key.startswith("_")}]}


def _default_attendance_mode(req: dict[str, Any]) -> str:
    raw = (req.get("attendance_mode") or "").casefold().strip()
    if raw in {"online", "onsite", "all"}:
        return raw
    if req.get("address") or req.get("radius_km") is not None:
        return "onsite"
    return "all"


def _filters(req: dict[str, Any], *, plan: str | None, attendance_mode: str) -> dict[str, Any]:
    filters = {
        "query": req.get("query"),
        "city": req.get("city") or "Berlin",
        "address": req.get("address"),
        "radius_km": req.get("radius_km"),
        "start_date": req.get("start_date"),
        "end_date": req.get("end_date"),
        "days": req.get("days"),
        "plan": plan or "all",
        "attendance_mode": attendance_mode,
        "min_spots": req.get("min_spots"),
    }
    return {key: value for key, value in filters.items() if value is not None}


def _summary(count: int, *, plan: str | None, attendance_mode: str) -> str:
    plan_text = f"Filtered to {plan.title()} plan." if plan else "Searched all Urban Sports plans."
    return f"Found {count} Urban Sports classes in {attendance_mode} mode. {plan_text}"
