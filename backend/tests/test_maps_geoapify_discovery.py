# contract-test: supporting surface=rest_api assertions=maps-search.discovery.bounded-provider-routing,maps-search.output.source-and-identity,maps-search.provider.budget-and-cache,maps-search.compatibility.regular-search
import asyncio
from types import SimpleNamespace

import httpx
import pytest

from backend.tests.test_geoapify_places_provider import _MemoryCache, _FakeSecretsManager
from backend.tests.test_maps_geoapify_enrichment import _prepare_skill
from backend.shared.providers.geoapify.budget import reserve_credit
from backend.shared.providers.geoapify.places import GEOAPIFY_SECRET_PATH, GeoapifyPlacesProvider
from backend.apps.maps.skills.discovery import CATEGORIES, DiscoveryArea, resolve_area

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def discovery_skill(monkeypatch):
    skill = await _prepare_skill(monkeypatch)
    cache = _MemoryCache()
    calls = []
    features = [{"properties": {
        "place_id": "provider-ruin-1", "lat": 52.52, "lon": 13.405,
        "categories": ["tourism.sights.ruines"],
        "datasource": {"raw": {"osm_type": "way", "osm_id": 123}},
    }}]

    async def fake_http(url, params, timeout):
        calls.append((url, dict(params)))
        if "geocode" in url:
            payload = [{"properties": {"lat": 52.52, "lon": 13.405, "rank": {"confidence": 1}}}]
        else:
            payload = features
        return httpx.Response(200, json={"features": payload})

    secrets = _FakeSecretsManager({(GEOAPIFY_SECRET_PATH, "api_key"): "private-geo-key"})

    async def get_secrets(*args, **kwargs):
        return secrets, None

    def provider_factory(**kwargs):
        return GeoapifyPlacesProvider(**kwargs, http_get=fake_http)

    async def forbidden_google(*args, **kwargs):
        raise AssertionError("Discovery must not invoke Google")

    monkeypatch.setattr(skill, "_get_or_create_secrets_manager", get_secrets)
    monkeypatch.setattr("backend.apps.maps.skills.search_skill.CacheService", lambda: cache)
    monkeypatch.setattr("backend.apps.maps.skills.search_skill.GeoapifyPlacesProvider", provider_factory)
    monkeypatch.setattr("backend.apps.maps.skills.search_skill.search_places", forbidden_google)
    return skill, calls, features, cache


def request(**overrides):
    return {"id": "ruins", "query": "Ruins near Berlin", "categories": ["ruins"],
            "area": {"latitude": 52.52, "longitude": 13.405, "radiusMeters": 10000}, **overrides}


# contract-test: supporting surface=rest_api assertions=maps-search.discovery.bounded-provider-routing,maps-search.output.source-and-identity
async def test_direct_search_ids_unknowns_and_parameter_order(discovery_skill):
    skill, calls, _, _ = discovery_skill
    result = await skill.execute([request()])
    assert result.error is None and result.provider == "Geoapify"
    group = result.results[0]
    place = group["results"][0]
    assert group["id"] == "ruins" and group["status"] == "ok"
    assert place["place_id"] == "geoapify:provider-ruin-1"
    assert place["name"] == "Unnamed ruins" and place["name_is_derived"]
    assert place["data_source"] == "OpenStreetMap via Geoapify"
    assert place["source_url"] == "https://www.openstreetmap.org/way/123"
    assert place["osm_enrichment"]["fields"]["wheelchair"]["value"] == "unknown"
    assert "rating" not in place and "open_now" not in place
    assert place["distance_meters"] == 0
    assert len(calls) == 1
    assert calls[0][1]["categories"] == "tourism.sights.ruines"
    assert calls[0][1]["filter"] == "circle:13.405,52.52,10000"
    assert "text" not in calls[0][1]


@pytest.mark.parametrize("category,provider_category", [(key, value[0]) for key, value in CATEGORIES.items()])
# contract-test: supporting surface=rest_api assertions=maps-search.discovery.bounded-provider-routing
async def test_all_six_category_mappings(discovery_skill, category, provider_category):
    skill, calls, _, _ = discovery_skill
    await skill.execute([request(categories=[category])])
    assert calls[0][1]["categories"] == provider_category


@pytest.mark.parametrize("overrides", [
    {"categories": []}, {"categories": ["abandoned"]}, {"area": None},
    {"area": {"latitude": 52.52}},
    {"area": {"latitude": float("nan"), "longitude": 13.4}},
    {"area": {"latitude": 91, "longitude": 13.4}},
    {"area": {"latitude": 52.52, "longitude": 13.4, "radiusMeters": 50001}},
    {"area": {"name": "Berlin", "latitude": 52.52, "longitude": 13.4}},
    {"minRating": 4}, {"openNow": True}, {"includeReviews": True},
])
# contract-test: supporting surface=rest_api assertions=maps-search.discovery.bounded-provider-routing
async def test_invalid_discovery_is_explicit_and_does_not_call_provider(discovery_skill, overrides):
    skill, calls, _, _ = discovery_skill
    result = await skill.execute([request(**overrides)])
    assert result.results[0]["error"]
    assert result.results[0]["status"] == "invalid_request"
    assert calls == []


# contract-test: supporting surface=rest_api assertions=maps-search.provider.budget-and-cache
async def test_named_area_and_search_cache_avoid_provider_calls(discovery_skill):
    skill, calls, _, cache = discovery_skill
    req = request(area={"name": "Berlin, Germany", "radiusMeters": 5000})
    first = await skill.execute([req])
    second = await skill.execute([{**req, "query": "Show historic ruins in Berlin"}])
    assert first.error is None and second.error is None
    assert len(calls) == 2  # One geocode and one search, no details request.
    assert second.results[0]["search_context"]["cache_hit"] is True
    assert all("Berlin" not in key and "private-geo-key" not in key for key in cache.values)
    keys = await cache.client.keys("geoapify:budget:*:20*")
    assert int(await cache.client.get(keys[0])) == 2


# contract-test: supporting surface=rest_api assertions=maps-search.output.source-and-identity
async def test_strict_unknown_amenities_and_bad_coordinates_are_not_matches(discovery_skill):
    skill, _, features, _ = discovery_skill
    features += [{"properties": {"place_id": "invalid", "lat": 999, "lon": 13.4}}]
    result = await skill.execute([request(amenityFilters={"wheelchair": True})])
    assert result.results[0]["results"] == []
    assert result.results[0]["filter_summary"]["candidate_count"] == 1
    assert result.results[0]["filter_summary"]["status"] == "no_verified_results"


# contract-test: supporting surface=rest_api assertions=maps-search.provider.budget-and-cache
async def test_quota_exhaustion_is_shared_across_endpoints_and_atomic(monkeypatch):
    cache = _MemoryCache()
    monkeypatch.setenv("GEOAPIFY_DAILY_CREDIT_LIMIT", "3")
    statuses = await asyncio.gather(*(reserve_credit(cache, "key") for _ in range(12)))
    assert statuses.count("ok") == 3
    assert statuses.count("quota_exhausted") == 9
    calls = []

    async def http(*args):
        calls.append(args)
        return httpx.Response(200, json={"features": []})

    provider = GeoapifyPlacesProvider(
        secrets_manager=_FakeSecretsManager({(GEOAPIFY_SECRET_PATH, "api_key"): "key"}),
        cache_service=cache, http_get=http,
    )
    assert (await provider.search_places(query="", categories=["amenity.toilet"])).status == "quota_exhausted"
    assert (await provider.geocode_area("Berlin, Germany")).status == "quota_exhausted"
    assert (await provider.get_place_details(place_id="place")).status == "quota_exhausted"
    assert calls == []


# contract-test: supporting surface=rest_api assertions=maps-search.provider.budget-and-cache
async def test_budget_failure_is_closed_and_rate_guard_is_shared(monkeypatch):
    assert await reserve_credit(None, "key") == "quota_unavailable"
    assert await reserve_credit(SimpleNamespace(client=None), "key") == "quota_unavailable"
    cache = _MemoryCache()
    for _ in range(5):
        assert await reserve_credit(cache, "key") == "ok"
    sleeps = []

    async def no_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr("backend.shared.providers.geoapify.budget.asyncio.sleep", no_sleep)
    assert await reserve_credit(cache, "key") == "rate_limited"
    assert len(sleeps) == 1 and 0 < sleeps[0] <= 1.05
    assert await reserve_credit(cache, "different-key") == "ok"


# contract-test: supporting surface=rest_api assertions=maps-search.discovery.bounded-provider-routing
def test_area_requires_explicit_center():
    assert DiscoveryArea(name="Berlin, Germany").radiusMeters == 10000


# contract-test: supporting surface=rest_api assertions=maps-search.output.source-and-identity
async def test_malformed_and_outside_area_features_do_not_drop_group(discovery_skill):
    skill, _, features, _ = discovery_skill
    features.extend([
        {"properties": []}, {"geometry": []},
        {"properties": {"lat": 52.52, "lon": 13.405, "datasource": [], "categories": 10}},
        {"properties": {"lat": 0, "lon": 0, "place_id": "outside-area"}},
    ])
    result = await skill.execute([request()])
    assert len(result.results) == 1 and result.error is None
    assert len(result.results[0]["results"]) == 2


# contract-test: supporting surface=rest_api assertions=maps-search.discovery.bounded-provider-routing
def test_ambiguous_or_unknown_area_requires_clarification():
    center, error = resolve_area([
        {"properties": {"lat": 40, "lon": 10, "rank": []}},
        {"properties": {"lat": 50, "lon": 10}},
    ])
    assert center is None and "ambiguous" in error
    assert resolve_area([{ "properties": [] }])[0] is None
