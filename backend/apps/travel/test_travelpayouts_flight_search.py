"""
Travelpayouts API - Comprehensive Test Script

Tests the Travelpayouts (Aviasales) flight search and data APIs:
  - Data API: cheapest tickets, non-stop, calendar, monthly, latest prices,
    alternative directions, popular routes, reference data
  - Flight Search API (new v2, Nov 2025): real-time search with polling,
    booking link generation
  - Signature generation (MD5)

The Data API uses a simple token (X-Access-Token header).
The Flight Search API requires marker + MD5 signature, and separate
access approval from Travelpayouts.

Setup:
    Pass credentials via CLI:
        python test_travelpayouts_flight_search.py --token <api_token> --marker <marker>

    Or set in .env:
        SECRET__TRAVELPAYOUTS__API_TOKEN=<your_api_token>
        SECRET__TRAVELPAYOUTS__MARKER=<your_marker_id>

    Get credentials from: https://app.travelpayouts.com/profile/api-token

Usage:
    # Run all Data API tests (no special access needed)
    python backend/apps/travel/test_travelpayouts_flight_search.py

    # Run a specific test
    python backend/apps/travel/test_travelpayouts_flight_search.py --test cheapest
    python backend/apps/travel/test_travelpayouts_flight_search.py --test flight-search
    python backend/apps/travel/test_travelpayouts_flight_search.py --test booking-link

    # Print raw JSON for all tests
    python backend/apps/travel/test_travelpayouts_flight_search.py --raw

    # Use specific origin/destination
    python backend/apps/travel/test_travelpayouts_flight_search.py --origin MUC --dest LHR

Available tests:
    --- Data API (token only) ---
    cheapest               Cheapest tickets for a route
    non-stop               Non-stop (direct) tickets only
    calendar               Daily prices for a month
    monthly                Cheapest tickets grouped by month
    latest                 Latest prices found in last 48h
    month-matrix           Price matrix for a month (v2)
    week-matrix            Price matrix for a week (v2)
    nearest-places         Prices for alternative nearby routes
    airline-routes         Popular routes for an airline
    city-directions        Popular directions from a city
    special-offers         Current airline special offers
    ref-airports           Reference: airports list
    ref-airlines           Reference: airlines list

    --- Flight Search API (requires approved access) ---
    flight-search          Real-time one-way flight search
    round-trip             Real-time round-trip search
    multi-city             Real-time multi-city / open-jaw search
    booking-link           Generate booking link from search results
"""

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DATA_API_BASE = "https://api.travelpayouts.com"
SEARCH_API_BASE = "https://tickets-api.travelpayouts.com"

# Filled after load_env()
TP_TOKEN: str | None = None
TP_MARKER: str | None = None

DATA_API_TESTS = [
    "cheapest",
    "non-stop",
    "calendar",
    "monthly",
    "latest",
    "month-matrix",
    "week-matrix",
    "nearest-places",
    "airline-routes",
    "city-directions",
    "special-offers",
    "ref-airports",
    "ref-airlines",
]

SEARCH_API_TESTS = [
    "flight-search",
    "round-trip",
    "multi-city",
    "booking-link",
]

ALL_TESTS = DATA_API_TESTS + SEARCH_API_TESTS


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
# Signature generation (MD5)
# ---------------------------------------------------------------------------
def _collect_values(obj: dict | list) -> list[str]:
    """Recursively collect all values from a nested dict/list, sorted
    alphabetically at each level (as required by the Travelpayouts
    signature algorithm).

    For dicts: keys are sorted alphabetically, then values are collected
    in that order. For nested dicts/lists, recurse into them.
    For lists: iterate in order (each element is a dict typically).
    """
    values: list[str] = []
    if isinstance(obj, dict):
        for key in sorted(obj.keys()):
            val = obj[key]
            if isinstance(val, (dict, list)):
                values.extend(_collect_values(val))
            else:
                values.append(str(val))
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, (dict, list)):
                values.extend(_collect_values(item))
            else:
                values.append(str(item))
    return values


def generate_signature(token: str, params: dict) -> str:
    """Generate MD5 signature for Travelpayouts Flight Search API.

    The signature is computed as:
        md5(token + ":" + sorted_param_values_joined_by_colon)

    Where param values are collected recursively from nested structures,
    sorted alphabetically at each dict level.
    """
    values = _collect_values(params)
    raw = token + ":" + ":".join(values)
    signature = hashlib.md5(raw.encode()).hexdigest()
    return signature


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
def data_api_get(
    token: str, path: str, params: dict | None = None
) -> dict | None:
    """GET request to the Travelpayouts Data API."""
    url = f"{DATA_API_BASE}{path}"
    headers = {
        "X-Access-Token": token,
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
    }
    try:
        response = requests.get(
            url, params=params or {}, headers=headers, timeout=30
        )
    except requests.RequestException as e:
        print(f"  REQUEST ERROR: {e}")
        return None

    if response.status_code != 200:
        print(f"  FAILED ({response.status_code}): {response.text[:500]}")
        return None

    content_type = response.headers.get("Content-Type", "")
    if "xml" in content_type or "xml" in path:
        # Special offers returns XML
        print(f"  Response ({len(response.text)} chars XML)")
        return {"_xml": response.text[:2000]}

    try:
        result = response.json()
        # Wrap list responses (e.g., reference data endpoints) in a dict
        if isinstance(result, list):
            return {"_list": result}
        return result
    except ValueError:
        print(f"  FAILED: Could not parse JSON. Response: {response.text[:300]}")
        return None


def search_api_post(
    token: str,
    marker: str,
    url: str,
    body: dict,
    user_ip: str = "83.169.44.1",
    host: str = "openmates.org",
) -> dict | None:
    """POST request to the Travelpayouts Flight Search API (new version).

    Adds required headers: x-real-host, x-user-ip, x-signature,
    x-affiliate-user-id.
    """
    # Build signature from the body params (excluding the signature field itself)
    body_for_sig = {k: v for k, v in body.items() if k != "signature"}
    signature = generate_signature(token, body_for_sig)
    body["signature"] = signature

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "x-real-host": host,
        "x-user-ip": user_ip,
        "x-signature": signature,
        "x-affiliate-user-id": token,
    }

    try:
        response = requests.post(url, json=body, headers=headers, timeout=60)
    except requests.RequestException as e:
        print(f"  REQUEST ERROR: {e}")
        return None

    if response.status_code not in (200, 201):
        print(f"  FAILED ({response.status_code}): {response.text[:500]}")
        return None

    try:
        return response.json()
    except ValueError:
        print(f"  FAILED: Could not parse JSON. Response: {response.text[:300]}")
        return None


def search_api_results_post(
    token: str,
    results_url: str,
    search_id: str,
    user_ip: str = "83.169.44.1",
    host: str = "openmates.org",
) -> dict | None:
    """POST to get search results from the new API.

    URL = results_url + /search/affiliate/results
    Body = { search_id, last_update_timestamp }
    """
    url = f"{results_url}/search/affiliate/results"
    body = {
        "search_id": search_id,
        "last_update_timestamp": 0,
    }

    # Signature for results request
    signature = generate_signature(token, body)

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "x-real-host": host,
        "x-user-ip": user_ip,
        "x-signature": signature,
        "x-affiliate-user-id": token,
    }

    try:
        response = requests.post(url, json=body, headers=headers, timeout=60)
    except requests.RequestException as e:
        print(f"  REQUEST ERROR: {e}")
        return None

    if response.status_code == 304:
        # No new results yet
        return {"_status": 304, "is_over": False}

    if response.status_code not in (200, 201):
        print(f"  FAILED ({response.status_code}): {response.text[:500]}")
        return None

    try:
        return response.json()
    except ValueError:
        print(f"  FAILED: Could not parse JSON. Response: {response.text[:300]}")
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
    """Format a price value for display."""
    try:
        return f"{float(value):,.0f} {currency}"
    except (ValueError, TypeError):
        return f"{value} {currency}"


def display_cheapest_tickets(data: dict, raw: bool) -> None:
    """Display results from /v1/prices/cheap."""
    if raw:
        print_json(data)
        return

    if not data.get("success"):
        print(f"  API returned error: {data}")
        return

    routes = data.get("data", {})
    if not routes:
        print("  No tickets found.")
        return

    total_routes = 0
    for dest_code, tickets in routes.items():
        for stops, ticket in tickets.items():
            total_routes += 1
            price = ticket.get("price", "?")
            airline = ticket.get("airline", "?")
            departure = ticket.get("departure_at", "?")
            return_at = ticket.get("return_at", "?")
            transfers = ticket.get("transfers", stops)
            flight_num = ticket.get("flight_number", "?")

            dep_date = departure[:10] if isinstance(departure, str) else "?"
            ret_date = return_at[:10] if isinstance(return_at, str) and return_at else "—"

            print(
                f"  [{dest_code}] {format_price(price, data.get('currency', 'EUR'))} | "
                f"{airline} {flight_num} | {dep_date} → {ret_date} | "
                f"{transfers} stop(s)"
            )

    print(f"\n  Total: {total_routes} route(s)")


def display_latest_prices(data: dict, raw: bool) -> None:
    """Display results from /v2/prices/latest."""
    if raw:
        print_json(data)
        return

    if not data.get("success"):
        print(f"  API returned error: {data}")
        return

    tickets = data.get("data", [])
    if not tickets:
        print("  No prices found.")
        return

    print(f"  Found {len(tickets)} price(s)\n")
    for i, t in enumerate(tickets[:20], 1):
        origin = t.get("origin", "?")
        dest = t.get("destination", "?")
        price = t.get("value", "?")
        airline = t.get("airline", "?")
        depart = t.get("depart_date", "?")
        return_date = t.get("return_date", "—")
        transfers = t.get("number_of_changes", "?")
        flight_num = t.get("flight_number", "?")
        gate = t.get("gate", "?")

        print(
            f"  {i:>2}. {origin}→{dest} | {format_price(price, 'EUR')} | "
            f"{airline} {flight_num} | {depart} → {return_date} | "
            f"{transfers} stop(s) | via {gate}"
        )

    print(f"\n  Total: {len(tickets)} price(s)")


def display_calendar(data: dict, raw: bool) -> None:
    """Display results from /v1/prices/calendar."""
    if raw:
        print_json(data)
        return

    if not data.get("success"):
        print(f"  API returned error: {data}")
        return

    tickets = data.get("data", {})
    if not tickets:
        print("  No calendar data found.")
        return

    print("  Prices by day:\n")
    for date_str in sorted(tickets.keys()):
        t = tickets[date_str]
        price = t.get("price", "?")
        airline = t.get("airline", "?")
        transfers = t.get("transfers", "?")
        flight_num = t.get("flight_number", "?")
        print(
            f"  {date_str} | {format_price(price, 'EUR')} | "
            f"{airline} {flight_num} | {transfers} stop(s)"
        )


def display_search_results(data: dict, raw: bool) -> None:
    """Display results from the new Flight Search API (v2 Nov 2025)."""
    if raw:
        print_json(data)
        return

    tickets = data.get("tickets", [])
    airlines = {a["iata"]: a for a in data.get("airlines", [])}
    agents = {a["id"]: a for a in data.get("agents", [])}
    flight_legs = data.get("flight_legs", [])

    if not tickets:
        print("  No tickets in this result batch.")
        return

    print(f"  Tickets: {len(tickets)}")
    print(f"  Airlines: {len(airlines)}")
    print(f"  Agents: {len(agents)}")
    print(f"  Flight legs: {len(flight_legs)}")
    print()

    for i, ticket in enumerate(tickets[:10], 1):
        proposals = ticket.get("proposals", [])
        segments = ticket.get("segments", [])

        if not proposals:
            continue

        # Best (cheapest) proposal
        best = min(proposals, key=lambda p: p.get("price", {}).get("amount", float("inf")))
        price_info = best.get("price", {})
        price_amount = price_info.get("amount", "?")
        price_currency = price_info.get("currency", "?")
        agent_id = best.get("agent_id", "?")
        agent_name = agents.get(agent_id, {}).get("label", str(agent_id))
        proposal_id = best.get("id", "?")

        print(f"  --- Ticket {i} (proposal: {proposal_id}) ---")
        print(f"  Best price: {format_price(price_amount, price_currency)} via {agent_name}")

        # Display per-person price if available
        ppp = best.get("price_per_person", {})
        if ppp:
            print(f"  Per person: {format_price(ppp.get('amount', '?'), ppp.get('currency', '?'))}")

        # Display flight terms (baggage etc.)
        flight_terms = best.get("flight_terms", [])
        for seg_idx, ft_list in enumerate(flight_terms):
            for ft in ft_list if isinstance(ft_list, list) else [ft_list]:
                baggage = ft.get("baggage", {})
                trip_class = ft.get("trip_class", "?")
                carrier = ft.get("carrier", "?")
                number = ft.get("number", "?")
                seats = ft.get("seats_available")

                bag_str = ""
                if baggage:
                    count = baggage.get("count", 0)
                    weight = baggage.get("weight")
                    bag_str = f"{count} bag(s)"
                    if weight:
                        bag_str += f" ({weight}kg)"

                seats_str = f" | {seats} seats left" if seats else ""
                print(
                    f"    Seg {seg_idx}: {carrier}{number} class={trip_class} "
                    f"| baggage: {bag_str or 'N/A'}{seats_str}"
                )

        # Display segments (legs)
        for seg_idx, segment in enumerate(segments):
            seg_flights = segment.get("flights", [])
            transfers = segment.get("transfers", [])

            direction = "Outbound" if seg_idx == 0 else (
                "Return" if seg_idx == 1 else f"Leg {seg_idx + 1}"
            )
            stop_count = len(transfers)
            stop_label = "direct" if stop_count == 0 else f"{stop_count} stop(s)"

            print(f"\n    {direction} ({stop_label}):")

            for leg_idx in seg_flights:
                if isinstance(leg_idx, int) and leg_idx < len(flight_legs):
                    leg = flight_legs[leg_idx]
                elif isinstance(leg_idx, dict):
                    leg = leg_idx
                else:
                    print(f"      [Leg index {leg_idx} out of range]")
                    continue

                origin = leg.get("origin", "?")
                dest = leg.get("destination", "?")
                dep_local = leg.get("local_departure_date_time", "?")
                arr_local = leg.get("local_arrival_date_time", "?")
                carrier_info = leg.get("operating_carrier_designator", {})
                carrier_code = carrier_info.get("carrier_code", "?") if isinstance(carrier_info, dict) else "?"
                flight_num = carrier_info.get("number", "?") if isinstance(carrier_info, dict) else "?"
                equipment = leg.get("equipment", {})
                aircraft = equipment.get("name", "?") if isinstance(equipment, dict) else "?"

                airline_name = airlines.get(carrier_code, {}).get("name", carrier_code)

                dep_time = dep_local[11:16] if isinstance(dep_local, str) and len(dep_local) > 15 else dep_local
                arr_time = arr_local[11:16] if isinstance(arr_local, str) and len(arr_local) > 15 else arr_local

                print(
                    f"      {origin} {dep_time} → {dest} {arr_time} | "
                    f"{airline_name} {carrier_code}{flight_num} | {aircraft}"
                )

            # Display transfer info
            for transfer in transfers:
                t_airport = transfer.get("airport_change")
                t_night = transfer.get("night_transfer")
                t_recheck = transfer.get("recheck_baggage")
                flags = []
                if t_airport:
                    flags.append("airport change")
                if t_night:
                    flags.append("night transfer")
                if t_recheck:
                    flags.append("recheck baggage")
                if flags:
                    print(f"      ⚠ Transfer: {', '.join(flags)}")

        print(f"  Proposals: {len(proposals)} offer(s) from {len(set(p.get('agent_id', '?') for p in proposals))} agent(s)")
        print()


# ---------------------------------------------------------------------------
# Test functions — Data API
# ---------------------------------------------------------------------------
def test_cheapest(token: str, origin: str, dest: str, raw: bool) -> bool:
    """Test: Cheapest tickets for a route (v1/prices/cheap)."""
    print_header(f"DATA API: Cheapest Tickets ({origin} → {dest})")

    depart_month = (datetime.now() + timedelta(days=30)).strftime("%Y-%m")

    data = data_api_get(token, "/v1/prices/cheap", {
        "origin": origin,
        "destination": dest,
        "depart_date": depart_month,
        "currency": "eur",
    })
    if data is None:
        return False

    display_cheapest_tickets(data, raw)
    return data.get("success", False)


def test_nonstop(token: str, origin: str, dest: str, raw: bool) -> bool:
    """Test: Non-stop (direct) tickets only (v1/prices/direct)."""
    print_header(f"DATA API: Non-stop Tickets ({origin} → {dest})")

    depart_month = (datetime.now() + timedelta(days=30)).strftime("%Y-%m")

    data = data_api_get(token, "/v1/prices/direct", {
        "origin": origin,
        "destination": dest,
        "depart_date": depart_month,
        "currency": "eur",
    })
    if data is None:
        return False

    if raw:
        print_json(data)
    else:
        if data.get("success"):
            routes = data.get("data", {})
            if not routes:
                print("  No direct flights found for this route/period.")
            else:
                for dest_code, ticket in routes.items():
                    price = ticket.get("price", "?")
                    airline = ticket.get("airline", "?")
                    departure = ticket.get("departure_at", "?")
                    dep_date = departure[:10] if isinstance(departure, str) else "?"
                    print(
                        f"  [{dest_code}] {format_price(price, 'EUR')} | "
                        f"{airline} | {dep_date}"
                    )
        else:
            print(f"  API returned error: {data}")

    return data.get("success", False)


def test_calendar(token: str, origin: str, dest: str, raw: bool) -> bool:
    """Test: Daily prices for a month (v1/prices/calendar)."""
    print_header(f"DATA API: Calendar Prices ({origin} → {dest})")

    depart_month = (datetime.now() + timedelta(days=30)).strftime("%Y-%m")

    data = data_api_get(token, "/v1/prices/calendar", {
        "origin": origin,
        "destination": dest,
        "departure_date": depart_month,
        "calendar_type": "departure_date",
        "currency": "eur",
    })
    if data is None:
        return False

    display_calendar(data, raw)
    return data.get("success", False)


def test_monthly(token: str, origin: str, dest: str, raw: bool) -> bool:
    """Test: Cheapest tickets grouped by month (v1/prices/monthly)."""
    print_header(f"DATA API: Monthly Prices ({origin} → {dest})")

    data = data_api_get(token, "/v1/prices/monthly", {
        "origin": origin,
        "destination": dest,
        "currency": "eur",
    })
    if data is None:
        return False

    if raw:
        print_json(data)
    else:
        if data.get("success"):
            months = data.get("data", {})
            if not months:
                print("  No monthly data found.")
            else:
                for month_key in sorted(months.keys()):
                    t = months[month_key]
                    price = t.get("price", "?")
                    airline = t.get("airline", "?")
                    transfers = t.get("transfers", "?")
                    print(
                        f"  {month_key} | {format_price(price, 'EUR')} | "
                        f"{airline} | {transfers} stop(s)"
                    )
        else:
            print(f"  API returned error: {data}")

    return data.get("success", False)


def test_latest(token: str, origin: str, dest: str, raw: bool) -> bool:
    """Test: Latest prices from last 48h (v2/prices/latest)."""
    print_header(f"DATA API: Latest Prices ({origin} → {dest})")

    data = data_api_get(token, "/v2/prices/latest", {
        "origin": origin,
        "destination": dest,
        "period_type": "month",
        "beginning_of_period": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-01"),
        "currency": "eur",
        "limit": 30,
        "sorting": "price",
    })
    if data is None:
        return False

    display_latest_prices(data, raw)
    return data.get("success", False)


def test_month_matrix(token: str, origin: str, dest: str, raw: bool) -> bool:
    """Test: Month price matrix (v2/prices/month-matrix)."""
    print_header(f"DATA API: Month Matrix ({origin} → {dest})")

    month = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-01")

    data = data_api_get(token, "/v2/prices/month-matrix", {
        "origin": origin,
        "destination": dest,
        "month": month,
        "currency": "eur",
    })
    if data is None:
        return False

    if raw:
        print_json(data)
    else:
        if data.get("success"):
            prices = data.get("data", [])
            if not prices:
                print("  No month matrix data found.")
            else:
                print(f"  Found {len(prices)} day(s) with prices:\n")
                for p in sorted(prices, key=lambda x: x.get("depart_date", "")):
                    depart = p.get("depart_date", "?")
                    ret = p.get("return_date", "—")
                    value = p.get("value", "?")
                    transfers = p.get("number_of_changes", "?")
                    print(
                        f"  {depart} → {ret} | {format_price(value, 'EUR')} | "
                        f"{transfers} stop(s)"
                    )
        else:
            print(f"  API returned error: {data}")

    return data.get("success", False)


def test_week_matrix(token: str, origin: str, dest: str, raw: bool) -> bool:
    """Test: Week price matrix (v2/prices/week-matrix)."""
    print_header(f"DATA API: Week Matrix ({origin} → {dest})")

    depart = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    ret = (datetime.now() + timedelta(days=37)).strftime("%Y-%m-%d")

    data = data_api_get(token, "/v2/prices/week-matrix", {
        "origin": origin,
        "destination": dest,
        "depart_date": depart,
        "return_date": ret,
        "currency": "eur",
    })
    if data is None:
        return False

    if raw:
        print_json(data)
    else:
        if data.get("success"):
            prices = data.get("data", [])
            if not prices:
                print("  No week matrix data found.")
            else:
                print(f"  Found {len(prices)} option(s):\n")
                for p in sorted(prices, key=lambda x: x.get("value", float("inf"))):
                    depart_d = p.get("depart_date", "?")
                    ret_d = p.get("return_date", "—")
                    value = p.get("value", "?")
                    transfers = p.get("number_of_changes", "?")
                    gate = p.get("gate", "?")
                    print(
                        f"  {depart_d} → {ret_d} | {format_price(value, 'EUR')} | "
                        f"{transfers} stop(s) | via {gate}"
                    )
        else:
            print(f"  API returned error: {data}")

    return data.get("success", False)


def test_nearest_places(token: str, origin: str, dest: str, raw: bool) -> bool:
    """Test: Alternative directions / nearest places (v2/prices/nearest-places-matrix)."""
    print_header(f"DATA API: Nearest Places Matrix ({origin} → {dest})")

    depart = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    ret = (datetime.now() + timedelta(days=37)).strftime("%Y-%m-%d")

    data = data_api_get(token, "/v2/prices/nearest-places-matrix", {
        "origin": origin,
        "destination": dest,
        "depart_date": depart,
        "return_date": ret,
        "currency": "eur",
        "limit": 10,
        "flexibility": 3,
    })
    if data is None:
        return False

    if raw:
        print_json(data)
    else:
        # This endpoint returns either {success: true, data: [...]}
        # or {prices: [...], origins: [...], destinations: [...]}
        prices = data.get("data", []) or data.get("prices", [])
        if not prices:
            print("  No alternative routes found.")
        else:
            print(f"  Found {len(prices)} alternative route(s):\n")
            for p in sorted(prices, key=lambda x: x.get("value", x.get("price", float("inf")))):
                orig = p.get("origin", "?")
                dst = p.get("destination", "?")
                # Handle both ISO datetime and date-only formats
                depart_raw = p.get("depart_date", "?")
                ret_raw = p.get("return_date", "—")
                depart_d = depart_raw[:10] if isinstance(depart_raw, str) and len(depart_raw) > 10 else depart_raw
                ret_d = ret_raw[:10] if isinstance(ret_raw, str) and len(ret_raw) > 10 else ret_raw
                value = p.get("value", p.get("price", "?"))
                transfers = p.get("number_of_changes", p.get("transfers", "?"))
                distance = p.get("distance", "?")
                gate = p.get("gate", "?")
                airline = p.get("main_airline", "")
                airline_str = f" | {airline}" if airline else ""
                print(
                    f"  {orig}→{dst} | {depart_d}→{ret_d} | "
                    f"{format_price(value, 'EUR')} | {transfers} stop(s) | "
                    f"{distance}km | via {gate}{airline_str}"
                )

    return bool(data.get("success") or data.get("prices"))


def test_airline_routes(token: str, raw: bool) -> bool:
    """Test: Popular routes for an airline (v1/airline-directions)."""
    print_header("DATA API: Airline Routes (LH = Lufthansa)")

    data = data_api_get(token, "/v1/airline-directions", {
        "airline_code": "LH",
        "limit": 20,
    })
    if data is None:
        return False

    if raw:
        print_json(data)
    else:
        if data.get("success"):
            routes = data.get("data", {})
            if not routes:
                print("  No routes found.")
            else:
                print(f"  Found {len(routes)} route(s):\n")
                for route_key, info in list(routes.items())[:20]:
                    print(f"  {route_key}: {info}")
        else:
            print(f"  API returned error: {data}")

    return data.get("success", False)


def test_city_directions(token: str, origin: str, raw: bool) -> bool:
    """Test: Popular directions from a city (v1/city-directions)."""
    print_header(f"DATA API: Popular Directions from {origin}")

    data = data_api_get(token, "/v1/city-directions", {
        "origin": origin,
        "currency": "eur",
    })
    if data is None:
        return False

    if raw:
        print_json(data)
    else:
        if data.get("success"):
            directions = data.get("data", {})
            if not directions:
                print("  No popular directions found.")
            else:
                print(f"  Found {len(directions)} direction(s):\n")
                for dest_code, info in list(directions.items())[:20]:
                    price = info.get("price", "?")
                    airline = info.get("airline", "?")
                    transfers = info.get("transfers", "?")
                    popularity = info.get("popularity", "?")
                    print(
                        f"  → {dest_code} | {format_price(price, 'EUR')} | "
                        f"{airline} | {transfers} stop(s) | popularity: {popularity}"
                    )
        else:
            print(f"  API returned error: {data}")

    return data.get("success", False)


def test_special_offers(token: str, raw: bool) -> bool:
    """Test: Current airline special offers (v2/prices/special-offers)."""
    print_header("DATA API: Special Offers")

    data = data_api_get(token, "/v2/prices/special-offers")
    if data is None:
        return False

    if raw:
        if isinstance(data, dict) and "_xml" in data:
            print(data["_xml"])
        else:
            print_json(data)
    else:
        if isinstance(data, dict) and "_xml" in data:
            xml_len = len(data["_xml"])
            print(f"  Received XML response ({xml_len} chars)")
            # Show first few lines
            lines = data["_xml"].split("\n")[:10]
            for line in lines:
                print(f"  {line.strip()}")
            if len(data["_xml"]) > 500:
                print("  ...")
        else:
            print_json(data)

    return True


def test_ref_airports(token: str, raw: bool) -> bool:
    """Test: Reference data — airports list."""
    print_header("DATA API: Reference — Airports")

    data = data_api_get(token, "/data/en/airports.json")
    if data is None:
        return False

    # Reference endpoints return lists, wrapped as {"_list": [...]}
    items = data.get("_list", [])
    if not items:
        print("  No airport data returned.")
        return False

    if raw:
        print_json(items[:5])
    else:
        print(f"  Total airports: {len(items)}")
        for ap in items[:5]:
            name = ap.get("name", "?")
            code = ap.get("code", "?")
            city = ap.get("city_code", "?")
            country = ap.get("country_code", "?")
            coords = ap.get("coordinates", {})
            lat = coords.get("lat", "?")
            lon = coords.get("lon", "?")
            print(f"  {code} | {name} | {city}, {country} | ({lat}, {lon})")
        print("  ...")

    return len(items) > 0


def test_ref_airlines(token: str, raw: bool) -> bool:
    """Test: Reference data — airlines list."""
    print_header("DATA API: Reference — Airlines")

    data = data_api_get(token, "/data/en/airlines.json")
    if data is None:
        return False

    # Reference endpoints return lists, wrapped as {"_list": [...]}
    items = data.get("_list", [])
    if not items:
        print("  No airline data returned.")
        return False

    if raw:
        print_json(items[:5])
    else:
        print(f"  Total airlines: {len(items)}")
        well_known = ["LH", "BA", "AF", "EK", "FR", "U2", "LX", "OS"]
        for al in items:
            if al.get("iata_code") in well_known or al.get("code") in well_known:
                name = al.get("name") or al.get("name_translations", {}).get("en", "?")
                code = al.get("iata_code") or al.get("code", "?")
                is_lcc = al.get("is_lowcost", False)
                alliance = al.get("alliance_name", "—")
                lcc_str = " [LCC]" if is_lcc else ""
                print(f"  {code} | {name}{lcc_str} | {alliance}")
        print("  ...")

    return len(items) > 0


# ---------------------------------------------------------------------------
# Test functions — Flight Search API (new v2, Nov 2025)
# ---------------------------------------------------------------------------
def _poll_search_results(
    token: str,
    results_url: str,
    search_id: str,
    raw: bool,
    max_polls: int = 15,
    poll_interval: float = 3.0,
) -> dict | None:
    """Poll the search results endpoint until is_over=true or max_polls reached.

    Returns the aggregated result (last response with tickets).
    """
    all_tickets = []
    all_airlines = {}
    all_agents = {}
    all_flight_legs = []
    last_timestamp = 0

    for attempt in range(1, max_polls + 1):
        print(f"  Polling attempt {attempt}/{max_polls}...")

        url = f"{results_url}/search/affiliate/results"
        body = {
            "search_id": search_id,
            "last_update_timestamp": last_timestamp,
        }
        signature = generate_signature(token, body)

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "x-real-host": "openmates.org",
            "x-user-ip": "83.169.44.1",
            "x-signature": signature,
            "x-affiliate-user-id": token,
        }

        try:
            response = requests.post(url, json=body, headers=headers, timeout=60)
        except requests.RequestException as e:
            print(f"    Request error: {e}")
            time.sleep(poll_interval)
            continue

        if response.status_code == 304:
            print("    No new results yet (304)")
            time.sleep(poll_interval)
            continue

        if response.status_code not in (200, 201):
            print(f"    Error ({response.status_code}): {response.text[:300]}")
            time.sleep(poll_interval)
            continue

        try:
            result = response.json()
        except ValueError:
            print(f"    Failed to parse JSON: {response.text[:200]}")
            time.sleep(poll_interval)
            continue

        # Accumulate results
        new_tickets = result.get("tickets", [])
        new_airlines = result.get("airlines", [])
        new_agents = result.get("agents", [])
        new_legs = result.get("flight_legs", [])

        all_tickets.extend(new_tickets)
        for al in new_airlines:
            all_airlines[al.get("iata", al.get("id", ""))] = al
        for ag in new_agents:
            all_agents[ag.get("id", "")] = ag
        all_flight_legs.extend(new_legs)

        last_timestamp = result.get("last_update_timestamp", last_timestamp)
        is_over = result.get("is_over", False)

        print(
            f"    +{len(new_tickets)} tickets, "
            f"+{len(new_legs)} legs | "
            f"Total: {len(all_tickets)} tickets | "
            f"is_over={is_over}"
        )

        if is_over:
            break

        time.sleep(poll_interval)

    if not all_tickets:
        print("  No tickets found after polling.")
        return None

    return {
        "tickets": all_tickets,
        "airlines": list(all_airlines.values()),
        "agents": list(all_agents.values()),
        "flight_legs": all_flight_legs,
    }


def _start_search(
    token: str,
    marker: str,
    directions: list[dict],
    trip_class: str = "Y",
    adults: int = 1,
    children: int = 0,
    infants: int = 0,
) -> tuple[str | None, str | None]:
    """Start a flight search and return (search_id, results_url) or (None, None)."""
    body = {
        "marker": marker,
        "locale": "en",
        "search_params": {
            "trip_class": trip_class,
            "passengers": {
                "adults": adults,
                "children": children,
                "infants": infants,
            },
            "directions": directions,
        },
    }

    # Generate signature from the actual body (excluding the signature field).
    # The algorithm recursively collects all values sorted alphabetically at
    # each dict level, then joins with ":" and prepends the token.
    signature = generate_signature(token, body)
    body["signature"] = signature

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "x-real-host": "openmates.org",
        "x-user-ip": "83.169.44.1",
        "x-signature": signature,
        "x-affiliate-user-id": token,
    }

    start_url = f"{SEARCH_API_BASE}/search/affiliate/start"
    print(f"  Starting search at: {start_url}")
    print(f"  Directions: {json.dumps(directions)}")

    try:
        response = requests.post(start_url, json=body, headers=headers, timeout=60)
    except requests.RequestException as e:
        print(f"  REQUEST ERROR: {e}")
        return None, None

    if response.status_code not in (200, 201):
        print(f"  FAILED ({response.status_code}): {response.text[:500]}")
        return None, None

    try:
        result = response.json()
    except ValueError:
        print(f"  FAILED: Could not parse JSON: {response.text[:300]}")
        return None, None

    search_id = result.get("search_id")
    results_url = result.get("results_url")

    if not search_id:
        print(f"  ERROR: No search_id in response: {result}")
        return None, None

    print(f"  search_id: {search_id}")
    print(f"  results_url: {results_url}")

    return search_id, results_url


def test_flight_search(
    token: str, marker: str, origin: str, dest: str, raw: bool
) -> bool:
    """Test: Real-time one-way flight search (new API)."""
    print_header(f"FLIGHT SEARCH: One-way ({origin} → {dest})")

    depart = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")

    search_id, results_url = _start_search(
        token, marker,
        directions=[{"origin": origin, "destination": dest, "date": depart}],
    )
    if not search_id:
        return False

    if not results_url:
        print("  WARNING: No results_url returned, using default domain.")
        results_url = "https://tickets-api.travelpayouts.com"

    # Wait a moment before first poll
    print("  Waiting 5s before polling results...")
    time.sleep(5)

    results = _poll_search_results(token, results_url, search_id, raw)
    if results is None:
        return False

    display_search_results(results, raw)
    return True


def test_round_trip(
    token: str, marker: str, origin: str, dest: str, raw: bool
) -> bool:
    """Test: Real-time round-trip flight search (new API)."""
    print_header(f"FLIGHT SEARCH: Round-trip ({origin} ↔ {dest})")

    depart = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
    return_date = (datetime.now() + timedelta(days=21)).strftime("%Y-%m-%d")

    search_id, results_url = _start_search(
        token, marker,
        directions=[
            {"origin": origin, "destination": dest, "date": depart},
            {"origin": dest, "destination": origin, "date": return_date},
        ],
    )
    if not search_id:
        return False

    if not results_url:
        results_url = "https://tickets-api.travelpayouts.com"

    print("  Waiting 5s before polling results...")
    time.sleep(5)

    results = _poll_search_results(token, results_url, search_id, raw)
    if results is None:
        return False

    display_search_results(results, raw)
    return True


def test_multi_city(
    token: str, marker: str, origin: str, dest: str, raw: bool
) -> bool:
    """Test: Real-time multi-city / open-jaw search (new API)."""
    # Example: origin → dest → third city → origin
    third_city = "BCN"  # Barcelona as a middle stop
    if origin == "BCN" or dest == "BCN":
        third_city = "AMS"  # Use Amsterdam if BCN is origin/dest

    print_header(f"FLIGHT SEARCH: Multi-city ({origin} → {dest} → {third_city} → {origin})")

    date1 = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
    date2 = (datetime.now() + timedelta(days=18)).strftime("%Y-%m-%d")
    date3 = (datetime.now() + timedelta(days=22)).strftime("%Y-%m-%d")

    search_id, results_url = _start_search(
        token, marker,
        directions=[
            {"origin": origin, "destination": dest, "date": date1},
            {"origin": dest, "destination": third_city, "date": date2},
            {"origin": third_city, "destination": origin, "date": date3},
        ],
    )
    if not search_id:
        return False

    if not results_url:
        results_url = "https://tickets-api.travelpayouts.com"

    print("  Waiting 5s before polling results...")
    time.sleep(5)

    results = _poll_search_results(token, results_url, search_id, raw)
    if results is None:
        return False

    display_search_results(results, raw)
    return True


def test_booking_link(
    token: str, marker: str, origin: str, dest: str, raw: bool
) -> bool:
    """Test: Generate a booking link from search results.

    This runs a search first, then attempts to generate a booking link
    for the cheapest proposal found.
    """
    print_header(f"FLIGHT SEARCH: Booking Link ({origin} → {dest})")

    depart = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")

    # Step 1: Start search
    search_id, results_url = _start_search(
        token, marker,
        directions=[{"origin": origin, "destination": dest, "date": depart}],
    )
    if not search_id:
        return False

    if not results_url:
        results_url = "https://tickets-api.travelpayouts.com"

    # Step 2: Poll for results
    print("  Waiting 5s before polling...")
    time.sleep(5)

    results = _poll_search_results(token, results_url, search_id, raw, max_polls=10)
    if results is None:
        print("  No results to generate booking link from.")
        return False

    # Step 3: Find cheapest proposal
    best_proposal_id = None
    best_price = float("inf")
    best_agent = None

    for ticket in results.get("tickets", []):
        for proposal in ticket.get("proposals", []):
            price = proposal.get("price", {}).get("amount", float("inf"))
            try:
                price_float = float(price)
            except (ValueError, TypeError):
                continue
            if price_float < best_price:
                best_price = price_float
                best_proposal_id = proposal.get("id")
                best_agent = proposal.get("agent_id")

    if not best_proposal_id:
        print("  No proposals found to generate booking link.")
        return False

    agents = {a["id"]: a for a in results.get("agents", [])}
    agent_name = agents.get(best_agent, {}).get("label", str(best_agent))

    print(f"\n  Best proposal: {best_proposal_id}")
    print(f"  Price: {format_price(best_price, 'EUR')}")
    print(f"  Agent: {agent_name}")

    # Step 4: Generate booking link
    # URL: results_url/searches/search_id/clicks/proposal_id
    click_url = f"{results_url}/searches/{search_id}/clicks/{best_proposal_id}"
    print(f"\n  Requesting booking link: {click_url}")

    headers = {
        "Accept": "application/json",
        "x-real-host": "openmates.org",
        "x-user-ip": "83.169.44.1",
        "x-affiliate-user-id": token,
        "x-marker": marker,
    }

    try:
        response = requests.get(click_url, headers=headers, timeout=30)
    except requests.RequestException as e:
        print(f"  REQUEST ERROR: {e}")
        return False

    if response.status_code != 200:
        print(f"  FAILED ({response.status_code}): {response.text[:500]}")
        # This is expected if the search API access hasn't been fully approved
        print("\n  NOTE: Booking link generation requires approved Flight Search API access.")
        print("  The search itself may work but click-through links need full approval.")
        return False

    try:
        click_data = response.json()
    except ValueError:
        print(f"  FAILED: Could not parse JSON: {response.text[:300]}")
        return False

    if raw:
        print_json(click_data)
    else:
        booking_url = click_data.get("url", "?")
        click_id = click_data.get("click_id") or click_data.get("str_click_id", "?")
        method = click_data.get("method", "GET")
        expire = click_data.get("expire_at_unix_sec")
        expire_str = (
            datetime.fromtimestamp(expire).strftime("%Y-%m-%d %H:%M:%S")
            if expire else "?"
        )

        print("\n  ✓ Booking link generated!")
        print(f"  URL: {booking_url}")
        print(f"  Method: {method}")
        print(f"  Click ID: {click_id}")
        print(f"  Expires: {expire_str}")

        # Check for POST method (some agencies require form submission)
        params = click_data.get("params", {})
        if method == "POST" and params:
            print(f"\n  NOTE: This agency requires POST redirect with {len(params)} params")

    return True


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------
def run_tests(
    tests: list[str],
    token: str,
    marker: str | None,
    origin: str,
    dest: str,
    raw: bool,
) -> dict[str, bool]:
    """Run specified tests and return results."""
    results: dict[str, bool] = {}

    for test_name in tests:
        try:
            if test_name == "cheapest":
                results[test_name] = test_cheapest(token, origin, dest, raw)
            elif test_name == "non-stop":
                results[test_name] = test_nonstop(token, origin, dest, raw)
            elif test_name == "calendar":
                results[test_name] = test_calendar(token, origin, dest, raw)
            elif test_name == "monthly":
                results[test_name] = test_monthly(token, origin, dest, raw)
            elif test_name == "latest":
                results[test_name] = test_latest(token, origin, dest, raw)
            elif test_name == "month-matrix":
                results[test_name] = test_month_matrix(token, origin, dest, raw)
            elif test_name == "week-matrix":
                results[test_name] = test_week_matrix(token, origin, dest, raw)
            elif test_name == "nearest-places":
                results[test_name] = test_nearest_places(token, origin, dest, raw)
            elif test_name == "airline-routes":
                results[test_name] = test_airline_routes(token, raw)
            elif test_name == "city-directions":
                results[test_name] = test_city_directions(token, origin, raw)
            elif test_name == "special-offers":
                results[test_name] = test_special_offers(token, raw)
            elif test_name == "ref-airports":
                results[test_name] = test_ref_airports(token, raw)
            elif test_name == "ref-airlines":
                results[test_name] = test_ref_airlines(token, raw)
            # Flight Search API tests (require marker)
            elif test_name in SEARCH_API_TESTS:
                if not marker:
                    print(f"\n  SKIPPING '{test_name}' — no marker provided.")
                    print("  Flight Search API requires --marker <your_marker_id>")
                    results[test_name] = False
                    continue
                if test_name == "flight-search":
                    results[test_name] = test_flight_search(token, marker, origin, dest, raw)
                elif test_name == "round-trip":
                    results[test_name] = test_round_trip(token, marker, origin, dest, raw)
                elif test_name == "multi-city":
                    results[test_name] = test_multi_city(token, marker, origin, dest, raw)
                elif test_name == "booking-link":
                    results[test_name] = test_booking_link(token, marker, origin, dest, raw)
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
        description="Travelpayouts API - Comprehensive Test Script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run all Data API tests (simple token auth)
  python %(prog)s --token YOUR_TOKEN

  # Run a specific test
  python %(prog)s --token YOUR_TOKEN --test cheapest
  python %(prog)s --token YOUR_TOKEN --test latest --raw

  # Run Flight Search API tests (requires marker + approved access)
  python %(prog)s --token YOUR_TOKEN --marker YOUR_MARKER --test flight-search

  # Custom route
  python %(prog)s --token YOUR_TOKEN --origin MUC --dest LHR

  # Run only Data API tests
  python %(prog)s --token YOUR_TOKEN --data-only

  # Run only Flight Search API tests
  python %(prog)s --token YOUR_TOKEN --marker YOUR_MARKER --search-only
        """,
    )
    parser.add_argument(
        "--token",
        type=str,
        default=None,
        help="Travelpayouts API token (overrides .env)",
    )
    parser.add_argument(
        "--marker",
        type=str,
        default=None,
        help="Travelpayouts affiliate marker/partner ID (required for Flight Search API)",
    )
    parser.add_argument(
        "--test",
        type=str,
        default=None,
        help=f"Run a specific test. Options: {', '.join(ALL_TESTS)}",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Print raw JSON responses",
    )
    parser.add_argument(
        "--origin",
        type=str,
        default="MUC",
        help="Origin IATA code (default: MUC)",
    )
    parser.add_argument(
        "--dest",
        type=str,
        default="LHR",
        help="Destination IATA code (default: LHR)",
    )
    parser.add_argument(
        "--data-only",
        action="store_true",
        help="Run only Data API tests (no Flight Search API)",
    )
    parser.add_argument(
        "--search-only",
        action="store_true",
        help="Run only Flight Search API tests",
    )

    args = parser.parse_args()

    # Load environment
    load_env()

    # Resolve token
    global TP_TOKEN, TP_MARKER
    TP_TOKEN = (
        args.token
        or os.environ.get("SECRET__TRAVELPAYOUTS__API_TOKEN")
        or os.environ.get("TRAVELPAYOUTS_API_TOKEN")
    )
    TP_MARKER = (
        args.marker
        or os.environ.get("SECRET__TRAVELPAYOUTS__MARKER")
        or os.environ.get("TRAVELPAYOUTS_MARKER")
    )

    if not TP_TOKEN:
        print("\n  ERROR: No API token provided.")
        print("  Pass via --token flag or set SECRET__TRAVELPAYOUTS__API_TOKEN in .env")
        print("  Get your token from: https://app.travelpayouts.com/profile/api-token")
        sys.exit(1)

    # Print config
    print(f"\n  Token: {TP_TOKEN[:8]}...{TP_TOKEN[-4:]}" if len(TP_TOKEN) > 12 else f"\n  Token: {TP_TOKEN}")
    print(f"  Marker: {TP_MARKER or '(not set — Flight Search API tests will be skipped)'}")
    print(f"  Route: {args.origin} → {args.dest}")
    print(f"  Raw mode: {args.raw}")

    # Determine which tests to run
    if args.test:
        if args.test not in ALL_TESTS:
            print(f"\n  ERROR: Unknown test '{args.test}'")
            print(f"  Available: {', '.join(ALL_TESTS)}")
            sys.exit(1)
        tests_to_run = [args.test]
    elif args.data_only:
        tests_to_run = DATA_API_TESTS
    elif args.search_only:
        tests_to_run = SEARCH_API_TESTS
    else:
        # Default: run Data API tests only (Search API requires special access)
        tests_to_run = DATA_API_TESTS
        if TP_MARKER:
            print("\n  Marker provided — including Flight Search API tests.")
            tests_to_run = ALL_TESTS

    # Run tests
    results = run_tests(
        tests_to_run,
        TP_TOKEN,
        TP_MARKER,
        args.origin.upper(),
        args.dest.upper(),
        args.raw,
    )

    # Summary
    print_header("TEST SUMMARY")
    passed = sum(1 for v in results.values() if v)
    failed = sum(1 for v in results.values() if not v)
    total = len(results)

    for test_name, success in results.items():
        status = "PASS" if success else "FAIL"
        icon = "+" if success else "-"
        print(f"  [{icon}] {test_name}: {status}")

    print(f"\n  Results: {passed}/{total} passed, {failed} failed")

    if failed > 0:
        print("\n  NOTE: Some tests may fail if:")
        print("  - The API token is invalid or expired")
        print("  - The route has no cached price data (try popular routes like MUC→LHR)")
        print("  - Flight Search API access has not been approved (need to apply)")
        print("  - Rate limit exceeded (100 req/hour for Search, varies for Data API)")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
