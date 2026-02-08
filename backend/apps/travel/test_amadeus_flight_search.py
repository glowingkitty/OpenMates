"""
Amadeus Self-Service API - Comprehensive Test Script

Tests all major Amadeus API capabilities: flight search, airport/airline lookups,
price analysis, flight inspiration, flight status, activities, and more.

Setup:
    Add to your .env file:
        SECRET__AMADEUS__API_KEY=your_api_key
        SECRET__AMADEUS__API_SECRET=your_api_secret

    Get credentials from: https://developers.amadeus.com/

Usage:
    # Run all tests
    python backend/apps/travel/test_amadeus_flight_search.py

    # Run a specific test
    python backend/apps/travel/test_amadeus_flight_search.py --test flight-search
    python backend/apps/travel/test_amadeus_flight_search.py --test airport-search
    python backend/apps/travel/test_amadeus_flight_search.py --test airline-lookup

    # Use production API
    python backend/apps/travel/test_amadeus_flight_search.py --prod

    # Print raw JSON for all tests
    python backend/apps/travel/test_amadeus_flight_search.py --raw

Available tests:
    flight-search          Search for flight offers (GET)
    flight-search-post     Search for flights with advanced filters (POST)
    flight-price           Confirm pricing for a flight offer
    flight-inspiration     Cheapest destinations from an origin
    flight-cheapest-dates  Cheapest dates for a route
    flight-availabilities  Seat availability by fare class
    flight-status          Real-time flight schedule status
    flight-delay           Predict flight delay probability
    price-analysis         Historical price analysis for a route
    airport-search         Search airports/cities by keyword
    airport-nearest        Find nearest airports to coordinates
    airport-routes         Direct destinations from an airport
    airport-ontime         Airport on-time performance prediction
    airline-lookup         Look up airline by IATA/ICAO code
    airline-routes         All destinations served by an airline
    checkin-links          Get airline check-in page URLs
    activities             Tours and activities at a location
    hotel-search           Search for hotel offers
    recommendations        AI-powered destination recommendations
"""

import argparse
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
AMADEUS_BASE_URL_TEST = "https://test.api.amadeus.com"
AMADEUS_BASE_URL_PROD = "https://api.amadeus.com"

# All available test names
ALL_TESTS = [
    "flight-search",
    "flight-search-post",
    "flight-price",
    "flight-inspiration",
    "flight-cheapest-dates",
    "flight-availabilities",
    "flight-status",
    "flight-delay",
    "price-analysis",
    "airport-search",
    "airport-nearest",
    "airport-routes",
    "airport-ontime",
    "airline-lookup",
    "airline-routes",
    "checkin-links",
    "activities",
    "hotel-search",
    "recommendations",
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
            print(f"Loaded .env from: {resolved}")
            return
    print("WARNING: No .env file found. Relying on environment variables.")


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
def get_access_token(api_key: str, api_secret: str, base_url: str) -> str:
    """Authenticate with Amadeus OAuth2 and return a bearer token."""
    response = requests.post(
        f"{base_url}/v1/security/oauth2/token",
        data={
            "grant_type": "client_credentials",
            "client_id": api_key,
            "client_secret": api_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if response.status_code != 200:
        print(f"ERROR: Authentication failed ({response.status_code})")
        print(f"Response: {response.text}")
        sys.exit(1)

    token_data = response.json()
    print(f"Authenticated (token expires in {token_data['expires_in']}s)\n")
    return token_data["access_token"]


def api_get(token: str, base_url: str, path: str, params: dict | None = None) -> dict | None:
    """Make a GET request to the Amadeus API. Returns parsed JSON or None on error."""
    url = f"{base_url}{path}"
    response = requests.get(
        url,
        params=params or {},
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    if response.status_code != 200:
        print(f"  FAILED ({response.status_code}): {response.text[:300]}")
        return None
    return response.json()


def api_post(token: str, base_url: str, path: str, body: dict) -> dict | None:
    """Make a POST request to the Amadeus API. Returns parsed JSON or None on error."""
    url = f"{base_url}{path}"
    response = requests.post(
        url,
        json=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/vnd.amadeus+json",
            "X-HTTP-Method-Override": "GET",
        },
    )
    if response.status_code != 200:
        print(f"  FAILED ({response.status_code}): {response.text[:300]}")
        return None
    return response.json()


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------
def format_duration(iso_duration: str) -> str:
    """Convert ISO 8601 duration (e.g. 'PT2H30M') to '2h 30m'."""
    duration = iso_duration.replace("PT", "")
    hours = minutes = 0
    if "H" in duration:
        h_parts = duration.split("H")
        hours = int(h_parts[0])
        duration = h_parts[1]
    if "M" in duration:
        minutes = int(duration.replace("M", ""))
    return f"{hours}h {minutes}m"


def print_header(title: str) -> None:
    print(f"\n{'=' * 80}")
    print(f"  {title}")
    print(f"{'=' * 80}")


def print_json(data: dict) -> None:
    print(json.dumps(data, indent=2))


def display_flight_offers(response: dict) -> None:
    """Pretty-print flight offers."""
    offers = response.get("data", [])
    carriers = response.get("dictionaries", {}).get("carriers", {})

    if not offers:
        print("  No flight offers found.")
        return

    print(f"  Found {len(offers)} offer(s)\n")

    for i, offer in enumerate(offers, 1):
        price = offer["price"]
        itineraries = offer["itineraries"]

        print(f"  --- Offer {i} ---")
        print(f"  Price: {price['total']} {price['currency']} (base: {price.get('base', 'N/A')})")
        print(f"  Bookable seats: {offer.get('numberOfBookableSeats', 'N/A')}")
        print(f"  Last ticketing: {offer.get('lastTicketingDate', 'N/A')}")

        for j, itinerary in enumerate(itineraries):
            direction = "Outbound" if j == 0 else "Return"
            segments = itinerary["segments"]
            duration = format_duration(itinerary["duration"])
            stops = len(segments) - 1

            print(f"\n    {direction} ({duration}, {'direct' if stops == 0 else f'{stops} stop(s)'}):")

            for seg in segments:
                carrier_code = seg["carrierCode"]
                carrier_name = carriers.get(carrier_code, carrier_code)
                dep = seg["departure"]
                arr = seg["arrival"]
                seg_duration = format_duration(seg["duration"])

                print(
                    f"      {carrier_name} {seg['number']}  "
                    f"{dep['iataCode']} {dep['at']} -> "
                    f"{arr['iataCode']} {arr['at']}  "
                    f"({seg_duration})"
                )
        print()


# ---------------------------------------------------------------------------
# Individual test functions
# ---------------------------------------------------------------------------

def test_flight_search(token: str, base_url: str, raw: bool) -> dict | None:
    """GET /v2/shopping/flight-offers - Search for flight offers."""
    print_header("Flight Offers Search (GET)")
    print("  GET /v2/shopping/flight-offers")
    print("  Route: MUC -> LHR | Economy | 1 adult | Round trip\n")

    departure = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
    return_date = (datetime.now() + timedelta(days=21)).strftime("%Y-%m-%d")

    result = api_get(token, base_url, "/v2/shopping/flight-offers", {
        "originLocationCode": "MUC",
        "destinationLocationCode": "LHR",
        "departureDate": departure,
        "returnDate": return_date,
        "adults": 1,
        "travelClass": "ECONOMY",
        "nonStop": "false",
        "max": 3,
    })
    if result:
        if raw:
            print_json(result)
        else:
            display_flight_offers(result)
    return result


def test_flight_search_post(token: str, base_url: str, raw: bool) -> dict | None:
    """POST /v2/shopping/flight-offers - Advanced multi-city search."""
    print_header("Flight Offers Search (POST) - Multi-city")
    print("  POST /v2/shopping/flight-offers")
    print("  Route: MUC -> BCN -> LIS (multi-city) | Economy | 2 adults\n")

    dep1 = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
    dep2 = (datetime.now() + timedelta(days=18)).strftime("%Y-%m-%d")

    body = {
        "originDestinations": [
            {
                "id": "1",
                "originLocationCode": "MUC",
                "destinationLocationCode": "BCN",
                "departureDateTimeRange": {"date": dep1},
            },
            {
                "id": "2",
                "originLocationCode": "BCN",
                "destinationLocationCode": "LIS",
                "departureDateTimeRange": {"date": dep2},
            },
        ],
        "travelers": [
            {"id": "1", "travelerType": "ADULT"},
            {"id": "2", "travelerType": "ADULT"},
        ],
        "sources": ["GDS"],
        "searchCriteria": {
            "maxFlightOffers": 3,
            "flightFilters": {
                "cabinRestrictions": [
                    {
                        "cabin": "ECONOMY",
                        "coverage": "MOST_SEGMENTS",
                        "originDestinationIds": ["1", "2"],
                    }
                ]
            },
        },
    }

    result = api_post(token, base_url, "/v2/shopping/flight-offers", body)
    if result:
        if raw:
            print_json(result)
        else:
            display_flight_offers(result)
    return result


def test_flight_price(token: str, base_url: str, raw: bool) -> dict | None:
    """POST /v1/shopping/flight-offers/pricing - Confirm pricing for an offer."""
    print_header("Flight Offers Price")
    print("  POST /v1/shopping/flight-offers/pricing")
    print("  First searching for an offer, then confirming its price...\n")

    departure = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
    search_result = api_get(token, base_url, "/v2/shopping/flight-offers", {
        "originLocationCode": "MUC",
        "destinationLocationCode": "LHR",
        "departureDate": departure,
        "adults": 1,
        "max": 1,
    })

    if not search_result or not search_result.get("data"):
        print("  No offers found to price.")
        return None

    offer = search_result["data"][0]
    print(f"  Pricing offer: {offer['price']['total']} {offer['price']['currency']}")

    result = api_post(token, base_url, "/v1/shopping/flight-offers/pricing", {
        "data": {
            "type": "flight-offers-pricing",
            "flightOffers": [offer],
        }
    })

    if result:
        if raw:
            print_json(result)
        else:
            priced = result.get("data", {}).get("flightOffers", [])
            if priced:
                p = priced[0]["price"]
                print(f"\n  Confirmed price: {p['total']} {p['currency']}")
                print(f"  Base fare: {p.get('base', 'N/A')}")
                print(f"  Grand total: {p.get('grandTotal', 'N/A')}")
                # Show fee breakdown if available
                fees = p.get("fees", [])
                if fees:
                    for fee in fees:
                        print(f"  Fee ({fee.get('type', '?')}): {fee.get('amount', 'N/A')}")
            else:
                print("  No priced offers returned.")
    return result


def test_flight_inspiration(token: str, base_url: str, raw: bool) -> dict | None:
    """GET /v1/shopping/flight-destinations - Cheapest destinations from origin."""
    print_header("Flight Inspiration Search")
    print("  GET /v1/shopping/flight-destinations")
    print("  From: MUC | Cheapest destinations\n")

    result = api_get(token, base_url, "/v1/shopping/flight-destinations", {
        "origin": "MUC",
        "maxPrice": 200,
    })

    if result:
        if raw:
            print_json(result)
        else:
            destinations = result.get("data", [])
            print(f"  Found {len(destinations)} destination(s):\n")
            for d in destinations[:10]:
                print(
                    f"    {d.get('destination', '?'):5s}  "
                    f"{d['price'].get('total', '?'):>8s} {result.get('dictionaries', {}).get('currencies', {})}"
                    if 'price' in d else f"    {d}"
                )
    return result


def test_flight_cheapest_dates(token: str, base_url: str, raw: bool) -> dict | None:
    """GET /v1/shopping/flight-dates - Cheapest travel dates for a route."""
    print_header("Flight Cheapest Date Search")
    print("  GET /v1/shopping/flight-dates")
    print("  Route: MUC -> BCN | Finding cheapest dates\n")

    result = api_get(token, base_url, "/v1/shopping/flight-dates", {
        "origin": "MUC",
        "destination": "BCN",
    })

    if result:
        if raw:
            print_json(result)
        else:
            dates = result.get("data", [])
            print(f"  Found {len(dates)} date option(s):\n")
            for d in dates[:10]:
                dep = d.get("departureDate", "?")
                ret = d.get("returnDate", "N/A")
                price = d.get("price", {})
                print(f"    Depart: {dep}  Return: {ret}  Price: {price.get('total', '?')}")
    return result


def test_flight_availabilities(token: str, base_url: str, raw: bool) -> dict | None:
    """POST /v1/shopping/availability/flight-availabilities - Seat availability by fare class."""
    print_header("Flight Availabilities Search")
    print("  POST /v1/shopping/availability/flight-availabilities")
    print("  Route: MUC -> LHR | Checking bookable seat counts by fare class\n")

    departure = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")

    result = api_post(token, base_url, "/v1/shopping/availability/flight-availabilities", {
        "originDestinations": [
            {
                "id": "1",
                "originLocationCode": "MUC",
                "destinationLocationCode": "LHR",
                "departureDateTime": {"date": departure},
            }
        ],
        "travelers": [{"id": "1", "travelerType": "ADULT"}],
        "sources": ["GDS"],
    })

    if result:
        if raw:
            print_json(result)
        else:
            avails = result.get("data", [])
            print(f"  Found {len(avails)} availability option(s):\n")
            for a in avails[:5]:
                segs = a.get("segments", [])
                for seg in segs:
                    dep = seg.get("departure", {})
                    arr = seg.get("arrival", {})
                    classes = seg.get("availabilityClasses", [])
                    class_str = ", ".join(
                        f"{c.get('class', '?')}:{c.get('numberOfBookableSeats', '?')}"
                        for c in classes[:6]
                    )
                    print(
                        f"    {seg.get('carrierCode', '?')}{seg.get('number', '?')}  "
                        f"{dep.get('iataCode', '?')} {dep.get('at', '?')[:16]} -> "
                        f"{arr.get('iataCode', '?')} {arr.get('at', '?')[:16]}  "
                        f"[{class_str}]"
                    )
    return result


def test_flight_status(token: str, base_url: str, raw: bool) -> dict | None:
    """GET /v2/schedule/flights - Real-time flight schedule/status."""
    print_header("On-Demand Flight Status")
    print("  GET /v2/schedule/flights")
    print("  Checking: LH 2472 (Lufthansa MUC->LHR)\n")

    # Use tomorrow's date to increase chance of data
    date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    result = api_get(token, base_url, "/v2/schedule/flights", {
        "carrierCode": "LH",
        "flightNumber": "2472",
        "scheduledDepartureDate": date,
    })

    if result:
        if raw:
            print_json(result)
        else:
            flights = result.get("data", [])
            if not flights:
                print("  No schedule data found for this flight/date.")
            for f in flights:
                dep = f.get("flightPoints", [{}])[0] if f.get("flightPoints") else {}
                arr = f.get("flightPoints", [{}])[-1] if f.get("flightPoints") else {}
                dep_times = dep.get("departure", {}).get("timings", [{}])
                arr_times = arr.get("arrival", {}).get("timings", [{}])
                print(f"    Flight: {f.get('flightDesignator', {}).get('carrierCode', '?')}"
                      f"{f.get('flightDesignator', {}).get('flightNumber', '?')}")
                print(f"    From: {dep.get('iataCode', '?')}")
                print(f"    To: {arr.get('iataCode', '?')}")
                if dep_times:
                    print(f"    Scheduled departure: {dep_times[0].get('value', '?')}")
                if arr_times:
                    print(f"    Scheduled arrival: {arr_times[0].get('value', '?')}")
                legs = f.get("legs", [])
                if legs:
                    print(f"    Aircraft: {legs[0].get('aircraftEquipment', {}).get('aircraftType', '?')}")
    return result


def test_flight_delay(token: str, base_url: str, raw: bool) -> dict | None:
    """GET /v1/travel/predictions/flight-delay - Predict delay probability."""
    print_header("Flight Delay Prediction")
    print("  GET /v1/travel/predictions/flight-delay")
    print("  Predicting delay for: MUC -> LHR on LH\n")

    dep_date = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")

    result = api_get(token, base_url, "/v1/travel/predictions/flight-delay", {
        "originLocationCode": "MUC",
        "destinationLocationCode": "LHR",
        "departureDate": dep_date,
        "departureTime": "09:25:00",
        "arrivalDate": dep_date,
        "arrivalTime": "10:25:00",
        "aircraftCode": "32N",
        "carrierCode": "LH",
        "flightNumber": "2472",
        "duration": "PT2H0M",
    })

    if result:
        if raw:
            print_json(result)
        else:
            predictions = result.get("data", [])
            if not predictions:
                print("  No prediction data available.")
            for p in predictions:
                res = p.get("result", {})
                print(f"    Prediction: {p.get('subType', '?')}")
                print(f"    Most likely: {res.get('category', '?')} (probability: {res.get('probability', '?')})")
                # Show all delay brackets if available
                detail = p.get("result", {})
                if isinstance(detail, dict):
                    for key, val in detail.items():
                        if key not in ("category", "probability"):
                            print(f"    {key}: {val}")
    return result


def test_price_analysis(token: str, base_url: str, raw: bool) -> dict | None:
    """GET /v1/analytics/itinerary-price-metrics - Historical price analysis."""
    print_header("Flight Price Analysis")
    print("  GET /v1/analytics/itinerary-price-metrics")
    print("  Route: MUC -> BCN | Price quartiles\n")

    departure = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

    result = api_get(token, base_url, "/v1/analytics/itinerary-price-metrics", {
        "originIataCode": "MUC",
        "destinationIataCode": "BCN",
        "departureDate": departure,
        "currencyCode": "EUR",
    })

    if result:
        if raw:
            print_json(result)
        else:
            metrics = result.get("data", [])
            if not metrics:
                print("  No price metrics available.")
            for m in metrics:
                print(f"    Route: {m.get('origin', {}).get('iataCode', '?')} -> "
                      f"{m.get('destination', {}).get('iataCode', '?')}")
                print(f"    Date: {m.get('departureDate', '?')}")
                print(f"    One-way: {m.get('oneWay', '?')}")
                print(f"    Currency: {m.get('currencyCode', '?')}")
                print()
                for pm in m.get("priceMetrics", []):
                    ranking = pm.get("quartileRanking", "?")
                    amount = pm.get("amount", "?")
                    print(f"    {ranking:10s}  {amount} EUR")
    return result


def test_airport_search(token: str, base_url: str, raw: bool) -> dict | None:
    """GET /v1/reference-data/locations - Search airports/cities by keyword."""
    print_header("Airport & City Search")
    print("  GET /v1/reference-data/locations")
    print("  Keyword: 'Munich'\n")

    result = api_get(token, base_url, "/v1/reference-data/locations", {
        "subType": "AIRPORT,CITY",
        "keyword": "Munich",
        "page[limit]": 5,
        "view": "FULL",
    })

    if result:
        if raw:
            print_json(result)
        else:
            locations = result.get("data", [])
            print(f"  Found {len(locations)} result(s):\n")
            for loc in locations:
                geo = loc.get("geoCode", {})
                addr = loc.get("address", {})
                score = loc.get("analytics", {}).get("travelers", {}).get("score", "?")
                print(f"    [{loc.get('subType', '?'):7s}] {loc.get('iataCode', '?'):5s} "
                      f"{loc.get('name', '?')}")
                print(f"             City: {addr.get('cityName', '?')}, "
                      f"{addr.get('countryName', '?')}")
                print(f"             Coords: {geo.get('latitude', '?')}, {geo.get('longitude', '?')}")
                print(f"             Traveler score: {score}")
                print()
    return result


def test_airport_nearest(token: str, base_url: str, raw: bool) -> dict | None:
    """GET /v1/reference-data/locations/airports - Nearest airports to coordinates."""
    print_header("Nearest Airport Search")
    print("  GET /v1/reference-data/locations/airports")
    print("  Location: Munich city center (48.1351, 11.5820)\n")

    result = api_get(token, base_url, "/v1/reference-data/locations/airports", {
        "latitude": 48.1351,
        "longitude": 11.5820,
        "radius": 100,
        "sort": "distance",
    })

    if result:
        if raw:
            print_json(result)
        else:
            airports = result.get("data", [])
            print(f"  Found {len(airports)} airport(s):\n")
            for a in airports[:10]:
                dist = a.get("distance", {})
                geo = a.get("geoCode", {})
                print(f"    {a.get('iataCode', '?'):5s} {a.get('name', '?')}")
                print(f"           Distance: {dist.get('value', '?')} {dist.get('unit', '')}")
                print(f"           Coords: {geo.get('latitude', '?')}, {geo.get('longitude', '?')}")
                print()
    return result


def test_airport_routes(token: str, base_url: str, raw: bool) -> dict | None:
    """GET /v1/airport/direct-destinations - Direct destinations from an airport."""
    print_header("Airport Direct Destinations")
    print("  GET /v1/airport/direct-destinations")
    print("  From: MUC (Munich)\n")

    result = api_get(token, base_url, "/v1/airport/direct-destinations", {
        "departureAirportCode": "MUC",
        "max": 20,
    })

    if result:
        if raw:
            print_json(result)
        else:
            routes = result.get("data", [])
            print(f"  Found {len(routes)} direct destination(s):\n")
            dest_list = []
            for r in routes:
                dest_list.append(r.get("destination", "?"))
            # Display in columns
            for i in range(0, len(dest_list), 10):
                chunk = dest_list[i:i + 10]
                print(f"    {', '.join(chunk)}")
    return result


def test_airport_ontime(token: str, base_url: str, raw: bool) -> dict | None:
    """GET /v1/airport/predictions/on-time - Airport on-time performance."""
    print_header("Airport On-Time Performance")
    print("  GET /v1/airport/predictions/on-time")
    print("  Airport: JFK | Tomorrow\n")

    date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    result = api_get(token, base_url, "/v1/airport/predictions/on-time", {
        "airportCode": "JFK",
        "date": date,
    })

    if result:
        if raw:
            print_json(result)
        else:
            data = result.get("data", {})
            res = data.get("result", {})
            print(f"    Airport: {data.get('id', '?')}")
            print(f"    Prediction: {res.get('category', '?')}")
            print(f"    Probability: {res.get('probability', '?')}")
    return result


def test_airline_lookup(token: str, base_url: str, raw: bool) -> dict | None:
    """GET /v1/reference-data/airlines - Look up airline by code."""
    print_header("Airline Code Lookup")
    print("  GET /v1/reference-data/airlines")
    print("  Codes: LH, BA, AF, EW, FR\n")

    result = api_get(token, base_url, "/v1/reference-data/airlines", {
        "airlineCodes": "LH,BA,AF,EW,FR",
    })

    if result:
        if raw:
            print_json(result)
        else:
            airlines = result.get("data", [])
            print(f"  Found {len(airlines)} airline(s):\n")
            for a in airlines:
                print(f"    {a.get('iataCode', '?'):4s} / {a.get('icaoCode', '?'):5s}  "
                      f"{a.get('businessName', '?')} ({a.get('commonName', '?')})")
    return result


def test_airline_routes(token: str, base_url: str, raw: bool) -> dict | None:
    """GET /v1/airline/destinations - All destinations served by an airline."""
    print_header("Airline Routes (Destinations)")
    print("  GET /v1/airline/destinations")
    print("  Airline: EW (Eurowings)\n")

    result = api_get(token, base_url, "/v1/airline/destinations", {
        "airlineCode": "EW",
        "max": 20,
    })

    if result:
        if raw:
            print_json(result)
        else:
            routes = result.get("data", [])
            print(f"  Found {len(routes)} destination(s):\n")
            dest_list = []
            for r in routes:
                dest_list.append(r.get("destination", "?"))
            for i in range(0, len(dest_list), 10):
                chunk = dest_list[i:i + 10]
                print(f"    {', '.join(chunk)}")
    return result


def test_checkin_links(token: str, base_url: str, raw: bool) -> dict | None:
    """GET /v2/reference-data/urls/checkin-links - Airline check-in URLs."""
    print_header("Airline Check-in Links")
    print("  GET /v2/reference-data/urls/checkin-links")
    print("  Airlines: LH (Lufthansa), BA (British Airways)\n")

    last_result: dict | None = None
    for code in ["LH", "BA"]:
        result = api_get(token, base_url, "/v2/reference-data/urls/checkin-links", {
            "airlineCode": code,
        })
        if result:
            last_result = result
            if raw:
                print_json(result)
            else:
                links = result.get("data", [])
                for link in links:
                    print(f"    {code} [{link.get('channel', '?'):6s}]: {link.get('href', '?')}")
        print()
    return last_result


def test_activities(token: str, base_url: str, raw: bool) -> dict | None:
    """GET /v1/shopping/activities - Tours and activities at a location."""
    print_header("Tours & Activities Search")
    print("  GET /v1/shopping/activities")
    print("  Location: Barcelona (41.3851, 2.1734)\n")

    result = api_get(token, base_url, "/v1/shopping/activities", {
        "latitude": 41.3851,
        "longitude": 2.1734,
        "radius": 2,
    })

    if result:
        if raw:
            print_json(result)
        else:
            activities = result.get("data", [])
            print(f"  Found {len(activities)} activit(y/ies):\n")
            for a in activities[:8]:
                price = a.get("price", {})
                rating = a.get("rating", "N/A")
                price_str = f"{price.get('amount', '?')} {price.get('currencyCode', '')}" if price else "N/A"
                print(f"    [{rating:>4s}] {a.get('name', '?')[:60]}")
                print(f"           Price: {price_str}")
                desc = a.get("shortDescription", "")
                if desc:
                    print(f"           {desc[:80]}...")
                print()
    return result


def test_hotel_search(token: str, base_url: str, raw: bool) -> dict | None:
    """GET /v3/shopping/hotel-offers - Search for hotel offers."""
    print_header("Hotel Offers Search")
    print("  GET /v3/shopping/hotel-offers")
    print("  First searching for hotels by city, then fetching offers...\n")

    # Step 1: Get hotel IDs by city
    city_result = api_get(token, base_url, "/v1/reference-data/locations/hotels/by-city", {
        "cityCode": "BCN",
        "radius": 5,
        "radiusUnit": "KM",
    })

    if not city_result or not city_result.get("data"):
        print("  No hotels found in city search.")
        return None

    hotels = city_result["data"][:5]
    hotel_ids = ",".join(h.get("hotelId", "") for h in hotels)
    print(f"  Found {len(city_result['data'])} hotels, checking offers for first 5...\n")

    if not raw:
        for h in hotels:
            print(f"    {h.get('hotelId', '?'):10s} {h.get('name', '?')}")
        print()

    # Step 2: Get offers for those hotels
    checkin = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    checkout = (datetime.now() + timedelta(days=32)).strftime("%Y-%m-%d")

    result = api_get(token, base_url, "/v3/shopping/hotel-offers", {
        "hotelIds": hotel_ids,
        "adults": 1,
        "checkInDate": checkin,
        "checkOutDate": checkout,
        "roomQuantity": 1,
        "currency": "EUR",
    })

    if result:
        if raw:
            print_json(result)
        else:
            hotel_offers = result.get("data", [])
            print(f"  Got offers from {len(hotel_offers)} hotel(s):\n")
            for ho in hotel_offers:
                hotel = ho.get("hotel", {})
                offers = ho.get("offers", [])
                print(f"    {hotel.get('name', '?')} ({hotel.get('hotelId', '?')})")
                for o in offers[:2]:
                    price = o.get("price", {})
                    room = o.get("room", {})
                    print(f"      Room: {room.get('typeEstimated', {}).get('category', '?')} "
                          f"({room.get('typeEstimated', {}).get('beds', '?')} bed(s))")
                    print(f"      Price: {price.get('total', '?')} {price.get('currency', '')}")
                print()
    return result


def test_recommendations(token: str, base_url: str, raw: bool) -> dict | None:
    """GET /v1/reference-data/recommended-locations - AI destination recommendations."""
    print_header("Travel Recommendations (AI)")
    print("  GET /v1/reference-data/recommended-locations")
    print("  Based on: Munich traveler profile\n")

    result = api_get(token, base_url, "/v1/reference-data/recommended-locations", {
        "cityCodes": "MUC",
        "travelerCountryCode": "DE",
    })

    if result:
        if raw:
            print_json(result)
        else:
            recs = result.get("data", [])
            print(f"  Found {len(recs)} recommendation(s):\n")
            for r in recs[:10]:
                geo = r.get("geoCode", {})
                print(f"    {r.get('iataCode', '?'):5s} {r.get('name', '?')}")
                print(f"           {r.get('subType', '?')} | "
                      f"Relevance: {r.get('relevance', '?')}")
                print()
    return result


# ---------------------------------------------------------------------------
# Test registry
# ---------------------------------------------------------------------------
TEST_REGISTRY: dict = {
    "flight-search": test_flight_search,
    "flight-search-post": test_flight_search_post,
    "flight-price": test_flight_price,
    "flight-inspiration": test_flight_inspiration,
    "flight-cheapest-dates": test_flight_cheapest_dates,
    "flight-availabilities": test_flight_availabilities,
    "flight-status": test_flight_status,
    "flight-delay": test_flight_delay,
    "price-analysis": test_price_analysis,
    "airport-search": test_airport_search,
    "airport-nearest": test_airport_nearest,
    "airport-routes": test_airport_routes,
    "airport-ontime": test_airport_ontime,
    "airline-lookup": test_airline_lookup,
    "airline-routes": test_airline_routes,
    "checkin-links": test_checkin_links,
    "activities": test_activities,
    "hotel-search": test_hotel_search,
    "recommendations": test_recommendations,
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Comprehensive Amadeus Self-Service API test script.",
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
    parser.add_argument("--prod", action="store_true", help="Use production API")
    parser.add_argument("--raw", action="store_true", help="Print raw JSON responses")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tests_to_run = args.tests or ALL_TESTS

    # Load credentials
    load_env()
    api_key = os.getenv("SECRET__AMADEUS__API_KEY")
    api_secret = os.getenv("SECRET__AMADEUS__API_SECRET")

    if not api_key or not api_secret:
        print(
            "ERROR: Missing Amadeus credentials.\n"
            "Add to your .env file:\n"
            "  SECRET__AMADEUS__API_KEY=your_api_key\n"
            "  SECRET__AMADEUS__API_SECRET=your_api_secret\n"
            "Get credentials from: https://developers.amadeus.com/"
        )
        sys.exit(1)

    base_url = AMADEUS_BASE_URL_PROD if args.prod else AMADEUS_BASE_URL_TEST
    print(f"Environment: {'PRODUCTION' if args.prod else 'TEST'} ({base_url})")
    print(f"Tests to run: {len(tests_to_run)}\n")

    # Authenticate
    access_token = get_access_token(api_key, api_secret, base_url)

    # Run tests
    results: dict[str, str] = {}
    for test_name in tests_to_run:
        test_fn = TEST_REGISTRY[test_name]
        try:
            result = test_fn(access_token, base_url, args.raw)
            results[test_name] = "PASS" if result else "FAIL (no data)"
        except Exception as e:
            print(f"  EXCEPTION: {e}")
            results[test_name] = f"ERROR: {e}"

    # Summary
    print_header("TEST SUMMARY")
    passed = sum(1 for v in results.values() if v == "PASS")
    failed = sum(1 for v in results.values() if v != "PASS")
    for name, status in results.items():
        icon = "OK" if status == "PASS" else "FAIL"
        print(f"  [{icon:4s}] {name:30s} {status}")
    print(f"\n  Total: {len(results)} | Passed: {passed} | Failed: {failed}")
    print(f"{'=' * 80}\n")


if __name__ == "__main__":
    main()
