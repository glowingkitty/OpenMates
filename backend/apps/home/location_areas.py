"""Deterministic Home area geometry; coordinates alone never establish an address."""
from __future__ import annotations

import math
import re
import unicodedata
from typing import Any

RULE_VERSION = "home-area-v1"


def _record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def coordinates(latitude: Any, longitude: Any) -> tuple[float, float] | None:
    lat, lon = number(latitude), number(longitude)
    return (lat, lon) if lat is not None and lon is not None and abs(lat) <= 90 and abs(lon) <= 180 else None


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    dlat, dlon = math.radians(b[0] - a[0]), math.radians(b[1] - a[1])
    square = math.sin(dlat / 2) ** 2 + math.cos(math.radians(a[0])) * math.cos(math.radians(b[0])) * math.sin(dlon / 2) ** 2
    return 12742000 * math.asin(min(1, math.sqrt(square)))


def normalized(value: Any) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).casefold().split())


def address_components(listing: dict[str, Any]) -> tuple[str, str] | None:
    """Require a public street and house number, not a postcode or an anchor."""
    address = listing.get("address")
    if re.search(r"\b(?:office|agency|advertiser|makler\w*|büro|buero|geschäftsstelle|impressum)\b", str(address or ""), re.I):
        return None
    fields = address if isinstance(address, dict) else {}
    street = str(listing.get("street") or fields.get("street") or "").strip()
    house = str(listing.get("house_number") or fields.get("house_number") or "").strip()
    house_pattern = r"\d{1,4}\s?[a-zA-Z]?(?:\s?[-/]\s?\d{1,4}[a-zA-Z]?)?"
    if street and re.fullmatch(house_pattern, house):
        return street, house
    # Some adapters retain the full public address as a string only. Require a
    # street-like comma component; a five-digit postal code cannot be a house.
    if not isinstance(address, str):
        return None
    localities = {normalized(listing.get(key)) for key in ("city", "district")}
    for component in address[:500].split(",")[:5]:
        for pattern in (rf"(.+?)\s+({house_pattern})", rf"({house_pattern})\s+(.+)"):
            match = re.fullmatch(pattern, component.strip())
            if not match:
                continue
            candidate = match[1] if pattern.startswith("(.+") else match[2]
            if normalized(candidate) not in localities and sum(char.isalpha() for char in candidate) >= 3:
                return candidate, match[2] if pattern.startswith("(.+") else match[1]
    return None


def has_exact_address(listing: dict[str, Any]) -> bool:
    return address_components(listing) is not None


def matching_address(feature: dict[str, Any], listing: dict[str, Any], city: str) -> bool:
    parts = address_components(listing)
    props = _record(feature.get("properties"))
    context = listing.get("city") or _record(listing.get("address")).get("city") or city
    return bool(parts and normalized(props.get("street")) == normalized(parts[0])
                and normalized(props.get("housenumber") or props.get("house_number")) == normalized(parts[1])
                and normalized(props.get("city") or props.get("town")) == normalized(context))


def feature_point(feature: dict[str, Any]) -> tuple[float, float] | None:
    props = _record(feature.get("properties"))
    point = coordinates(props.get("lat"), props.get("lon"))
    if point:
        return point
    geometry = _record(feature.get("geometry"))
    raw = geometry.get("coordinates")
    if geometry.get("type") == "Point" and isinstance(raw, list) and len(raw) >= 2:
        return coordinates(raw[1], raw[0])
    return None


def feature_extent(feature: dict[str, Any]) -> list[float] | None:
    """Read an actual extent, never invent uncertainty from a representative point."""
    props = _record(feature.get("properties"))
    raw = feature.get("bbox") or props.get("bbox")
    if isinstance(raw, dict):
        raw = [raw.get("lon1"), raw.get("lat1"), raw.get("lon2"), raw.get("lat2")]
    if isinstance(raw, (list, tuple)) and len(raw) == 4:
        values = [number(value) for value in raw]
        if all(value is not None for value in values):
            west, south, east, north = values
            if -180 <= west <= 180 and -180 <= east <= 180 and -90 <= south < north <= 90 and west != east:
                return values
    geometry = _record(feature.get("geometry"))
    if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        return None
    points: list[tuple[float, float]] = []

    def collect(value: Any, depth: int = 0) -> None:
        if depth > 4 or not isinstance(value, list) or len(points) > 2000:
            raise ValueError("Invalid or oversized extent")
        if len(value) >= 2 and not isinstance(value[0], list):
            point = coordinates(value[1], value[0])
            if point is None:
                raise ValueError("Invalid extent vertex")
            points.append(point)
        else:
            for item in value:
                collect(item, depth + 1)
    try:
        collect(geometry.get("coordinates"))
    except ValueError:
        return None
    if len(points) < 3:
        return None
    return [min(p[1] for p in points), min(p[0] for p in points), max(p[1] for p in points), max(p[0] for p in points)]


def area_from_feature(feature: dict[str, Any], *, basis: str, source: str, checked_at: str | None = None) -> dict[str, Any] | None:
    extent = feature_extent(feature)
    if extent is None:
        return None
    west, south, east, north = extent
    span = (east - west) % 360
    if span > 60 or north - south > 30:
        return None  # Country-scale matches are not useful city/district evidence.
    center = ((south + north) / 2, ((west + span / 2 + 180) % 360) - 180)
    radius = max(distance(center, (lat, lon)) for lat in (south, north) for lon in (west, east))
    if radius <= 0:
        return None
    return {"latitude": center[0], "longitude": center[1], "radius_m": math.ceil(radius / 100) * 100,
            "basis": basis, "method": "administrative_extent", "rule_version": RULE_VERSION,
            "source": source, "checked_at": checked_at, "bounds": extent}


def matching_region(feature: dict[str, Any], name: str, basis: str, city: str) -> bool:
    props = _record(feature.get("properties"))
    types = {"city", "town", "village", "municipality"} if basis == "city" else {"district", "suburb", "neighbourhood", "neighborhood", "quarter", "postcode"}
    if props.get("result_type") not in types:
        return False
    labels = [props.get(key) for key in ("name", "city", "town", "village", "district", "suburb", "quarter", "postcode")]
    if normalized(name) not in {normalized(label) for label in labels if label}:
        return False
    claimed_city = props.get("city") or props.get("town")
    return bool(claimed_city and normalized(claimed_city) == normalized(city))


def matching_anchor(feature: dict[str, Any], clue: dict[str, Any], city: str) -> bool:
    props = _record(feature.get("properties"))
    if normalized(props.get("city") or props.get("town")) != normalized(city):
        return False
    def name(value: Any) -> str:
        text = normalized(value)
        text = re.sub(r"\b(?:s-bahnhof|u-bahnhof|bahnhof|station|s-bahn|u-bahn)\b", " ", text)
        return " ".join(text.split()).removeprefix(normalized(city) + " ")
    if not name(props.get("name")) or name(props.get("name")) != name(clue.get("anchor_name")):
        return False
    categories = props.get("categories")
    categories = [value for value in categories if isinstance(value, str)] if isinstance(categories, list) else []
    if isinstance(props.get("category"), str):
        categories.append(props["category"])
    raw = _record(_record(props.get("datasource")).get("raw"))
    kind = clue.get("anchor_type")
    if kind in {"station", "transit"}:
        return (any(value.startswith("public_transport") for value in categories)
                or raw.get("railway") in {"station", "halt", "tram_stop", "subway_entrance", "platform"}
                or raw.get("public_transport") in {"station", "stop_position", "platform"})
    if kind == "park":
        return any(value.startswith("leisure.park") for value in categories) or raw.get("leisure") == "park"
    if kind == "water":
        return any(value.startswith("natural.water") for value in categories) or raw.get("natural") == "water"
    if kind == "street":
        return props.get("result_type") == "street"
    if kind in {"district", "neighborhood"}:
        return props.get("result_type") in {"district", "suburb", "neighbourhood", "neighborhood", "quarter"}
    return kind == "landmark"


def apply_area(listing: dict[str, Any], area: dict[str, Any]) -> None:
    previous = listing.get("location") or {}
    precision = "district" if area["basis"] in {"district", "description"} else "city"
    listing.update(latitude=area["latitude"], longitude=area["longitude"], location_approximate=True,
                   location_precision=precision, location_source=area["source"])
    listing["location"] = {**previous, "area": area, "precision": precision, "approximate": True,
                           "exact_address": has_exact_address(listing), "source": area["source"],
                           "status": "approximate", "method": area["method"]}


def clue_area(clue: dict[str, Any], feature: dict[str, Any], *, source: str, checked_at: str | None) -> dict[str, Any] | None:
    """Only supported numeric relations refine v1; qualitative near stays broad."""
    center = feature_point(feature)
    quantity = number(clue.get("quantity"))
    if center is None or quantity is None or quantity <= 0:
        return None
    if clue.get("relation") == "distance" and clue.get("unit") in {"m", "km"}:
        meters = quantity * (1000 if clue["unit"] == "km" else 1)
    elif clue.get("relation") == "walk_time" and clue.get("unit") == "minutes" and quantity <= 120:
        meters = quantity * 100  # Conservative envelope, not a verified walking route.
    else:
        return None
    if meters > 25000:
        return None
    footprint = area_from_feature(feature, basis="description", source=source)
    # Include full station extent even when its representative point is off-center.
    anchor_allowance = 250.0
    if footprint:
        anchor_allowance = max(anchor_allowance, footprint["radius_m"] + distance(center, (footprint["latitude"], footprint["longitude"])))
    radius = math.ceil((meters + max(100, meters * 0.25) + anchor_allowance) / 100) * 100
    props = _record(feature.get("properties"))
    return {"latitude": center[0], "longitude": center[1], "radius_m": radius,
            "basis": "description", "method": "advertised_distance" if clue["relation"] == "distance" else "advertised_walking_envelope",
            "rule_version": RULE_VERSION, "source": source, "checked_at": checked_at,
            "anchor_name": clue["anchor_name"], "anchor_id": props.get("place_id"),
            "evidence_quote": clue["evidence_quote"]}
