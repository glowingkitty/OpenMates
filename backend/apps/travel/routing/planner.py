"""Add mixed routes for owned passes to one connection search group and rank it by amount paid.

Runs after the installed providers answered the traveller's own request. With an
owned pass that covers one end of a trip leaving the pass area, it searches at
most two parts per selected hub (the pass part with the pass's product filter,
the paid part with the requested transport methods), composes them and ranks
the whole group. Identical part searches are reused for 15 minutes.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections import Counter
from datetime import timedelta
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from backend.apps.travel.routing.compose import (
    MIN_SEPARATE_TICKET_TRANSFER_MINUTES,
    PAID_THEN_PASS,
    PASS_THEN_PAID,
    annotate_savings,
    compose_routes,
    parse_time,
    prune_composed,
    rank_results,
    segments_of,
)
from backend.apps.travel.routing.hubs import GeoPoint, Hub, near_hub, select_hubs
from backend.apps.travel.routing.passes import TravelPass, resolve_passes

logger = logging.getLogger(__name__)

SEARCH_CACHE_TTL_SECONDS = 15 * 60
# Hub searches must finish inside the skill's 60 s envelope after the providers answered.
COMPOSE_BUDGET_SECONDS = 30.0
PART_MAX_RESULTS = 10
GROUND_METHODS = ("train", "bus")
COPIED_FIELDS = ("passengers", "children", "infants_in_seat", "infants_on_lap", "travel_class", "currency",
                 "min_transfer_minutes")
CACHE_ERRORS = (ConnectionError, OSError, RuntimeError, TimeoutError, ValueError, TypeError)

Search = Callable[[Dict[str, Any]], Awaitable[List[Dict[str, Any]]]]
Locate = Callable[[str], Awaitable[Optional[GeoPoint]]]


def _trip(contract_input: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
    legs = contract_input.get("legs")
    if isinstance(legs, list):
        if len(legs) != 1 or not isinstance(legs[0], dict):
            return None
        leg = legs[0]
    else:
        leg = contract_input
    origin, destination, date = leg.get("origin"), leg.get("destination"), leg.get("date")
    if isinstance(origin, str) and isinstance(destination, str) and isinstance(date, str) \
            and origin.strip() and destination.strip() and date.strip():
        return origin, destination, date
    return None


def _point(segment: Dict[str, Any], side: str) -> Optional[GeoPoint]:
    lat, lon = segment.get(f"{side}_latitude"), segment.get(f"{side}_longitude")
    country = segment.get(f"{side}_country_code")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and isinstance(country, str) and country:
        return GeoPoint(float(lat), float(lon), country.upper())
    return None


def _endpoint_from_results(results: Sequence[Dict[str, Any]], side: str) -> Optional[GeoPoint]:
    """Most common start (``departure``) or end (``arrival``) point among the results."""
    points = []
    for result in results:
        segments = segments_of(result)
        if segments:
            point = _point(segments[0] if side == "departure" else segments[-1], side)
            if point is not None:
                points.append(point)
    if not points:
        return None
    country, _ = Counter(point.country for point in points).most_common(1)[0]
    return next(point for point in points if point.country == country)


def _part_item(contract_input: Dict[str, Any], origin: str, destination: str, date: str,
               methods: Sequence[str], countries: Sequence[str], *, rail_products: Optional[List[str]] = None,
               min_departure: Optional[str] = None, keep_window: bool = False) -> Dict[str, Any]:
    item: Dict[str, Any] = {key: contract_input[key] for key in COPIED_FIELDS if key in contract_input}
    item.update({
        "legs": [{"origin": origin, "destination": destination, "date": date}],
        "transport_methods": list(methods),
        "countries": sorted(set(countries)),
        "owned_passes": list(contract_input.get("owned_passes") or []),
        "max_results": PART_MAX_RESULTS,
        "sort_by": "departure_asc",
    })
    if rail_products:
        item["rail_products"] = rail_products
    if keep_window:
        for key in ("min_departure_time", "max_departure_time"):
            if contract_input.get(key):
                item[key] = contract_input[key]
    if min_departure:
        item["min_departure_time"] = min_departure
    return item


def _earliest_after(results: Sequence[Dict[str, Any]], date: str) -> Optional[str]:
    """HH:MM of the earliest arrival plus the minimum separate-ticket buffer, on ``date`` only."""
    arrivals = [parse_time(segments_of(result)[-1].get("arrival_time")) for result in results if segments_of(result)]
    arrivals = [arrival for arrival in arrivals if arrival is not None]
    if not arrivals:
        return None
    earliest = min(arrivals) + timedelta(minutes=MIN_SEPARATE_TICKET_TRANSFER_MINUTES)
    return earliest.strftime("%H:%M") if earliest.strftime("%Y-%m-%d") == date else None


class CachedSearch:
    """Reuse identical part searches for 15 minutes; a cache failure only costs a search."""

    def __init__(self, search: Search, cache_service: Any = None) -> None:
        self._search, self._cache = search, cache_service
        self.searches = 0

    @staticmethod
    def key(item: Dict[str, Any]) -> str:
        digest = hashlib.sha256(json.dumps(item, sort_keys=True, default=str).encode()).hexdigest()[:32]
        return f"travel:mixed_route_part:v1:{digest}"

    async def __call__(self, item: Dict[str, Any]) -> List[Dict[str, Any]]:
        key = self.key(item)
        if self._cache is not None:
            try:
                cached = await self._cache.get(key)
            except CACHE_ERRORS as exc:
                logger.warning("[MixedRoutes] Part cache read failed: %s", exc)
                cached = None
            if isinstance(cached, list):
                return cached
        self.searches += 1
        results = await self._search(item)
        if self._cache is not None:
            try:
                await self._cache.set(key, results, ttl=SEARCH_CACHE_TTL_SECONDS)
            except CACHE_ERRORS as exc:
                logger.warning("[MixedRoutes] Part cache write failed: %s", exc)
        return results


def _at_hub(results: Sequence[Dict[str, Any]], hub: Hub, side: str) -> List[Dict[str, Any]]:
    """Results whose hub-side stop (``arrival`` of the last or ``departure`` of the first segment) is at the hub."""
    kept = []
    for result in results:
        segments = segments_of(result)
        if not segments:
            continue
        segment = segments[-1] if side == "arrival" else segments[0]
        if near_hub(hub, segment.get(f"{side}_latitude"), segment.get(f"{side}_longitude")):
            kept.append(result)
    return kept


async def _compose_through(hub: Hub, kind: str, contract_input: Dict[str, Any], trip: Tuple[str, str, str],
                           travel_pass: TravelPass, passes: Sequence[TravelPass], other_country: str,
                           methods: Sequence[str], search: Search) -> List[Dict[str, Any]]:
    origin, destination, date = trip
    pass_countries = sorted(travel_pass.countries)
    if kind == PASS_THEN_PAID:
        covered = _at_hub(await search(_part_item(
            contract_input, origin, hub.name, date, ["train"], pass_countries,
            rail_products=travel_pass.search_rail_products, keep_window=True)), hub, "arrival")
        after = _earliest_after(covered, date)
        if after is None:
            return []
        paid = _at_hub(await search(_part_item(contract_input, hub.name, destination, date, methods,
                                               [hub.country, other_country], min_departure=after)),
                       hub, "departure")
    else:
        paid = _at_hub(await search(_part_item(contract_input, origin, hub.name, date, methods,
                                               [other_country, hub.country], keep_window=True)),
                       hub, "arrival")
        after = _earliest_after(paid, date)
        if after is None:
            return []
        covered = _at_hub(await search(_part_item(
            contract_input, hub.name, destination, date, ["train"], pass_countries,
            rail_products=travel_pass.search_rail_products, min_departure=after)), hub, "departure")
    return compose_routes(covered, paid, kind, passes, hub.name, int(contract_input.get("min_transfer_minutes") or 0))


async def plan_mixed_routes(group: Dict[str, Any], contract_input: Dict[str, Any], search: Search,
                            locate: Optional[Locate] = None, cache_service: Any = None) -> None:
    """Add composed routes to ``group`` and rank its results; no-op without an owned pass."""
    passes = resolve_passes(contract_input.get("owned_passes") or [])
    if not passes:
        return
    results: List[Dict[str, Any]] = list(group.get("results") or [])
    composed: List[Dict[str, Any]] = []
    trip = _trip(contract_input)
    methods = [m for m in contract_input.get("transport_methods") or [] if m in GROUND_METHODS]
    hubs: List[Hub] = []
    timed_out = False
    cached = CachedSearch(search, cache_service)
    if trip is not None and methods:
        start = _endpoint_from_results(results, "departure") or (await locate(trip[0]) if locate else None)
        end = _endpoint_from_results(results, "arrival") or (await locate(trip[1]) if locate else None)
        plan = _choose_plan(start, end, passes)
        if plan is not None:
            kind, travel_pass, covered_end, other_end = plan
            hubs = select_hubs(covered_end, other_end, travel_pass.countries)
            try:
                per_hub = await asyncio.wait_for(asyncio.gather(*(
                    _compose_through(hub, kind, contract_input, trip, travel_pass, passes, other_end.country,
                                     methods, cached)
                    for hub in hubs
                )), timeout=COMPOSE_BUDGET_SECONDS)
            except asyncio.TimeoutError:
                # Finished part searches stay cached; the traveller still gets the ranked direct results.
                logger.warning("[MixedRoutes] Hub searches exceeded %.0fs; no composed routes this time",
                               COMPOSE_BUDGET_SECONDS)
                per_hub, timed_out = [], True
            composed = prune_composed([route for routes in per_hub for route in routes], results, passes)
    merged = results + composed
    annotate_savings(merged, passes)
    group["results"] = rank_results(merged, passes)
    group["providers"] = list(dict.fromkeys(
        pid for result in group["results"] for pid in (result.get("provider_ids") or [result.get("provider_id")]) if pid))
    group["mixed_routes"] = {
        "passes": [travel_pass.pass_id for travel_pass in passes],
        "hubs": [hub.name for hub in hubs],
        "composed": len(composed),
        "part_searches": cached.searches,
        "timed_out": timed_out,
        "ranking": "amount_paid_then_duration_then_changes",
    }
    logger.info("[MixedRoutes] passes=%s hubs=%s composed=%d part_searches=%d",
                group["mixed_routes"]["passes"], group["mixed_routes"]["hubs"], len(composed), cached.searches)


def _choose_plan(start: Optional[GeoPoint], end: Optional[GeoPoint], passes: Sequence[TravelPass]
                 ) -> Optional[Tuple[str, TravelPass, GeoPoint, GeoPoint]]:
    """Which end the pass covers; None for trips inside or outside every pass area."""
    if start is None or end is None:
        return None
    for travel_pass in passes:
        start_in, end_in = start.country in travel_pass.countries, end.country in travel_pass.countries
        if start_in and not end_in:
            return PASS_THEN_PAID, travel_pass, start, end
        if end_in and not start_in:
            return PAID_THEN_PASS, travel_pass, end, start
    return None


def geoapify_locator(secrets_manager: Any, cache_service: Any) -> Locate:
    """Place name to point and country through the official geocoding API (cached, budgeted)."""
    from backend.shared.providers.geoapify.places import GeoapifyPlacesProvider

    provider = GeoapifyPlacesProvider(secrets_manager=secrets_manager, cache_service=cache_service,
                                      timeout_seconds=3.0)

    async def locate(name: str) -> Optional[GeoPoint]:
        found = await provider.geocode_area(name)
        if found.status != "ok" or not found.places:
            return None
        properties = found.places[0].get("properties") if isinstance(found.places[0], dict) else None
        if not isinstance(properties, dict):
            return None
        lat, lon, country = properties.get("lat"), properties.get("lon"), properties.get("country_code")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and isinstance(country, str):
            return GeoPoint(float(lat), float(lon), country.upper())
        return None

    return locate


async def refine_installed_group(group: Dict[str, Any], contract_input: Dict[str, Any], search: Search,
                                 secrets_manager: Any = None) -> None:
    """Hook for the installed-provider delegate: mixed routes and amount-paid ranking."""
    from backend.core.api.app.services.cache import CacheService

    cache_service = CacheService()
    await plan_mixed_routes(group, contract_input, search, geoapify_locator(secrets_manager, cache_service),
                            cache_service)
