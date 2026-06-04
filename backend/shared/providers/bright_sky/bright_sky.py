# backend/shared/providers/bright_sky/bright_sky.py
#
# Bright Sky weather provider wrapper.
# Wraps Bright Sky's JSON API for DWD-based Germany forecasts.
# Normalizes hourly provider rows into one compact day result per forecast day.
#
# Documentation: https://brightsky.dev/docs/

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BRIGHT_SKY_BASE_URL = "https://api.brightsky.dev"
BRIGHT_SKY_PROVIDER_LABEL = "Deutscher Wetterdienst (DWD)"
DEFAULT_TIMEOUT_SECONDS = 20.0


async def fetch_weather(
    *,
    latitude: float,
    longitude: float,
    start_date: date,
    days: int,
    timezone: str = "Europe/Berlin",
) -> dict[str, Any]:
    """Fetch hourly weather rows from Bright Sky for a date range."""
    last_date = start_date + timedelta(days=days)
    params: dict[str, Any] = {
        "lat": latitude,
        "lon": longitude,
        "date": start_date.isoformat(),
        "last_date": last_date.isoformat(),
        "tz": timezone,
    }
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
        response = await client.get(f"{BRIGHT_SKY_BASE_URL}/weather", params=params)
        response.raise_for_status()
        return response.json()


def _mode(values: list[str]) -> str | None:
    if not values:
        return None
    return Counter(values).most_common(1)[0][0]


def _round_number(value: float | int | None, digits: int = 1) -> float | int | None:
    if value is None:
        return None
    rounded = round(float(value), digits)
    return int(rounded) if rounded.is_integer() else rounded


def _build_source(source: dict[str, Any] | None) -> dict[str, Any] | None:
    if not source:
        return None
    return {
        "provider": BRIGHT_SKY_PROVIDER_LABEL,
        "station_name": source.get("station_name"),
        "dwd_station_id": source.get("dwd_station_id"),
        "wmo_station_id": source.get("wmo_station_id"),
        "observation_type": source.get("observation_type"),
        "distance_m": source.get("distance"),
        "lat": source.get("lat"),
        "lon": source.get("lon"),
        "height_m": source.get("height"),
        "first_record": source.get("first_record"),
        "last_record": source.get("last_record"),
    }


def normalize_weather_days(
    payload: dict[str, Any],
    *,
    location_name: str,
    country_code: str | None,
    timezone: str,
    requested_days: int,
) -> list[dict[str, Any]]:
    """Normalize Bright Sky hourly rows into one weather_day result per day."""
    weather_rows = payload.get("weather") or []
    sources_by_id = {source.get("id"): source for source in payload.get("sources") or []}

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in weather_rows:
        timestamp = row.get("timestamp")
        if not isinstance(timestamp, str) or len(timestamp) < 10:
            continue
        grouped[timestamp[:10]].append(row)

    results: list[dict[str, Any]] = []
    for index, day in enumerate(sorted(grouped)[:requested_days]):
        rows = grouped[day]
        temperatures = [row.get("temperature") for row in rows if row.get("temperature") is not None]
        precipitations = [float(row.get("precipitation") or 0) for row in rows]
        probabilities = [
            int(row.get("precipitation_probability"))
            for row in rows
            if row.get("precipitation_probability") is not None
        ]
        wind_speeds = [row.get("wind_speed") for row in rows if row.get("wind_speed") is not None]
        gust_speeds = [row.get("wind_gust_speed") for row in rows if row.get("wind_gust_speed") is not None]
        humidity_values = [row.get("relative_humidity") for row in rows if row.get("relative_humidity") is not None]
        cloud_values = [row.get("cloud_cover") for row in rows if row.get("cloud_cover") is not None]
        conditions = [str(row.get("condition")) for row in rows if row.get("condition")]
        icons = [str(row.get("icon")) for row in rows if row.get("icon")]
        source_ids = [row.get("source_id") for row in rows if row.get("source_id") is not None]
        source = _build_source(sources_by_id.get(Counter(source_ids).most_common(1)[0][0])) if source_ids else None

        hourly: list[dict[str, Any]] = []
        for row in rows:
            hourly.append({
                "time": str(row.get("timestamp", ""))[11:16],
                "timestamp": row.get("timestamp"),
                "condition": row.get("condition"),
                "icon": row.get("icon"),
                "temperature_c": row.get("temperature"),
                "precipitation_mm": row.get("precipitation"),
                "precipitation_probability_pct": row.get("precipitation_probability"),
                "precipitation_probability_6h_pct": row.get("precipitation_probability_6h"),
                "cloud_cover_pct": row.get("cloud_cover"),
                "relative_humidity_pct": row.get("relative_humidity"),
                "dew_point_c": row.get("dew_point"),
                "pressure_msl_hpa": row.get("pressure_msl"),
                "visibility_m": row.get("visibility"),
                "wind_direction_deg": row.get("wind_direction"),
                "wind_speed_kmh": row.get("wind_speed"),
                "wind_gust_direction_deg": row.get("wind_gust_direction"),
                "wind_gust_speed_kmh": row.get("wind_gust_speed"),
                "sunshine_minutes": row.get("sunshine"),
                "solar": row.get("solar"),
                "source_id": row.get("source_id"),
                "fallback_source_ids": row.get("fallback_source_ids"),
            })

        rain_hours = sum(
            1 for row in rows
            if float(row.get("precipitation") or 0) > 0 or row.get("condition") == "rain"
        )

        result = {
            "type": "weather_day",
            "title": f"{location_name} weather {day}",
            "date": day,
            "label": "today" if index == 0 else "tomorrow" if index == 1 else None,
            "location_name": location_name,
            "country_code": country_code,
            "timezone": timezone,
            "provider": BRIGHT_SKY_PROVIDER_LABEL,
            "condition": _mode(conditions),
            "icon": _mode(icons),
            "temperature_min_c": min(temperatures) if temperatures else None,
            "temperature_max_c": max(temperatures) if temperatures else None,
            "precipitation_total_mm": _round_number(sum(precipitations), 2),
            "precipitation_probability_max_pct": max(probabilities) if probabilities else None,
            "rain_hours": rain_hours,
            "wind_speed_max_kmh": max(wind_speeds) if wind_speeds else None,
            "wind_gust_speed_max_kmh": max(gust_speeds) if gust_speeds else None,
            "cloud_cover_avg_pct": _round_number(sum(cloud_values) / len(cloud_values), 1) if cloud_values else None,
            "relative_humidity_avg_pct": _round_number(sum(humidity_values) / len(humidity_values), 1) if humidity_values else None,
            "hourly": hourly,
            "source": source,
            "data_quality": {
                "hourly_rows": len(rows),
                "raw_source_count": len(payload.get("sources") or []),
            },
        }
        results.append(result)

    return results
