# backend/tests/test_flix_provider.py
#
# Unit tests for the FlixBus / FlixTrain travel provider.
# These tests mock the reverse-engineered Flix endpoints so they do not depend
# on live API availability and can validate booking links and normalization.

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from backend.apps.travel.providers.flix_provider import FlixProvider


BERLIN_AUTOCOMPLETE = {
    "name": "Berlin",
    "legacy_id": 88,
    "id": "40d8f682-8646-11e6-9066-549f350fcb0c",
    "country": "de",
    "stations": [
        {"name": "Berlin central bus station", "legacy_id": 1, "is_train": False},
        {"name": "Berlin Central Station", "legacy_id": 20688, "is_train": True},
    ],
}

HAMBURG_AUTOCOMPLETE = {
    "name": "Hamburg",
    "legacy_id": 118,
    "id": "40d91e53-8646-11e6-9066-549f350fcb0c",
    "country": "de",
    "stations": [
        {"name": "Hamburg ZOB", "legacy_id": 36, "is_train": False},
        {"name": "Hamburg Central Station", "legacy_id": 22308, "is_train": True},
    ],
}


def _time(timestamp: int) -> Dict[str, Any]:
    return {"timestamp": timestamp, "tz": "GMT+02:00"}


def _direct_trip() -> Dict[str, Any]:
    return {
        "trips": [
            {
                "from": {
                    "name": "Berlin central bus station",
                    "country": {"code": "DE"},
                    "location": {"latitude": 52.507171, "longitude": 13.279399},
                },
                "to": {
                    "name": "Hamburg ZOB",
                    "country": {"code": "DE"},
                    "location": {"latitude": 53.551767, "longitude": 10.011657},
                },
                "links": [{"rel": "shop:search", "href": "https://shop.global.flixbus.com/s?departureCity=88"}],
                "items": [
                    {
                        "uid": "direct:1:36",
                        "departure": _time(1779231600),
                        "arrival": _time(1779243300),
                        "duration": {"hour": 3, "minutes": 15},
                        "status": "available",
                        "price_total_sum": 21.49,
                        "transfer_type_key": "direct",
                        "info_message": "1 seat left at this price",
                        "available": {"seats": 999},
                        "operated_by": [{"label": "FlixBus DACH GmbH", "key": "mfb"}],
                        "interconnection_transfers": [],
                        "amenities": [[{"type": "WIFI", "label": "Free Wi-Fi"}]],
                    }
                ],
            }
        ]
    }


def _mixed_train_trip() -> Dict[str, Any]:
    return {
        "trips": [
            {
                "from": {"name": "Berlin Central Station", "country": {"code": "DE"}, "location": {}},
                "to": {"name": "Stuttgart Airport", "country": {"code": "DE"}, "location": {}},
                "links": [{"rel": "shop:search", "href": "https://shop.global.flixbus.com/s?departureCity=88"}],
                "items": [
                    {
                        "uid": "interconnection:train-bus",
                        "departure": _time(1779263820),
                        "arrival": _time(1779293400),
                        "duration": {"hour": 8, "minutes": 13},
                        "status": "available",
                        "price_total_sum": 27.48,
                        "transfer_type_key": "train#direct",
                        "info_message": "",
                        "available": {"seats": 999},
                        "operated_by": [
                            {"label": "FlixTrain GmbH", "key": "train"},
                            {"label": "FlixBus Italia S.r.l.", "key": "flixital"},
                        ],
                        "interconnection_transfers": [
                            {
                                "station_id": 26,
                                "station_name": "Karlsruhe",
                                "arrival": _time(1779283740),
                                "departure": _time(1779289500),
                                "duration": {"hour": 1, "minutes": 36},
                                "message": "",
                            }
                        ],
                        "amenities": [[], []],
                    }
                ],
            }
        ]
    }


@pytest.mark.asyncio
async def test_flix_provider_returns_bus_with_booking_url(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: List[tuple[int, int]] = []

    async def fake_autocomplete(query: str, **kwargs: Any) -> List[Dict[str, Any]]:
        return [BERLIN_AUTOCOMPLETE if query == "Berlin" else HAMBURG_AUTOCOMPLETE]

    async def fake_search_trips(from_id: int, to_id: int, **kwargs: Any) -> Dict[str, Any]:
        calls.append((from_id, to_id))
        return _direct_trip()

    from backend.apps.travel.providers import flix_provider

    monkeypatch.setattr(flix_provider, "autocomplete_locations", fake_autocomplete)
    monkeypatch.setattr(flix_provider, "search_trips", fake_search_trips)

    results = await FlixProvider(supported_methods={"bus"}).search_connections(
        legs=[{"origin": "Berlin", "destination": "Hamburg", "date": "2026-05-20"}],
        passengers=1,
        travel_class="economy",
        max_results=5,
        non_stop_only=False,
        currency="EUR",
    )

    assert calls == [(88, 118)]
    assert len(results) == 1
    assert results[0].transport_method == "bus"
    assert results[0].source_provider == "flix"
    assert results[0].booking_url == "https://shop.global.flixbus.com/s?departureCity=88"
    assert results[0].bookable_seats == 1
    assert results[0].legs[0].segments[0].carrier == "FlixBus DACH GmbH"


@pytest.mark.asyncio
async def test_flix_provider_filters_train_results_for_bus_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_autocomplete(query: str, **kwargs: Any) -> List[Dict[str, Any]]:
        return [BERLIN_AUTOCOMPLETE if query == "Berlin" else HAMBURG_AUTOCOMPLETE]

    async def fake_search_trips(from_id: int, to_id: int, **kwargs: Any) -> Dict[str, Any]:
        return _mixed_train_trip()

    from backend.apps.travel.providers import flix_provider

    monkeypatch.setattr(flix_provider, "autocomplete_locations", fake_autocomplete)
    monkeypatch.setattr(flix_provider, "search_trips", fake_search_trips)

    results = await FlixProvider(supported_methods={"bus"}).search_connections(
        legs=[{"origin": "Berlin", "destination": "Hamburg", "date": "2026-05-20"}],
        passengers=1,
        travel_class="economy",
        max_results=5,
        non_stop_only=False,
        currency="EUR",
    )

    assert results == []


@pytest.mark.asyncio
async def test_flix_provider_maps_mixed_train_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    autocomplete_train_only_values: List[bool] = []

    async def fake_autocomplete(query: str, **kwargs: Any) -> List[Dict[str, Any]]:
        autocomplete_train_only_values.append(bool(kwargs.get("train_only")))
        return [BERLIN_AUTOCOMPLETE if query == "Berlin" else HAMBURG_AUTOCOMPLETE]

    async def fake_search_trips(from_id: int, to_id: int, **kwargs: Any) -> Dict[str, Any]:
        return _mixed_train_trip()

    from backend.apps.travel.providers import flix_provider

    monkeypatch.setattr(flix_provider, "autocomplete_locations", fake_autocomplete)
    monkeypatch.setattr(flix_provider, "search_trips", fake_search_trips)

    results = await FlixProvider(supported_methods={"train"}).search_connections(
        legs=[{"origin": "Berlin", "destination": "Hamburg", "date": "2026-05-20"}],
        passengers=1,
        travel_class="economy",
        max_results=5,
        non_stop_only=False,
        currency="EUR",
    )

    assert autocomplete_train_only_values == [True, True]
    assert len(results) == 1
    connection = results[0]
    assert connection.transport_method == "train"
    assert connection.total_price == "27.48"
    assert connection.legs[0].stops == 1
    assert [segment.carrier for segment in connection.legs[0].segments] == [
        "FlixTrain GmbH",
        "FlixBus Italia S.r.l.",
    ]
    assert connection.legs[0].layovers[0].airport == "Karlsruhe"
    assert connection.legs[0].layovers[0].duration_minutes == 96
