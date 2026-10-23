"""Topic filtering runs independently of optional event-purpose ranking."""

from typing import Any

import pytest

from backend.apps.events.skills import search_skill
from backend.shared.providers.typesafe.client import DecisionProviderUnavailable
from backend.shared.providers.typesafe.models import DecisionResponse
from backend.shared.python_utils import search_relevance


def _event(identity: str, title: str, day: int) -> dict[str, Any]:
    return {
        "id": identity, "title": title, "provider": "luma",
        "url": f"https://example.invalid/events/{identity}",
        "date_start": f"2030-10-{day:02d}T18:00:00+02:00",
        "event_type": "PHYSICAL",
    }


@pytest.fixture
def event_search(monkeypatch):
    candidates = [
        _event("builders", "AI Builders Breakfast", 1),
        _event("crafts", "Bookbinding Social", 2),
        _event("learning", "Machine Learning Workshop", 3),
    ]
    capture: dict[str, Any] = {"provider_counts": [], "decisions": [], "enriched": []}

    async def provider(_self, **kwargs):
        capture["provider_counts"].append(kwargs["count"])
        return candidates, len(candidates), None

    async def enrich(results, **_kwargs):
        capture["enriched"].append([event["id"] for event in results])

    class DecisionClient:
        def __init__(self, **_kwargs):
            pass

        async def evaluate(self, *, state, questions):
            capture["decisions"].append(state)
            if capture.get("fail"):
                raise DecisionProviderUnavailable("synthetic decision outage")
            scores = capture.get("scores", [1.0, 0.0, 4.0])
            return DecisionResponse(model="jev", answers={
                key: {"type": "score", "score": scores[int(key[-3:])],
                      "legend": {"0": "unrelated", "1": "weak fit", "4": "direct fit"},
                      "probabilities": {
                          level: float(float(level) == scores[int(key[-3:])])
                          for level in ("0", "1", "4")
                      },
                      "confidence": 1.0}
                for key in questions
            })

    monkeypatch.setattr(search_skill.SearchSkill, "_search_luma", provider)
    monkeypatch.setattr(search_skill.SearchSkill, "_search_pretalx", provider)
    monkeypatch.setattr(search_skill.SearchSkill, "_enrich_finalists", staticmethod(enrich))
    monkeypatch.setattr(search_relevance, "JevDecisionClient", DecisionClient)
    skill = object.__new__(search_skill.SearchSkill)
    request = {"query": "AI meetup", "location": "Berlin", "lat": 52.52,
               "lon": 13.405, "provider": "luma", "count": 3}
    return skill, request, capture


# contract-test: direct surface=rest_api assertions=events-search.relevance.evidence-ranking,events-search.relevance.activation,events-search.enrichment.deferred
@pytest.mark.anyio
@pytest.mark.parametrize("criteria", [None, "", "   "])
async def test_plain_topic_filters_unrelated_candidates_without_changing_order(event_search, criteria):
    skill, request, capture = event_search
    if criteria is not None:
        request["relevance_criteria"] = criteria
    _, results, error, *_ = await skill._process_single_search_request(request, "topic", object())

    assert error is None
    assert [event["id"] for event in results] == ["builders", "learning"]
    assert capture["provider_counts"] == [3]  # no larger provider request for a plain search
    assert capture["enriched"] == [["builders", "learning"]]
    assert len(capture["decisions"]) == 1
    decision = capture["decisions"][0]
    assert decision["profile"] == "events_topic"
    assert decision["relevance_criteria"] == "Events about AI"
    assert decision["search_parameters"]["query"] == "AI"
    assert decision["candidate_content_is_untrusted"] is True


# contract-test: direct surface=rest_api assertions=events-search.relevance.evidence-ranking
@pytest.mark.anyio
async def test_plain_topic_returns_empty_instead_of_padding(event_search):
    skill, request, capture = event_search
    capture["scores"] = [0.0, 0.0, 0.0]
    _, results, error, *_ = await skill._process_single_search_request(request, "no-fit", object())
    assert error is None
    assert results == []
    assert capture["enriched"] == [[]]


# contract-test: direct surface=rest_api assertions=events-search.relevance.safe-fallback
@pytest.mark.anyio
async def test_plain_topic_decision_failure_preserves_provider_results(event_search):
    skill, request, capture = event_search
    capture["fail"] = True
    _, results, error, *_ = await skill._process_single_search_request(request, "fallback", object())
    assert error is None
    assert [event["id"] for event in results] == ["builders", "crafts", "learning"]


# contract-test: direct surface=rest_api assertions=events-search.relevance.activation,events-search.relevance.bounded-candidates
@pytest.mark.anyio
async def test_stated_goal_still_ranks_and_uses_bounded_larger_pool(event_search):
    skill, request, capture = event_search
    request["relevance_criteria"] = "Meet people building machine learning systems"
    _, results, error, *_ = await skill._process_single_search_request(request, "goal", object())
    assert error is None
    assert [event["id"] for event in results] == ["learning", "builders"]
    assert capture["provider_counts"] == [40]
    assert capture["decisions"][0]["profile"] == "events"


# contract-test: direct surface=rest_api assertions=events-search.conference.supported,events-search.relevance.activation
@pytest.mark.anyio
@pytest.mark.parametrize("query", [None, "39c3"])
async def test_conference_schedule_without_separate_topic_needs_no_decision(event_search, query):
    skill, request, capture = event_search
    request.update(provider="pretalx", conference="39C3", query=query)
    _, results, error, *_ = await skill._process_single_search_request(request, "schedule", object())
    assert error is None
    assert len(results) == 3
    assert capture["decisions"] == []
