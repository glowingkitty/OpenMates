"""Regression tests for travel app-skill constraint quality.

The tests focus on deterministic post-provider behavior and metadata contracts so
live flight/hotel provider data cannot make the quality contract flaky.
"""

from __future__ import annotations

import yaml

from backend.apps.travel.skills.search_connections import SearchConnectionsSkill
from backend.apps.travel.skills.search_stays import SearchStaysSkill


def test_search_connections_filters_max_stops_and_price() -> None:
    skill = SearchConnectionsSkill(
        app=None,
        app_id="travel",
        skill_id="search_connections",
        skill_name="Search connections",
        skill_description="Search connections",
    )
    results = [
        {"origin": "Berlin", "destination": "Barcelona", "stops": 1, "total_price": "131", "duration": "5h 15m"},
        {"origin": "Berlin", "destination": "Barcelona", "stops": 0, "total_price": "164", "duration": "2h 45m"},
        {"origin": "Berlin", "destination": "Barcelona", "stops": 0, "total_price": "235", "duration": "2h 35m"},
    ]

    filtered = skill._filter_results(results, {"max_stops": 0, "max_price": 200})

    assert filtered == [{"origin": "Berlin", "destination": "Barcelona", "stops": 0, "total_price": "164", "duration": "2h 45m"}]


def test_travel_app_schema_exposes_supported_flight_constraints() -> None:
    with open("backend/apps/travel/app.yml", "r", encoding="utf-8") as handle:
        app_config = yaml.safe_load(handle)
    search_connections = next(skill for skill in app_config["skills"] if skill["id"] == "search_connections")
    request_props = search_connections["tool_schema"]["properties"]["requests"]["items"]["properties"]

    for field in [
        "max_stops",
        "max_price",
        "include_airlines",
        "exclude_airlines",
        "min_departure_time",
        "max_departure_time",
        "max_duration_minutes",
        "max_layover_minutes",
        "avoid_overnight_layovers",
    ]:
        assert field in request_props


def test_search_stays_filters_over_budget_strict_results() -> None:
    results = [
        {"name": "Budget Pool Hotel", "extracted_rate_per_night": 172, "amenities": ["Pool", "Free Wi-Fi"]},
        {"name": "Luxury Beach Hotel", "extracted_rate_per_night": 407, "amenities": ["Pools", "Beach access"]},
        {"name": "Unknown Price Hotel", "amenities": ["Pool"]},
    ]

    filtered, metadata = SearchStaysSkill._apply_quality_filters(
        results,
        max_price=180,
        query="Barcelona beach hotels with pool",
    )

    assert [result["name"] for result in filtered] == ["Budget Pool Hotel"]
    assert metadata["filtered_out_count"] == 2
    assert metadata["no_result_reason"] is None


def test_search_stays_no_result_metadata_explains_filtered_out() -> None:
    results = [
        {"name": "Luxury Beach Hotel", "extracted_rate_per_night": 407, "amenities": ["Pools", "Beach access"]},
    ]

    filtered, metadata = SearchStaysSkill._apply_quality_filters(
        results,
        max_price=180,
        query="Barcelona beach hotels with pool",
    )

    assert filtered == []
    assert metadata["no_result_reason"] == "filtered_out"
    assert metadata["suggestions"]
