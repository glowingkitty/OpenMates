# backend/tests/test_rest_api_apps.py
#
# Integration tests for miscellaneous app skills:
#   - travel/search_connections (Amadeus flights)
#   - travel/search_stays (hotels)
#   - travel/get_flight (Flightradar24 — known past flight)
##   - code/get_docs
#   - math/calculate (sympy/mpmath symbolic + numeric)
#   - shopping/search_products (REWE supermarket)
#   - health/search_appointments (Doctolib Germany)
#   - reminder/set-reminder, list-reminders, cancel-reminder (full lifecycle)
#   - openmates/share-usecase
#
# Skills NOT tested here (require session/encryption → CLI E2E tests):
#   - audio/transcribe       → planned: cli-skills-audio.spec.ts
#   - pdf/read, search, view → cli-skills-pdf.spec.ts
#   - mail/search            → planned CLI test (needs Proton Bridge)
#   - images/*               → cli-images.spec.ts (REST returns 404 by design)
#
# Execution:
#   /OpenMates/.venv/bin/python3 -m pytest -s backend/tests/test_rest_api_apps.py

from datetime import datetime, timedelta, timezone

import pytest


@pytest.mark.integration
def test_execute_skill_travel_search_connections(api_client):
    """
    Test executing the 'travel/search_connections' skill.
    Searches for a one-way flight from Munich to London via the Amadeus API.
    """
    departure_date = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")

    payload = {
        "requests": [
            {
                "legs": [
                    {
                        "origin": "Munich",
                        "destination": "London",
                        "date": departure_date,
                    }
                ],
                "transport_methods": ["airplane"],
                "passengers": 1,
                "travel_class": "economy",
                "max_results": 3,
                "currency": "EUR",
            }
        ]
    }

    print(
        f"\n[TRAVEL] Searching flights: Munich -> London on {departure_date}"
    )
    response = api_client.post(
        "/v1/apps/travel/skills/search_connections",
        json=payload,
        timeout=30.0,
    )
    assert response.status_code == 200, (
        f"Travel search_connections failed: {response.text}"
    )

    data = response.json()
    assert data["success"] is True, f"Skill returned success=False: {data}"
    assert "data" in data
    skill_data = data["data"]
    assert "results" in skill_data

    results = skill_data["results"]
    assert len(results) > 0, "Expected at least one result group"

    first_group = results[0]
    assert "id" in first_group, "Result group should have 'id'"
    assert "results" in first_group, "Result group should have 'results'"

    connections = first_group["results"]
    assert len(connections) > 0, "Expected at least one flight connection"

    conn = connections[0]
    assert conn["type"] == "connection", (
        f"Expected type 'connection', got '{conn.get('type')}'"
    )
    assert conn["transport_method"] == "airplane"
    assert conn.get("total_price") is not None, "Expected a price"
    assert conn.get("currency") is not None, "Expected a currency"
    assert conn.get("legs") is not None, "Expected legs array"
    assert len(conn["legs"]) >= 1, "Expected at least one leg"

    leg = conn["legs"][0]
    assert "origin" in leg, "Leg should have 'origin'"
    assert "destination" in leg, "Leg should have 'destination'"
    assert "departure" in leg, "Leg should have 'departure'"
    assert "arrival" in leg, "Leg should have 'arrival'"
    assert "duration" in leg, "Leg should have 'duration'"
    assert "stops" in leg, "Leg should have 'stops'"
    assert "segments" in leg, "Leg should have 'segments'"

    assert len(leg["segments"]) >= 1, "Expected at least one segment"
    segment = leg["segments"][0]
    assert "carrier" in segment, "Segment should have 'carrier'"
    assert "departure_station" in segment, (
        "Segment should have 'departure_station'"
    )
    assert "arrival_station" in segment, (
        "Segment should have 'arrival_station'"
    )

    print(f"[TRAVEL] Found {len(connections)} connection(s)")
    for i, c in enumerate(connections[:3]):
        legs_info = c.get("legs", [])
        if legs_info:
            first = legs_info[0]
            print(
                f"  [{i + 1}] {first.get('origin')} -> "
                f"{first.get('destination')} | "
                f"{first.get('duration')} | {first.get('stops')} stop(s) | "
                f"{c.get('total_price')} {c.get('currency')}"
            )

    assert skill_data.get("provider") == "Amadeus", (
        f"Expected provider 'Amadeus', got '{skill_data.get('provider')}'"
    )


@pytest.mark.integration
def test_execute_skill_travel_search_stays(api_client):
    """
    Test executing the 'travel/search_stays' skill.
    Searches for hotels in Paris for a future date.
    """
    check_in = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    check_out = (datetime.now() + timedelta(days=33)).strftime("%Y-%m-%d")

    payload = {
        "requests": [
            {
                "query": "Hotels in Paris near Eiffel Tower",
                "check_in_date": check_in,
                "check_out_date": check_out,
                "adults": 2,
                "currency": "EUR",
                "max_results": 3,
            }
        ]
    }

    print(
        f"\n[TRAVEL STAYS] Searching hotels in Paris: {check_in} to {check_out}"
    )
    response = api_client.post(
        "/v1/apps/travel/skills/search_stays", json=payload, timeout=30.0
    )
    assert response.status_code == 200, (
        f"travel/search_stays failed: {response.text}"
    )

    data = response.json()
    assert data["success"] is True, f"Skill returned success=False: {data}"
    assert "data" in data
    skill_data = data["data"]
    assert "results" in skill_data

    results = skill_data["results"]
    assert len(results) > 0, "Expected at least one result group"

    first_group = results[0]
    assert "results" in first_group, "Result group should have 'results'"

    stays = first_group["results"]
    assert len(stays) > 0, "Expected at least one stay result"

    stay = stays[0]
    assert stay.get("name"), "Stay should have a 'name'"

    print(f"[TRAVEL STAYS] Found {len(stays)} stay(s)")
    print(f"[TRAVEL STAYS] First result: {stay.get('name')}")


@pytest.mark.integration
def test_execute_skill_code_get_docs(api_client):
    """
    Test executing the 'code/get_docs' skill.
    Fetches documentation for the FastAPI library.
    """
    payload = {
        "library": "FastAPI",
        "question": "How to create a simple GET endpoint?",
    }

    print("\n[CODE DOCS] Fetching FastAPI documentation...")
    response = api_client.post(
        "/v1/apps/code/skills/get_docs", json=payload, timeout=30.0
    )
    assert response.status_code == 200, (
        f"code/get_docs failed: {response.text}"
    )

    data = response.json()
    assert data["success"] is True, f"Skill returned success=False: {data}"
    assert "data" in data
    skill_data = data["data"]

    assert "documentation" in skill_data, (
        f"Response missing 'documentation'. Keys: {list(skill_data.keys())}"
    )
    documentation = skill_data.get("documentation") or ""
    assert len(documentation) > 50, (
        f"Documentation too short: {len(documentation)} chars"
    )

    print(f"[CODE DOCS] Documentation length: {len(documentation)} chars")
    print(f"[CODE DOCS] Preview: {documentation[:200]}")


@pytest.mark.integration
def test_execute_skill_reminder_lifecycle(api_client):
    """
    Test the full reminder lifecycle: set -> list -> cancel.
    Exercises the 'reminder/set-reminder', 'reminder/list-reminders', and
    'reminder/cancel-reminder' skills in sequence.
    """
    trigger_dt = (
        datetime.now(timezone.utc) + timedelta(hours=1)
    ).strftime("%Y-%m-%dT%H:%M:%S")

    set_payload = {
        "prompt": "Test reminder from automated test suite - please ignore",
        "trigger_type": "specific",
        "timezone": "UTC",
        "trigger_datetime": trigger_dt,
        "target_type": "new_chat",
        "new_chat_title": "Test Reminder Chat",
    }

    # --- 1. Set reminder ---
    print(f"\n[REMINDER] Setting reminder for {trigger_dt} UTC...")
    set_resp = api_client.post(
        "/v1/apps/reminder/skills/set-reminder",
        json=set_payload,
        timeout=20.0,
    )
    assert set_resp.status_code == 200, (
        f"set-reminder failed: {set_resp.text}"
    )

    set_data = set_resp.json()
    assert set_data["success"] is True, (
        f"set-reminder success=False: {set_data}"
    )
    assert "data" in set_data
    reminder_result = set_data["data"]
    assert reminder_result.get("success") is True, (
        f"Inner success=False: {reminder_result}"
    )
    assert reminder_result.get("reminder_id"), (
        "Expected a reminder_id in response"
    )

    reminder_id = reminder_result["reminder_id"]
    print(f"[REMINDER] Created reminder ID: {reminder_id}")

    # --- 2. List reminders ---
    print("[REMINDER] Listing pending reminders...")
    list_payload = {"status": "pending"}
    list_resp = api_client.post(
        "/v1/apps/reminder/skills/list-reminders",
        json=list_payload,
        timeout=15.0,
    )
    assert list_resp.status_code == 200, (
        f"list-reminders failed: {list_resp.text}"
    )

    list_data = list_resp.json()
    assert list_data["success"] is True, (
        f"list-reminders success=False: {list_data}"
    )
    assert "data" in list_data
    list_result = list_data["data"]
    assert list_result.get("success") is True, (
        f"Inner list success=False: {list_result}"
    )

    reminders = list_result.get("reminders", [])
    reminder_ids = [r.get("reminder_id") for r in reminders]
    assert reminder_id in reminder_ids, (
        f"Newly created reminder {reminder_id} not found in list. "
        f"Found: {reminder_ids}"
    )
    print(
        f"[REMINDER] Found {len(reminders)} pending reminder(s), "
        f"our reminder is listed"
    )

    # --- 3. Cancel reminder ---
    print(f"[REMINDER] Cancelling reminder {reminder_id}...")
    cancel_payload = {"reminder_id": reminder_id}
    cancel_resp = api_client.post(
        "/v1/apps/reminder/skills/cancel-reminder",
        json=cancel_payload,
        timeout=15.0,
    )
    assert cancel_resp.status_code == 200, (
        f"cancel-reminder failed: {cancel_resp.text}"
    )

    cancel_data = cancel_resp.json()
    assert cancel_data["success"] is True, (
        f"cancel-reminder success=False: {cancel_data}"
    )
    assert "data" in cancel_data
    cancel_result = cancel_data["data"]
    assert cancel_result.get("success") is True, (
        f"Inner cancel success=False: {cancel_result}"
    )

    print(
        "[REMINDER] Lifecycle test PASSED - set/list/cancel all successful!"
    )


@pytest.mark.integration
def test_execute_skill_openmates_share_usecase(api_client):
    """
    Test executing the 'openmates/share-usecase' skill.
    Submits an anonymous use-case summary and validates the response.
    """
    payload = {
        "summary": (
            "This is an automated test submission from the integration test "
            "suite. The user wants to use OpenMates to search the web and "
            "summarize results."
        ),
        "language": "en",
    }

    print("\n[SHARE USECASE] Submitting anonymous use-case summary...")
    response = api_client.post(
        "/v1/apps/openmates/skills/share-usecase",
        json=payload,
        timeout=20.0,
    )
    assert response.status_code == 200, (
        f"openmates/share-usecase failed: {response.text}"
    )

    data = response.json()
    assert data["success"] is True, f"Skill returned success=False: {data}"
    assert "data" in data
    skill_data = data["data"]

    assert skill_data.get("success") is True, (
        f"Inner success=False: {skill_data}"
    )
    assert not skill_data.get("error"), (
        f"Unexpected error: {skill_data.get('error')}"
    )

    print(f"[SHARE USECASE] Response: {skill_data.get('message', 'OK')}")
    print("[SHARE USECASE] PASSED")


@pytest.mark.integration
def test_execute_skill_math_calculate_numeric(api_client):
    """
    Test executing the 'math/calculate' skill with a simple numeric expression.
    Uses sympy/mpmath for accurate symbolic and numeric computation.
    """
    payload = {
        "expression": "sqrt(2)",
        "mode": "numeric",
        "precision": 10,
    }

    print("\n[MATH] Evaluating sqrt(2) numerically...")
    response = api_client.post(
        "/v1/apps/math/skills/calculate",
        json=payload,
        timeout=20.0,
    )
    assert response.status_code == 200, f"math/calculate failed: {response.text}"

    data = response.json()
    assert data["success"] is True, f"Skill returned success=False: {data}"
    assert "data" in data
    skill_data = data["data"]

    # math/calculate returns a flat CalculateResponse (not requests array pattern)
    assert skill_data.get("result"), f"Expected 'result' field: {skill_data}"
    assert skill_data.get("mode"), f"Expected 'mode' field: {skill_data}"

    # sqrt(2) ≈ 1.41421356...
    result_str = str(skill_data.get("result", ""))
    assert "1.4142" in result_str, (
        f"Expected sqrt(2) ≈ 1.4142..., got: {result_str}"
    )

    print(f"[MATH] sqrt(2) = {skill_data.get('result')} (mode={skill_data.get('mode')})")
    print("[MATH] PASSED")


@pytest.mark.integration
def test_execute_skill_math_calculate_symbolic(api_client):
    """
    Test the 'math/calculate' skill with symbolic differentiation.
    Verifies sympy symbolic mode returns LaTeX output.
    """
    payload = {
        "expression": "diff(sin(x)*x, x)",
        "mode": "diff",
        "variable": "x",
    }

    print("\n[MATH] Differentiating sin(x)*x symbolically...")
    response = api_client.post(
        "/v1/apps/math/skills/calculate",
        json=payload,
        timeout=20.0,
    )
    assert response.status_code == 200, f"math/calculate symbolic failed: {response.text}"

    data = response.json()
    assert data["success"] is True, f"success=False: {data}"
    skill_data = data["data"]

    # math/calculate returns a flat CalculateResponse (not requests array pattern)
    assert skill_data.get("result"), f"Expected 'result' field: {skill_data}"

    # d/dx[sin(x)*x] = sin(x) + x*cos(x)
    result_str = str(skill_data.get("result", "")).lower()
    assert "sin" in result_str or "cos" in result_str, (
        f"Expected symbolic result with trig functions, got: {result_str}"
    )

    print(f"[MATH] diff(sin(x)*x, x) = {skill_data.get('result')}")
    print("[MATH SYMBOLIC] PASSED")


@pytest.mark.integration
def test_execute_skill_shopping_search_products(api_client):
    """
    Test executing the 'shopping/search_products' skill with a REWE supermarket search.
    Searches for a common grocery item and verifies product list structure.
    """
    payload = {
        "requests": [
            {
                "query": "bio joghurt",
                "provider": "REWE",
                "max_results": 5,
            }
        ]
    }

    print("\n[SHOPPING] Searching REWE for 'bio joghurt'...")
    response = api_client.post(
        "/v1/apps/shopping/skills/search_products",
        json=payload,
        timeout=30.0,
    )
    assert response.status_code == 200, (
        f"shopping/search_products failed: {response.text}"
    )

    data = response.json()
    assert data["success"] is True, f"success=False: {data}"
    assert "data" in data
    skill_data = data["data"]
    assert "results" in skill_data, f"Missing 'results': {skill_data}"

    result_groups = skill_data["results"]
    assert len(result_groups) > 0, "Expected at least one result group"

    products = result_groups[0].get("results", [])
    assert len(products) > 0, "Expected at least one product"

    product = products[0]
    # Shopping products use 'title' (REWE) not 'name'
    assert product.get("title") or product.get("name"), (
        f"Product missing 'title' or 'name': {list(product.keys())}"
    )

    print(f"[SHOPPING] Found {len(products)} product(s)")
    print(f"[SHOPPING] First: {product.get('title') or product.get('name')} — {product.get('price_eur')}")
    print("[SHOPPING] PASSED")


@pytest.mark.integration
def test_execute_skill_health_search_appointments(api_client):
    """
    Test executing the 'health/search_appointments' skill via Doctolib Germany.
    Searches for general practitioners in Berlin and verifies the response structure.
    """
    payload = {
        "requests": [
            {
                "speciality": "allgemeinmedizin",
                "city": "Berlin",
                "provider_platform": "doctolib_de",
                "insurance_sector": "public",
            }
        ]
    }

    print("\n[HEALTH] Searching Doctolib Germany for GPs in Berlin...")
    response = api_client.post(
        "/v1/apps/health/skills/search_appointments",
        json=payload,
        timeout=45.0,
    )
    assert response.status_code == 200, (
        f"health/search_appointments failed: {response.text}"
    )

    data = response.json()
    assert data["success"] is True, f"success=False: {data}"
    assert "data" in data
    skill_data = data["data"]
    assert "results" in skill_data, f"Missing 'results': {skill_data}"

    result_groups = skill_data["results"]
    assert len(result_groups) > 0, "Expected at least one result group"

    doctors = result_groups[0].get("results", [])
    assert len(doctors) > 0, "Expected at least one doctor"

    doctor = doctors[0]
    assert doctor.get("name"), f"Doctor missing 'name': {doctor}"
    # practice_url is the canonical field per the skill docs (see skill header comment)
    assert doctor.get("practice_url") or doctor.get("url"), (
        f"Doctor missing 'practice_url' or 'url': {doctor}"
    )

    print(f"[HEALTH] Found {len(doctors)} doctor(s)")
    print(f"[HEALTH] First: {doctor.get('name')} — {doctor.get('practice_url')}")
    print("[HEALTH] PASSED")


@pytest.mark.integration
def test_execute_skill_travel_get_flight(api_client):
    """
    Test executing the 'travel/get_flight' skill via Flightradar24.
    Uses a known Lufthansa flight from the past to verify track data is returned.
    Flight LH400 (FRA→JFK) is a daily long-haul route with reliable historical data.
    """
    # Use a recent past date (7 days ago) to ensure the flight has completed
    flight_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    payload = {
        "flight_number": "LH400",
        "departure_date": flight_date,
    }

    print(f"\n[FLIGHT] Fetching LH400 on {flight_date}...")
    response = api_client.post(
        "/v1/apps/travel/skills/get_flight",
        json=payload,
        timeout=30.0,
    )
    assert response.status_code == 200, (
        f"travel/get_flight failed: {response.text}"
    )

    data = response.json()
    assert data["success"] is True, f"success=False: {data}"
    assert "data" in data
    skill_data = data["data"]

    # The skill returns success=True/False inside the data payload
    assert skill_data.get("success") is True, (
        f"Flight data fetch failed: {skill_data.get('error', 'no error detail')}"
    )
    assert skill_data.get("flight_number"), "Missing 'flight_number'"
    assert skill_data.get("data_source") == "flightradar24", (
        f"Expected data_source=flightradar24, got: {skill_data.get('data_source')}"
    )

    tracks = skill_data.get("tracks", [])
    assert len(tracks) > 10, (
        f"Expected GPS track points (>10), got {len(tracks)}"
    )

    # Verify track point structure
    point = tracks[0]
    assert "lat" in point, "Track point missing 'lat'"
    assert "lon" in point, "Track point missing 'lon'"
    assert "timestamp" in point, "Track point missing 'timestamp'"

    print(f"[FLIGHT] {skill_data.get('flight_number')}: "
          f"{len(tracks)} track points, "
          f"takeoff={skill_data.get('actual_takeoff')}, "
          f"landing={skill_data.get('actual_landing')}")
    print("[FLIGHT] PASSED")
