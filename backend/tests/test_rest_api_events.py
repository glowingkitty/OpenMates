"""Deterministic event skill contracts supporting the REST request/result surface.

Real endpoint auth and provider-boundary rejection are covered by isolated REST
E2E. These cases use fake conference data and never call a live source.
"""

from unittest.mock import AsyncMock

import pytest

from backend.apps.events.skills.search_skill import SearchRequest, SearchSkill


@pytest.fixture
def skill(monkeypatch):
    instance = object.__new__(SearchSkill)
    upstream = AsyncMock(side_effect=AssertionError("Unexpected conference request"))
    monkeypatch.setattr(instance, "_search_pretalx", upstream)
    return instance, upstream


# contract-test: supporting surface=rest_api assertions=app-skills.providers.unavailable-no-network,events-search.request.validated
@pytest.mark.asyncio
async def test_general_event_discovery_is_unavailable_without_source_requests(skill):
    instance, upstream = skill
    request = SearchRequest(requests=[{"id": "general", "query": "technology", "location": "Berlin"}])
    response = await instance.execute(request)
    assert response.error and "unavailable" in response.error.lower()
    assert response.results[0]["id"] == "general"
    assert response.results[0]["results"] == []
    assert response.providers == []
    upstream.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=app-skills.providers.unavailable-no-network,events-search.providers.explicit
@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["unsupported-source", "unconfigured-source"])
async def test_explicit_unsupported_provider_never_falls_back(skill, provider):
    instance, upstream = skill
    result = await instance._process_single_search_request(
        {"conference": "39C3", "provider": provider, "count": 5}, "explicit"
    )
    identity, events, error, total, sources = result
    assert identity == "explicit"
    assert events == [] and total == 0 and sources == []
    assert error and "unavailable" in error.lower()
    upstream.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=events-search.conference.supported,events-search.results.actionable
@pytest.mark.asyncio
async def test_supported_conference_preserves_shape_and_count(skill):
    instance, upstream = skill
    upstream.side_effect = None
    upstream.return_value = ([
        {"id": "first", "title": "Official conference session", "description": "A published conference session.",
         "url": "https://example.org/conference/first", "provider": "pretalx", "date_start": "2099-12-28T12:00:00+00:00"},
        {"id": "second", "title": "Another conference session", "description": "Another published session.",
         "url": "https://example.org/conference/second", "provider": "pretalx", "date_start": "2099-12-28T13:00:00+00:00"},
    ], 2, None)
    identity, events, error, total, sources = await instance._process_single_search_request(
        {"conference": "39C3", "provider": "pretalx", "count": 1}, "conference"
    )
    assert error is None and identity == "conference" and total == 2
    assert sources == ["pretalx"] and len(events) == 1
    assert events[0]["id"] == "first"
    assert events[0]["type"] == "event_result"
    assert events[0]["title"] and events[0]["url"] and events[0]["date_start"]
    assert upstream.await_args.kwargs["conference"] == "39c3"
    assert upstream.await_args.kwargs["count"] == 1


# contract-test: supporting surface=rest_api assertions=events-search.request.validated,events-search.surface-parity
@pytest.mark.asyncio
async def test_mixed_batch_preserves_groups_and_visible_errors(skill):
    instance, upstream = skill
    upstream.side_effect = None
    upstream.return_value = ([], 0, None)
    response = await instance.execute(SearchRequest(requests=[
        {"id": "unsupported", "query": "technology", "location": "Berlin"},
        {"id": "schedule", "conference": "39C3", "count": 2},
    ]))
    assert [group["id"] for group in response.results] == ["unsupported", "schedule"]
    assert response.results[0]["error"]
    assert response.results[1]["results"] == []
    assert "error" not in response.results[1]
    assert response.providers == ["pretalx"]
    upstream.assert_awaited_once()


# contract-test: supporting surface=rest_api assertions=events-search.conference.supported,events-search.surface-parity
@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"requests": [{"id": "schedule", "providers": ["gpn24"]}]},
    {"requests": [{"id": "schedule"}], "providers": ["gpn24"]},
])
async def test_conference_provider_arrays_supply_the_schedule_hint_before_validation(skill, payload):
    instance, upstream = skill
    upstream.side_effect = None
    upstream.return_value = ([], 0, None)
    response = await instance.execute(SearchRequest(**payload))
    assert response.error is None
    assert response.results[0]["id"] == "schedule"
    assert "error" not in response.results[0]
    assert response.providers == ["pretalx"]
    upstream.assert_awaited_once()
    assert upstream.await_args.kwargs["conference"] == "gpn24"
