# backend/apps/weather/skills/forecast_skill.py
#
# Weather forecast skill implementation.
# Produces one normalized weather_day result per requested forecast day.
# Full hourly details are stored in embeds while heavy fields are hidden from LLM inference.
#
# Architecture: docs/architecture/apps/app-skills.md

from __future__ import annotations

import logging
from datetime import datetime, timezone as datetime_timezone
from typing import Any

from celery import Celery
from pydantic import BaseModel, Field, model_validator

from backend.apps.base_skill import BaseSkill
from backend.shared.providers.bright_sky import fetch_weather, normalize_weather_days
from backend.shared.providers.open_meteo import (
    fetch_forecast,
    geocode_location,
    normalize_forecast_days,
)

logger = logging.getLogger(__name__)

DEFAULT_FORECAST_DAYS = 7
MAX_FORECAST_DAYS = 14
GERMANY_COUNTRY_CODE = "DE"
DEFAULT_TIMEZONE = "Europe/Berlin"
METRIC_UNITS = "metric"
DWD_PROVIDER_LABEL = "Deutscher Wetterdienst (DWD)"
OPEN_METEO_PROVIDER_LABEL = "Open-Meteo"
WEATHER_INFERENCE_EXCLUDE_FIELDS = [
    "type",
    "hourly",
    "source",
    "provider_raw",
    "fallback_source_ids",
    "data_quality",
]


class ForecastRequest(BaseModel):
    """Weather forecast request parameters."""

    location: str | None = Field(default=None, description="Place name for the forecast.")
    days: int = Field(default=DEFAULT_FORECAST_DAYS, ge=1, le=MAX_FORECAST_DAYS)
    latitude: float | None = Field(default=None, description="Optional exact latitude.")
    longitude: float | None = Field(default=None, description="Optional exact longitude.")
    timezone: str | None = Field(default=None, description="Optional IANA timezone.")
    units: str = Field(default=METRIC_UNITS, description="Unit system. Only metric is supported.")

    @model_validator(mode="after")
    def validate_location_or_coordinates(self) -> "ForecastRequest":
        """Require either a location name or a complete coordinate pair."""
        has_location = bool(self.location and self.location.strip())
        has_coordinates = self.latitude is not None and self.longitude is not None
        if not has_location and not has_coordinates:
            raise ValueError("Provide either location or latitude and longitude.")
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together.")
        if self.units != METRIC_UNITS:
            raise ValueError("Only metric units are currently supported.")
        return self


class ForecastResponse(BaseModel):
    """Weather forecast skill response."""

    results: list[dict[str, Any]] = Field(default_factory=list)
    provider: str
    location: dict[str, Any]
    days_requested: int
    suggestions_follow_up_requests: list[str] = Field(default_factory=list)
    ignore_fields_for_inference: list[str] = Field(default_factory=lambda: list(WEATHER_INFERENCE_EXCLUDE_FIELDS))
    error: str | None = None


class ForecastSkill(BaseSkill):
    """Get weather forecasts with one detailed embed-ready result per day."""

    def __init__(
        self,
        app: Any,
        app_id: str,
        skill_id: str,
        skill_name: str,
        skill_description: str,
        stage: str = "development",
        full_model_reference: str | None = None,
        pricing_config: dict[str, Any] | None = None,
        celery_producer: Celery | None = None,
        skill_operational_defaults: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            app=app,
            app_id=app_id,
            skill_id=skill_id,
            skill_name=skill_name,
            skill_description=skill_description,
            stage=stage,
            full_model_reference=full_model_reference,
            pricing_config=pricing_config,
            celery_producer=celery_producer,
            skill_operational_defaults=skill_operational_defaults,
        )

    @classmethod
    def resolve_preview_metadata(cls, request: dict[str, Any]) -> dict[str, Any]:
        """Return fields shown while the forecast skill is processing."""
        location = request.get("location") or "Weather forecast"
        days = request.get("days") or DEFAULT_FORECAST_DAYS
        return {
            "query": f"{location} weather forecast",
            "location": location,
            "days_requested": days,
            "provider": f"{DWD_PROVIDER_LABEL} + {OPEN_METEO_PROVIDER_LABEL}",
        }

    async def _resolve_location(self, request: ForecastRequest) -> dict[str, Any]:
        """Resolve request location to coordinates and display metadata."""
        if request.latitude is not None and request.longitude is not None:
            return {
                "name": request.location or f"{request.latitude:.4f}, {request.longitude:.4f}",
                "country_code": None,
                "country": None,
                "latitude": request.latitude,
                "longitude": request.longitude,
                "timezone": request.timezone or DEFAULT_TIMEZONE,
            }

        assert request.location is not None
        resolved = await geocode_location(request.location)
        if not resolved:
            raise ValueError(f"Could not resolve weather location: {request.location}")
        if resolved.get("latitude") is None or resolved.get("longitude") is None:
            raise ValueError(f"Resolved weather location lacks coordinates: {request.location}")
        if request.timezone:
            resolved["timezone"] = request.timezone
        return resolved

    async def execute(
        self,
        location: str | None = None,
        days: int = DEFAULT_FORECAST_DAYS,
        latitude: float | None = None,
        longitude: float | None = None,
        timezone: str | None = None,
        units: str = METRIC_UNITS,
        **kwargs: Any,
    ) -> ForecastResponse:
        """Execute the forecast skill and return embed-ready day results."""
        try:
            request = ForecastRequest(
                location=location,
                days=days,
                latitude=latitude,
                longitude=longitude,
                timezone=timezone,
                units=units,
            )
            resolved_location = await self._resolve_location(request)
            resolved_timezone = resolved_location.get("timezone") or timezone or DEFAULT_TIMEZONE
            location_name = str(resolved_location.get("name") or location or "Weather forecast")
            country_code = resolved_location.get("country_code")
            lat = float(resolved_location["latitude"])
            lon = float(resolved_location["longitude"])

            if country_code == GERMANY_COUNTRY_CODE:
                provider_payload = await fetch_weather(
                    latitude=lat,
                    longitude=lon,
                    start_date=datetime.now(datetime_timezone.utc).date(),
                    days=request.days,
                    timezone=resolved_timezone,
                )
                results = normalize_weather_days(
                    provider_payload,
                    location_name=location_name,
                    country_code=country_code,
                    timezone=resolved_timezone,
                    requested_days=request.days,
                )
                provider = DWD_PROVIDER_LABEL
            else:
                provider_payload = await fetch_forecast(
                    latitude=lat,
                    longitude=lon,
                    days=request.days,
                    timezone=resolved_timezone,
                )
                results = normalize_forecast_days(
                    provider_payload,
                    location_name=location_name,
                    country_code=country_code,
                    timezone=resolved_timezone,
                    requested_days=request.days,
                )
                provider = OPEN_METEO_PROVIDER_LABEL

            return ForecastResponse(
                results=results,
                provider=provider,
                location={
                    "name": location_name,
                    "country": resolved_location.get("country"),
                    "country_code": country_code,
                    "admin1": resolved_location.get("admin1"),
                    "latitude": lat,
                    "longitude": lon,
                    "timezone": resolved_timezone,
                },
                days_requested=request.days,
                suggestions_follow_up_requests=[
                    "When will it rain exactly?",
                    "Show the hourly forecast for one day",
                    "Compare the next few days",
                ],
            )
        except Exception as error:
            logger.error("ForecastSkill failed: %s", error, exc_info=True)
            return ForecastResponse(
                results=[],
                provider="Weather",
                location={"name": location or "Weather forecast"},
                days_requested=days,
                error=str(error),
            )
