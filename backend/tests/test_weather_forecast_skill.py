# backend/tests/test_weather_forecast_skill.py
#
# Unit tests for the Weather forecast skill.
# Covers provider normalization, Germany provider routing, global fallback routing,
# and LLM inference-field minimization without live network calls.

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
import sys
from types import ModuleType
from zoneinfo import ZoneInfo

import pytest
import yaml

from backend.shared.python_utils.billing_utils import calculate_total_credits

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


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity,billing.surface.semantic-parity
def test_forecast_declares_flat_execution_price_and_provider_ids() -> None:
    app_path = Path(__file__).resolve().parents[1] / "apps" / "weather" / "app.yml"
    app = yaml.safe_load(app_path.read_text(encoding="utf-8"))
    forecast = next(skill for skill in app["skills"] if skill["id"] == "forecast")

    assert forecast["pricing"] == {"fixed": 1}
    assert forecast["providers"] == [
        {
            "name": "deutscher_wetterdienst",
            "display_name": "Deutscher Wetterdienst (DWD)",
            "no_api_key": True,
        },
        {
            "name": "open_meteo",
            "display_name": "Open-Meteo",
            "no_api_key": True,
        },
    ]
    assert calculate_total_credits(pricing_config=forecast["pricing"], units_processed=1) == 1
    assert calculate_total_credits(pricing_config=forecast["pricing"], units_processed=14) == 1


# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract
def test_forecast_request_resolves_inclusive_date_range_and_legacy_days() -> None:
    from backend.apps.weather.skills.forecast_skill import ForecastRequest

    today = date(2026, 9, 14)
    request = ForecastRequest(location="Berlin", start_date="2026-09-16", end_date="2026-09-18")
    assert request.resolve_date_range(today) == (date(2026, 9, 16), date(2026, 9, 18), 3)
    assert ForecastRequest(location="Berlin", days=2).resolve_date_range(today) == (
        today,
        date(2026, 9, 15),
        2,
    )


# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract
@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"start_date": "2026-09-14"}, "both start_date and end_date"),
        ({"start_date": "2026-09-14", "end_date": "2026-09-14", "days": 1}, "instead of days"),
    ],
)
def test_forecast_request_rejects_incomplete_or_mixed_date_range(values, message: str) -> None:
    from backend.apps.weather.skills.forecast_skill import ForecastRequest

    with pytest.raises(ValueError, match=message):
        ForecastRequest(location="Berlin", **values)


# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract
@pytest.mark.parametrize(
    ("start_date", "end_date", "message"),
    [
        (date(2026, 9, 15), date(2026, 9, 14), "on or after start_date"),
        (date(2026, 9, 13), date(2026, 9, 14), "today or later"),
        (date(2026, 9, 14), date(2026, 9, 28), "14-day forecast window"),
    ],
)
def test_forecast_request_returns_readable_date_range_errors(
    start_date: date, end_date: date, message: str
) -> None:
    from backend.apps.weather.skills.forecast_skill import ForecastRequest

    request = ForecastRequest(location="Berlin", start_date=start_date, end_date=end_date)
    with pytest.raises(ValueError, match=message):
        request.resolve_date_range(date(2026, 9, 14))


# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract
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


# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract
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


# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract
@pytest.mark.asyncio
async def test_provider_wrappers_send_inclusive_date_ranges(monkeypatch) -> None:
    from backend.shared.providers.bright_sky import bright_sky
    from backend.shared.providers.open_meteo import open_meteo

    requests = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, params):
            requests.append((url, params))
            return FakeResponse()

    monkeypatch.setattr(bright_sky.httpx, "AsyncClient", lambda **kwargs: FakeClient())
    monkeypatch.setattr(open_meteo.httpx, "AsyncClient", lambda **kwargs: FakeClient())
    start = date(2026, 9, 14)
    end = date(2026, 9, 16)

    await bright_sky.fetch_weather(
        latitude=52.52, longitude=13.405, start_date=start, end_date=end
    )
    await open_meteo.fetch_forecast(
        latitude=35.6764,
        longitude=139.65,
        start_date=start,
        end_date=end,
        timezone="Asia/Tokyo",
    )

    assert requests[0][1]["date"] == "2026-09-14"
    assert requests[0][1]["last_date"] == "2026-09-17"
    assert requests[1][1]["start_date"] == "2026-09-14"
    assert requests[1][1]["end_date"] == "2026-09-16"
    assert "forecast_days" not in requests[1][1]


# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract
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
        assert isinstance(kwargs["start_date"], date)
        assert kwargs["end_date"] - kwargs["start_date"] == timedelta(days=1)
        return {"weather": [], "sources": []}

    def fake_normalize_weather_days(payload, **kwargs):
        assert kwargs["country_code"] == "DE"
        return [{"type": "weather_day", "date": "2026-06-02", "hourly": []}]

    monkeypatch.setattr(forecast_skill, "geocode_location", fake_geocode_location)
    monkeypatch.setattr(forecast_skill, "fetch_weather", fake_fetch_weather)
    monkeypatch.setattr(forecast_skill, "normalize_weather_days", fake_normalize_weather_days)

    response = await make_skill().execute(location="Berlin", days=2)

    assert response.provider == "Deutscher Wetterdienst (DWD)"
    assert response.provider_id == "deutscher_wetterdienst"
    assert response.location["country_code"] == "DE"
    assert len(response.results) == 1
    assert "hourly" in response.ignore_fields_for_inference


# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract
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
        assert kwargs["end_date"] == kwargs["start_date"]
        return {"hourly": {}, "daily": {}}

    def fake_normalize_forecast_days(payload, **kwargs):
        assert kwargs["country_code"] == "JP"
        return [{"type": "weather_day", "date": "2026-06-02", "hourly": []}]

    monkeypatch.setattr(forecast_skill, "geocode_location", fake_geocode_location)
    monkeypatch.setattr(forecast_skill, "fetch_forecast", fake_fetch_forecast)
    monkeypatch.setattr(forecast_skill, "normalize_forecast_days", fake_normalize_forecast_days)

    response = await make_skill().execute(location="Tokyo", days=1)

    assert response.provider == "Open-Meteo"
    assert response.provider_id == "open_meteo"
    assert response.location["country_code"] == "JP"
    assert response.results[0]["type"] == "weather_day"


# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract
@pytest.mark.asyncio
async def test_forecast_skill_passes_exact_inclusive_range_to_provider(monkeypatch) -> None:
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

    calls = []

    async def fake_fetch_forecast(**kwargs):
        calls.append(kwargs)
        return {"hourly": {}, "daily": {}}

    monkeypatch.setattr(forecast_skill, "geocode_location", fake_geocode_location)
    monkeypatch.setattr(forecast_skill, "fetch_forecast", fake_fetch_forecast)

    today = datetime.now(ZoneInfo("Asia/Tokyo")).date()
    start = today + timedelta(days=2)
    end = today + timedelta(days=4)
    response = await make_skill().execute(
        location="Tokyo", start_date=start.isoformat(), end_date=end.isoformat()
    )

    assert calls[0]["start_date"] == start
    assert calls[0]["end_date"] == end
    assert response.days_requested == 3
    assert response.start_date == start
    assert response.end_date == end


# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract
@pytest.mark.asyncio
async def test_forecast_skill_surfaces_readable_invalid_range_error(monkeypatch) -> None:
    from backend.apps.weather.skills import forecast_skill

    async def fake_geocode_location(location: str):
        return {
            "name": "Berlin",
            "country_code": "DE",
            "latitude": 52.52,
            "longitude": 13.405,
            "timezone": "Europe/Berlin",
        }

    monkeypatch.setattr(forecast_skill, "geocode_location", fake_geocode_location)
    today = datetime.now(ZoneInfo("Europe/Berlin")).date()
    response = await make_skill().execute(
        location="Berlin",
        start_date=today.isoformat(),
        end_date=(today + timedelta(days=14)).isoformat(),
    )

    assert response.results == []
    assert response.error is not None
    assert "14-day forecast window" in response.error

    incomplete = await make_skill().execute(location="Berlin", start_date=today.isoformat())
    assert incomplete.error == "Provide both start_date and end_date for a forecast date range."
