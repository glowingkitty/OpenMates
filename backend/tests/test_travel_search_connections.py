"""Unavailable search must not resolve secrets or execute transport providers."""
# contract-test-file: infrastructure
from unittest.mock import AsyncMock

import pytest
import yaml
from pathlib import Path

from backend.apps.travel.skills.search_connections import (
    SearchConnectionsSkill, SearchConnectionsResponse, _create_providers,
    _normalize_connection_requests,
)
from backend.apps.travel.skills.search_stays import SearchStaysSkill
from backend.apps.shopping.skills.search_products import SearchProductsSkill
from backend.apps.travel.providers.stay_models import StayResult


def make_skill(cls, app_id, skill_id):
    return cls(app=None, app_id=app_id, skill_id=skill_id,
               skill_name=skill_id, skill_description="Contract test")


@pytest.mark.asyncio
@pytest.mark.parametrize("cls,app_id,skill_id", [
    (SearchConnectionsSkill, "travel", "search_connections"),
    (SearchStaysSkill, "travel", "search_stays"),
    (SearchProductsSkill, "shopping", "search_products"),
])
async def test_no_source_capability_is_unavailable_without_secret_access(monkeypatch, cls, app_id, skill_id):
    skill = make_skill(cls, app_id, skill_id)
    secrets = AsyncMock(side_effect=AssertionError("Unavailable skills must not resolve secrets"))
    monkeypatch.setattr(skill, "_get_or_create_secrets_manager", secrets)
    response = await skill.execute(requests=[{"id": "request-a", "query": "synthetic"}])
    assert response.provider == "" and response.providers == []
    assert response.provider_required is True and response.available is False
    assert "unavailable" in response.error
    assert response.results == [{"id": "request-a", "results": [], "error": response.error}]
    assert skill.resolve_preview_metadata({})["providers"] == []
    secrets.assert_not_called()


@pytest.mark.parametrize("app,skill_id", [
    ("shopping", "search_products"), ("travel", "search_connections"), ("travel", "search_stays"),
])
def test_unavailable_metadata_has_no_provider_selector_or_price(app, skill_id):
    config = yaml.safe_load((Path(__file__).parents[1] / "apps" / app / "app.yml").read_text())
    skill = next(item for item in config["skills"] if item["id"] == skill_id)
    assert skill["provider_required"] is True and skill["providers"] == []
    assert "pricing" not in skill
    fields = skill["tool_schema"]["properties"]["requests"]["items"]["properties"]
    assert "provider" not in fields and "providers" not in fields


def test_connection_registry_and_default_response_do_not_invent_provider():
    assert _create_providers() == []
    assert SearchConnectionsResponse().provider == ""
    assert SearchConnectionsResponse().providers == []


def test_flat_route_normalization_remains_provider_independent():
    requests = _normalize_connection_requests([{
        "origin": "City A", "destination": "City B", "date": "2027-01-01",
        "transport_method": "train",
    }])
    assert requests[0]["legs"] == [{"origin": "City A", "destination": "City B", "date": "2027-01-01"}]
    assert requests[0]["transport_methods"] == ["train"]


def test_historical_connection_filters_keep_price_and_transfer_semantics():
    skill = make_skill(SearchConnectionsSkill, "travel", "search_connections")
    results = [
        {"stops": 0, "total_price": "120", "duration": "2h 30m", "legs": []},
        {"stops": 1, "total_price": "80", "duration": "5h 30m", "legs": []},
    ]
    assert skill._filter_results(results, {"max_stops": 0, "max_price": 150}) == results[:1]
    assert not skill._matches_layover_filters(
        {"legs": [{"layovers": [{"duration_minutes": 4}]}]}, 10, None, False,
    )


def test_historical_stay_serialization_keeps_gallery_and_prices():
    result = StayResult(name="Synthetic property", extracted_rate_per_night=123,
                        images=[{"original_image": "https://example.test/property.jpg"}]).to_dict()
    assert result["type"] == "stay"
    assert result["extracted_rate_per_night"] == 123
    assert result["images"] == [{"original_image": "https://example.test/property.jpg"}]


@pytest.mark.asyncio
async def test_documented_calendar_retains_local_resolution_and_response_contract(monkeypatch):
    from backend.apps.travel.skills.price_calendar import PriceCalendarSkill
    from backend.apps.travel.providers.travelpayouts_provider import TravelpayoutsProvider
    from backend.apps.travel.providers.base_provider import PriceCalendarEntry
    from backend.apps.travel.providers.airport_codes import resolve_iata_code

    assert resolve_iata_code("Munich") == "MUC"
    assert resolve_iata_code("LHR") == "LHR"
    assert resolve_iata_code("Unknown synthetic place") is None
    calendar = AsyncMock(return_value=[PriceCalendarEntry(date="2027-01-03", price=99)])
    monkeypatch.setattr(TravelpayoutsProvider, "get_price_calendar", calendar)
    skill = make_skill(PriceCalendarSkill, "travel", "price_calendar")
    response = await skill.execute(requests=[{
        "id": "calendar-a", "origin": "Munich", "destination": "London", "month": "2027-01",
    }])
    calendar.assert_awaited_once_with(origin="MUC", destination="LHR", month="2027-01", currency="eur")
    assert response.provider == "Travelpayouts" and response.error is None
    result = response.results[0]["results"][0]
    assert result["type"] == "price_calendar"
    assert result["cheapest_price"] == 99 and result["days_with_data"] == 1
