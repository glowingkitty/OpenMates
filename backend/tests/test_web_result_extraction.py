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
def test_web_event_preserves_only_a_street_address_stated_on_the_page():
    text = EVENT_PAGE + "Venue entrance: [24 rue des Fleurs, **Lyon**](https://maps.example.org/venue).\n"
    event = {"title": "Libre Days", "date_start": "2027-01-14", "city": "Lyon"}
    stated = rows(extraction.KIND_EVENT, [{**event, "venue_address": "24 rue des Fleurs, Lyon"}], text)
    unstated = rows(extraction.KIND_EVENT, [{**event, "venue_address": "42 rue des Fleurs"}], text)
    assert stated[0]["venue"] == {"city": "Lyon", "address": "24 rue des Fleurs, Lyon"}
    assert unstated[0]["venue"] == {"city": "Lyon"}


# contract-test: direct surface=rest_api assertions=instance-app-packages.web-source,events-search.results.actionable
def test_event_description_carries_facts_and_online_event_has_no_physical_venue():
    description = "Free software maintainers will share packaging advice in workshops and report on community security audits."
    common = {"title": "Libre Days", "date_start": "2027-01-14", "city": "Lyon", "country": "France"}
    generic, rich = rows(extraction.KIND_EVENT, [
        {**common, "description": "Open Source Conference in Lyon, France, Europe"},
        {**common, "online": True, "description": description,
         "image_url": "https://example.org/banner.jpg"},
    ], EVENT_PAGE + description)
    assert "description" not in generic
    assert rich["description"] == description
    assert rich["image_url"] == "https://example.org/banner.jpg"
    assert rich["event_type"] == "online" and "venue" not in rich


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
    # Usage for billing: the answered search plus the tokens of the page whose extraction succeeded.
    assert outcome.usage == {"web_search_requests": 1, "model": "inception/mercury-3",
                             "input_tokens": 100, "output_tokens": 20}


# contract-test: direct surface=rest_api assertions=instance-app-packages.web-source
@pytest.mark.anyio
async def test_pages_of_sites_whose_terms_forbid_collection_are_never_read(monkeypatch):
    read_urls: List[str] = []

    async def search(query, secrets_manager, **kwargs):
        return {"results": [{"url": "https://www.linkedin.com/events/123"}, {"url": "https://m.facebook.com/e/1"},
                            {"url": "https://events.my-provider.example/list"}, {"url": "https://a.example.org/1"},
                            {"url": "https://notlinkedin.com.example.org/2"}]}

    async def read(url, **kwargs):
        read_urls.append(url)
        return {"markdown": EVENT_PAGE, "title": "Conferences"}

    async def complete(kind, request, page_url, page_title, page_text, **kwargs):
        return [{"title": "Libre Days", "date_start": "2027-01-14"}], 10, 5

    monkeypatch.setenv(extraction.EXCLUDED_HOSTS_ENV, " my-provider.example , ")
    monkeypatch.setattr(extraction, "search_web", search)
    monkeypatch.setattr(extraction, "read_public_web_page", read)
    monkeypatch.setattr(extraction, "complete_page", complete)
    outcome = await extraction.extract_web_results(extraction.KIND_EVENT, {"query": "conferences"},
                                                   secrets_manager=None)
    assert sorted(read_urls) == ["https://a.example.org/1", "https://notlinkedin.com.example.org/2"]
    assert outcome.pages_excluded == 3 and outcome.pages_found == 2
    assert {row["source_page_url"] for row in outcome.results} == set(read_urls)


# contract-test: supporting surface=rest_api assertions=instance-app-packages.web-source
def test_excluded_host_matches_the_host_and_its_subdomains_only():
    hosts = extraction.excluded_hosts()
    assert extraction.excluded_host("https://www.youtube.com/watch?v=1", hosts)
    assert extraction.excluded_host("https://x.com/someone", hosts)
    assert not extraction.excluded_host("https://fosdem.org/2027/", hosts)
    assert not extraction.excluded_host("https://box.com/file", hosts)


# contract-test: direct surface=rest_api assertions=instance-app-packages.web-source
@pytest.mark.anyio
async def test_unavailable_web_search_is_a_warning_without_results(monkeypatch):
    async def search(query, secrets_manager, **kwargs):
        return {"results": [], "error": "quota"}

    monkeypatch.setattr(extraction, "search_web", search)
    outcome = await web_source.run_web_source(extraction.KIND_EVENT, {"query": "conferences"}, None)
    assert outcome.results == [] and outcome.error == "Web search is unavailable."
    assert outcome.usage["web_search_requests"] == 0 and outcome.usage["input_tokens"] == 0


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
    hint = skill["preprocessor_hint"]
    assert hint.endswith(" Search events in a city.") and "public web pages" in hint
    # Stage-one app routing reads only the first ~100 characters of the first sentence: that
    # sentence alone says what the skill finds and that it beats web search.
    first_sentence = hint.split(". ", 1)[0]
    assert len(first_sentence) <= 100 and first_sentence.startswith("Find events and conferences")
    assert "prefer this over web search" in first_sentence
    bare = {"id": "search"}
    overlay._add_web_source_hint("events", bare)
    other = {"id": "search_stays", "preprocessor_hint": "Stays."}
    overlay._add_web_source_hint("travel", other)
    assert "preprocessor_hint" not in bare and other["preprocessor_hint"] == "Stays."


# contract-test: supporting surface=rest_api assertions=instance-app-packages.web-source
def test_installed_provider_descriptions_replace_tool_schema_texts():
    from backend.shared.app_packages import overlay

    skill = {
        "id": "search",
        "installed_provider_descriptions": {"properties.requests.items.properties.location": "City; omit for a region."},
        "tool_schema": {"properties": {"requests": {"items": {"properties": {
            "location": {"type": "string", "description": "A location alone does not enable discovery."}}}}}},
    }
    overlay._apply_installed_descriptions(skill)
    location = skill["tool_schema"]["properties"]["requests"]["items"]["properties"]["location"]
    assert location == {"type": "string", "description": "City; omit for a region."}


# contract-test: supporting surface=rest_api assertions=instance-app-packages.web-source
def test_installed_provider_description_with_unknown_path_fails_loudly():
    import pytest
    from backend.shared.app_packages import overlay

    skill = {"installed_provider_descriptions": {"properties.missing": "x"}, "tool_schema": {"properties": {}}}
    with pytest.raises(ValueError, match="properties.missing"):
        overlay._apply_installed_descriptions(skill)


# contract-test: supporting surface=rest_api assertions=instance-app-packages.web-source
def test_events_app_declares_reachable_installed_provider_descriptions():
    from pathlib import Path

    import yaml
    from backend.shared.app_packages import overlay

    with open(Path(__file__).resolve().parents[1] / "apps/events/app.yml", encoding="utf-8") as handle:
        skill = next(s for s in yaml.safe_load(handle)["skills"] if s["id"] == "search")
    overlay._apply_installed_descriptions(skill)
    requests = skill["tool_schema"]["properties"]["requests"]
    assert "Europe" in requests["description"] and "unavailable" not in requests["description"]


# contract-test: direct surface=rest_api assertions=instance-app-packages.web-source
def test_open_ended_event_search_also_looks_for_next_years_edition() -> None:
    from datetime import date

    today = date(2026, 11, 20)
    request = {"query": "Example conference", "location": "Example City"}
    # Late in a year the next edition of an annual event is dated the year after the start date.
    assert extraction.search_query(extraction.KIND_EVENT, {**request, "start_date": "2026-11-20T20:00:00+01:00"},
                                   today) == "Example conference Example City 2026 2027"
    assert extraction.search_query(extraction.KIND_EVENT, request, today) == "Example conference Example City 2026 2027"
    # A window that ends in its start year stays in that year.
    assert extraction.search_query(extraction.KIND_EVENT, {**request, "start_date": "2026-03-01",
                                                           "end_date": "2026-06-30"}, today) == \
        "Example conference Example City 2026"


# contract-test: direct surface=rest_api assertions=instance-app-packages.web-source
@pytest.mark.anyio
async def test_a_named_events_official_page_is_read_before_second_pages_of_one_site(monkeypatch):
    """Several pages of one site must not take the page budget (and reader queue) from other sites."""
    read_urls: List[str] = []
    top = "https://conf.example.org/2027/"

    async def search(query, secrets_manager, **kwargs):
        return {"results": [{"url": top}, {"url": "https://conf.example.org/2027/news/"},
                            {"url": "https://conf.example.org/2027/calendar/"},
                            {"url": "https://conf.example.org/2027/about/"},
                            {"url": "https://archive.example.org/2026/"}, {"url": "https://wiki.example.org/Conf"}]}

    async def read(url, **kwargs):
        read_urls.append(url)
        return {"markdown": EVENT_PAGE, "title": "Conferences"}

    async def complete(kind, request, page_url, page_title, page_text, **kwargs):
        return [{"title": "Libre Days", "date_start": "2027-01-14"}], 10, 5

    monkeypatch.setattr(extraction, "search_web", search)
    monkeypatch.setattr(extraction, "read_public_web_page", read)
    monkeypatch.setattr(extraction, "complete_page", complete)
    outcome = await extraction.extract_web_results(extraction.KIND_EVENT, {"query": "Libre Days"},
                                                   secrets_manager=None)
    assert read_urls[:3] == [top, "https://archive.example.org/2026/", "https://wiki.example.org/Conf"]
    assert len(read_urls) == extraction.MAX_PAGES and top in {row["source_page_url"] for row in outcome.results}


# contract-test: direct surface=rest_api assertions=instance-app-packages.web-source,events-search.results.actionable
@pytest.mark.anyio
async def test_upcoming_edition_and_linked_event_details_fit_the_page_budget(monkeypatch):
    from datetime import date

    year = date.today().year + 1
    official = f"https://libre.example/{year}/"
    directory = "https://directory.example/events"
    detail = f"https://directory.example/libre-days-{year}"
    cover = "https://directory.example/images/libre-days.jpg"
    hits = [directory, "https://overview.example", "https://calendar.example", "https://events.example",
            "https://more.example", official]
    seen = []
    mock_day = f"{year}-01-14"

    async def search(*_args, **_kwargs):
        return {"results": [{"url": url} for url in hits]}

    async def read(url, **_kwargs):
        seen.append(url)
        return {
            "title": f"All about Libre Days {year}" if url == detail else "Conferences",
            "markdown": f"Libre Days {year}, January 14. 24 rue des Fleurs, Lyon. "
                        f"[Libre Days]({detail}) [{url}]({official})",
            "og_image": cover,
        }

    async def complete(kind, request, url, title, text, **kwargs):
        if url not in (official, detail):
            return [], 10, 5
        event = {"title": f"Libre Days {year}", "date_start": mock_day, "url": official}
        if url == official:
            event["venue_address"] = "24 rue des Fleurs"
        else:
            event["description"] = "Maintainers compare security and packaging workflows in hands-on workshops."
        return [event], 10, 5

    monkeypatch.setattr(extraction, "search_web", search)
    monkeypatch.setattr(extraction, "read_public_web_page", read)
    monkeypatch.setattr(extraction, "complete_page", complete)
    result = await extraction.extract_web_results(extraction.KIND_EVENT, {"query": "open source conferences"},
                                                  secrets_manager=None)
    assert len(seen) == extraction.MAX_PAGES
    assert seen[0] == official and seen[-1] == detail
    assert result.search_requests == 1
    assert result.results[0]["venue"]["address"] == "24 rue des Fleurs"
    assert result.results[1]["image_url"] == cover
    assert "packaging workflows" in result.results[1]["description"]


# contract-test: supporting surface=rest_api assertions=events-search.results.actionable
def test_directory_logo_does_not_become_the_events_cover():
    event = {"title": "Libre Days"}
    extraction._event_page_cover(event, {
        "title": "All about Libre Days 2027",
        "og_image": "https://directory.example/img/logo.png",
    })
    assert "image_url" not in event


# contract-test: supporting surface=rest_api assertions=events-search.results.actionable
def test_event_detail_context_uses_same_publisher_and_edition_only():
    official = "https://libre.example/2027/"
    about = "https://libre.example/2027/about/"
    assert extraction._matching_about_page([
        "https://other.example/2027/about/",
        "https://libre.example/2026/about/",
        "https://libre.example/2027/about/speakers/",
        about,
    ], official) == about


# contract-test: supporting surface=rest_api assertions=events-search.results.actionable
def test_named_event_detail_prioritizes_its_homepage_over_similar_titles():
    directory = "https://directory.example/all-events"
    nearby = "https://summit.example/"
    named = "https://libre-week.example/"
    previews = [
        {"url": directory, "title": "Conference directory"},
        {"url": nearby, "title": "Homepage - Libre Week Policy Summit"},
        {"url": named, "title": "Home - Libre Week"},
    ]
    assert extraction._named_event_pages([directory, nearby, named], previews, "libre week") == [
        named, directory, nearby,
    ]


# contract-test: supporting surface=rest_api assertions=events-search.results.actionable
def test_structured_listing_recovers_missed_events_from_visible_dates():
    page = """Upcoming events in 2027.

[Jan 25 - Feb 1
27](https://directory.example/ical/libre-week "Add to calendar")

oss

## [Libre Week](https://directory.example/libre-week)

### [Open Source](https://directory.example/oss) conference in [Lyon](https://directory.example/lyon), [France](https://directory.example/fr)
"""
    rows = extraction.validated_rows(
        extraction.KIND_EVENT, extraction._listed_event_facts(page), page_url="https://directory.example/oss",
        page_title="Events", page_text=page,
    )
    assert [(row["title"], row["date_start"], row["date_end"], row["venue"]) for row in rows] == [
        ("Libre Week", "2027-01-25", "2027-02-01", {"city": "Lyon", "country": "France"}),
    ]


# contract-test: supporting surface=rest_api assertions=events-search.results.actionable
def test_named_programme_excerpt_requires_the_edition_and_dates_on_the_page():
    request = {"named_edition": "Libre Week", "start_date": "2027-01-25", "end_date": "2027-02-01",
               "location": "Lyon"}
    sentence = "The programme brings together open source maintainers and public sector teams for hands-on workshops about deployment, accessibility and secure software updates."
    page = f"25 Jan – 1 Feb\n\nLyon\n\n# LIBRE WEEK 2027\n\n{sentence}\n\n## Workshops"
    result = extraction._named_programme_excerpt(request, page)
    assert result["description"] == sentence
    assert result["city"] == "Lyon"
    assert extraction._named_programme_excerpt({**request, "start_date": "2027-01-26"}, page) is None
    assert extraction._named_programme_excerpt({**request, "named_edition": "Other Week"}, page) is None
