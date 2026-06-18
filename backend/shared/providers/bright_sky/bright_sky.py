# backend/shared/providers/bright_sky/bright_sky.py
#
# Bright Sky weather provider wrapper.
# Wraps Bright Sky's JSON API for DWD-based Germany forecasts.
# Normalizes hourly provider rows into one compact day result per forecast day.
#
# Documentation: https://brightsky.dev/docs/

from __future__ import annotations

import base64
import json
import logging
import math
import zlib
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
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


async def fetch_radar(
    *,
    latitude: float,
    longitude: float,
    radius_km: int,
    timezone: str = "UTC",
) -> dict[str, Any]:
    """Fetch DWD radar rows around a coordinate from Bright Sky."""
    params: dict[str, Any] = {
        "lat": latitude,
        "lon": longitude,
        "distance": radius_km * 1000,
        "format": "compressed",
        "tz": timezone,
    }
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
        response = await client.get(f"{BRIGHT_SKY_BASE_URL}/radar", params=params)
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


def _decode_precipitation_grid(encoded: str) -> list[int]:
    raw = zlib.decompress(base64.b64decode(encoded))
    return [int.from_bytes(raw[index:index + 2], "big", signed=False) for index in range(0, len(raw), 2)]


def _radar_grid_dimensions(payload: dict[str, Any], value_count: int) -> tuple[int, int]:
    bbox = payload.get("bbox")
    if isinstance(bbox, list) and len(bbox) == 4:
        try:
            top, left, bottom, right = [int(value) for value in bbox]
            width = abs(right - left) + 1
            height = abs(bottom - top) + 1
            if width > 0 and height > 0 and width * height == value_count:
                return width, height
        except (TypeError, ValueError):
            pass

    side = int(math.sqrt(value_count))
    if side > 0 and side * side == value_count:
        return side, side
    return value_count, 1


def _classify_precipitation(value: int) -> str:
    mm_5min = value / 100
    if mm_5min <= 0:
        return "none"
    if mm_5min < 0.5:
        return "light"
    if mm_5min < 2:
        return "moderate"
    return "heavy"


def _frame_kind(timestamp: str, now_timestamp: str) -> str:
    try:
        frame_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        now_time = datetime.fromisoformat(now_timestamp.replace("Z", "+00:00"))
    except ValueError:
        return "current"
    if frame_time < now_time:
        return "past"
    if frame_time == now_time:
        return "current"
    return "forecast"


def _frame_label(timestamp: str, now_timestamp: str) -> str:
    try:
        frame_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        now_time = datetime.fromisoformat(now_timestamp.replace("Z", "+00:00"))
    except ValueError:
        return timestamp
    minutes = round((frame_time - now_time).total_seconds() / 60)
    if minutes == 0:
        return "now"
    prefix = "+" if minutes > 0 else ""
    return f"{prefix}{minutes} min"


def _bounds_from_geometry(geometry: dict[str, Any] | None) -> dict[str, float] | None:
    if not geometry:
        return None
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or not coordinates:
        return None
    points = coordinates[0]
    if not isinstance(points, list):
        return None
    lons = [float(point[0]) for point in points if isinstance(point, list) and len(point) >= 2]
    lats = [float(point[1]) for point in points if isinstance(point, list) and len(point) >= 2]
    if not lons or not lats:
        return None
    return {
        "north": max(lats),
        "west": min(lons),
        "south": min(lats),
        "east": max(lons),
    }


def normalize_radar_frames(
    payload: dict[str, Any],
    *,
    location_name: str,
    latitude: float,
    longitude: float,
    radius_km: int,
    now_timestamp: str,
) -> dict[str, Any]:
    """Normalize Bright Sky radar grids into compact embed metadata plus blob data."""
    radar_rows = payload.get("radar") or []
    frames: list[dict[str, Any]] = []
    blob_frames: list[dict[str, Any]] = []
    grid_width = 0
    grid_height = 0

    for index, row in enumerate(radar_rows):
        encoded = row.get("precipitation_5")
        timestamp = str(row.get("timestamp") or "")
        if not encoded or not timestamp:
            continue
        values = _decode_precipitation_grid(str(encoded))
        if not values:
            continue
        grid_width, grid_height = _radar_grid_dimensions(payload, len(values))
        center_index = min(len(values) - 1, (grid_height // 2) * grid_width + (grid_width // 2)) if grid_width else 0
        center_value = values[center_index]
        rainy_values = [value for value in values if value > 0]
        max_value = max(values)
        frame_id = f"frame-{len(frames)}"
        frames.append({
            "frame_id": frame_id,
            "timestamp": timestamp,
            "kind": _frame_kind(timestamp, now_timestamp),
            "label": _frame_label(timestamp, now_timestamp),
            "rain_at_location_mm_5min": _round_number(center_value / 100, 2),
            "max_intensity": _classify_precipitation(max_value),
            "rain_area_pct": _round_number((len(rainy_values) / len(values)) * 100, 1),
        })
        blob_frames.append({
            "frame_id": frame_id,
            "timestamp": timestamp,
            "kind": frames[-1]["kind"],
            "values": values,
        })

    preview_frame = _select_preview_frame(frames, now_timestamp)
    rain_expected = any(frame["max_intensity"] != "none" for frame in frames)
    peak_intensity = _peak_intensity(frame["max_intensity"] for frame in frames)
    summary = {
        "rain_expected": rain_expected,
        "in_10_min": _describe_frame(preview_frame, location_name),
        "next_2_hours": _describe_timeline(frames, location_name),
        "peak_intensity": peak_intensity,
        "preview_frame_id": preview_frame.get("frame_id") if preview_frame else None,
    }
    bounds = _bounds_from_geometry(payload.get("geometry"))
    blob = {
        "version": 1,
        "bounds": bounds,
        "grid": {
            "width": grid_width,
            "height": grid_height,
            "resolution_km": 1,
            "unit": "0.01mm_per_5min",
        },
        "frames": blob_frames,
    }

    return {
        "type": "rain_radar",
        "location_name": location_name,
        "latitude": latitude,
        "longitude": longitude,
        "provider": f"{BRIGHT_SKY_PROVIDER_LABEL} via Bright Sky",
        "coverage": {"status": "available", "radius_km": radius_km},
        "summary": summary,
        "timeline": frames,
        "rendering": {
            "mode": "external_radar_blob",
            "preview_frame_id": summary["preview_frame_id"],
            "bounds": bounds,
            "frame_count": len(frames),
            "grid_resolution_km": 1,
            "radius_km": radius_km,
        },
        "radar_blob_b64": base64.b64encode(zlib.compress(json.dumps(blob, separators=(",", ":")).encode("utf-8"))).decode("ascii"),
    }


def _select_preview_frame(frames: list[dict[str, Any]], now_timestamp: str) -> dict[str, Any]:
    if not frames:
        return {}
    try:
        now_time = datetime.fromisoformat(now_timestamp.replace("Z", "+00:00"))
        target = now_time + timedelta(minutes=10)
        return min(
            frames,
            key=lambda frame: abs(
                datetime.fromisoformat(str(frame["timestamp"]).replace("Z", "+00:00")) - target
            ),
        )
    except (ValueError, TypeError):
        return frames[min(len(frames) - 1, len(frames) // 2)]


def _peak_intensity(intensities: Any) -> str:
    rank = {"none": 0, "light": 1, "moderate": 2, "heavy": 3}
    peak = "none"
    for intensity in intensities:
        if rank.get(str(intensity), 0) > rank[peak]:
            peak = str(intensity)
    return peak


def _describe_frame(frame: dict[str, Any], location_name: str) -> str:
    intensity = frame.get("max_intensity")
    if not frame or intensity == "none":
        return f"No rain visible near {location_name}."
    return f"{str(intensity).capitalize()} rain visible near {location_name}."


def _describe_timeline(frames: list[dict[str, Any]], location_name: str) -> str:
    if not frames or all(frame.get("max_intensity") == "none" for frame in frames):
        return f"No rain is visible near {location_name} in the radar timeline."
    peak = _peak_intensity(frame.get("max_intensity") for frame in frames)
    return f"{peak.capitalize()} rain appears in the radar timeline near {location_name}."


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
