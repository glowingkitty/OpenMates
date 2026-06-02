# backend/tests/test_weather_forecast_skill.py
#
# Unit tests for the Weather forecast skill.
# Covers provider normalization, Germany provider routing, global fallback routing,
# and LLM inference-field minimization without live network calls.

from __future__ import annotations

from datetime import date
import sys
from types import ModuleType

import pytest

celery_stub = ModuleType("celery")
celery_stub.Celery = object
sys.modules.setdefault("celery", celery_stub)


class DummyApp:
    secrets_manager = None


def make_skill():
    from backend.apps.weather.skills.forecast_skill import ForecastSkill

    return ForecastSkill(
        app=DummyApp(),
        app_id="weather",
        skill_id="forecast",
        skill_name="Forecast",
        skill_description="Get a weather forecast.",
    )


def test_bright_sky_normalization_returns_one_embed_ready_result_per_day() -> None:
    from backend.shared.providers.bright_sky.bright_sky import normalize_weather_days

    payload = {
        "sources": [
            {
                "id": 1,
                "station_name": "BERLIN-ALEX.",
                "dwd_station_id": "00399",
                "wmo_station_id": "10389",
                "observation_type": "forecast",
                "distance": 1016,
            }
        ],
        "weather": [
            {
                "timestamp": "2026-06-02T00:00:00+02:00",
                "source_id": 1,
                "condition": "dry",
                "icon": "cloudy",
                "temperature": 14.0,
                "precipitation": 0.0,
                "precipitation_probability": 4,
                "wind_speed": 10,
                "relative_humidity": 70,
                "cloud_cover": 90,
            },
            {
                "timestamp": "2026-06-02T01:00:00+02:00",
                "source_id": 1,
                "condition": "rain",
                "icon": "rain",
                "temperature": 13.5,
                "precipitation": 0.2,
                "precipitation_probability": 50,
                "wind_speed": 12,
                "relative_humidity": 80,
                "cloud_cover": 100,
            },
            {
                "timestamp": "2026-06-03T00:00:00+02:00",
                "source_id": 1,
                "condition": "dry",
                "icon": "clear-day",
                "temperature": 15.0,
                "precipitation": 0.0,
                "precipitation_probability": 3,
                "wind_speed": 8,
            },
        ],
    }

    results = normalize_weather_days(
        payload,
        location_name="Berlin",
        country_code="DE",
        timezone="Europe/Berlin",
        requested_days=2,
    )

    assert len(results) == 2
    first = results[0]
    assert first["type"] == "weather_day"
    assert first["date"] == "2026-06-02"
    assert first["temperature_min_c"] == 13.5
    assert first["temperature_max_c"] == 14.0
    assert first["precipitation_total_mm"] == 0.2
    assert first["precipitation_probability_max_pct"] == 50
    assert first["rain_hours"] == 1
    assert len(first["hourly"]) == 2
    assert first["source"]["station_name"] == "BERLIN-ALEX."


def test_open_meteo_normalization_matches_weather_day_shape() -> None:
    from backend.shared.providers.open_meteo.open_meteo import normalize_forecast_days

    payload = {
        "hourly": {
            "time": ["2026-06-02T00:00", "2026-06-02T01:00"],
            "temperature_2m": [20.0, 19.5],
            "precipitation": [0.0, 1.0],
            "precipitation_probability": [0, 80],
            "rain": [0.0, 1.0],
            "showers": [0.0, 0.0],
            "weather_code": [3, 61],
            "cloud_cover": [50, 90],
            "relative_humidity_2m": [60, 75],
            "wind_speed_10m": [8, 9],
            "wind_gusts_10m": [12, 14],
        },
        "daily": {
            "time": ["2026-06-02"],
            "weather_code": [61],
            "temperature_2m_max": [21.0],
            "temperature_2m_min": [18.0],
            "precipitation_sum": [1.0],
            "rain_sum": [1.0],
            "showers_sum": [0.0],
            "precipitation_probability_max": [80],
            "precipitation_hours": [1.0],
            "wind_speed_10m_max": [9],
            "wind_gusts_10m_max": [14],
        },
    }

    results = normalize_forecast_days(
        payload,
        location_name="Tokyo",
        country_code="JP",
        timezone="Asia/Tokyo",
        requested_days=1,
    )

    assert len(results) == 1
    day = results[0]
    assert day["type"] == "weather_day"
    assert day["provider"] == "Open-Meteo"
    assert day["condition"] == "wmo_61"
    assert day["precipitation_total_mm"] == 1.0
    assert len(day["hourly"]) == 2


@pytest.mark.asyncio
async def test_forecast_skill_uses_bright_sky_for_germany(monkeypatch) -> None:
    from backend.apps.weather.skills import forecast_skill

    async def fake_geocode_location(location: str):
        return {
            "name": "Berlin",
            "country_code": "DE",
            "country": "Germany",
            "latitude": 52.52,
            "longitude": 13.405,
            "timezone": "Europe/Berlin",
        }

    async def fake_fetch_weather(**kwargs):
        assert kwargs["days"] == 2
        assert isinstance(kwargs["start_date"], date)
        return {"weather": [], "sources": []}

    def fake_normalize_weather_days(payload, **kwargs):
        assert kwargs["country_code"] == "DE"
        return [{"type": "weather_day", "date": "2026-06-02", "hourly": []}]

    monkeypatch.setattr(forecast_skill, "geocode_location", fake_geocode_location)
    monkeypatch.setattr(forecast_skill, "fetch_weather", fake_fetch_weather)
    monkeypatch.setattr(forecast_skill, "normalize_weather_days", fake_normalize_weather_days)

    response = await make_skill().execute(location="Berlin", days=2)

    assert response.provider == "Bright Sky / DWD"
    assert response.location["country_code"] == "DE"
    assert len(response.results) == 1
    assert "hourly" in response.ignore_fields_for_inference


@pytest.mark.asyncio
async def test_forecast_skill_uses_open_meteo_outside_germany(monkeypatch) -> None:
    from backend.apps.weather.skills import forecast_skill

    async def fake_geocode_location(location: str):
        return {
            "name": "Tokyo",
            "country_code": "JP",
            "country": "Japan",
            "latitude": 35.6764,
            "longitude": 139.65,
            "timezone": "Asia/Tokyo",
        }

    async def fake_fetch_forecast(**kwargs):
        assert kwargs["days"] == 1
        return {"hourly": {}, "daily": {}}

    def fake_normalize_forecast_days(payload, **kwargs):
        assert kwargs["country_code"] == "JP"
        return [{"type": "weather_day", "date": "2026-06-02", "hourly": []}]

    monkeypatch.setattr(forecast_skill, "geocode_location", fake_geocode_location)
    monkeypatch.setattr(forecast_skill, "fetch_forecast", fake_fetch_forecast)
    monkeypatch.setattr(forecast_skill, "normalize_forecast_days", fake_normalize_forecast_days)

    response = await make_skill().execute(location="Tokyo", days=1)

    assert response.provider == "Open-Meteo"
    assert response.location["country_code"] == "JP"
    assert response.results[0]["type"] == "weather_day"
