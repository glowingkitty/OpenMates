"""Bounded apartment-search tests without provider or geocoding traffic."""
import pytest

from backend.apps.home.skills import search_skill
from backend.apps.home.providers.wg_gesucht import _build_search_url


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=workflows.surface.semantic-parity
async def test_apartment_monitor_does_not_hide_new_listings_behind_cheapest(monkeypatch):
    calls = []
    async def provider(**kwargs):
        calls.append(kwargs)
        return [{"id": "new", "price": 1200, "rooms": 3}, {"id": "old", "price": 700, "rooms": 2}]
    async def no_geocode(*args, **kwargs):
        pass
    monkeypatch.setattr(search_skill, "PROVIDER_MAP", {"Kleinanzeigen": provider})
    skill = object.__new__(search_skill.SearchSkill)
    monkeypatch.setattr(skill, "_geocode_listings", no_geocode)
    _, listings, error, warnings = await skill._process_single_request({"query": "Berlin", "sort": "newest", "max_results": 1}, "request")
    assert [item["id"] for item in listings] == ["new"]
    assert not error and not warnings
    assert calls[0]["property_type"] == "apartment"
    assert calls[0]["max_results"] == 20
    assert "wohnungen-in-Berlin" in _build_search_url("Berlin", 8, category="2")
    _, listings, _, _ = await skill._process_single_request({"query": "Berlin", "max_price_eur": 1000}, "request")
    assert [item["id"] for item in listings] == ["old"]


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=workflows.surface.semantic-parity
async def test_provider_failure_is_distinct_from_empty_and_partial(monkeypatch):
    async def fail(**kwargs):
        raise RuntimeError("Provider returned HTTP 429")
    async def empty(**kwargs):
        return []
    async def no_geocode(*args, **kwargs):
        pass
    skill = object.__new__(search_skill.SearchSkill)
    monkeypatch.setattr(skill, "_geocode_listings", no_geocode)
    monkeypatch.setattr(search_skill, "PROVIDER_MAP", {"Kleinanzeigen": fail})
    _, listings, error, _ = await skill._process_single_request({"query": "Berlin"}, "request")
    assert not listings and "HTTP 429" in error
    monkeypatch.setattr(search_skill, "PROVIDER_MAP", {"Kleinanzeigen": fail, "ImmoScout24": empty})
    _, listings, error, warnings = await skill._process_single_request({"query": "Berlin"}, "request")
    assert not listings and error is None and "HTTP 429" in warnings[0]
    monkeypatch.setattr(search_skill, "PROVIDER_MAP", {"Kleinanzeigen": empty})
    _, listings, error, warnings = await skill._process_single_request({"query": "Berlin"}, "request")
    assert not listings and error is None and not warnings


# contract-test: supporting surface=rest_api assertions=workflows.surface.semantic-parity
def test_listing_links_preserve_provider_canonical_path():
    from backend.apps.home.providers.kleinanzeigen import _parse_listings_from_html
    html = '<article data-adid="123"><a class="ellipsis" href="/s-anzeige/flat/123-203-3331">Apartment</a></article>'
    listing = _parse_listings_from_html(html, "rent", "Berlin")[0]
    assert listing["id"] == "ka_123"
    assert listing["url"] == "https://www.kleinanzeigen.de/s-anzeige/flat/123-203-3331"
