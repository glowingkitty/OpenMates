# backend/shared/providers/urban_sports/client.py
#
# Async public-web client for Urban Sports Club discovery pages.
#
# This client intentionally uses logged-out venue/activity pages and parses only
# public data. It never sends OpenMates user identifiers or stores credentials;
# user-entered addresses are transient inputs for geocoding/radius filtering.

from __future__ import annotations

import datetime as dt
from typing import Any
from urllib.parse import urlencode

import httpx

from backend.shared.providers.urban_sports.parsers import (
    UrbanSportsClassCard,
    UrbanSportsVenueCard,
    class_has_min_spots,
    dedupe_classes,
    filter_by_plan,
    haversine_km,
    matches_query,
    parse_activity_cards,
    parse_venue_cards,
    parse_venue_detail,
)
from backend.shared.python_utils.geo_utils import geocode_address


BASE_URL = "https://urbansportsclub.com"
DEFAULT_LANGUAGE = "en"
DEFAULT_CITY_ID = "1"
DEFAULT_BUSINESS_TYPE = "b2c"
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_USER_AGENT = "OpenMates/1.0 (https://openmates.org)"
PLAN_TYPE_IDS = {
    "essential": "1",
    "classic": "2",
    "premium": "3",
    "max": "6",
}


class UrbanSportsClient:
    def __init__(self, *, base_url: str = BASE_URL, language: str = DEFAULT_LANGUAGE, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.base_url = base_url.rstrip("/")
        self.language = language.strip("/") or DEFAULT_LANGUAGE
        self.timeout = timeout
        self._venue_detail_cache: dict[str, dict[str, Any]] = {}

    async def search_locations(
        self,
        *,
        query: str | None = None,
        city: str | None = None,
        city_id: str | None = None,
        address: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        radius_km: float | None = None,
        plan: str | None = None,
        category: str | None = None,
        limit: int = 10,
        language: str | None = None,
    ) -> list[dict[str, Any]]:
        center = await self._resolve_center(address=address, city=city, lat=lat, lon=lon)
        html = await self._fetch_search_page(
            "venues",
            language=language,
            city_id=city_id or DEFAULT_CITY_ID,
            plan=plan,
            category=category,
            page=1,
        )
        venues = [venue for venue in filter_by_plan(parse_venue_cards(html), plan) if matches_query(venue.to_dict(), query)]
        enriched = [await self._venue_to_result(venue, center=center) for venue in venues]
        filtered = _filter_radius(enriched, radius_km)
        filtered.sort(key=lambda item: (item.get("distance_km") is None, item.get("distance_km") or 9999, item.get("name") or ""))
        return filtered[: max(1, min(int(limit or 10), 50))]

    async def search_classes(
        self,
        *,
        query: str | None = None,
        city: str | None = None,
        city_id: str | None = None,
        address: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        radius_km: float | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        days: int | None = None,
        plan: str | None = None,
        attendance_mode: str = "onsite",
        min_spots: int = 1,
        category: str | None = None,
        venue_id: str | None = None,
        limit: int = 10,
        language: str | None = None,
    ) -> list[dict[str, Any]]:
        center = await self._resolve_center(address=address, city=city, lat=lat, lon=lon)
        search_dates = _date_window(start_date=start_date, end_date=end_date, days=days)
        classes: list[UrbanSportsClassCard] = []
        for search_date in search_dates:
            html = await self._fetch_search_page(
                "activities",
                language=language,
                city_id=city_id or DEFAULT_CITY_ID,
                plan=plan,
                category=category,
                venue=venue_id,
                attendance_mode=attendance_mode,
                date=search_date,
                page=1,
            )
            classes.extend(parse_activity_cards(html, date=search_date))

        classes = dedupe_classes(classes)
        classes = [item for item in filter_by_plan(classes, plan) if class_has_min_spots(item, max(int(min_spots), 0))]
        if attendance_mode in {"online", "onsite"}:
            classes = [item for item in classes if item.attendance_mode == attendance_mode]
        classes = [item for item in classes if matches_query(item.to_dict(), query)]

        enriched = [await self._class_to_result(item, center=center) for item in classes]
        filtered = _filter_radius(enriched, radius_km)
        filtered.sort(key=lambda item: (item.get("date") or "9999", item.get("time_range") or "", item.get("distance_km") or 9999))
        return filtered[: max(1, min(int(limit or 10), 50))]

    async def _venue_to_result(self, venue: UrbanSportsVenueCard, *, center: tuple[float, float] | None) -> dict[str, Any]:
        detail = await self._get_venue_detail(venue.url)
        lat = detail.get("lat")
        lon = detail.get("lon")
        distance = haversine_km(center[0], center[1], lat, lon) if center else None
        street = detail.get("street") or venue.street
        city = detail.get("city")
        return {
            "id": _slug_from_url(venue.url),
            "provider": "Urban Sports Club",
            "venue_id": _slug_from_url(venue.url),
            "address_id": venue.address_id,
            "name": detail.get("name") or venue.name,
            "url": venue.url,
            "address": _join_address(street, detail.get("postal_code"), city),
            "street": street,
            "postal_code": detail.get("postal_code"),
            "city": city,
            "country": detail.get("country"),
            "lat": lat,
            "lon": lon,
            "distance_km": round(distance, 3) if distance is not None and distance != float("inf") else None,
            "disciplines": venue.disciplines,
            "plans_required": venue.plans_required,
            "image_url": detail.get("image_url") or venue.image_url,
            "rating": detail.get("rating"),
            "rating_count": detail.get("rating_count"),
        }

    async def _class_to_result(self, item: UrbanSportsClassCard, *, center: tuple[float, float] | None) -> dict[str, Any]:
        venue_detail = await self._get_venue_detail(item.venue_url) if item.venue_url else {}
        lat = venue_detail.get("lat")
        lon = venue_detail.get("lon")
        distance = haversine_km(center[0], center[1], lat, lon) if center else None
        return {
            "id": item.appointment_id,
            "provider": "Urban Sports Club",
            "appointment_id": item.appointment_id,
            "name": item.name,
            "category": item.category,
            "class_type": item.class_type,
            "attendance_mode": item.attendance_mode,
            "date": item.date,
            "time_range": item.time_range,
            "venue_name": item.venue_name,
            "venue_url": item.venue_url,
            "venue_address": _join_address(venue_detail.get("street"), venue_detail.get("postal_code"), venue_detail.get("city")),
            "venue_postal_code": venue_detail.get("postal_code"),
            "venue_city": venue_detail.get("city"),
            "venue_lat": lat,
            "venue_lon": lon,
            "distance_km": round(distance, 3) if distance is not None and distance != float("inf") else None,
            "spots_left": item.spots_left,
            "spots_display": item.spots_display,
            "plans_required": item.plans_required,
            "detail_url": item.detail_url,
            "image_url": item.image_url or venue_detail.get("image_url"),
        }

    async def _get_venue_detail(self, url: str | None) -> dict[str, Any]:
        if not url:
            return {}
        if url in self._venue_detail_cache:
            return self._venue_detail_cache[url]
        html = await self._fetch_url(url)
        detail = parse_venue_detail(html, url=url).to_dict()
        self._venue_detail_cache[url] = detail
        return detail

    async def _resolve_center(
        self,
        *,
        address: str | None,
        city: str | None,
        lat: float | None,
        lon: float | None,
    ) -> tuple[float, float] | None:
        if lat is not None and lon is not None:
            return float(lat), float(lon)
        if address or city:
            return await geocode_address(address, city=city, country="Germany" if city and city.casefold() == "berlin" else None)
        return None

    async def _fetch_search_page(self, endpoint: str, **params: Any) -> str:
        language = params.pop("language", None) or self.language
        url = self._build_search_url(endpoint, language=language, params=params)
        return await self._fetch_url(url)

    async def _fetch_url(self, url: str) -> str:
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": DEFAULT_USER_AGENT,
        }
        async with httpx.AsyncClient(timeout=self.timeout, headers=headers, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text

    def _build_search_url(self, endpoint: str, *, language: str, params: dict[str, Any]) -> str:
        query: list[tuple[str, str]] = []
        for key, value in params.items():
            if value in (None, "", "all"):
                continue
            if key == "business_type":
                query.append(("business_type[]", str(value)))
            elif key == "plan":
                plan_id = PLAN_TYPE_IDS.get(str(value).casefold())
                if plan_id:
                    query.append(("plan_type", plan_id))
            elif key == "attendance_mode":
                if value == "online":
                    query.append(("type[]", "live"))
                elif value == "onsite":
                    query.append(("type[]", "onsite"))
            elif key == "date":
                query.append(("date", str(value)))
            elif key == "city_id":
                query.append(("city_id", str(value)))
            elif key == "venue":
                query.append(("venue", str(value)))
            elif key != "page" or int(value) > 1:
                query.append((key, str(value)))
        query.append(("business_type[]", DEFAULT_BUSINESS_TYPE))
        encoded = urlencode(query)
        return f"{self.base_url}/{language}/{endpoint}?{encoded}"


def _filter_radius(items: list[dict[str, Any]], radius_km: float | None) -> list[dict[str, Any]]:
    if radius_km is None:
        return items
    radius = float(radius_km)
    return [item for item in items if item.get("distance_km") is not None and float(item["distance_km"]) <= radius]


def _date_window(*, start_date: str | None, end_date: str | None, days: int | None) -> list[str]:
    start = dt.date.fromisoformat(start_date) if start_date else dt.date.today()
    if end_date:
        end = dt.date.fromisoformat(end_date)
        day_count = max((end - start).days + 1, 1)
    else:
        day_count = max(int(days or 1), 1)
    return [(start + dt.timedelta(days=offset)).isoformat() for offset in range(min(day_count, 14))]


def _join_address(street: str | None, postal_code: str | None, city: str | None) -> str | None:
    parts = [part for part in (street, " ".join(part for part in (postal_code, city) if part)) if part]
    return ", ".join(parts) if parts else None


def _slug_from_url(url: str | None) -> str | None:
    if not url:
        return None
    return url.rstrip("/").rsplit("/", 1)[-1]
