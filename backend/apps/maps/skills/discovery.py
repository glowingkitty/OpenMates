"""Category discovery contract for maps.search.

Validates bounded, explicit geographic areas and the six supported categories.
Normalizes OSM-backed results into the existing maps-place child embed shape.
Missing data stays unknown and each result retains its provider and source.
Spec: specifications/features/app-skills/maps-search/specification.yml
"""

import hashlib
import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.shared.providers.geoapify.places import GEOAPIFY_SOURCE_LABEL, normalize_place_details

DiscoveryCategory = Literal["ruins", "viewpoints", "drinking_water", "toilets", "picnic_sites", "campsites"]
CATEGORIES = {
    "ruins": ("tourism.sights.ruines", "Ruins"),  # Geoapify's documented spelling.
    "viewpoints": ("tourism.attraction.viewpoint", "Viewpoint"),
    "drinking_water": ("amenity.drinking_water", "Drinking water"),
    "toilets": ("amenity.toilet", "Toilets"),
    "picnic_sites": ("leisure.picnic.picnic_site", "Picnic site"),
    "campsites": ("camping.camp_site", "Campsite"),
}


class DiscoveryArea(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    name: str | None = Field(default=None, min_length=2, max_length=200)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    radiusMeters: int = Field(default=10000, ge=1, le=50000)

    @model_validator(mode="after")
    def validate_center(self) -> "DiscoveryArea":
        coordinates = self.latitude is not None and self.longitude is not None
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("area requires both latitude and longitude")
        named = bool(self.name and self.name.strip())
        if named == coordinates:
            raise ValueError("area requires either a name or latitude and longitude")
        return self


class DiscoveryRequest(BaseModel):
    categories: list[DiscoveryCategory] = Field(min_length=1, max_length=6)
    area: DiscoveryArea


def coordinates(feature: dict[str, Any]) -> tuple[float, float] | None:
    properties = _record(feature.get("properties"))
    geometry = _record(feature.get("geometry"))
    pair = geometry.get("coordinates") if geometry.get("type") == "Point" else None
    lat = properties.get("lat", pair[1] if isinstance(pair, list) and len(pair) >= 2 else None)
    lon = properties.get("lon", pair[0] if isinstance(pair, list) and len(pair) >= 2 else None)
    if isinstance(lat, bool) or isinstance(lon, bool):
        return None
    try:
        lat, lon = float(lat), float(lon)
        if math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180:
            return lat, lon
    except (TypeError, ValueError):
        pass
    return None


def distance_meters(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlat, dlon = lat2 - lat1, math.radians(b[1] - a[1])
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(min(1, h)))


def resolve_area(features: list[dict[str, Any]]) -> tuple[tuple[float, float] | None, str | None]:
    valid = [item for item in features if isinstance(item, dict) and coordinates(item)]
    if not valid:
        return None, "Area was not found. Specify a city and country, or latitude and longitude."
    first = valid[0]
    best = coordinates(first)
    if len(valid) > 1:
        def confidence(item: dict[str, Any]) -> float:
            rank = _record(_record(item.get("properties")).get("rank"))
            value = rank.get("confidence")
            return float(value) if isinstance(value, (float, int)) and math.isfinite(value) else 1.0
        if confidence(valid[1]) >= confidence(first) - 0.05 and distance_meters(best, coordinates(valid[1])) > 1000:
            return None, "Area is ambiguous. Specify a city and country, or latitude and longitude."
    return best, None


def normalize_discovered_place(
    feature: dict[str, Any], requested_categories: list[str], center: tuple[float, float],
) -> dict[str, Any] | None:
    point = coordinates(feature)
    if not point:
        return None
    properties = _record(feature.get("properties"))
    actual_categories = properties.get("categories")
    actual_categories = [item for item in actual_categories if isinstance(item, str)] if isinstance(actual_categories, list) else []
    matched = [category for category in requested_categories if CATEGORIES[category][0] in actual_categories]
    # Do not label an unverified multi-category result as an arbitrary requested category.
    category = matched[0] if matched else (requested_categories[0] if len(requested_categories) == 1 else None)
    label = CATEGORIES[category][1] if category else "Place"
    name = properties.get("name")
    name_is_derived = not isinstance(name, str) or not name.strip()
    name = f"Unnamed {label.lower()}" if name_is_derived else name.strip()
    raw_id = properties.get("place_id") or feature.get("id")
    if not raw_id:
        raw_id = hashlib.sha256(f"{point[0]}|{point[1]}|{name}".encode()).hexdigest()
    place_id = f"geoapify:{raw_id}"
    source_url = f"https://www.openstreetmap.org/?mlat={point[0]}&mlon={point[1]}#map=17/{point[0]}/{point[1]}"
    raw = _record(_record(properties.get("datasource")).get("raw"))
    osm_type, osm_id = raw.get("osm_type"), raw.get("osm_id")
    if osm_type in {"node", "way", "relation"} and str(osm_id).isdigit():
        source_url = f"https://www.openstreetmap.org/{osm_type}/{osm_id}"
    enrichment = normalize_place_details(feature)
    enrichment["match"]["method"] = "places"
    return {
        "type": "place_result", "place_id": place_id,
        "hash": hashlib.md5(place_id.encode()).hexdigest()[:16],
        "provider": "Geoapify", "provider_place_id": str(raw_id),
        "name": name, "name_is_derived": name_is_derived,
        "formatted_address": properties.get("formatted") or properties.get("address_line2"),
        "location": {"latitude": point[0], "longitude": point[1]},
        "categories": matched, "types": actual_categories, "place_type": label,
        "distance_meters": round(distance_meters(center, point)),
        "data_source": GEOAPIFY_SOURCE_LABEL, "source_url": source_url,
        "osm_enrichment": enrichment,
    }


def _record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
