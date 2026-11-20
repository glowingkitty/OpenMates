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
    identity, events, error, total, sources, _warnings = result
    assert identity == "explicit"
    assert events == [] and total == 0 and sources == []
    assert error and "unavailable" in error.lower()
    upstream.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=events-search.providers.explicit
@pytest.mark.asyncio
async def test_named_schedule_for_another_conference_searches_nothing_and_points_to_auto(skill):
    instance, upstream = skill
    result = await instance._process_single_search_request(
        {"query": "Example open source summit", "location": "Example City", "provider": "pretalx", "count": 5},
        "other-conference", secrets_manager=object(),
    )
    identity, events, error, total, sources, _warnings = result
    assert identity == "other-conference"
    assert events == [] and total == 0 and sources == []
    assert error and "provider auto" in error
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
    identity, events, error, total, sources, _warnings = await instance._process_single_search_request(
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


# contract-test: supporting surface=rest_api assertions=instance-app-packages.web-source,events-search.results.actionable
@pytest.mark.asyncio
async def test_a_large_listing_source_never_pushes_web_matches_out_before_ranking(skill, monkeypatch):
    """Sources are interleaved before the bounded relevance cut (a conference found on the web ranks)."""
    from backend.apps.events.skills import search_skill as module
    from backend.shared.app_packages.provider_dispatch import InstalledProviderOutcome
    from backend.shared.python_utils.search_relevance import SearchRelevanceRankingResult

    instance, upstream = skill
    listings = [{"title": f"City meetup {n}", "date_start": "2027-01-10", "url": f"https://example.org/meetup/{n}",
                 "provider": "My provider"} for n in range(80)]
    conference = {"title": "Example conference 2027", "date_start": "2027-01-30", "date_end": "2027-01-31",
                  "url": "https://example.org/conference/2027/", "provider": "example.org"}
    monkeypatch.setattr(module, "_installed_provider_labels", lambda: {"my_provider": "My provider"})
    monkeypatch.setattr(module, "run_installed_providers", AsyncMock(
        return_value=[InstalledProviderOutcome("my_provider", results=listings)]))
    monkeypatch.setattr(instance, "_search_web", AsyncMock(
        return_value=InstalledProviderOutcome("web", results=[conference])))
    ranked: list = []

    async def rank(*, candidates, **_kwargs):
        ranked.extend(candidates)
        scores = [3.0 if event["title"] == conference["title"] else 0.1 for event in candidates]
        return SearchRelevanceRankingResult(candidates=list(candidates), applied=True, scores=scores)

    monkeypatch.setattr(module, "rank_search_candidates", rank)
    _identity, events, error, _total, sources, _warnings = await instance._process_single_search_request(
        {"query": "Example conference", "start_date": "2026-11-20", "count": 5,
         "relevance_criteria": "The largest conference of its kind"}, "conference", secrets_manager=object())

    assert error is None and sources == ["my_provider", "web"]
    assert len(ranked) < len(listings) + 1 and conference["title"] in [event["title"] for event in ranked]
    assert [event["title"] for event in events] == [conference["title"]]
    upstream.assert_not_awaited()
