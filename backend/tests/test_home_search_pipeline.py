"""Apartment constraints and pre-selection enrichment without provider traffic."""
from datetime import date
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from backend.apps.home.skills import search_skill as home
from backend.shared.python_utils.search_relevance import SearchRelevanceRankingResult


# contract-test: direct surface=rest_api assertions=home-search.filters.explicit-and-unknown
@pytest.mark.parametrize("constraint", [
    {"min_price_eur": 1200, "max_price_eur": 1000},
    {"min_rooms": 3, "max_rooms": 2}, {"min_size_sqm": 80, "max_size_sqm": 40},
    {"required_amenities": ["balcony"], "excluded_amenities": ["balcony"]},
    {"required_amenities": ["invented"]}, {"available_by": "not a date"},
])
def test_invalid_constraints_rejected_before_any_work(constraint):
    with pytest.raises(ValidationError):
        home.SearchRequestItem(query="Berlin", **constraint)


# contract-test: supporting surface=rest_api assertions=home-search.enrichment.bounded-and-reusable
def test_assistant_envelope_allows_bounded_detail_and_optional_evidence_stages():
    from backend.apps.ai.processing.skill_executor import get_skill_timeout
    from backend.apps.home.evidence import ASSESSMENT_SECONDS
    from backend.apps.home.location_enrichment import LOCATION_TIMEOUT_SECONDS
    from backend.shared.providers.housing.details import DETAIL_DEADLINE_SECONDS
    assert get_skill_timeout("home", "search", {"requests": [{"query": "Berlin"}]}) >= (
        15 + DETAIL_DEADLINE_SECONDS + ASSESSMENT_SECONDS + LOCATION_TIMEOUT_SECONDS + 4)


# contract-test: direct surface=rest_api assertions=home-search.filters.explicit-and-unknown
def test_warm_budget_never_uses_cold_rent_or_unknown_values():
    items = [{"id": "warm", "warm_rent_eur": 1200}, {"id": "cold", "cold_rent_eur": 900, "price": 900},
             {"id": "expensive", "warm_rent_eur": 1600}]
    matches, warnings = home.filter_home_listings(items, {"max_warm_rent_eur": 1300})
    assert [row["id"] for row in matches] == ["warm"]
    assert "1 listing(s)" in warnings[0]
    matches, _ = home.filter_home_listings(items, {"max_warm_rent_eur": 1300, "include_unconfirmed": True})
    assert [row["id"] for row in matches] == ["warm", "cold"]
    assert matches[1]["match_evidence"]["status"] == "unconfirmed"


# contract-test: direct surface=rest_api assertions=home-search.filters.explicit-and-unknown,home-search.vision.evidence-and-conflicts
@pytest.mark.parametrize("excluded", [False, True])
def test_explicit_amenity_evidence_and_unknowns(excluded):
    mode = "excluded_amenities" if excluded else "required_amenities"
    items = [{"id": "yes", "amenities": {"balcony": True}}, {"id": "no", "balcony": False}, {"id": "unknown"},
             {"id": "possible", "match_evidence": {"amenities": {"balcony": {"status": "possible", "visual_status": "visible"}}}},
             {"id": "text", "match_evidence": {"amenities": {"balcony": {"text_status": "absent" if excluded else "present"}}}}]
    matches, warnings = home.filter_home_listings(items, {mode: ["balcony"]})
    assert [row["id"] for row in matches] == (["no", "text"] if excluded else ["yes", "text"])
    assert warnings


# contract-test: direct surface=rest_api assertions=home-search.filters.explicit-and-unknown,home-search.vision.evidence-and-conflicts
def test_source_conflicts_never_count_as_confirmed_even_if_unknowns_allowed():
    item = {"balcony": True, "amenity_conflicts": {"balcony": [True, False]}}
    matches, _ = home.filter_home_listings([item], {"required_amenities": ["balcony"], "include_unconfirmed": True})
    assert matches == []


# contract-test: direct surface=rest_api assertions=home-search.filters.explicit-and-unknown
def test_availability_date_and_zero_values_are_not_missing():
    items = [{"id": "early", "available_from": "01.11.2026", "price": 0},
             {"id": "late", "available_from": "2026-12-01", "price": 100}, {"id": "missing", "price": 20}]
    matches, _ = home.filter_home_listings(items, {"available_by": date(2026, 11, 15), "max_price_eur": 500})
    assert [row["id"] for row in matches] == ["early"]


# contract-test: direct surface=rest_api assertions=home-search.water.distance-and-access,home-search.location.precision
def test_water_hard_limits_need_precise_shoreline_or_routed_public_access():
    def item(identity, **fields):
        return {"id": identity, "location_precision": "building", "location_approximate": False,
                "neighborhood": {"features": {"water": [{"distance_m": 100, "distance_method": "shoreline_geometry", **fields}]}}}
    items = [item("shore"), item("centroid", distance_method="representative_point"),
             {**item("district"), "location_precision": "district", "location_approximate": True},
             item("far", distance_m=1000)]
    matches, _ = home.filter_home_listings(items, {"max_water_distance_m": 500})
    assert [row["id"] for row in matches] == ["shore"]
    matches, _ = home.filter_home_listings(items, {"max_water_distance_m": 500, "include_unconfirmed": True})
    assert "far" not in [row["id"] for row in matches]
    items = [item("route", walk_minutes=8, walk_status="routed", walk_method="provider_walking_route"),
             item("estimate", walk_minutes=2, walk_method="estimate"), item("none")]
    matches, _ = home.filter_home_listings(items, {"max_water_walk_minutes": 10})
    assert [row["id"] for row in matches] == ["route"]


# contract-test: direct surface=rest_api assertions=home-search.vision.evidence-and-conflicts
def test_soft_photo_evidence_never_becomes_confirmed_from_hard_filtering():
    item = {"match_evidence": {"status": "unconfirmed", "amenities": {"balcony": {"status": "possible", "visual_status": "visible"}}}}
    matches, _ = home.filter_home_listings([item], {"preferred_amenities": ["balcony"]})
    assert matches[0]["match_evidence"]["status"] == "unconfirmed"


# contract-test: direct surface=rest_api assertions=home-search.relevance.natural-language,home-search.enrichment.bounded-and-reusable,home-search.neighborhood.sourced-facts
@pytest.mark.asyncio
async def test_enrichment_and_evidence_precede_final_selection(monkeypatch):
    calls = []
    async def provider(**kwargs):
        calls.append(("provider", kwargs["max_results"]))
        return [{"id": str(i), "title": f"Apartment {i}", "price": 1000 + i, "balcony": True,
                 "image_urls": [f"https://images.example/{i}/{n}.jpg" for n in range(18)]} for i in range(20)]
    async def assess(items, **kwargs):
        calls.append(("evidence", len(items)))
        return []
    async def enrich(items, **kwargs):
        calls.append(("location", len(items)))
        for item in items:
            item.update(latitude=52.5, longitude=13.4, location_precision="building", location_approximate=False,
                        neighborhood={"features": {"water": [{"name": "Canal", "distance_m": 200, "distance_method": "shoreline_geometry"}]}})
        return []
    async def rank(**kwargs):
        calls.append(("rank", len(kwargs["candidates"])))
        assert all(row["nearby"]["water"][0]["distance_m"] == 200 for row in kwargs["candidate_projections"])
        return SearchRelevanceRankingResult(candidates=list(reversed(kwargs["candidates"])), applied=True)
    monkeypatch.setattr(home, "PROVIDER_MAP", {"Kleinanzeigen": provider})
    monkeypatch.setattr(home, "assess_home_evidence", assess)
    monkeypatch.setattr(home, "enrich_home_locations", enrich)
    monkeypatch.setattr(home, "rank_search_candidates", rank)
    skill = object.__new__(home.SearchSkill)
    monkeypatch.setattr(skill, "_geocode_listings", AsyncMock())
    _, listings, error, warnings = await skill._process_single_request({"query": "Berlin", "required_amenities": ["balcony"],
        "neighborhood_categories": ["water"], "max_water_distance_m": 500, "max_results": 2}, "request")
    assert error is None
    assert calls == [("provider", 20), ("evidence", 20), ("location", 20), ("rank", 20)]
    assert [row["id"] for row in listings] == ["19", "18"]
    assert all(len(row["image_urls"]) == 18 for row in listings)
    assert any("not an exhaustive" in warning for warning in warnings)


# contract-test: direct surface=rest_api assertions=home-search.location.precision
@pytest.mark.asyncio
async def test_city_fallback_never_upgrades_provider_coordinates():
    listings = [{"id": "provider", "latitude": 52.4, "longitude": 13.3, "location_precision": "district", "location_approximate": True}, {"id": "fallback"}]
    await object.__new__(home.SearchSkill)._geocode_listings(listings, "Berlin")
    assert listings[0]["latitude"] == 52.4 and listings[0]["location_precision"] == "district"
    assert listings[1]["location_precision"] == "city" and listings[1]["location_approximate"] is True


# contract-test: direct surface=rest_api assertions=home-search.location.precision
@pytest.mark.asyncio
async def test_final_city_fallback_updates_nested_fields_that_embed_flattening_uses():
    item = {"provider": "WG-Gesucht", "location_precision": "street", "location_source": "WG-Gesucht",
            "location": {"precision": "street", "source": "WG-Gesucht", "method": "unknown", "status": "candidate_limit"}}
    await object.__new__(home.SearchSkill)._geocode_listings([item], "Berlin")
    assert item["latitude"] == 52.52 and item["longitude"] == 13.405
    assert item["location_precision"] == item["location"]["precision"] == "city"
    assert item["location_source"] == item["location"]["source"] != "WG-Gesucht"
    assert item["location_approximate"] == item["location"]["approximate"] is True
    assert item["location"]["method"] == "city_fallback"
    assert item["location"]["geocode_status"] == "candidate_limit"


# contract-test: direct surface=rest_api assertions=home-search.enrichment.bounded-and-reusable,home-search.neighborhood.sourced-facts
@pytest.mark.asyncio
async def test_final_amenity_matches_receive_geo_budget_instead_of_cheaper_conflicts(monkeypatch):
    from backend.apps.home import location_enrichment as geo
    from backend.shared.providers.geoapify.places import GeoapifyPlacesSearchResult

    rows = [{"id": str(i), "provider": "Example", "price": 500 + i, "balcony": i >= 35,
             "address": f"Example Street {i}, Berlin"} for i in range(40)]
    first = AsyncMock(return_value=rows[:20])
    second = AsyncMock(return_value=rows[20:])
    monkeypatch.setattr(home, "PROVIDER_MAP", {"Kleinanzeigen": first, "WG-Gesucht": second})
    monkeypatch.setattr(home, "relevance_candidate_target", lambda _: 40)
    monkeypatch.setattr(home, "assess_home_evidence", AsyncMock(return_value=[]))
    monkeypatch.setattr(geo, "MAX_LOCATION_CANDIDATES", 5)
    provider = type("Provider", (), {})()
    provider.geocode_address = AsyncMock(return_value=GeoapifyPlacesSearchResult(status="ok", places=[{
        "properties": {"lat": 52.51, "lon": 13.29, "result_type": "street",
                       "rank": {"confidence": 0.99, "match_type": "match_by_street"}},
    }]))
    provider.search_places = AsyncMock(return_value=GeoapifyPlacesSearchResult(status="ok"))
    monkeypatch.setattr(geo, "GeoapifyPlacesProvider", lambda **kwargs: provider)

    async def rank(**kwargs):
        assert len(kwargs["candidates"]) == 5
        assert all(item["location"]["method"] == "address_geocode" for item in kwargs["candidates"])
        return SearchRelevanceRankingResult(candidates=kwargs["candidates"], applied=True)

    monkeypatch.setattr(home, "rank_search_candidates", rank)
    _, items, error, _ = await object.__new__(home.SearchSkill)._process_single_request({
        "query": "Berlin", "required_amenities": ["balcony"], "max_price_eur": 1000,
        "neighborhood_categories": ["water"], "max_results": 5,
    }, "request")
    assert error is None
    assert [item["id"] for item in items] == [str(i) for i in range(35, 40)]
    assert provider.geocode_address.await_count == 5
    assert all(item["location_precision"] == "street" and item["longitude"] == 13.29 for item in items)
    assert all(item["location"]["status"] != "candidate_limit" for item in items)


# contract-test: supporting surface=rest_api assertions=home-search.enrichment.bounded-and-reusable
def test_optional_geocoding_prioritizes_supported_preferences_preserving_price_ties():
    items = [
        {"id": "unknown", "match_evidence": {"unconfirmed_requirements": ["balcony"]}},
        {"id": "cheap"}, {"id": "supported", "balcony": True}, {"id": "expensive"},
    ]
    prioritized = home.prioritize_location_candidates(items, {"preferred_amenities": ["balcony"]})
    assert [item["id"] for item in prioritized] == ["supported", "cheap", "expensive", "unknown"]
    assert [item["id"] for item in items] == ["unknown", "cheap", "supported", "expensive"]
