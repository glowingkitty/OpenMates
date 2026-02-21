# backend/tests/test_rest_api_apps.py
#
# Integration tests for miscellaneous app skills:
#   - travel/search_connections (Amadeus flights)
#   - travel/search_stays (hotels)
#   - code/get_docs
#   - reminder/set-reminder, list-reminders, cancel-reminder (full lifecycle)
#   - openmates/share-usecase
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
