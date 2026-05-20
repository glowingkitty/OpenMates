# backend/tests/test_travel_search_connections.py
#
# Unit tests for the travel search_connections skill limits and filters.
# These tests use a fake transport provider so they do not spend provider
# credits or depend on live flight/train APIs. They validate the skill-layer
# contract that all transport providers share.

from __future__ import annotations

import sys
import types
from typing import Any, List, Optional

import pytest
from backend.apps.travel.providers.base_provider import (
    BaseTransportProvider,
    ConnectionResult,
    LayoverResult,
    LegResult,
    SegmentResult,
)

airports_module = types.ModuleType("airports")
airports_module.airport_data = types.SimpleNamespace(get_airport_by_iata=lambda _iata: [])
sys.modules.setdefault("airports", airports_module)


def make_skill() -> Any:
    from backend.apps.travel.skills.search_connections import SearchConnectionsSkill

    return SearchConnectionsSkill(
        app=None,
        app_id="travel",
        skill_id="search_connections",
        skill_name="Search Connections",
        skill_description="Search transport connections",
    )


class FakeTransportProvider(BaseTransportProvider):
    def __init__(
        self,
        results: List[ConnectionResult],
        provider_id: str = "google_flights",
        supported_methods: Optional[set[str]] = None,
        supported_countries: Optional[set[str]] = None,
    ) -> None:
        self.results = results
        self.provider_id = provider_id
        self.supported_methods = supported_methods or {"airplane"}
        self.supported_countries = supported_countries
        self.requested_max_results: Optional[int] = None
        self.calls = 0

    def supports_transport_method(self, method: str) -> bool:
        return method in self.supported_methods

    async def search_connections(
        self,
        legs: List[dict],
        passengers: int,
        travel_class: str,
        max_results: int,
        non_stop_only: bool,
        currency: str,
        children: int = 0,
        infants_in_seat: int = 0,
        infants_on_lap: int = 0,
        max_stops: Optional[int] = None,
        include_airlines: Optional[List[str]] = None,
        exclude_airlines: Optional[List[str]] = None,
    ) -> List[ConnectionResult]:
        self.calls += 1
        self.requested_max_results = max_results
        return self.results[:max_results]


def make_connection(
    index: int,
    departure: str,
    arrival: str,
    duration: str = "2h 0m",
    layover_minutes: Optional[int] = None,
    overnight: bool = False,
) -> ConnectionResult:
    layovers = None
    if layover_minutes is not None:
        layovers = [
            LayoverResult(
                airport="Test Hub",
                duration=f"{layover_minutes}m",
                duration_minutes=layover_minutes,
                overnight=overnight,
            )
        ]

    leg = LegResult(
        leg_index=0,
        origin="Munich (MUC)",
        destination="London (LHR)",
        departure=departure,
        arrival=arrival,
        duration=duration,
        stops=1 if layovers else 0,
        layovers=layovers,
        segments=[
            SegmentResult(
                carrier="Test Air",
                carrier_code="TA",
                number=f"TA {index}",
                departure_station="MUC",
                departure_time=departure,
                arrival_station="LHR",
                arrival_time=arrival,
                duration=duration,
            )
        ],
    )
    return ConnectionResult(
        transport_method="airplane",
        source_provider="google_flights",
        total_price=str(100 + index),
        currency="EUR",
        legs=[leg],
    )


def make_result_dict(connection: ConnectionResult) -> dict[str, Any]:
    result = connection.model_dump()
    leg = connection.legs[0]
    result.update({
        "departure": leg.departure,
        "arrival": leg.arrival,
        "duration": leg.duration,
        "stops": leg.stops,
    })
    return result


@pytest.fixture(autouse=True)
def bypass_external_sanitizer(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.apps.travel.skills import search_connections as search_module

    async def passthrough(payload: Any, **kwargs: Any) -> Any:
        return payload

    monkeypatch.setattr(search_module, "sanitize_long_text_fields_in_payload", passthrough)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_search_connections_defaults_to_twenty_results() -> None:
    provider = FakeTransportProvider([
        make_connection(i, f"2026-06-01 {i % 24:02d}:00", f"2026-06-01 {(i + 2) % 24:02d}:00")
        for i in range(30)
    ])

    request_id, results, error = await make_skill()._process_single_request(
        {
            "legs": [{"origin": "Munich", "destination": "London", "date": "2026-06-01"}],
            "transport_methods": ["airplane"],
        },
        request_id="default-limit",
        all_providers=[provider],
    )

    assert request_id == "default-limit"
    assert error is None
    assert provider.requested_max_results == 20
    assert len(results) == 20


@pytest.mark.anyio
async def test_search_connections_clamps_requested_results_to_fifty() -> None:
    provider = FakeTransportProvider([
        make_connection(i, f"2026-06-01 {i % 24:02d}:00", f"2026-06-01 {(i + 2) % 24:02d}:00")
        for i in range(60)
    ])

    _, results, error = await make_skill()._process_single_request(
        {
            "legs": [{"origin": "Munich", "destination": "London", "date": "2026-06-01"}],
            "transport_methods": ["airplane"],
            "max_results": 200,
        },
        request_id="clamped-limit",
        all_providers=[provider],
    )

    assert error is None
    assert provider.requested_max_results == 50
    assert len(results) == 50


@pytest.mark.anyio
async def test_search_connections_overfetches_and_filters_before_final_cap() -> None:
    provider = FakeTransportProvider([
        make_connection(0, "2026-06-01 06:00", "2026-06-01 08:00"),
        make_connection(1, "2026-06-01 09:00", "2026-06-01 11:00"),
        make_connection(2, "2026-06-01 10:00", "2026-06-01 12:00"),
        make_connection(3, "2026-06-01 11:00", "2026-06-01 13:00"),
        make_connection(4, "2026-06-01 15:00", "2026-06-01 17:00"),
        make_connection(5, "2026-06-01 16:00", "2026-06-01 18:00"),
    ])

    _, results, error = await make_skill()._process_single_request(
        {
            "legs": [{"origin": "Munich", "destination": "London", "date": "2026-06-01"}],
            "transport_methods": ["airplane"],
            "max_results": 2,
            "min_departure_time": "09:00",
            "max_departure_time": "12:00",
            "sort_by": "departure_asc",
        },
        request_id="filtered-limit",
        all_providers=[provider],
    )

    assert error is None
    assert provider.requested_max_results == 6
    assert [result["departure"] for result in results] == [
        "2026-06-01 09:00",
        "2026-06-01 10:00",
    ]


@pytest.mark.anyio
async def test_execute_preserves_empty_search_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.apps.travel.skills import search_connections as search_module

    provider = FakeTransportProvider(
        [], provider_id="deutsche_bahn", supported_methods={"train"}, supported_countries={"DE"}
    )
    monkeypatch.setattr(search_module, "_create_providers", lambda secrets_manager=None: [provider])

    response = await make_skill().execute(
        requests=[{
            "legs": [{"origin": "Berlin", "destination": "Bad Schandau", "date": "2026-06-01"}],
            "transport_methods": ["train"],
            "countries": ["DE"],
        }],
        secrets_manager=object(),
    )

    assert response.error is None
    assert response.provider == "Deutsche Bahn"
    assert response.providers == [{
        "id": "deutsche_bahn",
        "name": "Deutsche Bahn",
        "icon_url": "https://www.bahn.de/favicon.ico",
    }]
    assert response.results[0]["query"] == "Berlin → Bad Schandau, 2026-06-01"
    assert response.results[0]["result_count"] == 0
    assert response.results[0]["transport_methods"] == ["train"]
    assert response.results[0]["providers"] == response.providers


def test_search_connections_response_has_no_fake_provider_default() -> None:
    from backend.apps.travel.skills.search_connections import SearchConnectionsResponse

    assert SearchConnectionsResponse().provider == ""


@pytest.mark.anyio
async def test_deutsche_bahn_location_resolution_retries_station_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.shared.providers import deutsche_bahn

    calls: list[str] = []

    async def fake_search_locations(query: str, max_results: int = 5) -> list[dict[str, Any]]:
        calls.append(query)
        if query == "Bad Schandau Bahnhof":
            return [{
                "locationId": "A=1@O=Bad Schandau Nationalparkbahnhof@L=8010053@",
                "name": "Bad Schandau Nationalparkbahnhof",
                "evaNr": "8010053",
                "coordinates": {},
            }]
        return []

    deutsche_bahn._location_cache.clear()
    monkeypatch.setattr(deutsche_bahn, "search_locations", fake_search_locations)

    assert await deutsche_bahn.resolve_location_id("Bad Schandau") == "A=1@O=Bad Schandau Nationalparkbahnhof@L=8010053@"
    assert calls[:2] == ["Bad Schandau", "Bad Schandau Bahnhof"]


def test_search_connections_filters_duration_and_layovers() -> None:
    skill = make_skill()
    results = [
        skill._filter_results([
            make_result_dict(make_connection(0, "2026-06-01 09:00", "2026-06-01 11:00", duration="2h 0m")),
            make_result_dict(make_connection(1, "2026-06-01 09:00", "2026-06-01 15:00", duration="6h 0m")),
        ], {"max_duration_minutes": 180}),
        skill._filter_results([
            make_result_dict(make_connection(2, "2026-06-01 09:00", "2026-06-01 13:00", layover_minutes=45)),
            make_result_dict(make_connection(3, "2026-06-01 09:00", "2026-06-01 14:00", layover_minutes=180)),
            make_result_dict(make_connection(4, "2026-06-01 22:00", "2026-06-02 08:00", layover_minutes=120, overnight=True)),
        ], {"max_layover_minutes": 90, "avoid_overnight_layovers": True}),
    ]

    assert [result["total_price"] for result in results[0]] == ["100"]
    assert [result["total_price"] for result in results[1]] == ["102"]


def test_search_connections_provider_matching_uses_all_transport_providers_by_default() -> None:
    from backend.apps.travel.skills.search_connections import _get_providers_for_request

    db = FakeTransportProvider(
        [], provider_id="deutsche_bahn", supported_methods={"train"}, supported_countries={"DE"}
    )
    flix = FakeTransportProvider(
        [], provider_id="flix", supported_methods={"train"}, supported_countries={"DE"}
    )
    flights = FakeTransportProvider(
        [], provider_id="google_flights", supported_methods={"airplane"}, supported_countries=None
    )

    matched = _get_providers_for_request([db, flix, flights], ["train"])

    assert [provider.provider_id for provider in matched] == ["deutsche_bahn", "flix"]


def test_search_connections_provider_matching_respects_explicit_provider() -> None:
    from backend.apps.travel.skills.search_connections import _get_providers_for_request

    db = FakeTransportProvider(
        [], provider_id="deutsche_bahn", supported_methods={"train"}, supported_countries={"DE"}
    )
    flix = FakeTransportProvider(
        [], provider_id="flix", supported_methods={"train"}, supported_countries={"DE"}
    )

    matched = _get_providers_for_request([db, flix], ["train"], requested_providers=["deutsche_bahn"])

    assert [provider.provider_id for provider in matched] == ["deutsche_bahn"]


def test_search_connections_provider_country_matching_uses_or_semantics() -> None:
    from backend.apps.travel.skills.search_connections import _get_providers_for_request

    db = FakeTransportProvider(
        [], provider_id="deutsche_bahn", supported_methods={"train"}, supported_countries={"DE"}
    )
    other_train = FakeTransportProvider(
        [], provider_id="flix", supported_methods={"train"}, supported_countries={"FR"}
    )
    flights = FakeTransportProvider(
        [], provider_id="google_flights", supported_methods={"airplane"}, supported_countries=None
    )

    matched = _get_providers_for_request([db, other_train, flights], ["train"], countries=["FR", "PT"])

    assert [provider.provider_id for provider in matched] == ["flix"]


def test_search_connections_country_matching_keeps_global_providers() -> None:
    from backend.apps.travel.skills.search_connections import _get_providers_for_request

    flights = FakeTransportProvider(
        [], provider_id="google_flights", supported_methods={"airplane"}, supported_countries=None
    )

    matched = _get_providers_for_request([flights], ["airplane"], countries=["FR", "PT"])

    assert [provider.provider_id for provider in matched] == ["google_flights"]


def test_train_provider_country_metadata_includes_cross_border_routes() -> None:
    from backend.apps.travel.providers.db_provider import DeutscheBahnProvider
    from backend.apps.travel.providers.flix_provider import FlixProvider

    assert DeutscheBahnProvider.supported_countries >= {"AT", "BE", "CH", "CZ", "DE", "FR", "NL"}
    assert FlixProvider(supported_methods={"train"}).supported_countries == {"AT", "CH", "DE", "NL"}
