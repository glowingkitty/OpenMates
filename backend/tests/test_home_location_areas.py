"""Home area contracts: synthetic ground truth, never real provider requests."""
import asyncio
from unittest.mock import AsyncMock

import pytest

from backend.apps.home import location_areas as areas
from backend.apps.home import location_enrichment as home
from backend.shared.providers.geoapify.places import GeoapifyPlacesSearchResult as Result


def region(name="Berlin", basis="city", bbox=None):
    return {"properties": {"name": name, "city": "Berlin", "result_type": basis,
                            "lat": 52.5, "lon": 13.4, "rank": {"confidence": 1}},
            "bbox": bbox or [13.0, 52.3, 13.8, 52.7]}


@pytest.mark.parametrize("listing,expected", [
    ({"address": "Kreuzberg, 10997 Berlin"}, False),
    ({"address": "10115 Berlin"}, False),
    ({"address": "Example Street 12a, Berlin"}, True),
    ({"address": "12 Example Street, London"}, True),
    ({"street": "Example Street", "house_number": "12"}, True),
    ({"street": "Example Street"}, False),
    ({"latitude": 52.5, "longitude": 13.4, "location_precision": "building"}, False),
    ({"address": "Our office 12, Berlin"}, False),
    ({"address": "500 m from Alexanderplatz, Berlin"}, False),
    ({"address": "Near Alexanderplatz 12, Berlin"}, False),
    ({"address": "5 minutes from Ostbahnhof, Berlin"}, False),
])
# contract-test: supporting surface=rest_api assertions=home-search.location.precision,home-search.enrichment.bounded-and-reusable,home-search.output.safe-and-truthful
def test_published_address_requires_a_house_not_a_postcode(listing, expected):
    assert areas.has_exact_address(listing) is expected


@pytest.mark.parametrize("latitude", [-65, -20, 0, 20, 52, 65])
@pytest.mark.parametrize("longitude", [-150, -100, -50, 0, 13, 40, 70, 100, 130, 170])
# contract-test: supporting surface=rest_api assertions=home-search.location.precision,home-search.enrichment.bounded-and-reusable,home-search.output.safe-and-truthful
def test_sixty_extents_are_enclosed(latitude, longitude):
    bbox = [longitude - .3, latitude - .2, longitude + .3, latitude + .2]
    area = areas.area_from_feature(region(bbox=bbox), basis="city", source="fixture")
    center = (area["latitude"], area["longitude"])
    for lat in (bbox[1], latitude, bbox[3]):
        for lon in (bbox[0], longitude, bbox[2]):
            assert areas.distance(center, (lat, lon)) <= area["radius_m"]
    assert area["basis"] == "city" and area["radius_m"] > 20000


# contract-test: supporting surface=rest_api assertions=home-search.location.precision,home-search.enrichment.bounded-and-reusable,home-search.output.safe-and-truthful
def test_extent_handles_dateline_and_rejects_points_without_extent():
    area = areas.area_from_feature(region(bbox=[179.8, -17.8, -179.8, -17.6]), basis="city", source="fixture")
    assert abs(area["longitude"]) == 180
    feature = region()
    del feature["bbox"]
    assert areas.area_from_feature(feature, basis="city", source="fixture") is None
    assert areas.area_from_feature(region(bbox=[-180, -90, 180, 90]), basis="city", source="fixture") is None
    assert areas.area_from_feature({"properties": "malformed", "geometry": []}, basis="city", source="fixture") is None


# contract-test: supporting surface=rest_api assertions=home-search.location.precision,home-search.enrichment.bounded-and-reusable,home-search.output.safe-and-truthful
def test_numeric_allowances_and_walking_are_conservative_not_model_radii():
    feature = {"properties": {"lat": 52.5, "lon": 13.4, "name": "Station X"}}
    clue = {"anchor_name": "Station X", "relation": "distance", "quantity": 500,
            "unit": "m", "evidence_quote": "about 500 m from Station X"}
    area = areas.clue_area(clue, feature, source="fixture", checked_at="2026-10-22")
    assert area["radius_m"] >= 500 + 125 + 250
    assert area["basis"] == "description" and area["evidence_quote"] == clue["evidence_quote"]
    walking = areas.clue_area({**clue, "relation": "walk_time", "quantity": 5, "unit": "minutes"}, feature, source="fixture", checked_at=None)
    assert walking["radius_m"] >= 500
    assert areas.clue_area({**clue, "relation": "near", "quantity": None}, feature, source="fixture", checked_at=None) is None


# contract-test: supporting surface=rest_api assertions=home-search.location.precision,home-search.enrichment.bounded-and-reusable,home-search.output.safe-and-truthful
def test_geo_match_must_match_the_advertised_address_and_anchor_type():
    listing = {"address": "Example Street 12, Berlin"}
    feature = {"properties": {"city": "Paris", "street": "Other Street", "housenumber": "99"}}
    assert not areas.matching_address(feature, listing, "Berlin")
    assert areas.matching_address({"properties": {"city": "Berlin", "street": "Example Street", "housenumber": "12"}}, listing, "Berlin")
    clue = {"anchor_type": "station", "anchor_name": "Alexanderplatz"}
    cafe = {"properties": {"name": "Cafe Alexanderplatz", "city": "Berlin", "categories": ["catering.cafe"]}}
    assert not areas.matching_anchor(cafe, clue, "Berlin")
    station = {"properties": {"name": "Alexanderplatz", "city": "Berlin", "categories": ["public_transport.train"]}}
    assert areas.matching_anchor(station, clue, "Berlin")
    assert not areas.matching_region({"properties": {"name": "Mitte", "result_type": "district"}}, "Mitte", "district", "Berlin")


@pytest.fixture
def geo(monkeypatch):
    fake = type("Provider", (), {})()
    fake.geocode_area = AsyncMock(return_value=Result(status="ok", places=[region()]))
    fake.geocode_address = AsyncMock(return_value=Result(status="no_match"))
    fake.search_places = AsyncMock(return_value=Result(status="ok"))
    monkeypatch.setattr(home, "GeoapifyPlacesProvider", lambda **kwargs: fake)
    monkeypatch.setattr(home, "geocode_address", AsyncMock(return_value=(52.52, 13.405)))
    monkeypatch.setattr(home, "extract_location_clues", AsyncMock(return_value={"status": "no_clues", "clues": []}))
    return fake


async def enrich(items):
    return await home.enrich_home_locations(items, city="Berlin", request={}, secrets_manager=None)


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=home-search.location.precision,home-search.enrichment.bounded-and-reusable,home-search.output.safe-and-truthful
async def test_coordinates_without_address_become_city_circle_and_retain_original(geo):
    item = {"latitude": 52.49, "longitude": 13.42, "location_precision": "building", "location_approximate": False}
    await enrich([item])
    assert item["location"]["exact_address"] is False
    assert item["location"]["area"]["basis"] == "city"
    assert item["location_approximate"] is True and item["location_precision"] != "building"
    assert item["location"]["provider_location"]["longitude"] == 13.42


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=home-search.location.precision,home-search.enrichment.bounded-and-reusable,home-search.output.safe-and-truthful
async def test_unrelated_building_cannot_turn_an_address_into_a_wrong_city_pin(geo):
    geo.geocode_address.return_value = Result(status="ok", places=[{
        "properties": {"city": "Paris", "street": "Other Street", "housenumber": "99",
                       "lat": 48.8, "lon": 2.3, "result_type": "building", "rank": {"confidence": 1}},
    }])
    item = {"address": "Example Street 12, Berlin"}
    await enrich([item])
    assert item["location_approximate"] is True
    assert item["location_precision"] == "city"
    assert item["location"]["area"]["basis"] == "city"
    assert item["latitude"] > 52 and item["longitude"] > 13


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=home-search.location.precision,home-search.enrichment.bounded-and-reusable,home-search.output.safe-and-truthful
async def test_district_precedes_city_and_exact_address_stays_precise(geo):
    async def lookup(query):
        feature = region("Kreuzberg", "district", [13.35, 52.47, 13.45, 52.52]) if "Kreuzberg" in query else region()
        return Result(status="ok", places=[feature])
    geo.geocode_area.side_effect = lookup
    item = {"district": "Kreuzberg", "city": "Berlin", "latitude": 52.49, "longitude": 13.4}
    exact = {"address": "Example Street 12, Berlin", "latitude": 52.5, "longitude": 13.4,
             "location_precision": "building", "location_approximate": False}
    await enrich([item, exact])
    assert item["location"]["area"]["basis"] == "district"
    assert exact["location"]["exact_address"] is True
    assert exact["location_approximate"] is False and "area" not in exact["location"]


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=home-search.location.precision,home-search.enrichment.bounded-and-reusable,home-search.output.safe-and-truthful
async def test_refinement_failure_and_deadline_retain_city_circle(geo, monkeypatch):
    async def slow(*args, **kwargs):
        await asyncio.sleep(1)
    monkeypatch.setattr(home, "extract_location_clues", slow)
    monkeypatch.setattr(home, "LOCATION_TIMEOUT_SECONDS", .02)
    item = {"description": "Close to station X"}
    warnings = await enrich([item])
    assert item["location"]["area"]["basis"] == "city"
    assert any("time limit" in warning for warning in warnings)


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=home-search.location.precision,home-search.enrichment.bounded-and-reusable,home-search.output.safe-and-truthful
async def test_grounded_numeric_anchor_refines_and_namesake_conflicts_abstain(geo, monkeypatch):
    clue = {"anchor_name": "Station X", "anchor_type": "station", "relation": "distance", "quantity": 500, "unit": "m", "evidence_quote": "500 m from Station X"}
    monkeypatch.setattr(home, "extract_location_clues", AsyncMock(return_value={"status": "ok", "clues": [clue]}))
    anchor = {"properties": {"name": "Station X", "categories": ["public_transport.station"], "city": "Berlin", "lat": 52.5, "lon": 13.4, "rank": {"confidence": 1}}}
    geo.geocode_address.return_value = Result(status="ok", places=[anchor])
    item = {"latitude": 52.49, "longitude": 13.42, "description": clue["evidence_quote"]}
    await enrich([item])
    assert item["location"]["area"]["basis"] == "description"
    assert item["location"]["refinement_status"] == "estimated"
    other = {"properties": {**anchor["properties"], "lon": 13.5}}
    geo.geocode_address.return_value = Result(status="ok", places=[anchor, other])
    ambiguous = {"description": clue["evidence_quote"], "latitude": 52.5, "longitude": 13.4}
    await enrich([ambiguous])
    assert ambiguous["location"]["area"]["basis"] == "city"
    assert ambiguous["location"]["refinement_status"] == "ambiguous"


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=home-search.location.precision,home-search.enrichment.bounded-and-reusable,home-search.output.safe-and-truthful
async def test_candidate_cap_still_downgrades_unaddressed_building_claims(geo, monkeypatch):
    monkeypatch.setattr(home, "MAX_LOCATION_CANDIDATES", 0)
    item = {"latitude": 52.5, "longitude": 13.4, "location_precision": "building", "location_approximate": False}
    await enrich([item])
    assert item["location_approximate"] is True
    assert item["location_precision"] != "building"
    assert item["location"]["exact_address"] is False
