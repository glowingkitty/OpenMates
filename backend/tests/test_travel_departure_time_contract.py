"""
Contract tests for travel connection departure-time propagation.

These tests prevent time-window searches from fetching an unrelated fixed
morning window before post-filtering. They cover the skill-to-provider leg
contract and the Deutsche Bahn provider-to-Navigator request contract.
"""

from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional

import pytest

from backend.apps.travel.providers.base_provider import BaseTransportProvider, ConnectionResult


airports_module = types.ModuleType("airports")
airports_module.airport_data = types.SimpleNamespace(get_airport_by_iata=lambda _iata: [])
sys.modules.setdefault("airports", airports_module)


class CapturingTransportProvider(BaseTransportProvider):
    provider_id = "deutsche_bahn"
    supported_countries = {"DE"}

    def __init__(self) -> None:
        self.requested_legs: Optional[List[dict]] = None

    def supports_transport_method(self, method: str) -> bool:
        return method == "train"

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
        owned_passes: Optional[List[str]] = None,
        pass_only: bool = False,
        rail_products: Optional[List[str]] = None,
        min_transfer_minutes: Optional[int] = None,
        cache_service: Any = None,
    ) -> List[ConnectionResult]:
        self.requested_legs = legs
        return []


def make_skill() -> Any:
    from backend.apps.travel.skills.search_connections import SearchConnectionsSkill

    return SearchConnectionsSkill(
        app=None,
        app_id="travel",
        skill_id="search_connections",
        skill_name="Search Connections",
        skill_description="Search transport connections",
    )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


# contract-test: direct surface=rest_api assertions=travel-search.departure-window.upstream
@pytest.mark.anyio
async def test_search_skill_forwards_minimum_departure_time_on_outbound_leg() -> None:
    provider = CapturingTransportProvider()

    _, _, error = await make_skill()._process_single_request(
        {
            "legs": [{"origin": "Rostock Hbf", "destination": "Berlin Südkreuz", "date": "2026-08-14"}],
            "transport_methods": ["train"],
            "providers": ["deutsche_bahn"],
            "min_departure_time": "16:20",
            "max_departure_time": "16:45",
        },
        request_id="afternoon-db-train",
        all_providers=[provider],
    )

    assert error is None
    assert provider.requested_legs == [
        {
            "origin": "Rostock Hbf",
            "destination": "Berlin Südkreuz",
            "date": "2026-08-14",
            "departure_time": "16:20",
            "max_departure_time": "16:45",
        }
    ]


# contract-test: supporting surface=rest_api assertions=travel-search.departure-window.upstream
@pytest.mark.anyio
async def test_search_skill_only_applies_outbound_window_to_first_leg() -> None:
    provider = CapturingTransportProvider()

    original_legs = [
        {"origin": "Berlin Hbf", "destination": "Hamburg Hbf", "date": "2026-08-14"},
        {"origin": "Hamburg Hbf", "destination": "Berlin Hbf", "date": "2026-08-16"},
    ]
    _, _, error = await make_skill()._process_single_request(
        {
            "legs": original_legs,
            "transport_methods": ["train"],
            "providers": ["deutsche_bahn"],
            "min_departure_time": "16:20",
        },
        request_id="multi-leg-afternoon",
        all_providers=[provider],
    )

    assert error is None
    assert provider.requested_legs == [
        {**original_legs[0], "departure_time": "16:20"},
        original_legs[1],
    ]
    assert "departure_time" not in original_legs[0]


# contract-test: supporting surface=rest_api assertions=travel-search.departure-window.filtered,travel-search.no-results.explicit
@pytest.mark.anyio
async def test_search_skill_fetches_from_midnight_for_maximum_only_window() -> None:
    provider = CapturingTransportProvider()

    _, _, error = await make_skill()._process_single_request(
        {
            "legs": [{"origin": "Berlin Hbf", "destination": "Hamburg Hbf", "date": "2026-08-14"}],
            "transport_methods": ["train"],
            "providers": ["deutsche_bahn"],
            "max_departure_time": "06:00",
        },
        request_id="early-db-train",
        all_providers=[provider],
    )

    assert error is None
    assert provider.requested_legs is not None
    assert provider.requested_legs[0]["departure_time"] == "00:00"
    assert provider.requested_legs[0]["max_departure_time"] == "06:00"


# contract-test: direct surface=rest_api assertions=travel-search.departure-window.upstream
@pytest.mark.anyio
async def test_deutsche_bahn_provider_forwards_leg_departure_time_to_navigator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.apps.travel.providers import db_provider

    calls: list[dict[str, Any]] = []

    async def fake_resolve_location_id(city_name: str) -> str:
        return f"A=1@O={city_name}@L=8000001@"

    async def fake_search_journeys(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"verbindungen": []}

    monkeypatch.setattr(db_provider, "resolve_location_id", fake_resolve_location_id)
    monkeypatch.setattr(db_provider, "search_journeys", fake_search_journeys)

    await db_provider.DeutscheBahnProvider().search_connections(
        legs=[{
            "origin": "Rostock Hbf",
            "destination": "Berlin Südkreuz",
            "date": "2026-08-14",
            "departure_time": "16:20",
        }],
        passengers=1,
        travel_class="economy",
        max_results=6,
        non_stop_only=False,
        currency="EUR",
    )

    assert calls[0]["time"] == "16:20:00"


# contract-test: direct surface=rest_api assertions=travel-search.departure-window.upstream
@pytest.mark.anyio
async def test_transitous_provider_converts_local_departure_time_for_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.apps.travel.providers.transitous_provider import TransitousProvider

    plan_calls: list[dict[str, Any]] = []

    async def fake_geocode(self: TransitousProvider, query: str, *, mode: Optional[str] = None) -> dict[str, Any]:
        return {
            "name": query,
            "lat": 52.525,
            "lon": 13.369,
            "timezone": "Europe/Berlin",
        }

    async def fake_plan(self: TransitousProvider, **kwargs: Any) -> dict[str, Any]:
        plan_calls.append(kwargs)
        return {"itineraries": []}

    monkeypatch.setattr(TransitousProvider, "_geocode", fake_geocode)
    monkeypatch.setattr(TransitousProvider, "_plan", fake_plan)

    await TransitousProvider().search_connections(
        legs=[{
            "origin": "Berlin Hbf",
            "destination": "Hamburg Hbf",
            "date": "2026-08-14",
            "departure_time": "16:20",
        }],
        passengers=1,
        travel_class="economy",
        max_results=6,
        non_stop_only=False,
        currency="EUR",
    )

    assert plan_calls[0]["departure_time"] == "16:20"
    assert plan_calls[0]["timezone_name"] == "Europe/Berlin"


# contract-test: supporting surface=rest_api assertions=travel-search.departure-window.upstream
def test_transitous_plan_time_handles_origin_timezone_and_dst_boundaries() -> None:
    from backend.apps.travel.providers.transitous_provider import _format_plan_time

    assert _format_plan_time("2026-08-14", "16:20", "Europe/Berlin") == "2026-08-14T14:20:00Z"
    assert _format_plan_time("2026-10-25", "02:30", "Europe/Berlin") == "2026-10-25T00:30:00Z"
    with pytest.raises(ValueError, match="invalid"):
        _format_plan_time("2026-03-29", "02:30", "Europe/Berlin")


# contract-test: direct surface=rest_api assertions=travel-search.departure-window.upstream
@pytest.mark.anyio
async def test_flix_provider_filters_by_departure_before_result_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.apps.travel.providers import flix_provider

    berlin = {"name": "Berlin", "legacy_id": 88}
    hamburg = {"name": "Hamburg", "legacy_id": 118}

    async def fake_autocomplete(query: str, **kwargs: Any) -> list[dict[str, Any]]:
        return [berlin if query == "Berlin" else hamburg]

    def flix_time(hour: int) -> dict[str, Any]:
        local = datetime(2026, 8, 14, hour, tzinfo=timezone(timedelta(hours=2)))
        return {"timestamp": int(local.timestamp()), "tz": "GMT+02:00"}

    def item(hour: int) -> dict[str, Any]:
        return {
            "departure": flix_time(hour),
            "arrival": flix_time(hour + 2),
            "duration": {"hour": 2, "minutes": 0},
            "price_total_sum": 20,
            "transfer_type_key": "direct",
            "operated_by": [{"label": "FlixBus", "key": "flix"}],
            "interconnection_transfers": [],
            "amenities": [[]],
        }

    async def fake_search_trips(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "trips": [{
                "from": berlin,
                "to": hamburg,
                "items": [item(8), item(16)],
            }]
        }

    monkeypatch.setattr(flix_provider, "autocomplete_locations", fake_autocomplete)
    monkeypatch.setattr(flix_provider, "search_trips", fake_search_trips)

    results = await flix_provider.FlixProvider(supported_methods={"bus"}).search_connections(
        legs=[{
            "origin": "Berlin",
            "destination": "Hamburg",
            "date": "2026-08-14",
            "departure_time": "16:00",
        }],
        passengers=1,
        travel_class="economy",
        max_results=1,
        non_stop_only=False,
        currency="EUR",
    )

    assert [result.legs[0].departure for result in results] == ["2026-08-14T16:00:00+02:00"]


# contract-test: direct surface=rest_api assertions=travel-search.departure-window.upstream,travel-search.departure-window.filtered
@pytest.mark.anyio
async def test_flix_provider_queries_next_date_for_overnight_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.apps.travel.providers import flix_provider

    berlin = {"name": "Berlin", "legacy_id": 88}
    hamburg = {"name": "Hamburg", "legacy_id": 118}
    searched_dates: list[str] = []

    async def fake_autocomplete(query: str, **kwargs: Any) -> list[dict[str, Any]]:
        return [berlin if query == "Berlin" else hamburg]

    def item(year: int, month: int, day: int, hour: int) -> dict[str, Any]:
        offset = timezone(timedelta(hours=2))
        departure = datetime(year, month, day, hour, tzinfo=offset)
        arrival = departure + timedelta(hours=2)
        return {
            "departure": {"timestamp": int(departure.timestamp()), "tz": "GMT+02:00"},
            "arrival": {"timestamp": int(arrival.timestamp()), "tz": "GMT+02:00"},
            "duration": {"hour": 2, "minutes": 0},
            "price_total_sum": 20,
            "transfer_type_key": "direct",
            "operated_by": [{"label": "FlixBus", "key": "flix"}],
            "interconnection_transfers": [],
            "amenities": [[]],
        }

    async def fake_search_trips(*args: Any, **kwargs: Any) -> dict[str, Any]:
        searched_dates.append(kwargs["departure_date"])
        result_item = item(2026, 8, 14, 23) if kwargs["departure_date"] == "14.08.2026" else item(2026, 8, 15, 0)
        return {"trips": [{"from": berlin, "to": hamburg, "items": [result_item]}]}

    monkeypatch.setattr(flix_provider, "autocomplete_locations", fake_autocomplete)
    monkeypatch.setattr(flix_provider, "search_trips", fake_search_trips)

    results = await flix_provider.FlixProvider(supported_methods={"bus"}).search_connections(
        legs=[{
            "origin": "Berlin",
            "destination": "Hamburg",
            "date": "2026-08-14",
            "departure_time": "23:00",
            "max_departure_time": "01:00",
        }],
        passengers=1,
        travel_class="economy",
        max_results=2,
        non_stop_only=False,
        currency="EUR",
    )

    assert searched_dates == ["14.08.2026", "15.08.2026"]
    assert [result.legs[0].departure for result in results] == [
        "2026-08-14T23:00:00+02:00",
        "2026-08-15T00:00:00+02:00",
    ]


# contract-test: direct surface=rest_api assertions=travel-search.departure-window.upstream
@pytest.mark.anyio
async def test_serpapi_provider_filters_by_departure_before_result_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.apps.travel.providers.serpapi_provider import SerpApiProvider

    def flight_group(hour: int) -> dict[str, Any]:
        return {
            "flights": [{
                "departure_airport": {"id": "BER", "time": f"2026-08-14 {hour:02d}:00"},
                "arrival_airport": {"id": "LHR", "time": f"2026-08-14 {hour + 2:02d}:00"},
                "airline": "Example Air",
                "flight_number": "EX 1",
                "duration": 120,
            }],
            "total_duration": 120,
            "price": 100,
        }

    provider = SerpApiProvider()

    async def fake_serpapi_get(params: dict[str, Any]) -> dict[str, Any]:
        return {"best_flights": [flight_group(8), flight_group(16)]}

    monkeypatch.setattr(provider, "_serpapi_get", fake_serpapi_get)
    results = await provider._search_one_way(
        api_key="test",
        resolved_leg={"origin": "BER", "destination": "LHR", "date": "2026-08-14"},
        original_leg={
            "origin": "BER",
            "destination": "LHR",
            "date": "2026-08-14",
            "departure_time": "16:00",
        },
        passengers=1,
        travel_class="economy",
        max_results=1,
        non_stop_only=False,
        currency="EUR",
    )

    assert [result.legs[0].departure for result in results] == ["2026-08-14 16:00"]


@pytest.mark.parametrize(
    ("departure", "expected"),
    [
        ("2026-08-14T23:00:00+02:00", True),
        ("2026-08-15T00:30:00+02:00", True),
        ("2026-08-15T01:00:00+02:00", True),
        ("2026-08-14T12:00:00+02:00", False),
    ],
)
# contract-test: direct surface=rest_api assertions=travel-search.departure-window.filtered
def test_search_skill_filters_overnight_departure_window(departure: str, expected: bool) -> None:
    assert make_skill()._matches_time_window(departure, "23:00", "01:00") is expected


# contract-test: direct surface=rest_api assertions=travel-search.no-results.explicit
@pytest.mark.anyio
async def test_deutsche_bahn_provider_does_not_turn_upstream_failure_into_empty_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.apps.travel.providers import db_provider

    async def fake_resolve_location_id(city_name: str) -> str:
        return f"A=1@O={city_name}@L=8000001@"

    async def failing_search_journeys(**kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("DB unavailable")

    monkeypatch.setattr(db_provider, "resolve_location_id", fake_resolve_location_id)
    monkeypatch.setattr(db_provider, "search_journeys", failing_search_journeys)

    with pytest.raises(RuntimeError, match="DB journey search failed"):
        await db_provider.DeutscheBahnProvider().search_connections(
            legs=[{"origin": "Berlin Hbf", "destination": "Hamburg Hbf", "date": "2026-08-14"}],
            passengers=1,
            travel_class="economy",
            max_results=6,
            non_stop_only=False,
            currency="EUR",
        )


# contract-test: direct surface=rest_api assertions=travel-search.transfer-amenities.source-labelled
@pytest.mark.anyio
async def test_transfer_amenity_summary_preserves_provider_error_status() -> None:
    class FakeAmenityProvider:
        async def search_places(self, **kwargs: Any) -> Any:
            return types.SimpleNamespace(status="provider_error", places=[])

    summary = await make_skill()._transfer_amenity_summary(
        FakeAmenityProvider(),
        cache_service=None,
        station="Wolfsburg Hbf",
        latitude=52.429,
        longitude=10.789,
    )

    assert summary["status"] == "provider_error"
    assert {group["status"] for group in summary["groups"].values()} == {"provider_error"}
