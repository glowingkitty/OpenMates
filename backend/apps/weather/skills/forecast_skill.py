# backend/apps/weather/skills/forecast_skill.py
#
# Weather forecast skill implementation.
# Produces one normalized weather_day result per requested forecast day.
# Full hourly details are stored in embeds while heavy fields are hidden from LLM inference.
#
# Architecture: docs/architecture/apps/app-skills.md

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from celery import Celery
from pydantic import BaseModel, Field, ValidationError, model_validator

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
DWD_PROVIDER_ID = "deutscher_wetterdienst"
OPEN_METEO_PROVIDER_ID = "open_meteo"
WEATHER_INFERENCE_EXCLUDE_FIELDS = [
    "type",
    "hourly",
    "source",
    "provider_raw",
    "fallback_source_ids",
    "data_quality",
]


def _readable_forecast_error(error: Exception) -> str:
    """Collapse Pydantic's developer-oriented validation report for skill users."""
    if not isinstance(error, ValidationError):
        return str(error)
    messages: list[str] = []
    for detail in error.errors(include_url=False):
        message = str(detail.get("msg") or "Invalid forecast input")
        messages.append(message.removeprefix("Value error, "))
    return "; ".join(messages)


class ForecastRequest(BaseModel):
    """Weather forecast request parameters."""

    location: str | None = Field(default=None, description="Place name for the forecast.")
    start_date: date | None = Field(default=None, description="First forecast date, inclusive.")
    end_date: date | None = Field(default=None, description="Last forecast date, inclusive.")
    days: int | None = Field(default=None, ge=1, le=MAX_FORECAST_DAYS)
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
        has_start = self.start_date is not None
        has_end = self.end_date is not None
        if has_start != has_end:
            raise ValueError("Provide both start_date and end_date for a forecast date range.")
        if has_start and self.days is not None:
            raise ValueError("Use start_date and end_date instead of days for a forecast date range.")
        return self

    def resolve_date_range(self, today: date) -> tuple[date, date, int]:
        """Resolve compatibility days or validate an inclusive provider date range."""
        if self.start_date is None or self.end_date is None:
            requested_days = self.days or DEFAULT_FORECAST_DAYS
            return today, today + timedelta(days=requested_days - 1), requested_days
        if self.end_date < self.start_date:
            raise ValueError("Forecast end_date must be on or after start_date.")
        if self.start_date < today:
            raise ValueError(f"Forecast start_date must be today or later ({today.isoformat()}).")
        last_available_date = today + timedelta(days=MAX_FORECAST_DAYS - 1)
        if self.end_date > last_available_date:
            raise ValueError(
                f"Forecast end_date must be on or before {last_available_date.isoformat()} "
                f"(the {MAX_FORECAST_DAYS}-day forecast window)."
            )
        requested_days = (self.end_date - self.start_date).days + 1
        if requested_days > MAX_FORECAST_DAYS:
            raise ValueError(f"Forecast date ranges can include at most {MAX_FORECAST_DAYS} days.")
        return self.start_date, self.end_date, requested_days


class ForecastResponse(BaseModel):
    """Weather forecast skill response."""

    results: list[dict[str, Any]] = Field(default_factory=list)
    provider: str
    provider_id: str | None = None
    location: dict[str, Any]
    days_requested: int
    start_date: date | None = None
    end_date: date | None = None
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
            full_model_reference=full_model_reference,
            pricing_config=pricing_config,
            celery_producer=celery_producer,
            skill_operational_defaults=skill_operational_defaults,
        )

    @classmethod
    def resolve_preview_metadata(cls, request: dict[str, Any]) -> dict[str, Any]:
        """Return fields shown while the forecast skill is processing."""
        location = request.get("location") or "Weather forecast"
        start_date = request.get("start_date")
        end_date = request.get("end_date")
        days = request.get("days") or DEFAULT_FORECAST_DAYS
        date_range = f" from {start_date} through {end_date}" if start_date and end_date else ""
        return {
            "query": f"{location} weather forecast{date_range}",
            "location": location,
            "days_requested": days,
            "start_date": start_date,
            "end_date": end_date,
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
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        days: int | None = None,
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
                start_date=start_date,
                end_date=end_date,
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
            today = datetime.now(ZoneInfo(resolved_timezone)).date()
            range_start, range_end, requested_days = request.resolve_date_range(today)

            if country_code == GERMANY_COUNTRY_CODE:
                provider_payload = await fetch_weather(
                    latitude=lat,
                    longitude=lon,
                    start_date=range_start,
                    end_date=range_end,
                    timezone=resolved_timezone,
                )
                results = normalize_weather_days(
                    provider_payload,
                    location_name=location_name,
                    country_code=country_code,
                    timezone=resolved_timezone,
                    requested_days=requested_days,
                    today=today,
                )
                provider = DWD_PROVIDER_LABEL
                provider_id = DWD_PROVIDER_ID
            else:
                provider_payload = await fetch_forecast(
                    latitude=lat,
                    longitude=lon,
                    start_date=range_start,
                    end_date=range_end,
                    timezone=resolved_timezone,
                )
                results = normalize_forecast_days(
                    provider_payload,
                    location_name=location_name,
                    country_code=country_code,
                    timezone=resolved_timezone,
                    requested_days=requested_days,
                    today=today,
                )
                provider = OPEN_METEO_PROVIDER_LABEL
                provider_id = OPEN_METEO_PROVIDER_ID

            return ForecastResponse(
                results=results,
                provider=provider,
                provider_id=provider_id,
                location={
                    "name": location_name,
                    "country": resolved_location.get("country"),
                    "country_code": country_code,
                    "admin1": resolved_location.get("admin1"),
                    "latitude": lat,
                    "longitude": lon,
                    "timezone": resolved_timezone,
                },
                days_requested=requested_days,
                start_date=range_start,
                end_date=range_end,
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
                days_requested=days or DEFAULT_FORECAST_DAYS,
                error=_readable_forecast_error(error),
            )
