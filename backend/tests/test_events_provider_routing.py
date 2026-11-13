"""Offline routing contracts: official conference schedules, web-page discovery and unknown sources."""
from unittest.mock import AsyncMock
import pytest
from backend.apps.events.skills import search_skill
from backend.apps.events.skills.search_skill import SearchRequest, SearchSkill
from backend.shared.app_packages.provider_dispatch import InstalledProviderOutcome
from backend.apps.events.skills.provider_routing import deterministic_auto_providers

# contract-test: direct surface=rest_api assertions=events-search.providers.explicit
@pytest.mark.anyio
async def test_unknown_source_is_unavailable_and_never_contacts_a_source(monkeypatch):
    skill = object.__new__(SearchSkill)
    source = AsyncMock(side_effect=AssertionError("must not contact a source"))
    monkeypatch.setattr(skill, "_search_pretalx", source)
    web = AsyncMock(side_effect=AssertionError("must not search the web"))
    monkeypatch.setattr(search_skill, "run_web_source", web)
    response = await skill.execute(SearchRequest(requests=[
        {"id": "city", "query": "concerts", "location": "Berlin", "provider": "unknown-source"}]), secrets_manager=object())
    assert "unavailable" in response.error.lower()
    assert response.results[0]["results"] == []
    assert response.providers == []
    source.assert_not_awaited()
    web.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=events-search.discovery.web-pages
@pytest.mark.anyio
@pytest.mark.parametrize("choice", ["auto", None])
async def test_general_discovery_without_installed_providers_answers_from_web_pages(monkeypatch, choice):
    skill = object.__new__(SearchSkill)
    monkeypatch.setattr(skill, "_search_pretalx", AsyncMock(side_effect=AssertionError("no known conference")))
    monkeypatch.setattr(search_skill, "_installed_provider_labels", lambda: {})
    page_event = {"title": "FOSDEM 2027", "date_start": "2099-01-30", "date_end": "2099-01-31",
                  "url": "https://example.org/fosdem", "venue": {"city": "Brussels", "country": "Belgium"},
                  "provider": "example.org", "provider_id": "web", "source_page_url": "https://example.org/list",
                  "source_page_title": "Open source conferences"}
    web = AsyncMock(return_value=InstalledProviderOutcome("web", results=[page_event]))
    monkeypatch.setattr(search_skill, "run_web_source", web)
    response = await skill.execute(SearchRequest(requests=[
        {"id": "eu", "query": "open source conferences", "provider": choice}]), secrets_manager=object())
    assert response.error is None
    assert response.providers == ["web"]
    rows = response.results[0]["results"]
    assert [row["title"] for row in rows] == ["FOSDEM 2027"]
    assert rows[0]["type"] == "event_result" and rows[0]["source_page_url"] == "https://example.org/list"
    web.assert_awaited_once()
    assert web.call_args.args[1]["query"] == "open source conferences"

# contract-test: direct surface=rest_api assertions=events-search.conference.supported,events-search.request.validated
@pytest.mark.anyio
async def test_only_explicit_known_conference_routes_without_city_or_query(monkeypatch):
    skill = object.__new__(SearchSkill)
    source = AsyncMock(return_value=([{"id": "session", "provider": "39c3", "title": "Opening", "url": "https://example.invalid/talk"}], 1, None))
    monkeypatch.setattr(skill, "_search_pretalx", source)
    response = await skill.execute(SearchRequest(requests=[{"id": "schedule", "conference": "39C3"}]))
    assert response.error is None
    assert response.providers == ["pretalx"]
    assert response.results[0]["id"] == "schedule"
    assert response.results[0]["results"][0]["type"] == "event_result"
    assert response.results[0]["results"][0]["hash"]
    source.assert_awaited_once()
    assert source.call_args.kwargs["conference"] == "39c3"

# contract-test: direct surface=rest_api assertions=events-search.providers.explicit
@pytest.mark.anyio
async def test_unknown_source_never_broadens_to_known_conference(monkeypatch):
    skill = object.__new__(SearchSkill)
    source = AsyncMock(side_effect=AssertionError("must not broaden source selection"))
    monkeypatch.setattr(skill, "_search_pretalx", source)
    response = await skill.execute(SearchRequest(provider="unknown-source", requests=[{"conference": "39C3"}]))
    assert "unavailable" in response.error.lower()
    source.assert_not_awaited()

# contract-test: direct surface=rest_api assertions=events-search.request.validated
@pytest.mark.anyio
async def test_invalid_date_range_does_not_contact_schedule(monkeypatch):
    skill = object.__new__(SearchSkill)
    source = AsyncMock(side_effect=AssertionError("invalid request must not dispatch"))
    monkeypatch.setattr(skill, "_search_pretalx", source)
    response = await skill.execute(SearchRequest(requests=[{"conference": "39C3", "start_date": "2030-10-02T00:00:00Z", "end_date": "2030-10-01T00:00:00Z"}]))
    assert "date range" in response.error.lower()
    source.assert_not_awaited()

# contract-test: supporting surface=rest_api assertions=events-search.providers.explicit
def test_conference_only_auto_routing():
    assert deterministic_auto_providers(query="concerts in Berlin", eligible_ids=["pretalx"]) == ([], [])
    assert deterministic_auto_providers(query="39C3 security", eligible_ids=["pretalx"]) == (["pretalx"], [])

# contract-test: direct surface=rest_api assertions=events-search.request.validated
@pytest.mark.anyio
async def test_missing_query_without_conference_returns_actionable_request_error(monkeypatch):
    skill = object.__new__(SearchSkill)
    source = AsyncMock(side_effect=AssertionError("must not contact a source"))
    monkeypatch.setattr(skill, "_search_pretalx", source)
    response = await skill.execute(SearchRequest(requests=[{"id": "berlin-tech-events", "location": "Berlin"}]))
    assert "'query'" in response.results[0]["error"]
    assert "Retry" in response.results[0]["error"]
    assert response.results[0]["results"] == []
    source.assert_not_awaited()

# contract-test: supporting surface=rest_api assertions=events-search.request.validated
def test_tool_schema_describes_query_requirement():
    import yaml
    from pathlib import Path
    app = yaml.safe_load(Path("backend/apps/events/app.yml").read_text())
    skill = next(s for s in app["skills"] if s["id"] == "search")
    query = skill["tool_schema"]["properties"]["requests"]["items"]["properties"]["query"]
    assert "Required" in query["description"] and "conference" in query["description"]
