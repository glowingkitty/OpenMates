"""
SerpAPI Google Flights - Comprehensive Test Script

Tests the SerpAPI Google Flights engine for real-time flight search
with booking link retrieval.

Flow:
  1. Search flights (one-way / round-trip outbound)
  2. For round-trip: use departure_token to get return flights
  3. Use booking_token to get booking options (airline/OTA links + prices)

Each search consumes 1 SerpAPI credit. A full round-trip with booking
links costs 3 credits (outbound + return + booking).

Setup:
    Pass the API key via CLI:
        python test_serpapi_flight_search.py --api-key YOUR_KEY

    Or set in .env:
        SECRET__SERPAPI__API_KEY=YOUR_KEY

    Get a key from: https://serpapi.com/manage-api-key

Usage:
    # Run all tests
    python backend/apps/travel/test_serpapi_flight_search.py --api-key KEY

    # Run a specific test
    python backend/apps/travel/test_serpapi_flight_search.py --api-key KEY --test one-way
    python backend/apps/travel/test_serpapi_flight_search.py --api-key KEY --test round-trip
    python backend/apps/travel/test_serpapi_flight_search.py --api-key KEY --test booking

    # Print raw JSON
    python backend/apps/travel/test_serpapi_flight_search.py --api-key KEY --raw

    # Custom route
    python backend/apps/travel/test_serpapi_flight_search.py --api-key KEY --origin MUC --dest LHR

Available tests:
    one-way             One-way flight search
    round-trip          Round-trip search (outbound + return via departure_token)
    multi-city          Multi-city search
    booking             Full flow: search → select cheapest → get booking links
    filters             Search with advanced filters (stops, class, bags)
    price-insights      Check price insights for a route
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
SERPAPI_BASE = "https://serpapi.com/search"

# Filled after load_env()
SERPAPI_KEY: str | None = None

ALL_TESTS = [
    "one-way",
    "round-trip",
    "multi-city",
    "booking",
    "filters",
    "price-insights",
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
    print("  WARNING: No .env file found.")


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------
def serpapi_get(api_key: str, params: dict) -> dict | None:
    """GET request to SerpAPI."""
    params["engine"] = "google_flights"
    params["api_key"] = api_key

    try:
        response = requests.get(SERPAPI_BASE, params=params, timeout=120)
    except requests.RequestException as e:
        print(f"  REQUEST ERROR: {e}")
        return None

    if response.status_code != 200:
        print(f"  FAILED ({response.status_code}): {response.text[:500]}")
        return None

    try:
        return response.json()
    except ValueError:
        print(f"  FAILED: Could not parse JSON: {response.text[:300]}")
        return None


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------
def print_header(title: str) -> None:
    print(f"\n{'=' * 80}")
    print(f"  {title}")
    print(f"{'=' * 80}")


def print_json(data: object) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def format_price(value: float | int | str, currency: str = "EUR") -> str:
    try:
        return f"{float(value):,.0f} {currency}"
    except (ValueError, TypeError):
        return f"{value} {currency}"


def display_flight(flight_group: dict, index: int, currency: str) -> None:
    """Display a single flight group (from best_flights or other_flights)."""
    flights = flight_group.get("flights", [])
    layovers = flight_group.get("layovers", [])
    total_duration = flight_group.get("total_duration", 0)
    price = flight_group.get("price")
    flight_type = flight_group.get("type", "")
    carbon = flight_group.get("carbon_emissions", {})
    extensions = flight_group.get("extensions", [])

    hours = total_duration // 60
    mins = total_duration % 60
    stops = len(layovers)
    stop_label = "direct" if stops == 0 else f"{stops} stop(s)"

    price_str = format_price(price, currency) if price else "N/A"

    print(f"\n  --- Flight {index} ---")
    print(f"  Price: {price_str} | {flight_type} | {hours}h {mins}m total | {stop_label}")

    if extensions:
        print(f"  Tags: {', '.join(extensions)}")

    for seg in flights:
        dep = seg.get("departure_airport", {})
        arr = seg.get("arrival_airport", {})
        airline = seg.get("airline", "?")
        flight_num = seg.get("flight_number", "?")
        duration = seg.get("duration", 0)
        airplane = seg.get("airplane", "?")
        legroom = seg.get("legroom", "?")
        travel_class = seg.get("travel_class", "?")
        often_delayed = seg.get("often_delayed_by_over_30_min", False)

        dep_time = dep.get("time", "?")
        arr_time = arr.get("time", "?")
        dep_code = dep.get("id", "?")
        arr_code = arr.get("id", "?")

        # Extract just the time portion if full datetime
        if isinstance(dep_time, str) and len(dep_time) > 10:
            dep_time = dep_time[11:16]
        if isinstance(arr_time, str) and len(arr_time) > 10:
            arr_time = arr_time[11:16]

        seg_h = duration // 60
        seg_m = duration % 60
        delay_warn = " [OFTEN DELAYED]" if often_delayed else ""

        print(
            f"    {dep_code} {dep_time} -> {arr_code} {arr_time} | "
            f"{airline} {flight_num} | {seg_h}h {seg_m}m | "
            f"{airplane} | {travel_class} | legroom: {legroom}{delay_warn}"
        )

        # Show who else sells this ticket
        also_sold = seg.get("ticket_also_sold_by", [])
        if also_sold:
            print(f"      Also sold by: {', '.join(also_sold)}")

        operated_by = seg.get("plane_and_crew_by")
        if operated_by:
            print(f"      Operated by: {operated_by}")

    # Layovers
    for lay in layovers:
        lay_dur = lay.get("duration", 0)
        lay_name = lay.get("name", "?")
        lay_code = lay.get("id", "?")
        overnight = " (overnight)" if lay.get("overnight") else ""
        lay_h = lay_dur // 60
        lay_m = lay_dur % 60
        print(f"    -- Layover: {lay_h}h {lay_m}m at {lay_name} ({lay_code}){overnight}")

    # Carbon
    if carbon:
        this_flight = carbon.get("this_flight", 0)
        typical = carbon.get("typical_for_this_route", 0)
        diff = carbon.get("difference_percent", 0)
        this_kg = this_flight / 1000 if this_flight else 0
        typical_kg = typical / 1000 if typical else 0
        sign = "+" if diff > 0 else ""
        print(f"    CO2: {this_kg:.0f}kg (typical: {typical_kg:.0f}kg, {sign}{diff}%)")


def display_search_results(data: dict, currency: str, raw: bool) -> None:
    """Display flight search results."""
    if raw:
        print_json(data)
        return

    best = data.get("best_flights", [])
    other = data.get("other_flights", [])
    price_insights = data.get("price_insights", {})

    total = len(best) + len(other)
    print(f"  Found {total} flight(s) ({len(best)} best, {len(other)} other)")

    # Price insights
    if price_insights:
        lowest = price_insights.get("lowest_price")
        level = price_insights.get("price_level", "?")
        typical = price_insights.get("typical_price_range", [])
        typical_str = f"{typical[0]}-{typical[1]} {currency}" if len(typical) == 2 else "?"
        print(f"  Price insights: lowest={format_price(lowest, currency)}, "
              f"level={level}, typical={typical_str}")

    idx = 1
    if best:
        print("\n  === BEST FLIGHTS ===")
        for fg in best:
            display_flight(fg, idx, currency)
            idx += 1

    if other:
        print("\n  === OTHER FLIGHTS ===")
        for fg in other[:10]:  # Cap display at 10
            display_flight(fg, idx, currency)
            idx += 1
        if len(other) > 10:
            print(f"\n  ... and {len(other) - 10} more")


def display_booking_options(data: dict, currency: str, raw: bool) -> None:
    """Display booking options from a booking_token request."""
    if raw:
        print_json(data)
        return

    selected = data.get("selected_flights", [])
    booking_opts = data.get("booking_options", [])
    baggage = data.get("baggage_prices", {})

    if selected:
        print("\n  === SELECTED FLIGHTS ===")
        for i, fg in enumerate(selected, 1):
            display_flight(fg, i, currency)

    if baggage:
        together_bags = baggage.get("together", [])
        departing_bags = baggage.get("departing", [])
        returning_bags = baggage.get("returning", [])
        print("\n  === BAGGAGE ===")
        if together_bags:
            for b in together_bags:
                print(f"    {b}")
        if departing_bags:
            print("    Departing:")
            for b in departing_bags:
                print(f"      {b}")
        if returning_bags:
            print("    Returning:")
            for b in returning_bags:
                print(f"      {b}")

    if not booking_opts:
        print("\n  No booking options found.")
        return

    print(f"\n  === BOOKING OPTIONS ({len(booking_opts)}) ===")
    for i, opt in enumerate(booking_opts, 1):
        separate = opt.get("separate_tickets", False)

        # Handle both "together" and "departing"/"returning" structures
        tickets_to_show = []
        if not separate and opt.get("together"):
            tickets_to_show.append(("", opt["together"]))
        else:
            if opt.get("departing"):
                tickets_to_show.append(("Departing", opt["departing"]))
            if opt.get("returning"):
                tickets_to_show.append(("Returning", opt["returning"]))

        for label, ticket in tickets_to_show:
            book_with = ticket.get("book_with", "?")
            is_airline = ticket.get("airline", False)
            price_val = ticket.get("price")
            option_title = ticket.get("option_title", "")
            extensions = ticket.get("extensions", [])
            marketed = ticket.get("marketed_as", [])
            booking_req = ticket.get("booking_request", {})
            local_prices = ticket.get("local_prices", [])

            seller_type = "Airline" if is_airline else "OTA/Agency"
            price_str = format_price(price_val, currency) if price_val else "N/A"
            label_prefix = f"[{label}] " if label else ""
            title_str = f" ({option_title})" if option_title else ""

            print(f"\n  {i}. {label_prefix}{book_with} [{seller_type}]{title_str}")
            print(f"     Price: {price_str}")

            if local_prices:
                for lp in local_prices:
                    lp_currency = lp.get("currency", "?")
                    lp_price = lp.get("price", "?")
                    print(f"     Local price: {format_price(lp_price, lp_currency)}")

            if marketed:
                print(f"     Flights: {', '.join(marketed)}")

            if extensions:
                print(f"     Features: {', '.join(extensions)}")

            # The key part: booking URL
            if booking_req:
                url = booking_req.get("url", "")
                post_data = booking_req.get("post_data", "")
                if url:
                    print(f"     BOOKING URL: {url}")
                if post_data:
                    print(f"     POST data: {post_data[:200]}{'...' if len(post_data) > 200 else ''}")

            # Phone booking
            phone = ticket.get("booking_phone")
            phone_fee = ticket.get("estimated_phone_service_fee")
            if phone:
                fee_str = f" (fee: {format_price(phone_fee, currency)})" if phone_fee else ""
                print(f"     Phone: {phone}{fee_str}")

        if separate:
            print("     NOTE: Separate tickets required (departing + returning)")


# ---------------------------------------------------------------------------
# Test functions
# ---------------------------------------------------------------------------
def test_one_way(
    api_key: str, origin: str, dest: str, currency: str, raw: bool
) -> bool:
    """Test: One-way flight search."""
    print_header(f"ONE-WAY: {origin} -> {dest}")

    outbound = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
    print(f"  Date: {outbound}")

    data = serpapi_get(api_key, {
        "departure_id": origin,
        "arrival_id": dest,
        "outbound_date": outbound,
        "type": "2",  # One way
        "currency": currency,
        "hl": "en",
        "gl": "us",
    })
    if data is None:
        return False

    if data.get("error"):
        print(f"  ERROR: {data['error']}")
        return False

    display_search_results(data, currency, raw)
    return bool(data.get("best_flights") or data.get("other_flights"))


def test_round_trip(
    api_key: str, origin: str, dest: str, currency: str, raw: bool
) -> bool:
    """Test: Round-trip search (outbound + return via departure_token).

    Step 1: Search outbound flights — costs 1 credit.
    Step 2: Pick cheapest, use its departure_token to get return flights — costs 1 credit.
    Total: 2 credits.
    """
    print_header(f"ROUND-TRIP: {origin} <-> {dest}")

    outbound = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
    return_date = (datetime.now() + timedelta(days=21)).strftime("%Y-%m-%d")
    print(f"  Outbound: {outbound}, Return: {return_date}")

    # Step 1: Outbound search
    print("\n  --- Step 1: Outbound flights ---")
    data = serpapi_get(api_key, {
        "departure_id": origin,
        "arrival_id": dest,
        "outbound_date": outbound,
        "return_date": return_date,
        "type": "1",  # Round trip
        "currency": currency,
        "hl": "en",
        "gl": "us",
    })
    if data is None:
        return False

    if data.get("error"):
        print(f"  ERROR: {data['error']}")
        return False

    display_search_results(data, currency, raw)

    # Find cheapest flight with a departure_token
    all_flights = data.get("best_flights", []) + data.get("other_flights", [])
    flights_with_token = [f for f in all_flights if f.get("departure_token")]

    if not flights_with_token:
        print("\n  No flights with departure_token found — cannot get return flights.")
        return True  # Search itself worked

    cheapest = min(flights_with_token, key=lambda f: f.get("price", float("inf")))
    dep_token = cheapest["departure_token"]
    cheapest_price = cheapest.get("price", "?")

    print(f"\n  Selected outbound: {format_price(cheapest_price, currency)}")
    print(f"  departure_token: {dep_token[:60]}...")

    # Step 2: Return flights
    print("\n  --- Step 2: Return flights ---")
    return_data = serpapi_get(api_key, {
        "departure_id": origin,
        "arrival_id": dest,
        "outbound_date": outbound,
        "return_date": return_date,
        "type": "1",
        "currency": currency,
        "hl": "en",
        "gl": "us",
        "departure_token": dep_token,
    })
    if return_data is None:
        return False

    if return_data.get("error"):
        print(f"  ERROR: {return_data['error']}")
        return False

    display_search_results(return_data, currency, raw)
    return True


def test_multi_city(
    api_key: str, origin: str, dest: str, currency: str, raw: bool
) -> bool:
    """Test: Multi-city search.

    Example: origin -> dest -> third_city
    Uses multi_city_json parameter.
    """
    third_city = "BCN"
    if origin == "BCN" or dest == "BCN":
        third_city = "AMS"

    print_header(f"MULTI-CITY: {origin} -> {dest} -> {third_city}")

    date1 = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
    date2 = (datetime.now() + timedelta(days=18)).strftime("%Y-%m-%d")

    multi_city = json.dumps([
        {"departure_id": origin, "arrival_id": dest, "date": date1},
        {"departure_id": dest, "arrival_id": third_city, "date": date2},
    ])

    print(f"  Legs: {multi_city}")

    # Step 1: First leg
    print("\n  --- Step 1: First leg ---")
    data = serpapi_get(api_key, {
        "type": "3",  # Multi-city
        "multi_city_json": multi_city,
        "currency": currency,
        "hl": "en",
        "gl": "us",
    })
    if data is None:
        return False

    if data.get("error"):
        print(f"  ERROR: {data['error']}")
        return False

    display_search_results(data, currency, raw)

    # Find a departure_token for second leg
    all_flights = data.get("best_flights", []) + data.get("other_flights", [])
    flights_with_token = [f for f in all_flights if f.get("departure_token")]

    if not flights_with_token:
        print("\n  No departure_token found — cannot get second leg.")
        return True

    cheapest = min(flights_with_token, key=lambda f: f.get("price", float("inf")))
    dep_token = cheapest["departure_token"]

    print(f"\n  Selected first leg: {format_price(cheapest.get('price', '?'), currency)}")

    # Step 2: Second leg
    print("\n  --- Step 2: Second leg ---")
    leg2_data = serpapi_get(api_key, {
        "type": "3",
        "multi_city_json": multi_city,
        "currency": currency,
        "hl": "en",
        "gl": "us",
        "departure_token": dep_token,
    })
    if leg2_data is None:
        return False

    if leg2_data.get("error"):
        print(f"  ERROR: {leg2_data['error']}")
        return False

    display_search_results(leg2_data, currency, raw)
    return True


def test_booking(
    api_key: str, origin: str, dest: str, currency: str, raw: bool
) -> bool:
    """Test: Full booking flow — search, select cheapest, get booking links.

    Step 1: One-way search — 1 credit.
    Step 2: booking_token request — 1 credit.
    Total: 2 credits.
    """
    print_header(f"BOOKING FLOW: {origin} -> {dest}")

    outbound = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
    print(f"  Date: {outbound}")

    # Step 1: Search
    print("\n  --- Step 1: Search flights ---")
    data = serpapi_get(api_key, {
        "departure_id": origin,
        "arrival_id": dest,
        "outbound_date": outbound,
        "type": "2",  # One way
        "currency": currency,
        "hl": "en",
        "gl": "us",
    })
    if data is None:
        return False

    if data.get("error"):
        print(f"  ERROR: {data['error']}")
        return False

    # Find cheapest flight with booking_token
    all_flights = data.get("best_flights", []) + data.get("other_flights", [])
    flights_with_token = [f for f in all_flights if f.get("booking_token")]

    if not flights_with_token:
        print("  No flights with booking_token found.")
        # Show what we have
        display_search_results(data, currency, raw)
        return False

    cheapest = min(flights_with_token, key=lambda f: f.get("price", float("inf")))
    booking_token = cheapest["booking_token"]
    cheapest_price = cheapest.get("price", "?")

    print(f"  Found {len(flights_with_token)} flights with booking tokens")
    print(f"  Cheapest: {format_price(cheapest_price, currency)}")

    # Show the selected flight
    display_flight(cheapest, 1, currency)

    print(f"\n  booking_token: {booking_token[:80]}...")

    # Step 2: Get booking options
    print("\n  --- Step 2: Get booking options ---")
    booking_data = serpapi_get(api_key, {
        "departure_id": origin,
        "arrival_id": dest,
        "outbound_date": outbound,
        "type": "2",
        "currency": currency,
        "hl": "en",
        "gl": "us",
        "booking_token": booking_token,
    })
    if booking_data is None:
        return False

    if booking_data.get("error"):
        print(f"  ERROR: {booking_data['error']}")
        return False

    display_booking_options(booking_data, currency, raw)

    # Count booking options with actual URLs
    opts = booking_data.get("booking_options", [])
    urls_found = 0
    for opt in opts:
        for key in ("together", "departing", "returning"):
            ticket = opt.get(key, {})
            if ticket and ticket.get("booking_request", {}).get("url"):
                urls_found += 1

    print(f"\n  Total booking options: {len(opts)}, with URLs: {urls_found}")
    return urls_found > 0


def test_filters(
    api_key: str, origin: str, dest: str, currency: str, raw: bool
) -> bool:
    """Test: Search with advanced filters."""
    print_header(f"FILTERED SEARCH: {origin} -> {dest} (nonstop, business)")

    outbound = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")

    data = serpapi_get(api_key, {
        "departure_id": origin,
        "arrival_id": dest,
        "outbound_date": outbound,
        "type": "2",
        "currency": currency,
        "hl": "en",
        "gl": "us",
        "stops": "1",          # Nonstop only
        "travel_class": "3",   # Business
        "bags": "1",           # 1 checked bag
        "sort_by": "2",        # Sort by price
    })
    if data is None:
        return False

    if data.get("error"):
        print(f"  ERROR: {data['error']}")
        return False

    display_search_results(data, currency, raw)
    return bool(data.get("best_flights") or data.get("other_flights"))


def test_price_insights(
    api_key: str, origin: str, dest: str, currency: str, raw: bool
) -> bool:
    """Test: Price insights for a route."""
    print_header(f"PRICE INSIGHTS: {origin} -> {dest}")

    outbound = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
    return_date = (datetime.now() + timedelta(days=21)).strftime("%Y-%m-%d")

    data = serpapi_get(api_key, {
        "departure_id": origin,
        "arrival_id": dest,
        "outbound_date": outbound,
        "return_date": return_date,
        "type": "1",
        "currency": currency,
        "hl": "en",
        "gl": "us",
    })
    if data is None:
        return False

    if data.get("error"):
        print(f"  ERROR: {data['error']}")
        return False

    insights = data.get("price_insights", {})
    if not insights:
        print("  No price insights available for this route.")
        if raw:
            print_json(data)
        return True

    if raw:
        print_json(insights)
    else:
        lowest = insights.get("lowest_price")
        level = insights.get("price_level", "?")
        typical = insights.get("typical_price_range", [])
        history = insights.get("price_history", [])

        print(f"  Lowest price: {format_price(lowest, currency)}")
        print(f"  Price level: {level}")
        if len(typical) == 2:
            print(f"  Typical range: {typical[0]}-{typical[1]} {currency}")
        if history:
            print(f"  Price history: {len(history)} data points")
            # Show last 5 points
            for ts, price in history[-5:]:
                date_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
                print(f"    {date_str}: {format_price(price, currency)}")

    return bool(insights)


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------
def run_tests(
    tests: list[str],
    api_key: str,
    origin: str,
    dest: str,
    currency: str,
    raw: bool,
) -> dict[str, bool]:
    """Run specified tests and return results."""
    results: dict[str, bool] = {}

    for test_name in tests:
        try:
            if test_name == "one-way":
                results[test_name] = test_one_way(api_key, origin, dest, currency, raw)
            elif test_name == "round-trip":
                results[test_name] = test_round_trip(api_key, origin, dest, currency, raw)
            elif test_name == "multi-city":
                results[test_name] = test_multi_city(api_key, origin, dest, currency, raw)
            elif test_name == "booking":
                results[test_name] = test_booking(api_key, origin, dest, currency, raw)
            elif test_name == "filters":
                results[test_name] = test_filters(api_key, origin, dest, currency, raw)
            elif test_name == "price-insights":
                results[test_name] = test_price_insights(api_key, origin, dest, currency, raw)
            else:
                print(f"\n  Unknown test: {test_name}")
                results[test_name] = False
        except Exception as e:
            print(f"\n  EXCEPTION in test '{test_name}': {e}")
            import traceback
            traceback.print_exc()
            results[test_name] = False

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="SerpAPI Google Flights - Comprehensive Test Script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run all tests
  python %(prog)s --api-key YOUR_KEY

  # One-way search only
  python %(prog)s --api-key YOUR_KEY --test one-way

  # Full booking flow (search + booking links)
  python %(prog)s --api-key YOUR_KEY --test booking

  # Custom route with raw JSON output
  python %(prog)s --api-key YOUR_KEY --origin FRA --dest BCN --raw

Credit usage per test:
  one-way:        1 credit
  round-trip:     2 credits (outbound + return)
  multi-city:     2 credits (leg 1 + leg 2)
  booking:        2 credits (search + booking options)
  filters:        1 credit
  price-insights: 1 credit
  ALL tests:      9 credits total
        """,
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="SerpAPI key (overrides .env)",
    )
    parser.add_argument(
        "--test",
        type=str,
        default=None,
        help=f"Run a specific test. Options: {', '.join(ALL_TESTS)}",
    )
    parser.add_argument("--raw", action="store_true", help="Print raw JSON responses")
    parser.add_argument("--origin", type=str, default="MUC", help="Origin IATA code (default: MUC)")
    parser.add_argument("--dest", type=str, default="LHR", help="Destination IATA code (default: LHR)")
    parser.add_argument("--currency", type=str, default="EUR", help="Currency (default: EUR)")

    args = parser.parse_args()

    load_env()

    global SERPAPI_KEY
    SERPAPI_KEY = (
        args.api_key
        or os.environ.get("SECRET__SERPAPI__API_KEY")
        or os.environ.get("SERPAPI_API_KEY")
    )

    if not SERPAPI_KEY:
        print("\n  ERROR: No API key provided.")
        print("  Pass via --api-key or set SECRET__SERPAPI__API_KEY in .env")
        print("  Get a key from: https://serpapi.com/manage-api-key")
        sys.exit(1)

    token_display = f"{SERPAPI_KEY[:8]}...{SERPAPI_KEY[-4:]}" if len(SERPAPI_KEY) > 12 else SERPAPI_KEY
    print(f"\n  API Key: {token_display}")
    print(f"  Route: {args.origin} -> {args.dest}")
    print(f"  Currency: {args.currency}")
    print(f"  Raw mode: {args.raw}")

    if args.test:
        if args.test not in ALL_TESTS:
            print(f"\n  ERROR: Unknown test '{args.test}'")
            print(f"  Available: {', '.join(ALL_TESTS)}")
            sys.exit(1)
        tests_to_run = [args.test]
    else:
        tests_to_run = ALL_TESTS

    # Warn about credit usage
    credit_map = {
        "one-way": 1, "round-trip": 2, "multi-city": 2,
        "booking": 2, "filters": 1, "price-insights": 1,
    }
    total_credits = sum(credit_map.get(t, 1) for t in tests_to_run)
    print(f"  Estimated credits: {total_credits}")

    results = run_tests(
        tests_to_run,
        SERPAPI_KEY,
        args.origin.upper(),
        args.dest.upper(),
        args.currency.upper(),
        args.raw,
    )

    # Summary
    print_header("TEST SUMMARY")
    passed = sum(1 for v in results.values() if v)
    failed = sum(1 for v in results.values() if not v)

    for test_name, success in results.items():
        icon = "+" if success else "-"
        status = "PASS" if success else "FAIL"
        print(f"  [{icon}] {test_name}: {status}")

    print(f"\n  Results: {passed}/{len(results)} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
