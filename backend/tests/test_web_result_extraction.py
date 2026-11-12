"""Web pages as a search source: only what a page states becomes a result."""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from backend.shared.app_packages import web_source
from backend.shared.python_utils import web_result_extraction as extraction
from backend.shared.python_utils.public_web_reader import PublicWebReadError

EVENT_PAGE = """# Conferences 2027
| [Libre Days](https://example.org/libre) | 14-16 January 2027 | Lyon, France |
Tickets are EUR 35.
![Banner](https://example.org/banner.jpg)
"""
PRODUCT_PAGE = """## [Quiet Mask Pro](https://shop.example.org/p/quiet-mask-pro)
![Quiet Mask Pro](https://shop.example.org/img/quiet.jpg)
Voice mask with microphone. **189,00 €**
## Silent Mini
Price on request.
"""


def rows(kind: str, items: List[Dict[str, Any]], text: str) -> List[Dict[str, Any]]:
    return extraction.validated_rows(kind, items, page_url="https://www.example.org/list", page_title="List",
                                     page_text=text)


# contract-test: direct surface=rest_api assertions=instance-app-packages.web-source
def test_event_needs_a_title_and_date_written_on_the_page():
    kept = rows(extraction.KIND_EVENT, [
        {"title": "Libre Days", "date_start": "2027-01-14", "date_end": "2027-01-16", "city": "Lyon",
         "country": "France", "fee_text": "EUR 35", "url": "https://example.org/libre",
         "image_url": "https://example.org/banner.jpg"},
        {"title": "Invented Summit", "date_start": "2027-01-14"},
        {"title": "Libre Days", "date_start": "2028-06-03"},
        {"title": "Libre Days", "date_start": "soon"},
    ], EVENT_PAGE)
    assert len(kept) == 1
    event = kept[0]
    assert event["url"] == "https://example.org/libre" and event["date_end"] == "2027-01-16"
    assert event["venue"] == {"city": "Lyon", "country": "France"} and event["fee"] == "EUR 35"
    assert event["provider_id"] == "web" and event["provider"] == "example.org"
    assert event["source_page_url"] == "https://www.example.org/list"


# contract-test: direct surface=rest_api assertions=instance-app-packages.web-source
def test_price_link_and_picture_are_kept_only_when_the_page_states_them():
    kept = rows(extraction.KIND_PRODUCT, [
        {"title": "Quiet Mask Pro", "price_text": "189,00 €", "price_amount": 189.0, "currency": "eur",
         "url": "https://shop.example.org/p/quiet-mask-pro", "image_url": "https://shop.example.org/img/quiet.jpg"},
        {"title": "Silent Mini", "price_text": "99,00 €", "price_amount": 99.0, "currency": "EUR",
         "url": "https://evil.example.com/x", "image_url": "javascript:alert(1)"},
        {"title": "Unlisted Gadget", "price_text": "189,00 €"},
    ], PRODUCT_PAGE)
    assert [row["title"] for row in kept] == ["Quiet Mask Pro", "Silent Mini"]
    stated, unstated = kept
    assert stated["price"] == "189,00 €" and stated["price_amount"] == 189.0 and stated["currency"] == "EUR"
    assert stated["purchase_url"] == "https://shop.example.org/p/quiet-mask-pro"
    assert stated["image_urls"] == ["https://shop.example.org/img/quiet.jpg"]
    assert "price" not in unstated and "price_amount" not in unstated and "image_url" not in unstated
    assert unstated["purchase_url"] == "https://www.example.org/list"


@pytest.fixture
def fake_web(monkeypatch):
    calls: Dict[str, Any] = {"queries": [], "pages": []}

    async def search(query, secrets_manager, **kwargs):
        calls["queries"].append((query, kwargs.get("country"), kwargs.get("search_lang")))
        return {"results": [{"url": "https://a.example.org/1"}, {"url": "https://b.example.org/2"},
                            {"url": "https://c.example.org/3"}]}

    async def read(url, **kwargs):
        if "b.example" in url:
            raise PublicWebReadError("robots_denied", "denied")
        return {"markdown": PRODUCT_PAGE, "title": "Shop"}

    async def complete(kind, request, page_url, page_title, page_text, **kwargs):
        calls["pages"].append(page_url)
        if "c.example" in page_url:
            raise ValueError("bad answer")
        return [{"title": "Quiet Mask Pro", "price_text": "189,00 €"}], 100, 20

    monkeypatch.setattr(extraction, "search_web", search)
    monkeypatch.setattr(extraction, "read_public_web_page", read)
    monkeypatch.setattr(extraction, "complete_page", complete)
    return calls


# contract-test: direct surface=rest_api assertions=instance-app-packages.web-source
@pytest.mark.anyio
async def test_denied_pages_and_failed_extractions_only_reduce_the_results(fake_web):
    outcome = await web_source.run_web_source(extraction.KIND_PRODUCT, {
        "query": "voice mask", "country": "DE", "id": 7, "user_note": "private"}, None)
    assert outcome.provider_id == "web" and outcome.error is None
    assert [row["source_page_url"] for row in outcome.results] == ["https://a.example.org/1"]
    assert fake_web["queries"] == [("voice mask buy price", "de", "de")]
    assert sorted(fake_web["pages"]) == ["https://a.example.org/1", "https://c.example.org/3"]


# contract-test: direct surface=rest_api assertions=instance-app-packages.web-source
@pytest.mark.anyio
async def test_unavailable_web_search_is_a_warning_without_results(monkeypatch):
    async def search(query, secrets_manager, **kwargs):
        return {"results": [], "error": "quota"}

    monkeypatch.setattr(extraction, "search_web", search)
    outcome = await web_source.run_web_source(extraction.KIND_EVENT, {"query": "conferences"}, None)
    assert outcome.results == [] and outcome.error == "Web search is unavailable."


# contract-test: direct surface=rest_api assertions=instance-app-packages.web-source
def test_schema_is_strict_and_only_product_search_is_delegated():
    for kind in (extraction.KIND_EVENT, extraction.KIND_PRODUCT):
        item = extraction.response_schema(kind)["properties"]["items"]["items"]
        assert item["additionalProperties"] is False and set(item["required"]) == set(item["properties"])
    assert web_source.delegate_web_kind("shopping", "search_products") == extraction.KIND_PRODUCT
    assert web_source.delegate_web_kind("travel", "search_stays") is None


# contract-test: supporting surface=rest_api assertions=instance-app-packages.web-source
def test_routing_hint_names_the_web_source_only_next_to_a_provider_hint():
    from backend.shared.app_packages import overlay

    skill = {"id": "search", "preprocessor_hint": "Search events in a city."}
    overlay._add_web_source_hint("events", skill)
    assert skill["preprocessor_hint"].startswith("Search events in a city. ") and "public web pages" in skill[
        "preprocessor_hint"]
    bare = {"id": "search"}
    overlay._add_web_source_hint("events", bare)
    other = {"id": "search_stays", "preprocessor_hint": "Stays."}
    overlay._add_web_source_hint("travel", other)
    assert "preprocessor_hint" not in bare and other["preprocessor_hint"] == "Stays."
