# backend/shared/providers/open_meteo/open_meteo.py
#
# Open-Meteo provider wrapper.
# Provides global geocoding and forecast fallback data for weather skills.
# Normalizes Open-Meteo hourly/daily rows into the same day shape as Bright Sky.
#
# Documentation: https://open-meteo.com/en/docs

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from typing import Any

import httpx

logger = logging.getLogger(__name__)

OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
OPEN_METEO_PROVIDER_LABEL = "Open-Meteo"
DEFAULT_TIMEOUT_SECONDS = 20.0


async def geocode_location(location: str, *, language: str = "en") -> dict[str, Any] | None:
    """Resolve a free-form location name to coordinates using Open-Meteo geocoding."""
    params = {
        "name": location,
        "count": 1,
        "language": language,
        "format": "json",
    }
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
        response = await client.get(OPEN_METEO_GEOCODING_URL, params=params)
        response.raise_for_status()
        data = response.json()
    results = data.get("results") or []
    if not results:
        return None
    result = results[0]
    return {
        "name": result.get("name") or location,
        "country_code": result.get("country_code"),
        "country": result.get("country"),
        "admin1": result.get("admin1"),
        "latitude": result.get("latitude"),
        "longitude": result.get("longitude"),
        "timezone": result.get("timezone"),
    }


async def fetch_forecast(
    *,
    latitude: float,
    longitude: float,
    days: int,
    timezone: str,
) -> dict[str, Any]:
    """Fetch global weather forecast from Open-Meteo."""
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "forecast_days": days,
        "timezone": timezone,
        "current": "temperature_2m,precipitation,rain,showers,weather_code",
        "hourly": "temperature_2m,precipitation,precipitation_probability,rain,showers,weather_code,cloud_cover,relative_humidity_2m,wind_speed_10m,wind_gusts_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,rain_sum,showers_sum,precipitation_probability_max,precipitation_hours,wind_speed_10m_max,wind_gusts_10m_max",
    }
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
        response = await client.get(OPEN_METEO_FORECAST_URL, params=params)
        response.raise_for_status()
        return response.json()


def _at(values: list[Any], index: int) -> Any:
    return values[index] if index < len(values) else None


def normalize_forecast_days(
    payload: dict[str, Any],
    *,
    location_name: str,
    country_code: str | None,
    timezone: str,
    requested_days: int,
) -> list[dict[str, Any]]:
    """Normalize Open-Meteo forecast rows into one weather_day result per day."""
    hourly = payload.get("hourly") or {}
    daily = payload.get("daily") or {}
    grouped_indexes: dict[str, list[int]] = defaultdict(list)
    times = hourly.get("time") or []
    for index, timestamp in enumerate(times):
        if isinstance(timestamp, str) and len(timestamp) >= 10:
            grouped_indexes[timestamp[:10]].append(index)

    daily_dates = daily.get("time") or []
    daily_by_date = {day: index for index, day in enumerate(daily_dates)}
    results: list[dict[str, Any]] = []

    for index, day in enumerate(sorted(grouped_indexes)[:requested_days]):
        row_indexes = grouped_indexes[day]
        daily_index = daily_by_date.get(day)
        weather_codes = [
            _at(hourly.get("weather_code") or [], row_index)
            for row_index in row_indexes
            if _at(hourly.get("weather_code") or [], row_index) is not None
        ]
        cloud_values = [
            _at(hourly.get("cloud_cover") or [], row_index)
            for row_index in row_indexes
            if _at(hourly.get("cloud_cover") or [], row_index) is not None
        ]
        humidity_values = [
            _at(hourly.get("relative_humidity_2m") or [], row_index)
            for row_index in row_indexes
            if _at(hourly.get("relative_humidity_2m") or [], row_index) is not None
        ]
        hourly_rows = []
        for row_index in row_indexes:
            precipitation = _at(hourly.get("precipitation") or [], row_index)
            rain = _at(hourly.get("rain") or [], row_index)
            showers = _at(hourly.get("showers") or [], row_index)
            hourly_rows.append({
                "time": str(_at(times, row_index) or "")[11:16],
                "timestamp": _at(times, row_index),
                "weather_code": _at(hourly.get("weather_code") or [], row_index),
                "condition": None,
                "icon": None,
                "temperature_c": _at(hourly.get("temperature_2m") or [], row_index),
                "precipitation_mm": precipitation,
                "precipitation_probability_pct": _at(hourly.get("precipitation_probability") or [], row_index),
                "rain_mm": rain,
                "showers_mm": showers,
                "cloud_cover_pct": _at(hourly.get("cloud_cover") or [], row_index),
                "relative_humidity_pct": _at(hourly.get("relative_humidity_2m") or [], row_index),
                "wind_speed_kmh": _at(hourly.get("wind_speed_10m") or [], row_index),
                "wind_gust_speed_kmh": _at(hourly.get("wind_gusts_10m") or [], row_index),
            })

        daily_weather_code = _at(daily.get("weather_code") or [], daily_index) if daily_index is not None else None
        condition = f"wmo_{daily_weather_code}" if daily_weather_code is not None else None
        result = {
            "type": "weather_day",
            "title": f"{location_name} weather {day}",
            "date": day,
            "label": "today" if index == 0 else "tomorrow" if index == 1 else None,
            "location_name": location_name,
            "country_code": country_code,
            "timezone": timezone,
            "provider": OPEN_METEO_PROVIDER_LABEL,
            "condition": condition,
            "icon": condition,
            "weather_code": daily_weather_code,
            "temperature_min_c": _at(daily.get("temperature_2m_min") or [], daily_index) if daily_index is not None else None,
            "temperature_max_c": _at(daily.get("temperature_2m_max") or [], daily_index) if daily_index is not None else None,
            "precipitation_total_mm": _at(daily.get("precipitation_sum") or [], daily_index) if daily_index is not None else None,
            "rain_total_mm": _at(daily.get("rain_sum") or [], daily_index) if daily_index is not None else None,
            "showers_total_mm": _at(daily.get("showers_sum") or [], daily_index) if daily_index is not None else None,
            "precipitation_probability_max_pct": _at(daily.get("precipitation_probability_max") or [], daily_index) if daily_index is not None else None,
            "rain_hours": int(_at(daily.get("precipitation_hours") or [], daily_index) or 0) if daily_index is not None else 0,
            "wind_speed_max_kmh": _at(daily.get("wind_speed_10m_max") or [], daily_index) if daily_index is not None else None,
            "wind_gust_speed_max_kmh": _at(daily.get("wind_gusts_10m_max") or [], daily_index) if daily_index is not None else None,
            "cloud_cover_avg_pct": round(sum(cloud_values) / len(cloud_values), 1) if cloud_values else None,
            "relative_humidity_avg_pct": round(sum(humidity_values) / len(humidity_values), 1) if humidity_values else None,
            "hourly": hourly_rows,
            "source": {"provider": OPEN_METEO_PROVIDER_LABEL, "model": "best_match"},
            "data_quality": {
                "hourly_rows": len(hourly_rows),
                "dominant_hourly_weather_code": Counter(weather_codes).most_common(1)[0][0] if weather_codes else None,
            },
        }
        results.append(result)

    return results
