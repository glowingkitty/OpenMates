"""Regression coverage for city-only FOSDEM listings from public discovery."""
from datetime import date
from unittest.mock import AsyncMock

import pytest

from backend.apps.events.providers import fosdem
from backend.apps.events.skills import search_skill
from backend.apps.events.skills.search_skill import SearchRequest, SearchSkill
from backend.shared.app_packages.provider_dispatch import InstalledProviderOutcome
from backend.shared.python_utils.web_source_billing import WebSourcePrices

HOME = "# FOSDEM'99\n\n30 & 31 January 2099\n\nBrussels, Belgium\n"
ABOUT = """FOSDEM is a non-commercial event organized by volunteers.
Free and open source software developers meet each other and attend talks and presentations.
FOSDEM vzw is a Belgian non-profit.
"""
TRANSPORT = """FOSDEM takes place at the ULB Solbosch Campus, Brussels, Belgium.

Université libre de Bruxelles
Campus du Solbosch
Avenue Franklin D. Roosevelt 50
1050 Bruxelles
Belgium

GPS coordinates: latitude N50.812375, longitude E4.380734.
"""


# contract-test: supporting surface=rest_api assertions=events-search.results.actionable
@pytest.mark.anyio
async def test_organizer_requires_the_requested_edition_and_unredirected_pages(monkeypatch):
    async def read(url, **kwargs):
        return {"url": url.replace("2098", "2099"), "markdown": HOME}

    monkeypatch.setattr(fosdem, "read_public_web_page", read)
    assert await fosdem.read_edition(2098) is None
    assert fosdem.edition_start({"title": "FOSDEM 2099: developer room", "date_start": "2099-01-30"}) is None
    assert fosdem.edition_start({"title": "FOSDEM by FOSDEM VZW", "date_start": "2099-01-30"}) == date(2099, 1, 30)


# contract-test: direct surface=rest_api assertions=events-search.results.actionable
@pytest.mark.anyio
async def test_listing_keeps_one_card_with_organizer_address_and_coordinates(monkeypatch):
    async def read(url, **kwargs):
        return {"url": url, "markdown": {
            "/2099/": HOME, "/2099/about/": ABOUT, "/2099/practical/transportation/": TRANSPORT,
        }[url.removeprefix("https://fosdem.org")]}

    monkeypatch.setattr(fosdem, "read_public_web_page", read)
    monkeypatch.setattr(search_skill, "_installed_provider_labels", lambda: {})
    monkeypatch.setattr(search_skill, "fetch_web_source_prices", AsyncMock(return_value=WebSourcePrices(
        10, "inception/mercury-3", {"tokens": {"input": {"per_credit_unit": 3335}, "output": {"per_credit_unit": 955}}})))
    seed = {
        "title": "FOSDEM by FOSDEM VZW", "url": "https://list.example/fosdem",
        "date_start": "2099-01-30", "venue": {"city": "Brussels", "lat": 50.851, "lon": 4.352},
        "description": "Directory summary", "provider": "list.example", "provider_id": "web",
        "source_page_url": "https://list.example/conferences", "source_page_title": "Conferences",
    }
    source = AsyncMock(return_value=InstalledProviderOutcome("web", results=[
        seed, {**seed, "title": "FOSDEM 2099", "url": "https://list.example/fosdem-2099"},
    ], usage={"web_search_requests": 1}))
    monkeypatch.setattr(search_skill, "run_web_source", source)
    skill = object.__new__(SearchSkill)
    response = await skill.execute(SearchRequest(requests=[
        {"query": "open source conferences in Europe"},
    ]), secrets_manager=object())
    result, = response.results[0]["results"]
    assert result["title"] == "FOSDEM 2099"
    assert result["url"] == "https://fosdem.org/2099/"
    assert result["date_end"] == "2099-01-31"
    assert result["venue"] == {
        "name": "ULB Solbosch Campus", "address": "Avenue Franklin D. Roosevelt 50",
        "city": "Brussels", "country": "Belgium", "lat": 50.812375, "lon": 4.380734,
    }
    assert "talks and presentations" in result["description"]
    assert result["organizer"] == "FOSDEM vzw"
    assert result["venue_source_url"] == "https://fosdem.org/2099/practical/transportation/"
    source.assert_awaited_once()
