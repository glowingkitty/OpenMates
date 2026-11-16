"""Compose pass-covered and paid connection results into mixed routes; rank by what is paid.

Pure functions over results of the generic connection contract (one-way
results; the first leg is the trip). A composed route is a normal connection
result plus ``tickets`` (one part per ticket, in travel order) and
``route_composition`` (hub, transfer, separate tickets, saving).
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from backend.apps.travel.routing.passes import TravelPass, covering_pass

PASS_THEN_PAID = "pass_then_paid"
PAID_THEN_PASS = "paid_then_pass"
COMPOSED_SOURCE = "composed"
MIN_SEPARATE_TICKET_TRANSFER_MINUTES = 20
MIN_CHANGE_OF_STOP_MINUTES = 45
MAX_WAIT_MINUTES = 180
ROUTES_PER_HUB = 2
BUS_MODES = {"bus", "coach", "long_distance_bus"}


def parse_time(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def minutes_between(start: Any, end: Any) -> Optional[int]:
    begin, finish = parse_time(start), parse_time(end)
    if begin is None or finish is None or (begin.tzinfo is None) != (finish.tzinfo is None):
        return None
    return int((finish - begin).total_seconds() // 60)


def format_minutes(total: int) -> str:
    hours, minutes = divmod(max(0, total), 60)
    return f"{hours}h {minutes}m" if hours else f"{minutes}m"


def first_leg(result: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    legs = result.get("legs")
    if not isinstance(legs, list) or len(legs) != 1 or not isinstance(legs[0], dict):
        return None
    return legs[0]


def segments_of(result: Mapping[str, Any]) -> List[Dict[str, Any]]:
    leg = first_leg(result)
    segments = leg.get("segments") if leg else None
    return [segment for segment in segments if isinstance(segment, dict)] if isinstance(segments, list) else []


def price_of(result: Mapping[str, Any]) -> Optional[float]:
    value = result.get("total_price")
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _station_key(name: Any) -> str:
    text = re.sub(r"\bgl\.?\s*[\w-]+", " ", str(name or "").casefold())
    return " ".join(re.sub(r"[^\w]+", " ", text).split())


def _is_bus(segment: Mapping[str, Any]) -> bool:
    return str(segment.get("mode") or "").casefold() in BUS_MODES


def transfer_minutes_needed(arriving: Mapping[str, Any], departing: Mapping[str, Any], requested: int) -> int:
    """Separate tickets carry no connection guarantee: at least 20 minutes, 45 across stops or rail/bus."""
    needed = max(int(requested or 0), MIN_SEPARATE_TICKET_TRANSFER_MINUTES)
    if _is_bus(arriving) != _is_bus(departing) or (
            _station_key(arriving.get("arrival_station")) != _station_key(departing.get("departure_station"))):
        needed = max(needed, MIN_CHANGE_OF_STOP_MINUTES)
    return needed


def effective_price(result: Mapping[str, Any], passes: Sequence[TravelPass]) -> Optional[float]:
    """Amount the traveller pays: composed amount, 0 when a pass covers every segment, else the fare."""
    composition = result.get("route_composition")
    if isinstance(composition, dict):
        amount = composition.get("paid_amount")
        return float(amount) if isinstance(amount, (int, float)) else None
    if passes and covering_pass(segments_of(result), passes) is not None:
        return 0.0
    return price_of(result)


def _duration(result: Mapping[str, Any]) -> int:
    leg = first_leg(result)
    found = minutes_between(leg.get("departure"), leg.get("arrival")) if leg else None
    return found if found is not None else 10 ** 6


def _changes(result: Mapping[str, Any]) -> int:
    return max(0, len(segments_of(result)) - 1)


def rank_results(results: List[Dict[str, Any]], passes: Sequence[TravelPass]) -> List[Dict[str, Any]]:
    """Priced routes first by amount paid, then duration, then changes; unknown fares last."""
    def key(result: Dict[str, Any]) -> Tuple[int, float, int, int]:
        paid = effective_price(result, passes)
        return (paid is None, paid or 0.0, _duration(result), _changes(result))
    return sorted(results, key=key)


def _ticket(result: Mapping[str, Any], segments: Sequence[Mapping[str, Any]],
            travel_pass: Optional[TravelPass]) -> Dict[str, Any]:
    price = None if travel_pass else price_of(result)
    coverage = "pass" if travel_pass else ("paid" if price is not None else "unknown_fare")
    ticket: Dict[str, Any] = {
        "route": f"{segments[0].get('departure_station')} -> {segments[-1].get('arrival_station')}",
        "departure": segments[0].get("departure_time"),
        "arrival": segments[-1].get("arrival_time"),
        "transport_method": result.get("transport_method"),
        "coverage": coverage,
        "pass_id": travel_pass.pass_id if travel_pass else None,
        "pass_label": travel_pass.label if travel_pass else None,
        "price": price,
        "currency": result.get("currency") if price is not None else None,
        "provider_id": result.get("provider_id"),
        "booking_url": None if travel_pass else result.get("booking_url"),
        "booking_provider": None if travel_pass else result.get("booking_provider"),
    }
    return ticket


def _marked_segments(segments: Sequence[Mapping[str, Any]], travel_pass: Optional[TravelPass],
                     priced: bool) -> List[Dict[str, Any]]:
    marked = []
    for segment in segments:
        copied = copy.deepcopy(dict(segment))
        copied["fare_coverage"] = f"pass:{travel_pass.pass_id}" if travel_pass else ("paid" if priced else None)
        marked.append(copied)
    return marked


def _hub_layover(arriving: Mapping[str, Any], departing: Mapping[str, Any], wait: int) -> Dict[str, Any]:
    layover: Dict[str, Any] = {
        "airport": arriving.get("arrival_station"),
        "airport_code": None,
        "duration": format_minutes(wait),
        "duration_minutes": wait,
        "overnight": False,
        "latitude": arriving.get("arrival_latitude"),
        "longitude": arriving.get("arrival_longitude"),
        "meets_min_transfer": True,
        "amenities": None,
        "separate_tickets": True,
    }
    if _station_key(arriving.get("arrival_station")) != _station_key(departing.get("departure_station")):
        layover["station_change"] = {"from": arriving.get("arrival_station"), "to": departing.get("departure_station")}
    return layover


def combine(first: Dict[str, Any], second: Dict[str, Any], kind: str, travel_pass: TravelPass,
            hub_name: str, wait: int) -> Dict[str, Any]:
    """One composed connection: ``first`` then ``second``; the pass covers one of them."""
    covered_first = kind == PASS_THEN_PAID
    paid = second if covered_first else first
    paid_price = price_of(paid)
    first_segments, second_segments = segments_of(first), segments_of(second)
    parts = [
        (first, first_segments, travel_pass if covered_first else None),
        (second, second_segments, None if covered_first else travel_pass),
    ]
    segments = [segment for result, part_segments, part_pass in parts
                for segment in _marked_segments(part_segments, part_pass, part_pass is None and paid_price is not None)]
    layovers = [
        *(first_leg(first).get("layovers") or []),
        _hub_layover(first_segments[-1], second_segments[0], wait),
        *(first_leg(second).get("layovers") or []),
    ]
    departure, arrival = first_segments[0].get("departure_time"), second_segments[-1].get("arrival_time")
    total = minutes_between(departure, arrival) or 0
    tickets = [_ticket(result, part_segments, part_pass) for result, part_segments, part_pass in parts]
    currency = paid.get("currency") if paid_price is not None else None
    covered = first if covered_first else second
    covered_route = tickets[0 if covered_first else 1]["route"]
    summary = (f"{currency} {paid_price:.2f} to pay; {covered_route} is covered by {travel_pass.label}."
               if paid_price is not None else
               f"{covered_route} is covered by {travel_pass.label}; the other ticket has no fare yet.")
    carriers = list(dict.fromkeys(str(segment.get("carrier")) for segment in segments if segment.get("carrier")))
    identity = json.dumps([first.get("hash"), second.get("hash"), travel_pass.pass_id], sort_keys=True)
    result: Dict[str, Any] = {
        "type": "connection",
        "transport_method": paid.get("transport_method") or covered.get("transport_method"),
        "source_provider": COMPOSED_SOURCE,
        "provider_id": paid.get("provider_id"),
        "provider_ids": list(dict.fromkeys(p for p in (first.get("provider_id"), second.get("provider_id")) if p)),
        "trip_type": "one_way",
        "origin": first_segments[0].get("departure_station"),
        "destination": second_segments[-1].get("arrival_station"),
        "departure": departure,
        "arrival": arrival,
        "duration": format_minutes(total),
        "stops": len(segments) - 1,
        "total_price": f"{paid_price:.2f}" if paid_price is not None else None,
        "currency": currency,
        "bookable_seats": paid.get("bookable_seats"),
        "last_ticketing_date": None,
        "carriers": carriers,
        "carrier_codes": sorted({str(s.get("carrier_code")) for s in segments if s.get("carrier_code")}),
        "fare": {
            "amount": paid_price, "currency": currency, "is_partial": True, "is_pass_only": False,
            "covered_by_passes": [travel_pass.pass_id], "pricing_provider": paid.get("provider_id"),
            "confidence": "partial" if paid_price is not None else "unknown", "summary": summary,
        },
        "fare_is_partial": True,
        "fare_passes_applied": [travel_pass.pass_id],
        "legs": [{
            "leg_index": 0, "origin": first_segments[0].get("departure_station"),
            "destination": second_segments[-1].get("arrival_station"), "departure": departure,
            "arrival": arrival, "duration": format_minutes(total), "stops": len(segments) - 1,
            "segments": segments, "layovers": layovers,
        }],
        "tickets": tickets,
        "route_composition": {
            "kind": kind, "hub": hub_name, "transfer_minutes": wait, "separate_tickets": True,
            "pass_id": travel_pass.pass_id, "pass_label": travel_pass.label,
            "paid_amount": paid_price, "currency": currency, "savings": None,
        },
        "hash": hashlib.sha256(identity.encode()).hexdigest()[:16],
    }
    if paid.get("booking_url"):
        result["booking_url"] = paid.get("booking_url")
        result["booking_provider"] = paid.get("booking_provider")
    return result


def _usable(result: Mapping[str, Any]) -> bool:
    segments = segments_of(result)
    return bool(segments) and all(parse_time(s.get("departure_time")) and parse_time(s.get("arrival_time"))
                                  for s in segments)


def compose_routes(covered_options: Sequence[Dict[str, Any]], paid_options: Sequence[Dict[str, Any]],
                   kind: str, passes: Sequence[TravelPass], hub_name: str, min_transfer: int,
                   limit: int = ROUTES_PER_HUB) -> List[Dict[str, Any]]:
    """Best composed routes through one hub: each paid option with the closest covered option."""
    covered: List[Tuple[Dict[str, Any], TravelPass]] = []
    for option in covered_options:
        travel_pass = covering_pass(segments_of(option), passes) if _usable(option) else None
        if travel_pass is not None:
            covered.append((option, travel_pass))
    composed: Dict[str, Dict[str, Any]] = {}
    for paid in (option for option in paid_options if _usable(option)):
        if covering_pass(segments_of(paid), passes) is not None:
            continue  # Fully covered already: not a paid part.
        best: Optional[Tuple[int, Dict[str, Any], TravelPass]] = None
        for option, travel_pass in covered:
            first, second = (option, paid) if kind == PASS_THEN_PAID else (paid, option)
            arriving, departing = segments_of(first)[-1], segments_of(second)[0]
            wait = minutes_between(arriving.get("arrival_time"), departing.get("departure_time"))
            if wait is None or wait < transfer_minutes_needed(arriving, departing, min_transfer) \
                    or wait > MAX_WAIT_MINUTES:
                continue
            if best is None or wait < best[0]:
                best = (wait, option, travel_pass)
        if best is not None:
            wait, option, travel_pass = best
            first, second = (option, paid) if kind == PASS_THEN_PAID else (paid, option)
            route = combine(first, second, kind, travel_pass, hub_name, wait)
            composed.setdefault(route["hash"], route)
    return rank_results(list(composed.values()), passes)[:limit]


def annotate_savings(results: Sequence[Dict[str, Any]], passes: Sequence[TravelPass]) -> None:
    """Saving of each priced composed route against the cheapest priced single-provider route.

    The baseline is the ticket price a traveller would pay; routes without a ticket price
    (pass-only or unknown fare) are not a baseline.
    """
    baseline: Optional[Tuple[float, Dict[str, Any]]] = None
    for result in results:
        if isinstance(result.get("route_composition"), dict):
            continue
        paid = price_of(result)
        if paid is not None and (baseline is None or paid < baseline[0]):
            baseline = (paid, result)
    if baseline is None:
        return
    amount, reference = baseline
    for result in results:
        composition = result.get("route_composition")
        if not isinstance(composition, dict) or not isinstance(composition.get("paid_amount"), (int, float)):
            continue
        if reference.get("currency") and composition.get("currency") != reference.get("currency"):
            continue
        saving = round(amount - composition["paid_amount"], 2)
        if saving > 0:
            composition["savings"] = {
                "amount": saving, "currency": composition.get("currency"),
                "compared_to": {"hash": reference.get("hash"), "price": amount,
                                "departure": reference.get("departure"),
                                "transport_method": reference.get("transport_method")},
            }


MAX_UNKNOWN_FARE_ROUTES = 2


def prune_composed(composed: Sequence[Dict[str, Any]], single: Sequence[Dict[str, Any]],
                   passes: Sequence[TravelPass]) -> List[Dict[str, Any]]:
    """Drop composed routes a single-provider route beats on both amount paid and duration.

    Composed routes with a part of unknown fare cannot be compared; at most two are kept.
    """
    priced_single = [(paid, _duration(result)) for result in single
                     if (paid := effective_price(result, passes)) is not None]
    kept: List[Dict[str, Any]] = []
    unknown = 0
    for route in rank_results(list(composed), passes):
        paid, duration = effective_price(route, passes), _duration(route)
        if paid is None:
            unknown += 1
            if unknown <= MAX_UNKNOWN_FARE_ROUTES:
                kept.append(route)
        elif not any(other_paid <= paid and other_duration <= duration
                     for other_paid, other_duration in priced_single):
            kept.append(route)
    return kept
