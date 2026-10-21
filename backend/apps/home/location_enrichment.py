"""Bounded, on-demand home location evidence; no local spatial index.

"""
from __future__ import annotations

import asyncio
import math
import re
from datetime import datetime, timezone
from typing import Any

from backend.shared.providers.geoapify.places import (
    GEOAPIFY_SOURCE_LABEL,
    GeoapifyPlacesProvider,
    GeoapifyPlacesSearchResult,
)
from backend.shared.python_utils.geo_utils import geocode_address

MAX_LOCATION_CANDIDATES = 24
MAX_LOCATION_REQUESTS = 36
MAX_LOCATION_CONCURRENCY = 3
LOCATION_TIMEOUT_SECONDS = 8.0
MAX_GEOMETRY_VERTICES = 2000

CATEGORIES = {
    "water": ["natural.water", "natural.coastal", "man_made.pier"],
    "park": ["leisure.park"],
    "transit": ["public_transport"],
    "groceries": ["commercial.supermarket", "commercial.food_and_drink"],
    "school": ["education.school"],
}
_CATEGORY_WORDS = {
    "water": r"\b(water|waterfront|lake|river|canal|shore|wasser|gewässer|gewaesser|see|fluss|kanal|ufer)\b",
    "park": r"\b(parks?|green\s+space|grünfläche|gruenflaeche)\b",
    "transit": r"\b(transit|public\s+transport|subway|tram|bus|öpnv|oepnv|nahverkehr|u-bahn|s-bahn|haltestelle)\b",
    "groceries": r"\b(groceries|grocery|supermarkets?|supermärkte|supermaerkte|lebensmittel|einkaufen)\b",
    "school": r"\b(schools?|schule|schulen)\b",
}


def requested_categories(request: Any) -> list[str]:
    """Use only explicitly requested categories or bounded English/German words."""
    explicit = _get(request, "neighborhood_categories", []) or []
    criteria = str(_get(request, "relevance_criteria", "") or "")[:4000].lower()
    result = [category for category in CATEGORIES if category in explicit or re.search(_CATEGORY_WORDS[category], criteria)]
    if (_get(request, "max_water_distance_m") is not None or _get(request, "max_water_walk_minutes") is not None) and "water" not in result:
        result.insert(0, "water")
    return result


async def enrich_home_locations(
    listings: list[dict[str, Any]], *, city: str, request: Any,
    secrets_manager: Any, cache_service: Any = None,
) -> list[str]:
    """Mutate listings with location and requested neighborhood evidence.

    Limits bound the pool, wrapper calls, concurrent listings and total optional
    latency. A cache hit is still counted against the per-search wrapper-call
    cap, while the provider's shared credit guard charges only outbound calls.
    Empty place searches are incomplete coverage, never proof of absence.
    """
    categories = requested_categories(request)
    radius = max(1, min(5000, int(_get(request, "neighborhood_radius_m", 1500) or 1500)))
    provider = GeoapifyPlacesProvider(secrets_manager=secrets_manager, cache_service=cache_service)
    warnings: set[str] = set()
    semaphore = asyncio.Semaphore(MAX_LOCATION_CONCURRENCY)
    requests_used = 0

    async def call(method: Any, *args: Any, **kwargs: Any) -> GeoapifyPlacesSearchResult:
        nonlocal requests_used
        if requests_used >= MAX_LOCATION_REQUESTS:
            return GeoapifyPlacesSearchResult(status="request_limit")
        requests_used += 1
        try:
            return await method(*args, **kwargs)
        except Exception:
            # Preserve usable housing evidence on optional provider failure.
            return GeoapifyPlacesSearchResult(status="unavailable")

    # One fallback per search; city-only even if Nominatim could find an address.
    fallback_task: asyncio.Task[Any] | None = None

    async def fallback() -> Any:
        nonlocal fallback_task
        if fallback_task is None:
            fallback_task = asyncio.create_task(geocode_address(None, city=city))
        return await fallback_task

    async def locate(listing: dict[str, Any]) -> None:
        async with semaphore:
            await _locate(listing, city, call, provider, fallback)
            location = listing["location"]
            if location["status"] not in {"ok", "provider"} or location["approximate"]:
                warnings.add("Some home locations are approximate or unavailable; precise proximity is unknown.")

    async def enrich(listing: dict[str, Any]) -> None:
        async with semaphore:
            location = listing["location"]
            if not categories:
                return
            neighborhood = listing["neighborhood"]
            neighborhood["location_precision"] = location["precision"]
            coords = _coords(listing.get("latitude"), listing.get("longitude"))
            if not coords or location["precision"] in {"city", "district", "unknown"}:
                neighborhood["status"] = "location_unknown" if not coords else "approximate_location"
                for category in categories:
                    neighborhood["coverage"][category]["status"] = neighborhood["status"]
                return
            lat, lon = coords
            precise = location["precision"] == "building" and not location["approximate"]
            statuses = []
            for category in categories:
                result = await call(
                    provider.search_places, query="", categories=CATEGORIES[category], limit=10,
                    geo_filter=f"circle:{lon},{lat},{radius}", bias=f"proximity:{lon},{lat}",
                )
                pairs = [(item, _feature(item, coords, category, precise, result.checked_at)) for item in result.places[:10] if isinstance(item, dict)]
                pairs = [(raw, item) for raw, item in pairs if item is not None]
                pairs.sort(key=lambda pair: pair[1]["distance_m"] if pair[1]["distance_m"] is not None else math.inf)
                features = [item for _, item in pairs]
                status = result.status if result.status != "ok" else "partial" if features else "no_features_returned"
                statuses.append(status)
                neighborhood["features"][category] = features
                neighborhood["coverage"][category] = {
                    "status": status, "cache_hit": result.cache_hit, "exhaustive": False,
                    "checked_at": result.checked_at, "returned_count": len(features),
                }
                if result.status != "ok":
                    warnings.add(f"Home neighborhood lookup has partial coverage ({result.status}).")
                if category == "water" and precise and _get(request, "max_water_walk_minutes") is not None:
                    # At most one route per listing. Do not route to lake centroids
                    # or shore segments with no explicit public pedestrian target.
                    for raw, feature in pairs:
                        target = _public_waterfront_target(raw, coords)
                        if target is None:
                            continue
                        route = await call(provider.walking_route, origin=coords, target=target)
                        feature["walk_status"] = route.status
                        if route.status == "ok" and route.places:
                            props = _mapping(_mapping(route.places[0]).get("properties"))
                            seconds = _number(props.get("time"))
                            distance = _number(props.get("distance"))
                            if seconds is not None and distance is not None and seconds >= 0 and distance >= 0:
                                feature.update(
                                    walk_minutes=round(seconds / 60, 2), walk_distance_m=round(distance),
                                    walk_status="routed", walk_method="provider_walking_route",
                                    walk_checked_at=route.checked_at, walk_cache_hit=route.cache_hit,
                                    walk_target={"latitude": target[0], "longitude": target[1], "access": "provider_public_pedestrian"},
                                )
                        break
                if category == "water" and any(item["distance_method"] != "shoreline_geometry" for item in features):
                    warnings.add("Water geometry is incomplete; representative-point distance does not establish shoreline proximity.")
                if category == "water" and _get(request, "max_water_walk_minutes") is not None and not any(item["walk_minutes"] is not None for item in features):
                    warnings.add("Walking access to public waterfront is unknown without a supported public target and route.")
            neighborhood["status"] = "partial" if statuses else "unknown"
            neighborhood["checked_at"] = datetime.now(timezone.utc).isoformat()

    for index, listing in enumerate(listings):
        if _is_city_fallback(listing):
            set_city_fallback(listing, _coords(listing.get("latitude"), listing.get("longitude")))
        if categories:
            listing["neighborhood"] = {
                "status": "pending" if index < MAX_LOCATION_CANDIDATES else "candidate_limit",
                "source": GEOAPIFY_SOURCE_LABEL, "checked_at": None,
                "radius_m": radius, "location_precision": "unknown",
                "coverage": {category: {"status": "not_checked", "exhaustive": False} for category in categories},
                "features": {category: [] for category in categories},
            }
    tasks = [asyncio.create_task(locate(listing)) for listing in listings[:MAX_LOCATION_CANDIDATES]]
    try:
        async with asyncio.timeout(LOCATION_TIMEOUT_SECONDS):
            await asyncio.gather(*tasks)
            # Locate all prioritized candidates before spending the remaining
            # shared budget on optional category searches for a few addresses.
            tasks = [asyncio.create_task(enrich(listing)) for listing in listings[:MAX_LOCATION_CANDIDATES]]
            await asyncio.gather(*tasks)
    except TimeoutError:
        warnings.add("Home location enrichment reached its time limit; coverage is partial.")
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if fallback_task is not None and not fallback_task.done():
            fallback_task.cancel()
            await asyncio.gather(fallback_task, return_exceptions=True)
    for index, listing in enumerate(listings):
        if "location" not in listing:
            _provider_location(listing, status="candidate_limit" if index >= MAX_LOCATION_CANDIDATES else "timed_out")
        listing["location_source"] = listing["location"].get("source")
        neighborhood = listing.get("neighborhood")
        if categories and neighborhood["status"] == "pending":
            neighborhood["status"] = "timed_out"
        if categories:
            for coverage in neighborhood["coverage"].values():
                if coverage["status"] == "not_checked":
                    coverage["status"] = neighborhood["status"]
    if len(listings) > MAX_LOCATION_CANDIDATES:
        warnings.add("Home location enrichment candidate limit reached; remaining locations retain provider evidence.")
    return sorted(warnings)


async def _locate(listing: dict[str, Any], city: str, call: Any, provider: Any, fallback: Any) -> None:
    """Preserve provider coordinates; never upgrade a declared approximation."""
    was_city_fallback = _is_city_fallback(listing)
    if _coords(listing.get("latitude"), listing.get("longitude")) and not was_city_fallback:
        _provider_location(listing)
        return
    address = listing.get("address")
    if isinstance(address, dict):
        address = ", ".join(str(address.get(key) or "") for key in ("street", "house_number", "postcode", "district", "city") if address.get(key))
    query = ", ".join(part for part in (str(address or "").strip(), city) if part)
    result = await call(provider.geocode_address, query)
    candidates = [item for item in result.places[:2] if isinstance(item, dict) and _feature_coords(item)]
    if result.status == "ok" and candidates:
        first = candidates[0]
        props = _mapping(first.get("properties"))
        rank = _mapping(props.get("rank"))
        precision = _precision(props.get("result_type"))
        match_type = rank.get("match_type")
        if match_type == "match_by_street":
            precision = "street"
        elif match_type in {"match_by_postcode", "match_by_city_or_disrict", "match_by_city_or_district"}:
            precision = "district"
        elif match_type == "match_by_country_or_state":
            precision = "unknown"
        confidence = _number(rank.get("confidence"))
        # Multiple materially different matches are ambiguous. Do not pick an
        # apartment based on an arbitrary first result or a weak match.
        ambiguous = False
        if len(candidates) > 1:
            first_coords, other_coords = _feature_coords(first), _feature_coords(candidates[1])
            ambiguous = _haversine(first_coords, other_coords) > 100
        if not ambiguous and confidence is not None and confidence >= 0.8:
            lat, lon = _feature_coords(first)
            declared = _precision(listing.get("location_precision"))
            if declared in {"city", "district"} and not was_city_fallback:
                precision = declared
            approximate = precision != "building" or _declared_approximation(listing)
            listing.update(latitude=lat, longitude=lon, location_precision=precision, location_approximate=approximate, location_source=GEOAPIFY_SOURCE_LABEL)
            listing["location"] = {
                "status": "ok", "precision": precision, "approximate": approximate,
                "source": GEOAPIFY_SOURCE_LABEL, "method": "address_geocode",
                "match_type": rank.get("match_type"), "confidence": confidence,
                "checked_at": result.checked_at, "cache_hit": result.cache_hit,
                "provider_result_type": props.get("result_type"),
            }
            return
        status = "ambiguous" if ambiguous else "low_confidence"
    else:
        status = result.status if result.status != "ok" else "no_match"
    coords = await fallback()
    if coords and _coords(*coords):
        set_city_fallback(listing, coords, geocode_status=status)
    else:
        _provider_location(listing, status=status)


def _provider_location(listing: dict[str, Any], status: str = "provider") -> None:
    previous = listing.get("location") if isinstance(listing.get("location"), dict) else {}
    precision = _precision(listing.get("location_precision") or previous.get("precision"))
    coords = _coords(listing.get("latitude"), listing.get("longitude"))
    approximate = _is_approximate(listing) or precision != "building"
    listing["location_precision"] = precision
    listing["location_approximate"] = approximate
    listing["location"] = {
        **previous, "status": status if coords or status != "provider" else "unavailable",
        "precision": precision, "approximate": approximate,
        "source": previous.get("source") or listing.get("location_source") or listing.get("provider") or "listing provider",
        "method": "provider_coordinates" if coords else "unknown",
        "checked_at": previous.get("checked_at"),
    }
    if not coords:
        listing["latitude"] = listing["longitude"] = None


def _feature(feature: dict[str, Any], origin: tuple[float, float], category: str, precise: bool, checked_at: str | None) -> dict[str, Any] | None:
    props = _mapping(feature.get("properties"))
    coords = _feature_coords(feature)
    geometry = _mapping(feature.get("geometry"))
    distance, method = None, "unknown"
    geometry_distance = _geometry_distance(geometry, origin)
    if precise and geometry_distance is not None:
        distance = round(geometry_distance)
        method = "shoreline_geometry" if category == "water" and geometry.get("type") in {"Polygon", "MultiPolygon"} and _is_water_area(feature) else "feature_geometry"
    elif precise and coords:
        distance, method = round(_haversine(origin, coords)), "representative_point"
    if not coords and distance is None:
        return None
    return {
        "name": props.get("name") or props.get("formatted") or category,
        "distance_m": distance, "distance_method": method,
        "walk_minutes": None, "walk_status": "access_unknown", "source": GEOAPIFY_SOURCE_LABEL,
        "checked_at": checked_at, "latitude": coords[0] if coords else None,
        "longitude": coords[1] if coords else None,
        "geometry_status": "available" if geometry_distance is not None else "representative_point_only" if coords else "unknown",
        "location_precision": "building" if precise else "approximate",
    }


def _public_waterfront_target(feature: dict[str, Any], origin: tuple[float, float]) -> tuple[float, float] | None:
    """Only explicitly public pedestrian pier geometry establishes a target.

    Water polygons, access tags on the water itself and representative points
    do not establish a reachable public waterfront entrance.
    """
    props = _mapping(feature.get("properties"))
    raw = _mapping(_mapping(props.get("datasource")).get("raw"))
    if raw.get("man_made") != "pier" or raw.get("access") not in {"yes", "public", "permissive"} or raw.get("foot") in {"no", "private"}:
        return None
    geometry = _mapping(feature.get("geometry"))
    if geometry.get("type") != "LineString":
        return None
    line = geometry.get("coordinates") or []
    if not 2 <= len(line) <= MAX_GEOMETRY_VERTICES:
        return None
    endpoints = [_coords(point[1], point[0]) for point in (line[0], line[-1]) if isinstance(point, list) and len(point) >= 2]
    endpoints = [point for point in endpoints if point]
    return min(endpoints, key=lambda point: _haversine(origin, point)) if endpoints else None


def _geometry_distance(geometry: dict[str, Any], origin: tuple[float, float]) -> float | None:
    """Local metric projection to finite provider segments, including polygon holes.

    Distances are rounded meters of supplied geometry, not survey accuracy.
    Line geometry is never described as shoreline (a river line can be its
    centerline). Oversize or malformed geometry remains unknown.
    """
    kind, coordinates = geometry.get("type"), geometry.get("coordinates")
    if kind == "LineString":
        lines = [coordinates]
    elif kind in {"MultiLineString", "Polygon"}:
        lines = coordinates
    elif kind == "MultiPolygon" and isinstance(coordinates, list):
        if len(coordinates) > MAX_GEOMETRY_VERTICES:
            return None
        lines = []
        for polygon in coordinates:
            if not isinstance(polygon, list) or len(lines) + len(polygon) > MAX_GEOMETRY_VERTICES:
                return None
            lines.extend(polygon)
    else:
        return None
    if not isinstance(lines, list) or len(lines) > MAX_GEOMETRY_VERTICES:
        return None
    count = 0
    best = math.inf
    scale_x = 111195 * math.cos(math.radians(origin[0]))
    for line in lines:
        if not isinstance(line, list) or len(line) < 2:
            return None
        if kind in {"Polygon", "MultiPolygon"} and (len(line) < 4 or line[0] != line[-1]):
            return None
        count += len(line)
        if count > MAX_GEOMETRY_VERTICES:
            return None
        points = []
        for point in line:
            if not isinstance(point, (list, tuple)) or len(point) < 2 or not _coords(point[1], point[0]):
                return None
            points.append(((float(point[0]) - origin[1]) * scale_x, (float(point[1]) - origin[0]) * 111195))
        for (ax, ay), (bx, by) in zip(points, points[1:]):
            dx, dy = bx - ax, by - ay
            fraction = max(0, min(1, -(ax * dx + ay * dy) / (dx * dx + dy * dy))) if dx or dy else 0
            best = min(best, math.hypot(ax + fraction * dx, ay + fraction * dy))
    return best if math.isfinite(best) else None


def _get(request: Any, key: str, default: Any = None) -> Any:
    return request.get(key, default) if isinstance(request, dict) else getattr(request, key, default)


def _precision(value: Any) -> str:
    return {"exact": "building", "address": "building", "house": "building", "building": "building", "street": "street", "district": "district", "suburb": "district", "neighborhood": "district", "postcode": "district", "city": "city"}.get(str(value or "").lower(), "unknown")


def _is_approximate(listing: dict[str, Any]) -> bool:
    location = _mapping(listing.get("location"))
    return any(value is True for value in (listing.get("location_approximate"), listing.get("approximate"), location.get("approximate")))


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _coords(lat: Any, lon: Any) -> tuple[float, float] | None:
    lat, lon = _number(lat), _number(lon)
    return (lat, lon) if lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180 else None


def _feature_coords(feature: dict[str, Any]) -> tuple[float, float] | None:
    props = _mapping(feature.get("properties"))
    coords = _coords(props.get("lat"), props.get("lon"))
    if coords:
        return coords
    geometry = _mapping(feature.get("geometry"))
    point = geometry.get("coordinates")
    return _coords(point[1], point[0]) if geometry.get("type") == "Point" and isinstance(point, list) and len(point) >= 2 else None


def _haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    dlat, dlon = math.radians(b[0] - a[0]), math.radians(b[1] - a[1])
    square = math.sin(dlat / 2) ** 2 + math.cos(math.radians(a[0])) * math.cos(math.radians(b[0])) * math.sin(dlon / 2) ** 2
    return 12742000 * math.asin(min(1, math.sqrt(square)))


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _is_water_area(feature: dict[str, Any]) -> bool:
    """Do not mistake pier or coastal-land polygons for a water shoreline."""
    props = _mapping(feature.get("properties"))
    raw = _mapping(_mapping(props.get("datasource")).get("raw"))
    categories = props.get("categories")
    return raw.get("natural") == "water" or raw.get("waterway") == "riverbank" or (
        isinstance(categories, list) and any(isinstance(value, str) and (value == "natural.water" or value.startswith("natural.water.")) for value in categories)
    )


def _declared_approximation(listing: dict[str, Any]) -> bool:
    """Distinguish provider intent from normalized unknown-location defaults.

    Housing adapters may mark an unknown point approximate by default. With no
    point and no source, that flag does not declare an intentionally hidden or
    approximate address. Adapters retain explicit raw declarations separately,
    including declarations supplied without coordinates.
    """
    location = _mapping(listing.get("location"))
    if listing.get("location_approximation_declared") is True or listing.get("approximate") is True:
        return True
    if location.get("approximate") is True and location.get("method") not in {"unknown", "city_fallback"}:
        return True
    return listing.get("location_approximate") is True and bool(listing.get("location_source")) and not _is_city_fallback(listing)


def _is_city_fallback(listing: dict[str, Any]) -> bool:
    """Recognize provenance, never guess a centroid from coordinate equality."""
    location = _mapping(listing.get("location"))
    return location.get("method") == "city_fallback" or any(
        str(source or "").lower() in {"city_lookup", "openmates city lookup", "openmates city lookup / openstreetmap nominatim"}
        for source in (listing.get("location_source"), location.get("source"))
    )


def set_city_fallback(
    listing: dict[str, Any], coords: tuple[float, float] | None, *,
    source: str = "OpenMates city lookup / OpenStreetMap Nominatim",
    geocode_status: str | None = None,
) -> None:
    """Keep root and nested city provenance consistent through embed flattening."""
    previous = _mapping(listing.get("location"))
    listing.update(
        latitude=coords[0] if coords else None, longitude=coords[1] if coords else None,
        location_precision="city", location_approximate=True, location_source=source,
    )
    listing["location"] = {
        "status": "approximate" if coords else "unavailable", "precision": "city",
        "approximate": True, "source": source, "method": "city_fallback", "checked_at": None,
        "geocode_status": geocode_status or previous.get("geocode_status") or previous.get("status") or "not_checked",
    }
