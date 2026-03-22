"""
Duffel API - Comprehensive Test Script

Tests all major Duffel API capabilities used by the DuffelProvider:
place resolution, flight search (one-way, round-trip, multi-city),
and response structure validation.

Uses the Duffel test/sandbox environment which returns mock "Duffel Airways"
(ZZ) data - useful for validating request/response parsing without real
airline data.

Setup:
    Pass the token directly via CLI:
        python test_duffel_flight_search.py --token duffel_test_...

    Or set in .env:
        SECRET__DUFFEL__API_TOKEN=duffel_test_...

    Get a free test token from: https://app.duffel.com

Usage:
    # Run all tests
    python backend/apps/travel/test_duffel_flight_search.py

    # Run a specific test
    python backend/apps/travel/test_duffel_flight_search.py --test places
    python backend/apps/travel/test_duffel_flight_search.py --test flight-search
    python backend/apps/travel/test_duffel_flight_search.py --test round-trip

    # Print raw JSON for all tests
    python backend/apps/travel/test_duffel_flight_search.py --raw

    # Use a live token from .env instead of the sandbox token
    python backend/apps/travel/test_duffel_flight_search.py --live

Available tests:
    places                 Resolve city/airport names to IATA codes
    places-iata            Verify IATA code pass-through
    places-ambiguous       Test ambiguous city name resolution
    flight-search          One-way flight search (MUC -> LHR)
    round-trip             Round-trip flight search (MUC -> LHR -> MUC)
    multi-city             Multi-city flight search (MUC -> BCN -> LIS)
    non-stop               Non-stop only flight search
    business-class         Business class cabin search
    multi-passenger        Multi-passenger search (2 adults)
    provider-integration   Full DuffelProvider integration test (async)
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DUFFEL_API_BASE = "https://api.duffel.com"
DUFFEL_API_VERSION = "v2"

# Sandbox test token is loaded from environment variable SECRET__DUFFEL__TEST_TOKEN
# or falls back to SECRET__DUFFEL__API_TOKEN from .env
DUFFEL_SANDBOX_TOKEN: str | None = None  # Set after load_env()

ALL_TESTS = [
    "places",
    "places-iata",
    "places-ambiguous",
    "flight-search",
    "round-trip",
    "multi-city",
    "non-stop",
    "business-class",
    "multi-passenger",
    "provider-integration",
]


# ---------------------------------------------------------------------------
# .env loading
# ---------------------------------------------------------------------------
def load_env() -> None:
    """Load the project root .env file."""
    script_dir = Path(__file__).resolve().parent
    candidates = [
        script_dir / "../../../.env",
        script_dir / "../../../../.env",
        Path(os.path.expanduser("~/projects/OpenMates/.env")),
    ]
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.exists():
            load_dotenv(resolved)
            print(f"  Loaded .env from: {resolved}")
            return
    print("  WARNING: No .env file found. Using sandbox token only.")


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
def build_headers(token: str) -> dict:
    """Build standard Duffel API request headers."""
    return {
        "Authorization": f"Bearer {token}",
        "Duffel-Version": DUFFEL_API_VERSION,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Accept-Encoding": "gzip",
    }


def api_get(token: str, path: str, params: dict | None = None) -> dict | None:
    """Make a GET request to the Duffel API."""
    url = f"{DUFFEL_API_BASE}{path}"
    response = requests.get(url, params=params or {}, headers=build_headers(token))
    if response.status_code != 200:
        print(f"  FAILED ({response.status_code}): {response.text[:400]}")
        return None
    return response.json()


def api_post(token: str, path: str, body: dict) -> dict | None:
    """Make a POST request to the Duffel API.
    Accepts 200 and 201 (Created) as success — Duffel's offer_requests returns 201."""
    url = f"{DUFFEL_API_BASE}{path}"
    response = requests.post(url, json=body, headers=build_headers(token))
    if response.status_code not in (200, 201):
        print(f"  FAILED ({response.status_code}): {response.text[:400]}")
        return None
    return response.json()


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------
def format_duration(iso_duration: str) -> str:
    """Convert ISO 8601 duration (e.g. 'PT7H30M') to '7h 30m'."""
    if not iso_duration:
        return "N/A"
    duration = iso_duration.replace("PT", "")
    hours = minutes = 0
    if "H" in duration:
        h_parts = duration.split("H")
        hours = int(h_parts[0])
        duration = h_parts[1]
    if "M" in duration:
        minutes = int(duration.replace("M", ""))
    if hours and minutes:
        return f"{hours}h {minutes}m"
    elif hours:
        return f"{hours}h"
    else:
        return f"{minutes}m"


def print_header(title: str) -> None:
    print(f"\n{'=' * 80}")
    print(f"  {title}")
    print(f"{'=' * 80}")


def print_json(data: dict) -> None:
    print(json.dumps(data, indent=2))


def display_offers(offers: list, raw: bool) -> None:
    """Pretty-print Duffel flight offers."""
    if not offers:
        print("  No offers found.")
        return

    print(f"  Found {len(offers)} offer(s)\n")

    for i, offer in enumerate(offers[:10], 1):
        owner = offer.get("owner", {})
        slices = offer.get("slices", [])
        total = offer.get("total_amount", "?")
        currency = offer.get("total_currency", "?")
        tax = offer.get("tax_amount", "?")

        print(f"  --- Offer {i} ---")
        print(f"  Price: {total} {currency} (tax: {tax})")
        print(f"  Validating airline: {owner.get('name', '?')} ({owner.get('iata_code', '?')})")

        # CO2 emissions if available
        passengers = offer.get("passengers", [])
        if passengers:
            for pax in passengers:
                co2 = pax.get("co2_emissions")
                if co2:
                    print(f"  CO2 emissions: {co2.get('amount', '?')} {co2.get('unit', 'kg')}")

        for j, sl in enumerate(slices):
            direction = "Outbound" if j == 0 else ("Return" if j == 1 else f"Leg {j + 1}")
            segments = sl.get("segments", [])
            duration = format_duration(sl.get("duration", ""))
            stops = len(segments) - 1

            print(f"\n    {direction} ({duration}, {'direct' if stops == 0 else f'{stops} stop(s)'}):")

            for seg in segments:
                origin = seg.get("origin", {})
                dest = seg.get("destination", {})
                operating = seg.get("operating_carrier", {})
                marketing = seg.get("marketing_carrier", {})

                carrier_code = operating.get("iata_code") or marketing.get("iata_code", "?")
                carrier_name = operating.get("name") or marketing.get("name", carrier_code)
                flight_num = (
                    seg.get("operating_carrier_flight_number")
                    or seg.get("marketing_carrier_flight_number", "?")
                )
                seg_duration = format_duration(seg.get("duration", ""))

                # Coordinates
                origin_lat = origin.get("latitude", "?")
                origin_lng = origin.get("longitude", "?")
                dest_lat = dest.get("latitude", "?")
                dest_lng = dest.get("longitude", "?")

                print(
                    f"      {carrier_name} {carrier_code}{flight_num}  "
                    f"{origin.get('iata_code', '?')} {seg.get('departing_at', '?')[:16]} -> "
                    f"{dest.get('iata_code', '?')} {seg.get('arriving_at', '?')[:16]}  "
                    f"({seg_duration})"
                )
                print(
                    f"        Origin: {origin.get('city_name', '?')} ({origin.get('iata_code', '?')}) "
                    f"[{origin_lat}, {origin_lng}]"
                )
                print(
                    f"        Dest:   {dest.get('city_name', '?')} ({dest.get('iata_code', '?')}) "
                    f"[{dest_lat}, {dest_lng}]"
                )
                aircraft = seg.get("aircraft") or {}
                print(f"        Aircraft: {aircraft.get('name', 'N/A')}")
        print()


# ---------------------------------------------------------------------------
# Individual test functions
# ---------------------------------------------------------------------------

def test_places(token: str, raw: bool) -> dict | None:
    """GET /air/places/suggestions - Resolve city names to IATA codes.
    NOTE: This API is NOT available in sandbox mode (returns 404). Use --live for real data."""
    print_header("Places Suggestions - City Name Resolution")
    print("  GET /air/places/suggestions")
    print("  Queries: 'Munich', 'London', 'Tokyo', 'New York'")
    print("  NOTE: Returns 404 in sandbox mode - use --live for real data.\n")

    queries = ["Munich", "London", "Tokyo", "New York"]
    last_result = None

    for query in queries:
        result = api_get(token, "/air/places/suggestions", {"query": query})
        if result:
            last_result = result
            if raw:
                print(f"  --- {query} ---")
                print_json(result)
            else:
                places = result.get("data", [])
                print(f"  '{query}' -> {len(places)} result(s):")
                for p in places[:5]:
                    ptype = p.get("type", "?")
                    iata = p.get("iata_code", "?")
                    name = p.get("name", "?")
                    city = p.get("city_name", "")
                    lat = p.get("latitude", "?")
                    lng = p.get("longitude", "?")
                    city_str = f" (city: {city})" if city else ""
                    print(f"    [{ptype:7s}] {iata:5s} {name}{city_str}")
                    print(f"              Coords: [{lat}, {lng}]")
                print()

    return last_result


def test_places_iata(token: str, raw: bool) -> dict | None:
    """Test that IATA codes resolve correctly through places API.
    NOTE: This API is NOT available in sandbox mode (returns 404). Use --live for real data."""
    print_header("Places Suggestions - IATA Code Lookup")
    print("  GET /air/places/suggestions")
    print("  Queries: 'MUC', 'LHR', 'JFK'")
    print("  NOTE: Returns 404 in sandbox mode - use --live for real data.\n")

    queries = ["MUC", "LHR", "JFK"]
    last_result = None

    for query in queries:
        result = api_get(token, "/air/places/suggestions", {"query": query})
        if result:
            last_result = result
            if raw:
                print(f"  --- {query} ---")
                print_json(result)
            else:
                places = result.get("data", [])
                if places:
                    top = places[0]
                    print(
                        f"  '{query}' -> {top.get('iata_code', '?')} "
                        f"({top.get('name', '?')}, {top.get('type', '?')})"
                    )
                else:
                    print(f"  '{query}' -> No results")
    print()
    return last_result


def test_places_ambiguous(token: str, raw: bool) -> dict | None:
    """Test ambiguous city name resolution (cities with multiple airports).
    NOTE: This API is NOT available in sandbox mode (returns 404). Use --live for real data."""
    print_header("Places Suggestions - Ambiguous Cities")
    print("  GET /air/places/suggestions")
    print("  Queries: 'Paris', 'Istanbul', 'Berlin'")
    print("  NOTE: Returns 404 in sandbox mode - use --live for real data.\n")

    queries = ["Paris", "Istanbul", "Berlin"]
    last_result = None

    for query in queries:
        result = api_get(token, "/air/places/suggestions", {"query": query})
        if result:
            last_result = result
            if raw:
                print(f"  --- {query} ---")
                print_json(result)
            else:
                places = result.get("data", [])
                print(f"  '{query}' -> {len(places)} result(s):")
                for p in places[:6]:
                    ptype = p.get("type", "?")
                    iata = p.get("iata_code", "?")
                    name = p.get("name", "?")
                    print(f"    [{ptype:7s}] {iata:5s} {name}")
                print()

    return last_result


def test_flight_search(token: str, raw: bool) -> dict | None:
    """POST /air/offer_requests - One-way flight search."""
    print_header("Flight Search - One Way (MUC -> LHR)")
    print("  POST /air/offer_requests?return_offers=true")

    departure = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
    print(f"  Route: MUC -> LHR | {departure} | Economy | 1 adult\n")

    body = {
        "data": {
            "slices": [
                {
                    "origin": "MUC",
                    "destination": "LHR",
                    "departure_date": departure,
                }
            ],
            "passengers": [{"type": "adult"}],
            "cabin_class": "economy",
            "max_connections": 1,
        }
    }

    result = api_post(
        token,
        "/air/offer_requests?return_offers=true&supplier_timeout=20000",
        body,
    )

    if result:
        if raw:
            print_json(result)
        else:
            data = result.get("data", {})
            offers = data.get("offers", [])
            # Sort by price
            offers.sort(key=lambda o: float(o.get("total_amount", "999999")))
            display_offers(offers[:6], raw)
            # Print summary stats
            if offers:
                prices = [float(o.get("total_amount", 0)) for o in offers]
                currency = offers[0].get("total_currency", "?")
                print(f"  Price range: {min(prices):.2f} - {max(prices):.2f} {currency}")
                print(f"  Total offers returned: {len(offers)}")
    return result


def test_round_trip(token: str, raw: bool) -> dict | None:
    """POST /air/offer_requests - Round-trip flight search."""
    print_header("Flight Search - Round Trip (MUC -> LHR -> MUC)")
    print("  POST /air/offer_requests?return_offers=true")

    dep_out = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
    dep_ret = (datetime.now() + timedelta(days=21)).strftime("%Y-%m-%d")
    print(f"  Outbound: MUC -> LHR | {dep_out}")
    print(f"  Return:   LHR -> MUC | {dep_ret}")
    print("  Economy | 1 adult\n")

    body = {
        "data": {
            "slices": [
                {
                    "origin": "MUC",
                    "destination": "LHR",
                    "departure_date": dep_out,
                },
                {
                    "origin": "LHR",
                    "destination": "MUC",
                    "departure_date": dep_ret,
                },
            ],
            "passengers": [{"type": "adult"}],
            "cabin_class": "economy",
            "max_connections": 1,
        }
    }

    result = api_post(
        token,
        "/air/offer_requests?return_offers=true&supplier_timeout=20000",
        body,
    )

    if result:
        if raw:
            print_json(result)
        else:
            data = result.get("data", {})
            offers = data.get("offers", [])
            offers.sort(key=lambda o: float(o.get("total_amount", "999999")))
            display_offers(offers[:5], raw)
            if offers:
                prices = [float(o.get("total_amount", 0)) for o in offers]
                currency = offers[0].get("total_currency", "?")
                print(f"  Price range: {min(prices):.2f} - {max(prices):.2f} {currency}")
                print(f"  Total offers returned: {len(offers)}")
    return result


def test_multi_city(token: str, raw: bool) -> dict | None:
    """POST /air/offer_requests - Multi-city flight search."""
    print_header("Flight Search - Multi-City (MUC -> BCN -> LIS)")
    print("  POST /air/offer_requests?return_offers=true")

    dep1 = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
    dep2 = (datetime.now() + timedelta(days=18)).strftime("%Y-%m-%d")
    print(f"  Leg 1: MUC -> BCN | {dep1}")
    print(f"  Leg 2: BCN -> LIS | {dep2}")
    print("  Economy | 1 adult\n")

    body = {
        "data": {
            "slices": [
                {
                    "origin": "MUC",
                    "destination": "BCN",
                    "departure_date": dep1,
                },
                {
                    "origin": "BCN",
                    "destination": "LIS",
                    "departure_date": dep2,
                },
            ],
            "passengers": [{"type": "adult"}],
            "cabin_class": "economy",
            "max_connections": 1,
        }
    }

    result = api_post(
        token,
        "/air/offer_requests?return_offers=true&supplier_timeout=20000",
        body,
    )

    if result:
        if raw:
            print_json(result)
        else:
            data = result.get("data", {})
            offers = data.get("offers", [])
            offers.sort(key=lambda o: float(o.get("total_amount", "999999")))
            display_offers(offers[:5], raw)
            if offers:
                prices = [float(o.get("total_amount", 0)) for o in offers]
                currency = offers[0].get("total_currency", "?")
                print(f"  Price range: {min(prices):.2f} - {max(prices):.2f} {currency}")
                print(f"  Total offers returned: {len(offers)}")
    return result


def test_non_stop(token: str, raw: bool) -> dict | None:
    """POST /air/offer_requests - Non-stop only flight search."""
    print_header("Flight Search - Non-Stop Only (MUC -> LHR)")
    print("  POST /air/offer_requests?return_offers=true")

    departure = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
    print(f"  Route: MUC -> LHR | {departure} | Economy | 1 adult | max_connections=0\n")

    body = {
        "data": {
            "slices": [
                {
                    "origin": "MUC",
                    "destination": "LHR",
                    "departure_date": departure,
                }
            ],
            "passengers": [{"type": "adult"}],
            "cabin_class": "economy",
            "max_connections": 0,
        }
    }

    result = api_post(
        token,
        "/air/offer_requests?return_offers=true&supplier_timeout=20000",
        body,
    )

    if result:
        if raw:
            print_json(result)
        else:
            data = result.get("data", {})
            offers = data.get("offers", [])
            offers.sort(key=lambda o: float(o.get("total_amount", "999999")))
            display_offers(offers[:5], raw)

            # Verify all offers are non-stop
            all_direct = True
            for offer in offers:
                for sl in offer.get("slices", []):
                    if len(sl.get("segments", [])) > 1:
                        all_direct = False
                        break

            status = "YES" if all_direct else "NO (bug!)"
            print(f"  All offers non-stop? {status}")
            print(f"  Total offers returned: {len(offers)}")
    return result


def test_business_class(token: str, raw: bool) -> dict | None:
    """POST /air/offer_requests - Business class cabin search."""
    print_header("Flight Search - Business Class (MUC -> LHR)")
    print("  POST /air/offer_requests?return_offers=true")

    departure = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
    print(f"  Route: MUC -> LHR | {departure} | Business | 1 adult\n")

    body = {
        "data": {
            "slices": [
                {
                    "origin": "MUC",
                    "destination": "LHR",
                    "departure_date": departure,
                }
            ],
            "passengers": [{"type": "adult"}],
            "cabin_class": "business",
            "max_connections": 1,
        }
    }

    result = api_post(
        token,
        "/air/offer_requests?return_offers=true&supplier_timeout=20000",
        body,
    )

    if result:
        if raw:
            print_json(result)
        else:
            data = result.get("data", {})
            offers = data.get("offers", [])
            offers.sort(key=lambda o: float(o.get("total_amount", "999999")))
            display_offers(offers[:5], raw)
            if offers:
                prices = [float(o.get("total_amount", 0)) for o in offers]
                currency = offers[0].get("total_currency", "?")
                print(f"  Price range: {min(prices):.2f} - {max(prices):.2f} {currency}")
                print(f"  Total offers returned: {len(offers)}")
    return result


def test_multi_passenger(token: str, raw: bool) -> dict | None:
    """POST /air/offer_requests - Multi-passenger search."""
    print_header("Flight Search - 2 Adults (MUC -> LHR)")
    print("  POST /air/offer_requests?return_offers=true")

    departure = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
    print(f"  Route: MUC -> LHR | {departure} | Economy | 2 adults\n")

    body = {
        "data": {
            "slices": [
                {
                    "origin": "MUC",
                    "destination": "LHR",
                    "departure_date": departure,
                }
            ],
            "passengers": [
                {"type": "adult"},
                {"type": "adult"},
            ],
            "cabin_class": "economy",
            "max_connections": 1,
        }
    }

    result = api_post(
        token,
        "/air/offer_requests?return_offers=true&supplier_timeout=20000",
        body,
    )

    if result:
        if raw:
            print_json(result)
        else:
            data = result.get("data", {})
            offers = data.get("offers", [])
            offers.sort(key=lambda o: float(o.get("total_amount", "999999")))
            display_offers(offers[:5], raw)
            if offers:
                prices = [float(o.get("total_amount", 0)) for o in offers]
                currency = offers[0].get("total_currency", "?")
                print(f"  Price range (total for 2 pax): {min(prices):.2f} - {max(prices):.2f} {currency}")
                print(f"  Total offers returned: {len(offers)}")
    return result


def test_provider_integration(token: str, raw: bool) -> dict | None:
    """Test the full DuffelProvider class integration (async)."""
    print_header("DuffelProvider Integration Test")
    print("  Testing: DuffelProvider.search_connections()")
    print("  Route: Munich -> London | One-way | Economy | 1 adult\n")

    # We need to run this async since DuffelProvider uses async httpx
    async def _run_provider_test() -> dict | None:
        # Import the provider
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent / "../../.."))
            from backend.apps.travel.providers.duffel_provider import DuffelProvider
        except ImportError as e:
            print(f"  ERROR: Could not import DuffelProvider: {e}")
            print("  Make sure you're running from the project root.")
            return None

        # Create a mock SecretsManager that returns the test token
        class MockSecretsManager:
            async def get_secrets_from_path(self, path: str) -> dict | None:
                if "duffel" in path:
                    return {"api_token": token}
                return None

        provider = DuffelProvider()
        provider._secrets_manager = MockSecretsManager()  # type: ignore[assignment]

        departure = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
        # Use IATA codes directly — sandbox doesn't support Places API
        # for city name resolution. In live mode, city names like "Munich"
        # would be resolved via /air/places/suggestions.
        legs = [
            {"origin": "MUC", "destination": "LHR", "date": departure}
        ]
        print("  NOTE: Using IATA codes (MUC, LHR) since sandbox doesn't support Places API.\n")

        try:
            results = await provider.search_connections(
                legs=legs,
                passengers=1,
                travel_class="economy",
                max_results=5,
                non_stop_only=False,
                currency="EUR",
            )
        except Exception as e:
            print(f"  ERROR: search_connections() failed: {e}")
            import traceback
            traceback.print_exc()
            return None

        if not results:
            print("  No results returned from DuffelProvider.")
            return {"results": []}

        print(f"  DuffelProvider returned {len(results)} ConnectionResult(s)\n")

        result_dicts = []
        for i, conn in enumerate(results, 1):
            result_dict = conn.model_dump()
            result_dicts.append(result_dict)

            if raw:
                print(f"  --- ConnectionResult {i} ---")
                print(json.dumps(result_dict, indent=2, default=str))
            else:
                print(f"  --- ConnectionResult {i} ---")
                print(f"  Transport: {conn.transport_method}")
                print(f"  Price: {conn.total_price} {conn.currency}")
                print(f"  Validating airline: {conn.validating_airline_code}")
                print(f"  Bookable seats: {conn.bookable_seats}")

                for leg in conn.legs:
                    print(f"\n    Leg {leg.leg_index}: {leg.origin} -> {leg.destination}")
                    print(f"    Departure: {leg.departure}")
                    print(f"    Arrival: {leg.arrival}")
                    print(f"    Duration: {leg.duration}")
                    print(f"    Stops: {leg.stops}")

                    for seg in leg.segments:
                        print(
                            f"      {seg.carrier} ({seg.carrier_code}) {seg.number or 'N/A'}  "
                            f"{seg.departure_station} {seg.departure_time[:16]} -> "
                            f"{seg.arrival_station} {seg.arrival_time[:16]}  "
                            f"({seg.duration})"
                        )
                        print(
                            f"        Coords: [{seg.departure_latitude}, {seg.departure_longitude}] "
                            f"-> [{seg.arrival_latitude}, {seg.arrival_longitude}]"
                        )
            print()

        # Validate structure
        print("  --- Structure Validation ---")
        issues = []
        for i, conn in enumerate(results):
            if not conn.total_price:
                issues.append(f"  Offer {i + 1}: missing total_price")
            if not conn.currency:
                issues.append(f"  Offer {i + 1}: missing currency")
            if not conn.legs:
                issues.append(f"  Offer {i + 1}: no legs")
            for leg in conn.legs:
                if not leg.origin:
                    issues.append(f"  Offer {i + 1}, Leg {leg.leg_index}: missing origin")
                if not leg.destination:
                    issues.append(f"  Offer {i + 1}, Leg {leg.leg_index}: missing destination")
                if not leg.segments:
                    issues.append(f"  Offer {i + 1}, Leg {leg.leg_index}: no segments")
                for seg in leg.segments:
                    if seg.departure_latitude is None:
                        issues.append(
                            f"  Offer {i + 1}, Leg {leg.leg_index}, "
                            f"Seg {seg.departure_station}->{seg.arrival_station}: "
                            f"missing departure_latitude"
                        )
                    if seg.arrival_latitude is None:
                        issues.append(
                            f"  Offer {i + 1}, Leg {leg.leg_index}, "
                            f"Seg {seg.departure_station}->{seg.arrival_station}: "
                            f"missing arrival_latitude"
                        )

        if issues:
            print(f"  Found {len(issues)} issue(s):")
            for issue in issues:
                print(f"    WARNING: {issue}")
        else:
            print("  All ConnectionResult objects have valid structure.")
            print("  All segments have coordinates (route map will work).")

        return {"results": result_dicts}

    return asyncio.run(_run_provider_test())


# ---------------------------------------------------------------------------
# Test registry
# ---------------------------------------------------------------------------
TEST_REGISTRY: dict = {
    "places": test_places,
    "places-iata": test_places_iata,
    "places-ambiguous": test_places_ambiguous,
    "flight-search": test_flight_search,
    "round-trip": test_round_trip,
    "multi-city": test_multi_city,
    "non-stop": test_non_stop,
    "business-class": test_business_class,
    "multi-passenger": test_multi_passenger,
    "provider-integration": test_provider_integration,
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Comprehensive Duffel API test script for the travel app.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Available tests:\n  " + "\n  ".join(ALL_TESTS),
    )
    parser.add_argument(
        "--test", "-t",
        action="append",
        dest="tests",
        choices=ALL_TESTS,
        help="Run specific test(s). Can be repeated. Omit to run all.",
    )
    parser.add_argument(
        "--raw", action="store_true",
        help="Print raw JSON responses",
    )
    parser.add_argument(
        "--live", action="store_true",
        help="Use live token from .env instead of sandbox token",
    )
    parser.add_argument(
        "--token",
        help="Duffel API token to use directly (overrides --live and env vars)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tests_to_run = args.tests or ALL_TESTS

    load_env()

    # Determine which token to use (priority: --token > --live > env vars)
    if args.token:
        token = args.token
        env_label = "SANDBOX" if token.startswith("duffel_test_") else "LIVE"
    elif args.live:
        token = os.getenv("SECRET__DUFFEL__API_TOKEN")
        if not token:
            print(
                "ERROR: --live flag specified but SECRET__DUFFEL__API_TOKEN not found in .env.\n"
                "Add to your .env file:\n"
                "  SECRET__DUFFEL__API_TOKEN=duffel_live_...\n"
                "Or pass directly: --token duffel_live_..."
            )
            sys.exit(1)
        env_label = "LIVE"
    else:
        # Try env vars
        token = (
            os.getenv("SECRET__DUFFEL__TEST_TOKEN")
            or os.getenv("SECRET__DUFFEL__API_TOKEN")
        )
        if not token:
            print(
                "ERROR: No Duffel token found.\n"
                "Pass via CLI:   --token duffel_test_...\n"
                "Or add to .env: SECRET__DUFFEL__API_TOKEN=duffel_test_...\n"
                "Get a free test token from: https://app.duffel.com"
            )
            sys.exit(1)
        env_label = "SANDBOX" if token.startswith("duffel_test_") else "LIVE (auto-detected)"

    print(f"  Token: ...{token[-8:]}")

    print(f"  Environment: {env_label}")
    print(f"  API base: {DUFFEL_API_BASE}")
    print(f"  API version: {DUFFEL_API_VERSION}")
    print(f"  Tests to run: {len(tests_to_run)}")

    # Run tests
    results: dict[str, str] = {}
    for test_name in tests_to_run:
        test_fn = TEST_REGISTRY[test_name]
        try:
            result = test_fn(token, args.raw)
            results[test_name] = "PASS" if result else "FAIL (no data)"
        except Exception as e:
            print(f"  EXCEPTION: {e}")
            import traceback
            traceback.print_exc()
            results[test_name] = f"ERROR: {e}"

    # Summary
    print_header("TEST SUMMARY")
    passed = sum(1 for v in results.values() if v == "PASS")
    failed = sum(1 for v in results.values() if v != "PASS")
    for name, status in results.items():
        icon = "OK" if status == "PASS" else "FAIL"
        print(f"  [{icon:4s}] {name:25s} {status}")
    print(f"\n  Total: {len(results)} | Passed: {passed} | Failed: {failed}")
    print(f"{'=' * 80}\n")


if __name__ == "__main__":
    main()
