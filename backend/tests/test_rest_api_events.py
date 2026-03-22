# backend/tests/test_rest_api_events.py
#
# Integration tests for the events app skills:
#   - events/search (provider=auto  — both Meetup + Luma in parallel)
#   - events/search (provider=meetup — Meetup only)
#   - events/search (provider=luma   — Luma only)
#
# Each test verifies the full response envelope, required event fields, and
# that the relevant provider(s) actually returned results.
#
# Architecture context: backend/apps/events/skills/search_skill.py
# Provider docs:        docs/apis/luma.md
#
# Execution:
#   /OpenMates/.venv/bin/python3 -m pytest -s backend/tests/test_rest_api_events.py

import time
from datetime import datetime, timedelta, timezone

import pytest

# ── Helpers ───────────────────────────────────────────────────────────────────

# Berlin is supported by both Meetup (global, lat/lon) and Luma (featured city),
# so it is the ideal city for cross-provider validation.
_BERLIN_LAT = 52.52
_BERLIN_LON = 13.405
_QUERY = "tech"  # platform-neutral; both Meetup and Luma return ~25 results
_COUNT = 10  # auto mode fetches 2x per provider; enough headroom for both to appear

# ── Rate-limit guard ──────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _inter_test_delay():
    """
    Sleep after each test to avoid hitting the dev API rate limit (30 req/min).
    A 5 s post-test pause keeps back-to-back skill calls well within the budget
    during normal usage. If the test account IP is already saturated from a prior
    session, run tests individually or wait ~60 s before starting the suite.
    """
    yield
    time.sleep(5)


def _build_payload(provider: str = "auto", count: int = _COUNT) -> dict:
    """Return a minimal-but-valid search payload for Berlin tech events."""
    # Use a 60-day window starting today so we always get real upcoming events.
    start = datetime.now(timezone.utc)
    end = start + timedelta(days=60)
    return {
        "requests": [
            {
                "query": _QUERY,
                "lat": _BERLIN_LAT,
                "lon": _BERLIN_LON,
                "location": "Berlin",
                "provider": provider,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "count": count,
            }
        ]
    }


def _assert_event_shape(event: dict, provider_label: str) -> None:
    """Assert that a single event dict contains the mandatory fields."""
    assert event.get("type") == "event_result", (
        f"[{provider_label}] Expected type 'event_result', got '{event.get('type')}'"
    )
    assert event.get("id"), f"[{provider_label}] Event missing 'id'"
    assert event.get("title"), f"[{provider_label}] Event missing 'title'"
    assert event.get("url"), f"[{provider_label}] Event missing 'url'"
    assert event.get("provider") in {"meetup", "luma"}, (
        f"[{provider_label}] Unexpected provider value: '{event.get('provider')}'"
    )
    assert event.get("date_start"), f"[{provider_label}] Event missing 'date_start'"


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_execute_skill_events_search_auto(api_client):
    """
    Test events/search with provider=auto.

    Both Meetup and Luma are queried in parallel. The merged result set must
    contain at least one event from each provider.
    """
    payload = _build_payload(provider="auto")

    print(f"\n[EVENTS AUTO] Searching: '{_QUERY}' in Berlin (provider=auto)...")
    response = api_client.post(
        "/v1/apps/events/skills/search", json=payload, timeout=60.0
    )
    assert response.status_code == 200, (
        f"events/search (auto) failed with HTTP {response.status_code}: {response.text}"
    )

    data = response.json()
    assert data["success"] is True, f"Skill returned success=False: {data}"
    assert "data" in data

    skill_data = data["data"]
    assert "results" in skill_data, "Response missing 'results'"

    results = skill_data["results"]
    assert len(results) > 0, "Expected at least one result group"

    first_group = results[0]
    assert "id" in first_group, "Result group missing 'id'"
    assert "results" in first_group, "Result group missing 'results'"

    events = first_group["results"]
    assert len(events) > 0, (
        "Expected at least one event from auto search. "
        f"Error field: {first_group.get('error')}"
    )

    # Validate shape of every returned event.
    for event in events:
        _assert_event_shape(event, provider_label="auto")

    # Both providers must appear in the merged result set.
    providers_seen = {e.get("provider") for e in events}
    print(f"[EVENTS AUTO] Providers in results: {providers_seen}")
    assert "meetup" in providers_seen, (
        f"Expected 'meetup' results in auto search, got providers: {providers_seen}"
    )
    assert "luma" in providers_seen, (
        f"Expected 'luma' results in auto search, got providers: {providers_seen}"
    )

    total_available = first_group.get("total_available", 0)
    print(
        f"[EVENTS AUTO] {len(events)} event(s) returned "
        f"(total_available={total_available})"
    )
    for i, ev in enumerate(events[:5]):
        print(
            f"  [{i + 1}] [{ev.get('provider')}] {ev.get('title')} "
            f"| {ev.get('date_start', '')[:10]}"
        )


@pytest.mark.integration
def test_execute_skill_events_search_meetup_only(api_client):
    """
    Test events/search with provider=meetup.

    All returned events must come from Meetup, identified by meetup.com URLs.
    """
    payload = _build_payload(provider="meetup")

    print(f"\n[EVENTS MEETUP] Searching: '{_QUERY}' in Berlin (provider=meetup)...")
    response = api_client.post(
        "/v1/apps/events/skills/search", json=payload, timeout=60.0
    )
    assert response.status_code == 200, (
        f"events/search (meetup) failed with HTTP {response.status_code}: {response.text}"
    )

    data = response.json()
    assert data["success"] is True, f"Skill returned success=False: {data}"

    skill_data = data["data"]
    results = skill_data["results"]
    assert len(results) > 0, "Expected at least one result group"

    first_group = results[0]
    events = first_group["results"]
    assert len(events) > 0, (
        "Expected Meetup results for Berlin tech search. "
        f"Error field: {first_group.get('error')}"
    )

    for event in events:
        _assert_event_shape(event, provider_label="meetup")
        assert event["provider"] == "meetup", (
            f"Expected provider='meetup' but got '{event['provider']}'"
        )
        assert "meetup.com" in event["url"], (
            f"Expected meetup.com URL, got: {event['url']}"
        )

    print(f"[EVENTS MEETUP] {len(events)} Meetup event(s) returned")
    for i, ev in enumerate(events[:3]):
        print(f"  [{i + 1}] {ev.get('title')} | {ev.get('date_start', '')[:10]}")


@pytest.mark.integration
def test_execute_skill_events_search_luma_only(api_client):
    """
    Test events/search with provider=luma.

    All returned events must come from Luma, identified by lu.ma URLs.
    Berlin is a Luma featured city so results are expected.
    """
    payload = _build_payload(provider="luma")

    print(f"\n[EVENTS LUMA] Searching: '{_QUERY}' in Berlin (provider=luma)...")
    response = api_client.post(
        "/v1/apps/events/skills/search", json=payload, timeout=60.0
    )
    assert response.status_code == 200, (
        f"events/search (luma) failed with HTTP {response.status_code}: {response.text}"
    )

    data = response.json()
    assert data["success"] is True, f"Skill returned success=False: {data}"

    skill_data = data["data"]
    results = skill_data["results"]
    assert len(results) > 0, "Expected at least one result group"

    first_group = results[0]
    events = first_group["results"]
    assert len(events) > 0, (
        "Expected Luma results for Berlin tech search. "
        "Berlin is a Luma featured city — if empty, check luma.py or Luma API availability. "
        f"Error field: {first_group.get('error')}"
    )

    for event in events:
        _assert_event_shape(event, provider_label="luma")
        assert event["provider"] == "luma", (
            f"Expected provider='luma' but got '{event['provider']}'"
        )
        assert "lu.ma" in event["url"], (
            f"Expected lu.ma URL, got: {event['url']}"
        )

    print(f"[EVENTS LUMA] {len(events)} Luma event(s) returned")
    for i, ev in enumerate(events[:3]):
        print(f"  [{i + 1}] {ev.get('title')} | {ev.get('date_start', '')[:10]}")
