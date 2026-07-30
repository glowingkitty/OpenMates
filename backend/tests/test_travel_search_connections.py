# backend/tests/test_travel_search_connections.py
#
# Unit tests for the travel search_connections skill limits and filters.
# These tests use a fake transport provider so they do not spend provider
# credits or depend on live flight/train APIs. They validate the skill-layer
# contract that all transport providers share.

from __future__ import annotations

import sys
import ssl
import types
from typing import Any, List, Optional

import pytest
from backend.apps.travel.providers.base_provider import (
    BaseTransportProvider,
    ConnectionResult,
    FareResult,
    LayoverResult,
    LegResult,
    SegmentResult,
)

airports_module = types.ModuleType("airports")
airports_module.airport_data = types.SimpleNamespace(get_airport_by_iata=lambda _iata: [])
sys.modules.setdefault("airports", airports_module)

_AUTO_PRICE = object()


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
        self.requested_owned_passes: Optional[List[str]] = None
        self.requested_pass_only: Optional[bool] = None
        self.requested_rail_products: Optional[List[str]] = None
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
        owned_passes: Optional[List[str]] = None,
        pass_only: bool = False,
        rail_products: Optional[List[str]] = None,
    ) -> List[ConnectionResult]:
        self.calls += 1
        self.requested_max_results = max_results
        self.requested_owned_passes = owned_passes
        self.requested_pass_only = pass_only
        self.requested_rail_products = rail_products
        return self.results[:max_results]


def make_connection(
    index: int,
    departure: str,
    arrival: str,
    duration: str = "2h 0m",
    layover_minutes: Optional[int] = None,
    overnight: bool = False,
    fare: Optional[FareResult] = None,
    source_provider: str = "google_flights",
    total_price: Any = _AUTO_PRICE,
) -> ConnectionResult:
    resolved_price = str(100 + index) if total_price is _AUTO_PRICE else total_price
    resolved_currency = "EUR" if resolved_price is not None else (fare.currency if fare else None)
    fare_coverage = None
    if fare and fare.confidence == "timetable_only":
        fare_coverage = "timetable_only"
    elif fare and fare.is_pass_only:
        fare_coverage = "pass_covered"
    elif resolved_price is not None or fare:
        fare_coverage = "paid"

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
                mode="airplane",
                line=f"TA {index}",
                operator="Test Air",
                source_provider=source_provider,
                fare_coverage=fare_coverage,
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
        source_provider=source_provider,
        total_price=resolved_price,
        currency=resolved_currency,
        fare=fare,
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
async def test_search_connections_forwards_owned_passes_to_provider() -> None:
    provider = FakeTransportProvider(
        [make_connection(0, "2026-06-01 09:00", "2026-06-01 11:00")],
        provider_id="deutsche_bahn",
        supported_methods={"train"},
        supported_countries={"DE"},
    )

    _, results, error = await make_skill()._process_single_request(
        {
            "legs": [{"origin": "Potsdam", "destination": "Munich", "date": "2026-06-01"}],
            "transport_methods": ["train"],
            "providers": ["deutsche_bahn"],
            "owned_passes": ["deutschland_ticket"],
        },
        request_id="pass-aware-train",
        all_providers=[provider],
    )

    assert error is None
    assert len(results) == 1
    assert provider.requested_owned_passes == ["deutschland_ticket"]


@pytest.mark.anyio
async def test_search_connections_serializes_structured_fares_and_sorts_timetable_only_last() -> None:
    timetable_only = make_connection(
        1,
        "2026-06-01 08:00",
        "2026-06-01 13:00",
        source_provider="transitous",
        total_price=None,
        fare=FareResult(
            amount=None,
            currency=None,
            is_partial=False,
            is_pass_only=False,
            covered_by_passes=[],
            pricing_provider=None,
            confidence="timetable_only",
            summary="Timetable only; no fare available.",
        ),
    )
    timetable_only.currency = None
    priced = make_connection(
        0,
        "2026-06-01 09:00",
        "2026-06-01 11:00",
        source_provider="deutsche_bahn",
        total_price="67.99",
        fare=FareResult(
            amount=67.99,
            currency="EUR",
            is_partial=True,
            is_pass_only=False,
            covered_by_passes=["deutschland_ticket"],
            pricing_provider="deutsche_bahn",
            confidence="partial",
            summary="EUR 67.99 paid portion after Deutschlandticket coverage.",
        ),
    )
    provider = FakeTransportProvider(
        [timetable_only, priced],
        provider_id="transitous",
        supported_methods={"train"},
        supported_countries=None,
    )

    _, results, error = await make_skill()._process_single_request(
        {
            "legs": [{"origin": "Potsdam", "destination": "Munich", "date": "2026-06-01"}],
            "transport_methods": ["train"],
            "providers": ["transitous"],
            "sort_by": "price_asc",
        },
        request_id="fare-sort",
        all_providers=[provider],
    )

    assert error is None
    assert [result["source_provider"] for result in results] == ["deutsche_bahn", "transitous"]
    assert results[0]["fare"] == {
        "amount": 67.99,
        "currency": "EUR",
        "is_partial": True,
        "is_pass_only": False,
        "covered_by_passes": ["deutschland_ticket"],
        "pricing_provider": "deutsche_bahn",
        "confidence": "partial",
        "summary": "EUR 67.99 paid portion after Deutschlandticket coverage.",
    }
    assert results[0]["fare_is_partial"] is True
    assert results[0]["fare_passes_applied"] == ["deutschland_ticket"]
    assert results[1]["fare"]["confidence"] == "timetable_only"
    assert results[1]["total_price"] is None


@pytest.mark.anyio
async def test_search_connections_forwards_pass_only_and_rail_products_to_db_provider() -> None:
    provider = FakeTransportProvider(
        [make_connection(0, "2026-06-01 09:00", "2026-06-01 11:00")],
        provider_id="deutsche_bahn",
        supported_methods={"train"},
        supported_countries={"DE"},
    )

    _, results, error = await make_skill()._process_single_request(
        {
            "legs": [{"origin": "Berlin", "destination": "Munich", "date": "2026-06-01"}],
            "transport_methods": ["train"],
            "providers": ["deutsche_bahn"],
            "owned_passes": ["deutschland_ticket"],
            "pass_only": True,
            "rail_products": ["regional", "s_bahn"],
        },
        request_id="db-pass-only",
        all_providers=[provider],
    )

    assert error is None
    assert len(results) == 1
    assert provider.requested_owned_passes == ["deutschland_ticket"]
    assert provider.requested_pass_only is True
    assert provider.requested_rail_products == ["regional", "s_bahn"]


@pytest.mark.anyio
async def test_deutsche_bahn_provider_forwards_deutschland_ticket_and_marks_partial_fare(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.apps.travel.providers import db_provider

    calls: list[dict[str, Any]] = []

    async def fake_resolve_location_id(city_name: str) -> str:
        return f"A=1@O={city_name} Hbf@L=8000001@"

    async def fake_search_journeys(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {
            "verbindungen": [{
                "verbindung": {
                    "reiseDauer": 17100,
                    "umstiegeAnzahl": 1,
                    "verbindungsAbschnitte": [{
                        "typ": "FAHRZEUG",
                        "produktGattung": "ICE",
                        "mitteltext": "ICE 1505",
                        "abschnittsDauer": 17100,
                        "abgangsOrt": {"name": "Potsdam Hbf", "position": {"latitude": 52.391, "longitude": 13.067}},
                        "ankunftsOrt": {"name": "München Hbf", "position": {"latitude": 48.140, "longitude": 11.558}},
                        "halte": [
                            {"abgangsDatum": "2026-06-01T08:00:00+02:00"},
                            {"ankunftsDatum": "2026-06-01T12:45:00+02:00"},
                        ],
                    }],
                },
                "angebote": {
                    "preise": {
                        "istTeilpreis": True,
                        "gesamt": {"ab": {"betrag": 67.99, "waehrung": "EUR"}},
                    }
                },
            }]
        }

    monkeypatch.setattr(db_provider, "resolve_location_id", fake_resolve_location_id)
    monkeypatch.setattr(db_provider, "search_journeys", fake_search_journeys)

    results = await db_provider.DeutscheBahnProvider().search_connections(
        legs=[{"origin": "Potsdam", "destination": "Munich", "date": "2026-06-01"}],
        passengers=1,
        travel_class="economy",
        max_results=3,
        non_stop_only=False,
        currency="EUR",
        owned_passes=["deutschland-ticket"],
    )

    assert calls[0]["deutschland_ticket"] is True
    assert len(results) == 1
    assert results[0].total_price == "67.99"
    assert results[0].fare == FareResult(
        amount=67.99,
        currency="EUR",
        is_partial=True,
        is_pass_only=False,
        covered_by_passes=["deutschland_ticket"],
        pricing_provider="deutsche_bahn",
        confidence="partial",
        summary="EUR 67.99 paid portion after Deutschlandticket coverage.",
    )
    assert results[0].fare_is_partial is True
    assert results[0].fare_passes_applied == ["deutschland_ticket"]


@pytest.mark.anyio
async def test_deutsche_bahn_provider_forwards_pass_only_and_rail_products(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.apps.travel.providers import db_provider

    calls: list[dict[str, Any]] = []

    async def fake_resolve_location_id(city_name: str) -> str:
        return f"A=1@O={city_name} Hbf@L=8000001@"

    async def fake_search_journeys(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {
            "verbindungen": [{
                "verbindung": {
                    "reiseDauer": 34200,
                    "umstiegeAnzahl": 4,
                    "verbindungsAbschnitte": [{
                        "typ": "FAHRZEUG",
                        "produktGattung": "S",
                        "mitteltext": "S7",
                        "abschnittsDauer": 1800,
                        "abgangsOrt": {"name": "Potsdam Hbf", "position": {"latitude": 52.391, "longitude": 13.067}},
                        "ankunftsOrt": {"name": "Berlin Hbf", "position": {"latitude": 52.525, "longitude": 13.369}},
                        "halte": [
                            {"abgangsDatum": "2026-06-01T08:00:00+02:00"},
                            {"ankunftsDatum": "2026-06-01T08:30:00+02:00"},
                        ],
                    }],
                },
                "angebote": {"preise": {"gesamt": {"ab": {}}}},
            }]
        }

    monkeypatch.setattr(db_provider, "resolve_location_id", fake_resolve_location_id)
    monkeypatch.setattr(db_provider, "search_journeys", fake_search_journeys)

    results = await db_provider.DeutscheBahnProvider().search_connections(
        legs=[{"origin": "Potsdam", "destination": "Munich", "date": "2026-06-01"}],
        passengers=1,
        travel_class="economy",
        max_results=3,
        non_stop_only=False,
        currency="EUR",
        owned_passes=["deutschland_ticket"],
        pass_only=True,
        rail_products=["regional", "s_bahn"],
    )

    assert calls[0]["deutschland_ticket"] is True
    assert calls[0]["deutschland_ticket_only"] is True
    assert calls[0]["transport_filter"] == ["NAHVERKEHRSONSTIGEZUEGE", "SBAHNEN"]
    assert len(results) == 1
    assert results[0].total_price is None
    assert results[0].fare == FareResult(
        amount=None,
        currency=None,
        is_partial=False,
        is_pass_only=True,
        covered_by_passes=["deutschland_ticket"],
        pricing_provider="deutsche_bahn",
        confidence="pass_only",
        summary="Covered by Deutschlandticket; no additional DB fare returned.",
    )


@pytest.mark.anyio
async def test_transitous_provider_maps_plan_to_timetable_only_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.apps.travel.providers.transitous_provider import TransitousProvider

    geocode_modes: list[Optional[str]] = []

    async def fake_geocode(self: TransitousProvider, query: str, *, mode: Optional[str] = None) -> dict[str, Any]:
        geocode_modes.append(mode)
        return {
            "name": query,
            "lat": 52.525,
            "lon": 13.369,
            "type": "STOP",
            "confidence": 0.95,
        }

    async def fake_plan(self: TransitousProvider, **kwargs: Any) -> dict[str, Any]:
        return {
            "itineraries": [{
                "duration": 29400,
                "transfers": 1,
                "legs": [
                    {
                        "mode": "RAIL",
                        "routeShortName": "ICE 9574",
                        "agencyName": "DB Fernverkehr AG",
                        "startTime": "2026-06-01T08:00:00+02:00",
                        "endTime": "2026-06-01T16:10:00+02:00",
                        "duration": 29400,
                        "from": {"name": "Berlin Hbf", "lat": 52.525, "lon": 13.369},
                        "to": {"name": "Paris Est", "lat": 48.876, "lon": 2.359},
                    }
                ],
                "fareTransfers": [{"effectiveFareLegProducts": []}],
            }]
        }

    monkeypatch.setattr(TransitousProvider, "_geocode", fake_geocode)
    monkeypatch.setattr(TransitousProvider, "_plan", fake_plan)

    results = await TransitousProvider().search_connections(
        legs=[{"origin": "Berlin Hbf", "destination": "Paris Gare de l'Est", "date": "2026-06-01"}],
        passengers=1,
        travel_class="economy",
        max_results=2,
        non_stop_only=False,
        currency="EUR",
    )

    assert len(results) == 1
    assert geocode_modes == ["RAIL", "RAIL"]
    result = results[0]
    assert result.source_provider == "transitous"
    assert result.total_price is None
    assert result.booking_url is None
    assert result.fare == FareResult(
        amount=None,
        currency=None,
        is_partial=False,
        is_pass_only=False,
        covered_by_passes=[],
        pricing_provider=None,
        confidence="timetable_only",
        summary="Timetable only; no fare available.",
    )
    segment = result.legs[0].segments[0]
    assert segment.mode == "train"
    assert segment.line == "ICE 9574"
    assert segment.operator == "DB Fernverkehr AG"
    assert segment.source_provider == "transitous"
    assert segment.fare_coverage == "timetable_only"


@pytest.mark.anyio
async def test_transitous_provider_rejects_ambiguous_geocode(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.apps.travel.providers.transitous_provider import TransitousLocationResolutionError, TransitousProvider

    async def fake_fetch_geocode(self: TransitousProvider, query: str, *, mode: Optional[str] = None) -> list[dict[str, Any]]:
        return [
            {"name": "St Pölten Hauptbahnhof", "lat": 48.208, "lon": 15.624, "type": "STOP"},
            {"name": "Potsdam, Bahnhof", "lat": 52.391, "lon": 13.067, "type": "ADDRESS"},
        ]

    monkeypatch.setattr(TransitousProvider, "_fetch_geocode_suggestions", fake_fetch_geocode)

    with pytest.raises(TransitousLocationResolutionError):
        await TransitousProvider()._geocode("Potsdam Hbf")


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


@pytest.mark.anyio
async def test_execute_normalizes_flat_llm_route_request(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.apps.travel.skills import search_connections as search_module

    provider = FakeTransportProvider(
        [make_connection(0, "2026-08-12 09:00", "2026-08-12 15:00", source_provider="deutsche_bahn")],
        provider_id="deutsche_bahn",
        supported_methods={"train"},
        supported_countries={"DE"},
    )
    monkeypatch.setattr(search_module, "_create_providers", lambda secrets_manager=None: [provider])

    response = await make_skill().execute(
        requests=[{
            "origin": "Bonn",
            "destination": "Munich",
            "date": "2026-08-12",
            "transport_method": "train",
            "provider": "deutsche_bahn",
            "owned_passes": ["deutschland_ticket"],
        }],
        secrets_manager=object(),
    )

    assert response.error is None
    assert provider.calls == 1
    assert provider.requested_owned_passes == ["deutschland_ticket"]
    assert response.providers == [{
        "id": "deutsche_bahn",
        "name": "Deutsche Bahn",
        "icon_url": "https://www.bahn.de/favicon.ico",
    }]
    assert response.results[0]["query"] == "Bonn → Munich, 2026-08-12"
    assert response.results[0]["legs"] == [{"origin": "Bonn", "destination": "Munich", "date": "2026-08-12"}]
    assert response.results[0]["transport_methods"] == ["train"]


def test_search_connections_response_has_no_fake_provider_default() -> None:
    from backend.apps.travel.skills.search_connections import SearchConnectionsResponse

    assert SearchConnectionsResponse().provider == ""


def test_transitous_plan_parameters_match_current_openapi() -> None:
    from backend.apps.travel.providers.transitous_provider import TransitousProvider, _format_plan_time

    assert _format_plan_time("2026-06-01") == "2026-06-01T08:00:00Z"
    assert TransitousProvider._format_place({"name": "Berlin Hbf", "lat": 52.52498, "lon": 13.369114}) == "52.52498,13.369114"


def test_deutsche_bahn_http_transport_uses_db_tls_context(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.shared.providers import deutsche_bahn

    captured: dict[str, Any] = {}

    class FakeTransport:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(deutsche_bahn.httpx, "AsyncHTTPTransport", FakeTransport)

    assert isinstance(deutsche_bahn._db_http_transport(), FakeTransport)
    assert captured["http2"] is False
    assert captured["trust_env"] is False
    assert isinstance(captured["verify"], ssl.SSLContext)


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
