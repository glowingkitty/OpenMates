"""Regression tests for travel app-skill constraint quality.

The tests focus on deterministic post-provider behavior and metadata contracts so
live flight/hotel provider data cannot make the quality contract flaky.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from backend.apps.travel.skills.search_connections import SearchConnectionsSkill


# contract-test: supporting surface=rest_api assertions=app-skills.history.renderable
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


# contract-test: supporting surface=rest_api assertions=app-skills.history.renderable
def test_travel_app_schema_exposes_supported_flight_constraints() -> None:
    app_yml = Path(__file__).resolve().parents[1] / "apps" / "travel" / "app.yml"
    with app_yml.open("r", encoding="utf-8") as handle:
        app_config = yaml.safe_load(handle)
    search_connections = next(skill for skill in app_config["skills"] if skill["id"] == "search_connections")
    request_item_schema = search_connections["tool_schema"]["properties"]["requests"]["items"]
    request_props = request_item_schema["properties"]

    for field in [
        "max_stops",
        "max_price",
        "include_airlines",
        "exclude_airlines",
        "owned_passes",
        "pass_only",
        "rail_products",
        "min_departure_time",
        "max_departure_time",
        "max_duration_minutes",
        "min_transfer_minutes",
        "max_layover_minutes",
        "avoid_overnight_layovers",
        "origin",
        "destination",
        "date",
        "transport_method",
    ]:
        assert field in request_props

    assert "legs" not in request_item_schema.get("required", [])
    assert "providers" not in request_props
    assert request_props["rail_products"]["items"]["enum"] == [
        "high_speed",
        "intercity",
        "regional_express",
        "regional",
        "s_bahn",
        "subway",
        "tram",
        "bus",
        "ferry",
    ]


# contract-test: supporting surface=rest_api assertions=app-skills.history.renderable
def test_search_connections_empty_group_metadata_explains_filtered_out() -> None:
    group = {"id": 1, "results": []}
    request = {"id": 1, "non_stop_only": True, "max_stops": 0, "max_price": 50}

    SearchConnectionsSkill._annotate_empty_result_group(group, request)

    assert group["no_result_reason"] == "filtered_out"
    assert "Increase the price limit" in group["suggestions"]
