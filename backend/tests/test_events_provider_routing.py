"""Offline routing contracts for official conference schedules only."""
from unittest.mock import AsyncMock
import pytest
from backend.apps.events.skills.search_skill import SearchRequest, SearchSkill
from backend.apps.events.skills.provider_routing import deterministic_auto_providers

# contract-test: direct surface=rest_api assertions=events-search.providers.explicit
@pytest.mark.anyio
@pytest.mark.parametrize("choice", ["unknown-source", "auto", None])
async def test_generic_discovery_unavailable_and_never_contacts_a_source(monkeypatch, choice):
    skill = object.__new__(SearchSkill)
    source = AsyncMock(side_effect=AssertionError("must not contact a source"))
    monkeypatch.setattr(skill, "_search_pretalx", source)
    response = await skill.execute(SearchRequest(requests=[{"id": "city", "query": "concerts", "location": "Berlin", "provider": choice}]))
    assert "unavailable" in response.error.lower()
    assert response.results[0]["results"] == []
    assert response.providers == []
    source.assert_not_awaited()

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
