"""Apartment constraints and pre-selection enrichment without provider traffic."""
from datetime import date

import pytest
from pydantic import ValidationError

from backend.apps.home.skills import search_skill as home


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


# contract-test: supporting surface=rest_api assertions=home-search.filters.explicit-and-unknown


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


# contract-test: supporting surface=rest_api assertions=home-search.filters.explicit-and-unknown
@pytest.mark.parametrize("excluded", [False, True])
def test_explicit_amenity_evidence_and_unknowns(excluded):
    mode = "excluded_amenities" if excluded else "required_amenities"
    items = [{"id": "yes", "amenities": {"balcony": True}}, {"id": "no", "balcony": False}, {"id": "unknown"},
             {"id": "possible", "match_evidence": {"amenities": {"balcony": {"status": "possible", "visual_status": "visible"}}}},
             {"id": "text", "match_evidence": {"amenities": {"balcony": {"text_status": "absent" if excluded else "present"}}}}]
    matches, warnings = home.filter_home_listings(items, {mode: ["balcony"]})
    assert [row["id"] for row in matches] == (["no", "text"] if excluded else ["yes", "text"])
    assert warnings


# contract-test: infrastructure
# Retained helper mechanics; no live discovery or historical rendering proof is claimed.
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


# contract-test: supporting surface=rest_api assertions=home-search.location.precision
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


# contract-test: supporting surface=rest_api assertions=home-search.filters.explicit-and-unknown
def test_soft_photo_evidence_never_becomes_confirmed_from_hard_filtering():
    item = {"match_evidence": {"status": "unconfirmed", "amenities": {"balcony": {"status": "possible", "visual_status": "visible"}}}}
    matches, _ = home.filter_home_listings([item], {"preferred_amenities": ["balcony"]})
    assert matches[0]["match_evidence"]["status"] == "unconfirmed"


# contract-test: infrastructure
# Retained helper mechanics; no live discovery or historical rendering proof is claimed.


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
    item = {"provider": "Example source", "location_precision": "street", "location_source": "Example source",
            "location": {"precision": "street", "source": "Example source", "method": "unknown", "status": "candidate_limit"}}
    await object.__new__(home.SearchSkill)._geocode_listings([item], "Berlin")
    assert item["latitude"] == 52.52 and item["longitude"] == 13.405
    assert item["location_precision"] == item["location"]["precision"] == "city"
    assert item["location_source"] == item["location"]["source"] != "Example source"
    assert item["location_approximate"] == item["location"]["approximate"] is True
    assert item["location"]["method"] == "city_fallback"
    assert item["location"]["geocode_status"] == "candidate_limit"


# contract-test: infrastructure
# Retained helper mechanics; no live discovery or historical rendering proof is claimed.


# contract-test: infrastructure
# Retained helper mechanics; no live discovery or historical rendering proof is claimed.
def test_optional_geocoding_prioritizes_supported_preferences_preserving_price_ties():
    items = [
        {"id": "unknown", "match_evidence": {"unconfirmed_requirements": ["balcony"]}},
        {"id": "cheap"}, {"id": "supported", "balcony": True}, {"id": "expensive"},
    ]
    prioritized = home.prioritize_location_candidates(items, {"preferred_amenities": ["balcony"]})
    assert [item["id"] for item in prioritized] == ["supported", "cheap", "expensive", "unknown"]
    assert [item["id"] for item in items] == ["unknown", "cheap", "supported", "expensive"]
