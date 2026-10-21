"""Mocked home geography contracts; no real API calls or shared runtime.

Spec: specifications/features/app-skills/home-search/specification.yml
"""
import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.apps.home import location_enrichment as home
from backend.shared.providers.geoapify.places import GeoapifyPlacesProvider, GeoapifyPlacesSearchResult

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def provider(monkeypatch):
    fake = type("Provider", (), {})()
    fake.geocode_address = AsyncMock(return_value=GeoapifyPlacesSearchResult(status="not_configured"))
    fake.search_places = AsyncMock(return_value=GeoapifyPlacesSearchResult(status="ok", checked_at="2026-10-01T12:00:00+00:00"))
    fake.walking_route = AsyncMock(return_value=GeoapifyPlacesSearchResult(status="unavailable"))
    monkeypatch.setattr(home, "GeoapifyPlacesProvider", lambda **kwargs: fake)
    monkeypatch.setattr(home, "geocode_address", AsyncMock(return_value=(52.52, 13.405)))
    return fake


def point(lon=13.401, lat=52.52, **properties):
    return {"properties": {"name": "Water", "lon": lon, "lat": lat, **properties}, "geometry": {"type": "Point", "coordinates": [lon, lat]}}


def listing(**kwargs):
    return {"latitude": 52.52, "longitude": 13.4, "location_precision": "building", "provider": "Example", **kwargs}


async def run(items, request=None):
    return await home.enrich_home_locations(items, city="Berlin", request=request or {}, secrets_manager=None)


# contract-test: supporting surface=rest_api assertions=home-search.location.precision
async def test_provider_coordinates_and_approximation_survive(provider):
    items = [listing(location_precision="district", location_approximate=True)]
    await run(items, {"neighborhood_categories": ["water"]})
    assert items[0]["latitude"] == 52.52
    assert items[0]["location"]["precision"] == "district"
    assert items[0]["location"]["approximate"] is True
    assert items[0]["neighborhood"]["status"] == "approximate_location"
    provider.geocode_address.assert_not_awaited()
    provider.search_places.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=home-search.location.precision
async def test_address_match_retains_actual_precision_and_provenance(provider):
    provider.geocode_address.return_value = GeoapifyPlacesSearchResult(
        status="ok", checked_at="2026-10-01", cache_hit=True,
        places=[point(result_type="street", rank={"confidence": 0.95, "match_type": "match_by_street"})],
    )
    items = [{"address": "Example Street"}]
    await run(items)
    assert items[0]["location"]["precision"] == "street"
    assert items[0]["location"]["approximate"] is True
    assert items[0]["location"]["checked_at"] == "2026-10-01"
    assert items[0]["location"]["cache_hit"] is True
    assert items[0]["location"]["match_type"] == "match_by_street"


# contract-test: supporting surface=rest_api assertions=home-search.location.precision
async def test_ambiguous_address_uses_city_fallback_without_precise_distances(provider):
    provider.geocode_address.return_value = GeoapifyPlacesSearchResult(
        status="ok", places=[point(rank={"confidence": 1}, result_type="building"), point(lon=13.5, rank={"confidence": 1}, result_type="building")],
    )
    items = [{"address": "Hidden address"}]
    await run(items, {"neighborhood_categories": ["water"]})
    assert items[0]["location"]["precision"] == "city"
    assert items[0]["location"]["geocode_status"] == "ambiguous"
    assert items[0]["neighborhood"]["features"]["water"] == []
    provider.search_places.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=home-search.neighborhood.sourced-facts
async def test_requested_categories_only_with_freshness_and_partial_empty_coverage(provider):
    items = [listing()]
    await run(items, {"relevance_criteria": "Near a park, groceries and public transport"})
    assert home.requested_categories({"relevance_criteria": "am Wasser mit Schule und ÖPNV"}) == ["water", "transit", "school"]
    coverage = items[0]["neighborhood"]["coverage"]
    assert set(coverage) == {"park", "groceries", "transit"}
    assert coverage["park"]["exhaustive"] is False
    assert coverage["park"]["status"] == "no_features_returned"
    assert coverage["park"]["checked_at"] == "2026-10-01T12:00:00+00:00"
    assert provider.search_places.await_count == 3


# contract-test: supporting surface=rest_api assertions=home-search.water.distance-and-access
async def test_polygon_shoreline_is_measured_not_water_centroid(provider):
    feature = point(lon=13.45, categories=["natural.water"])
    feature["geometry"] = {"type": "Polygon", "coordinates": [[[13.401, 52.519], [13.5, 52.519], [13.5, 52.521], [13.401, 52.521], [13.401, 52.519]]]}
    provider.search_places.return_value = GeoapifyPlacesSearchResult(status="ok", places=[feature])
    items = [listing()]
    warnings = await run(items, {"max_water_distance_m": 100, "max_water_walk_minutes": 10})
    fact = items[0]["neighborhood"]["features"]["water"][0]
    assert fact["distance_method"] == "shoreline_geometry"
    assert 60 < fact["distance_m"] < 75
    assert fact["walk_minutes"] is None
    assert any("Walking access" in warning for warning in warnings)
    provider.walking_route.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=home-search.water.distance-and-access
async def test_water_representative_point_and_street_location_never_imply_shoreline(provider):
    provider.search_places.return_value = GeoapifyPlacesSearchResult(status="ok", places=[point()])
    items = [listing(), listing(location_precision="street")]
    await run(items, {"neighborhood_categories": ["water"]})
    precise = items[0]["neighborhood"]["features"]["water"][0]
    street = items[1]["neighborhood"]["features"]["water"][0]
    assert precise["distance_method"] == "representative_point"
    assert precise["walk_minutes"] is None
    assert street["distance_m"] is None
    assert street["distance_method"] == "unknown"


# contract-test: supporting surface=rest_api assertions=home-search.water.distance-and-access
async def test_only_explicit_public_pier_geometry_allows_provider_walking_route(provider):
    pier = point(datasource={"raw": {"man_made": "pier", "access": "public"}})
    pier["geometry"] = {"type": "LineString", "coordinates": [[13.401, 52.52], [13.402, 52.52]]}
    provider.search_places.return_value = GeoapifyPlacesSearchResult(status="ok", places=[point(lon=13.4001), pier])
    provider.walking_route.return_value = GeoapifyPlacesSearchResult(status="ok", places=[{"properties": {"time": 480, "distance": 650}}], checked_at="route-time")
    items = [listing()]
    await run(items, {"max_water_walk_minutes": 10})
    facts = items[0]["neighborhood"]["features"]["water"]
    assert facts[0]["walk_minutes"] is None
    assert facts[1]["walk_minutes"] == 8
    assert facts[1]["walk_method"] == "provider_walking_route"
    assert facts[1]["walk_checked_at"] == "route-time"
    assert facts[1]["walk_target"]["longitude"] == 13.401
    assert provider.walking_route.await_count == 1
    pier["properties"]["datasource"]["raw"]["foot"] = "no"
    assert home._public_waterfront_target(pier, (52.52, 13.4)) is None


# contract-test: supporting surface=rest_api assertions=home-search.neighborhood.sourced-facts
async def test_quota_exhaustion_preserves_listings_and_unknown_coverage(provider):
    provider.search_places.return_value = GeoapifyPlacesSearchResult(status="quota_exhausted")
    items = [listing(title="Useful apartment")]
    warnings = await run(items, {"neighborhood_categories": ["park"]})
    assert items[0]["title"] == "Useful apartment"
    assert items[0]["neighborhood"]["coverage"]["park"]["status"] == "quota_exhausted"
    assert any("quota_exhausted" in warning for warning in warnings)


# contract-test: supporting surface=rest_api assertions=home-search.enrichment.bounded-and-reusable
async def test_call_candidate_and_concurrency_limits(provider, monkeypatch):
    monkeypatch.setattr(home, "MAX_LOCATION_CANDIDATES", 4)
    monkeypatch.setattr(home, "MAX_LOCATION_REQUESTS", 5)
    active = peak = 0

    async def places(**kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.001)
        active -= 1
        return GeoapifyPlacesSearchResult(status="ok")

    provider.search_places.side_effect = places
    items = [listing() for _ in range(8)]
    warnings = await run(items, {"neighborhood_categories": list(home.CATEGORIES)})
    assert provider.search_places.await_count == 5
    assert peak <= home.MAX_LOCATION_CONCURRENCY
    assert items[4]["neighborhood"]["status"] == "candidate_limit"
    assert any("candidate limit" in warning for warning in warnings)


# contract-test: supporting surface=rest_api assertions=home-search.enrichment.bounded-and-reusable
async def test_total_timeout_cancels_work_and_exposes_partial_coverage(provider, monkeypatch):
    monkeypatch.setattr(home, "LOCATION_TIMEOUT_SECONDS", 0.01)

    async def slow(**kwargs):
        await asyncio.sleep(30)

    provider.search_places.side_effect = slow
    items = [listing() for _ in range(6)]
    warnings = await run(items, {"neighborhood_categories": ["water"]})
    assert any("time limit" in warning for warning in warnings)
    assert all(item["neighborhood"]["status"] == "timed_out" for item in items)
    assert all(item["neighborhood"]["coverage"]["water"]["status"] == "timed_out" for item in items)


# contract-test: supporting surface=rest_api assertions=home-search.enrichment.bounded-and-reusable
async def test_address_provider_uses_shared_budget_hashed_cache_and_actual_result_types(monkeypatch):
    cache = type("Cache", (), {})()
    values = {}
    cache.get = AsyncMock(side_effect=lambda key: values.get(key))

    async def put(key, value, ttl):
        values[key] = value

    cache.set = AsyncMock(side_effect=put)
    budget = AsyncMock(return_value="ok")
    monkeypatch.setattr("backend.shared.providers.geoapify.places.reserve_credit", budget)
    transport = AsyncMock(return_value=httpx.Response(200, json={"features": [point(result_type="city")]}))
    real = GeoapifyPlacesProvider(secrets_manager=None, cache_service=cache, http_get=transport)
    real.get_api_key = AsyncMock(return_value="private-key")
    first = await real.geocode_address("Private address 123, Berlin")
    second = await real.geocode_address("Private address 123, Berlin")
    assert first.places[0]["properties"]["result_type"] == "city"
    assert first.checked_at and second.checked_at == first.checked_at
    assert second.cache_hit
    assert transport.await_count == budget.await_count == 1
    assert "type" not in transport.await_args.args[1]
    assert all("Private" not in key and "private-key" not in key for key in values)
    budget.return_value = "quota_exhausted"
    result = await real.geocode_address("Other address")
    assert result.status == "quota_exhausted"
    assert transport.await_count == 1


# contract-test: supporting surface=rest_api assertions=home-search.water.distance-and-access
async def test_route_provider_is_metered_cached_and_uses_walking_mode(monkeypatch):
    values = {}
    cache = type("Cache", (), {})()
    cache.get = AsyncMock(side_effect=lambda key: values.get(key))

    async def put(key, value, ttl):
        values[key] = value

    cache.set = AsyncMock(side_effect=put)
    budget = AsyncMock(return_value="ok")
    monkeypatch.setattr("backend.shared.providers.geoapify.places.reserve_credit", budget)
    transport = AsyncMock(return_value=httpx.Response(200, json={"features": [{"properties": {"time": 300, "distance": 400}}]}))
    real = GeoapifyPlacesProvider(secrets_manager=None, cache_service=cache, http_get=transport)
    real.get_api_key = AsyncMock(return_value="secret")
    result = await real.walking_route(origin=(52.52, 13.4), target=(52.52, 13.401))
    cached = await real.walking_route(origin=(52.52, 13.4), target=(52.52, 13.401))
    assert result.status == "ok" and cached.cache_hit
    assert transport.await_args.args[1]["mode"] == "walk"
    assert budget.await_count == transport.await_count == 1
    far = await real.walking_route(origin=(52.52, 13.4), target=(1, 1))
    assert far.status == "out_of_range"
    assert transport.await_count == 1


# contract-test: supporting surface=rest_api assertions=home-search.location.precision
async def test_building_result_with_street_match_is_not_apartment_precision(provider):
    provider.geocode_address.return_value = GeoapifyPlacesSearchResult(
        status="ok", places=[point(result_type="building", rank={"confidence": 0.99, "match_type": "match_by_street"})],
    )
    items = [{"address": "Example Street"}]
    await run(items)
    assert items[0]["location"]["provider_result_type"] == "building"
    assert items[0]["location"]["precision"] == "street"
    assert items[0]["location"]["approximate"] is True


# contract-test: supporting surface=rest_api assertions=home-search.water.distance-and-access
async def test_pier_polygon_is_not_water_shoreline(provider):
    feature = point(categories=["man_made.pier"])
    feature["geometry"] = {"type": "Polygon", "coordinates": [[[13.401, 52.519], [13.402, 52.519], [13.402, 52.521], [13.401, 52.519]]]}
    provider.search_places.return_value = GeoapifyPlacesSearchResult(status="ok", places=[feature])
    items = [listing()]
    await run(items, {"neighborhood_categories": ["water"]})
    assert items[0]["neighborhood"]["features"]["water"][0]["distance_method"] == "feature_geometry"


# contract-test: supporting surface=rest_api assertions=home-search.location.precision
async def test_provider_initialized_unknown_default_does_not_prevent_exact_address_geocode(provider):
    from backend.shared.providers.housing.details import defaults, location

    item = defaults({"provider": "ImmoScout24", "address": "Example Street 123, Berlin"})
    location(item, {"street": "Example Street", "houseNumber": "123", "city": "Berlin"})
    # Older normalized records used True for an unknown point. This is not an
    # explicit provider declaration and has neither coordinates nor a source.
    item["location_approximate"] = True
    assert item["latitude"] is None and item["location_source"] is None
    provider.geocode_address.return_value = GeoapifyPlacesSearchResult(
        status="ok", places=[point(result_type="building", rank={"confidence": 1, "match_type": "full_match"})],
    )
    await run([item])
    assert item["location_precision"] == "building"
    assert item["location_approximate"] is False
    assert item["location"]["approximate"] is False
    assert item["location_source"] == item["location"]["source"] == home.GEOAPIFY_SOURCE_LABEL


# contract-test: supporting surface=rest_api assertions=home-search.location.precision
@pytest.mark.parametrize("declaration", [
    {"location_approximation_declared": True},
    {"approximate": True},
    {"location_source": "ImmoScout24", "location_approximate": True},
    {"location": {"approximate": True, "source": "ImmoScout24"}},
])
async def test_intentionally_approximate_full_address_stays_approximate(provider, declaration):
    from backend.shared.providers.housing.details import defaults

    item = defaults({"provider": "ImmoScout24", "address": "Example Street 123, Berlin", **declaration})
    provider.geocode_address.return_value = GeoapifyPlacesSearchResult(
        status="ok", places=[point(result_type="building", rank={"confidence": 1, "match_type": "full_match"})],
    )
    await run([item])
    assert item["location_approximate"] is True
    assert item["location"]["approximate"] is True


# contract-test: supporting surface=rest_api assertions=home-search.location.precision
async def test_provider_point_root_source_matches_normalized_location(provider):
    item = listing(location_source="Advertised map point")
    await run([item])
    assert item["location_source"] == item["location"]["source"] == "Advertised map point"


# contract-test: supporting surface=rest_api assertions=home-search.location.precision
async def test_raw_provider_approximate_declaration_without_coordinates_survives_geocode(provider):
    from backend.shared.providers.housing.details import defaults, location

    item = defaults({"provider": "ImmoScout24", "address": "Example Street 123, Berlin"})
    location(item, {"street": "Example Street", "houseNumber": "123", "city": "Berlin", "approximate": True})
    assert item["latitude"] is None
    assert item["location_approximation_declared"] is True
    provider.geocode_address.return_value = GeoapifyPlacesSearchResult(
        status="ok", places=[point(result_type="building", rank={"confidence": 1, "match_type": "full_match"})],
    )
    await run([item])
    assert item["location"]["approximate"] is True
    assert item["location_approximate"] is True


# contract-test: supporting surface=rest_api assertions=home-search.location.precision
async def test_known_city_fallback_does_not_block_source_grounded_street_geocoding(provider):
    item = listing(address="Witzlebenstraße, 14057, Charlottenburg", location_precision="street",
                   longitude=13.405, location_approximate=True, location_source="city_lookup",
                   location={"status": "candidate_limit", "precision": "street", "source": "WG-Gesucht", "method": "unknown"})
    provider.geocode_address.return_value = GeoapifyPlacesSearchResult(
        status="ok", places=[point(lon=13.29, lat=52.51, result_type="street", rank={"confidence": 0.99, "match_type": "match_by_street"})],
    )
    await run([item])
    provider.geocode_address.assert_awaited_once()
    assert item["latitude"] == 52.51 and item["longitude"] == 13.29
    assert item["location"]["method"] == "address_geocode"
    assert item["location_precision"] == item["location"]["precision"] == "street"
    assert item["location_source"] == item["location"]["source"] == home.GEOAPIFY_SOURCE_LABEL


# contract-test: supporting surface=rest_api assertions=home-search.location.precision
async def test_city_fallback_outside_candidate_budget_keeps_city_provenance(provider, monkeypatch):
    monkeypatch.setattr(home, "MAX_LOCATION_CANDIDATES", 0)
    item = listing(location_precision="street", location_source="city_lookup", location_approximate=True,
                   location={"precision": "street", "source": "WG-Gesucht", "method": "unknown"})
    await run([item], {"neighborhood_categories": ["water"]})
    assert item["location_precision"] == item["location"]["precision"] == "city"
    assert item["location_source"] == item["location"]["source"] != "WG-Gesucht"
    assert item["location"]["method"] == "city_fallback"
    assert item["location"]["approximate"] is True
    provider.geocode_address.assert_not_awaited()
    provider.search_places.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=home-search.location.precision
async def test_real_provider_point_at_city_center_is_never_guessed_to_be_fallback(provider):
    item = listing(longitude=13.405, location_precision="district", location_approximate=True, location_source="WG-Gesucht")
    await run([item])
    assert item["longitude"] == 13.405
    assert item["location_source"] == "WG-Gesucht"
    assert item["location_precision"] == "district"
    provider.geocode_address.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=home-search.enrichment.bounded-and-reusable
async def test_coordinates_use_finite_budget_before_optional_category_calls(provider, monkeypatch):
    monkeypatch.setattr(home, "MAX_LOCATION_REQUESTS", 3)
    provider.geocode_address.return_value = GeoapifyPlacesSearchResult(
        status="ok", places=[point(result_type="building", rank={"confidence": 0.99, "match_type": "full_match"})],
    )
    items = [{"address": f"Example Street {i}"} for i in range(3)]
    await run(items, {"neighborhood_categories": list(home.CATEGORIES)})
    assert provider.geocode_address.await_count == 3
    provider.search_places.assert_not_awaited()
    assert all(item["location"]["method"] == "address_geocode" for item in items)
    assert all(item["neighborhood"]["coverage"]["park"]["status"] == "request_limit" for item in items)
