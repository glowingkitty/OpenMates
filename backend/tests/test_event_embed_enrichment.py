"""Server-side event coordinates: deterministic geocoding, never a bogus map."""

import asyncio

import pytest

from backend.core.api.app.services import event_embed_enrichment as enrichment


@pytest.fixture(autouse=True)
def _clear_cache():
    enrichment._cache.clear()
    yield
    enrichment._cache.clear()


def _fake_geocoder(calls, result=(50.8129, 4.3817)):
    async def fake(address, city=None, country=None):
        calls.append((address, city, country))
        return result
    return fake


# contract-test: supporting surface=rest_api assertions=authored-results.facts.provenance-and-drafts
@pytest.mark.parametrize("lat,lon", [(None, None), (float("nan"), 4.0), (0, 0), (91, 0), (0, 181), ("x", 1)])
def test_invalid_coordinates_are_rejected(lat, lon):
    assert enrichment.valid_coordinates(lat, lon) is None


# contract-test: supporting surface=rest_api assertions=authored-results.facts.provenance-and-drafts
def test_valid_coordinates_are_kept():
    assert enrichment.valid_coordinates("50.8", 4.38) == (50.8, 4.38)


# contract-test: supporting surface=rest_api assertions=authored-results.facts.provenance-and-drafts
def test_event_venue_without_coordinates_is_geocoded(monkeypatch):
    calls = []
    monkeypatch.setattr(enrichment, "geocode_address", _fake_geocoder(calls))
    content = {"title": "FOSDEM 2027", "venue": {"name": "ULB Solbosch", "city": "Brussels", "country": "Belgium"}}
    result = asyncio.run(enrichment.enrich_event_coordinates("event", content))
    assert result["venue"]["lat"] == 50.8129 and result["venue"]["lon"] == 4.3817
    assert calls == [("ULB Solbosch", "Brussels", "Belgium")]
    # Second identical venue hits the cache, not the provider.
    asyncio.run(enrichment.enrich_event_coordinates("event", {"venue": {"name": "ULB Solbosch", "city": "Brussels", "country": "Belgium"}}))
    assert len(calls) == 1


# contract-test: supporting surface=rest_api assertions=authored-results.facts.provenance-and-drafts
def test_null_island_is_stripped_and_regeocoded(monkeypatch):
    calls = []
    monkeypatch.setattr(enrichment, "geocode_address", _fake_geocoder(calls, result=None))
    content = {"venue": {"address": "Av. Franklin Roosevelt 50", "city": "Brussels", "lat": 0, "lon": 0}}
    result = asyncio.run(enrichment.enrich_event_coordinates("event", content))
    assert "lat" not in result["venue"] and "lon" not in result["venue"]
    assert calls == [("Av. Franklin Roosevelt 50", "Brussels", None)]


# contract-test: supporting surface=rest_api assertions=authored-results.facts.provenance-and-drafts
def test_online_and_non_event_content_is_untouched(monkeypatch):
    calls = []
    monkeypatch.setattr(enrichment, "geocode_address", _fake_geocoder(calls))
    online = {"online": True, "venue": {"city": "Brussels"}}
    other = {"venue": {"city": "Brussels"}}
    asyncio.run(enrichment.enrich_event_coordinates("event", online))
    asyncio.run(enrichment.enrich_event_coordinates("recipe", other))
    assert calls == [] and "lat" not in online["venue"] and "lat" not in other["venue"]


# contract-test: supporting surface=rest_api assertions=authored-results.facts.provenance-and-drafts
def test_geocoder_timeout_leaves_event_without_map(monkeypatch):
    async def slow(*_args, **_kwargs):
        await asyncio.sleep(1)
        return (1.0, 1.0)
    monkeypatch.setattr(enrichment, "geocode_address", slow)
    monkeypatch.setattr(enrichment, "GEOCODE_TIMEOUT_SECONDS", 0.01)
    content = {"location": "Brussels"}
    result = asyncio.run(enrichment.enrich_event_coordinates("event_result", content))
    assert result["venue"] == {"name": "Brussels"}


# contract-test: supporting surface=rest_api assertions=authored-results.facts.provenance-and-drafts
def test_authored_cards_replace_model_written_coordinates_with_geocoded_venue(monkeypatch):
    calls = []
    monkeypatch.setattr(enrichment, "geocode_address", _fake_geocoder(calls))
    authored = {"venue": {"name": "ULB Solbosch", "city": "Brussels", "lat": 50.851, "lon": 4.352}}
    asyncio.run(enrichment.enrich_event_coordinates("event", authored, trust_supplied=False))
    assert (authored["venue"]["lat"], authored["venue"]["lon"]) == (50.8129, 4.3817)
    provider = {"venue": {"name": "Hall", "city": "Brussels", "lat": 50.851, "lon": 4.352}}
    asyncio.run(enrichment.enrich_event_coordinates("event", provider))
    assert provider["venue"]["lat"] == 50.851 and len(calls) == 1
