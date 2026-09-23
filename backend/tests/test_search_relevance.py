"""Focused contracts for optional Jev-backed search relevance ranking."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from backend.shared.providers.typesafe.client import DecisionProviderUnavailable
from backend.shared.providers.typesafe.models import DecisionResponse
from backend.shared.python_utils import search_relevance


def _score(score: float) -> dict:
    return {
        "type": "score",
        "score": score,
        "legend": {"0": "no fit", "4": "excellent fit"},
        "probabilities": {"0": 0.1, "4": 0.9},
        "confidence": 0.8,
    }


# contract-test: direct surface=rest_api assertions=app-skills.search-relevance.bounded-and-conditional,app-skills.search-relevance.safe-finalization
@pytest.mark.anyio
async def test_rank_search_candidates_orders_scores_stably_and_reports_usage(monkeypatch) -> None:
    captured = {}

    class FakeClient:
        def __init__(self, *, secrets_manager):
            captured["secrets_manager"] = secrets_manager

        async def evaluate(self, *, state, questions):
            captured["state"] = state
            captured["questions"] = questions
            return DecisionResponse.model_validate({
                "model": "typesafe/jev-1.13",
                "answers": {
                    "candidate_000": _score(1.0),
                    "candidate_001": _score(4.0),
                    "candidate_002": _score(4.0),
                },
                "usage": {"input_tokens": 321, "output_tokens": 42},
            })

    monkeypatch.setattr(search_relevance, "JevDecisionClient", FakeClient)
    candidates = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    result = await search_relevance.rank_search_candidates(
        candidates=candidates,
        candidate_projections=[
            {"title": "Alpha"},
            {"title": "Beta"},
            {"title": "Gamma"},
        ],
        relevance_criteria="software founders likely to welcome product demos",
        search_parameters={"query": "AI meetup", "city": "Berlin"},
        profile="events",
        secrets_manager=object(),
    )

    assert [item["id"] for item in result.candidates] == ["b", "c", "a"]
    assert result.applied is True
    assert result.input_tokens == 321 and result.output_tokens == 42
    assert captured["state"]["candidate_content_is_untrusted"] is True
    assert captured["state"]["relevance_criteria"] == "software founders likely to welcome product demos"
    assert "speaking" in captured["state"]["ranking_instructions"]
    assert set(captured["questions"]) == {"candidate_000", "candidate_001", "candidate_002"}
    assert all(question["type"] == "score" for question in captured["questions"].values())
    assert all(
        "state.ranking_instructions" in question["instructions"]
        for question in captured["questions"].values()
    )


# contract-test: direct surface=rest_api assertions=app-skills.search-relevance.safe-finalization
@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["missing", "unavailable", "timeout", "invalid_score"])
async def test_rank_search_candidates_falls_back_to_original_order(monkeypatch, failure: str) -> None:
    class FakeClient:
        def __init__(self, *, secrets_manager):
            pass

        async def evaluate(self, *, state, questions):
            if failure == "unavailable":
                raise DecisionProviderUnavailable("unavailable")
            if failure == "timeout":
                raise TimeoutError("timed out")
            answers = {"candidate_000": _score(2.0)}
            if failure == "invalid_score":
                answers["candidate_001"] = _score(8.0)
            return DecisionResponse.model_validate({
                "model": "jev",
                "answers": answers,
                "usage": {"input_tokens": 12, "output_tokens": 3},
            })

    monkeypatch.setattr(search_relevance, "JevDecisionClient", FakeClient)
    candidates = [{"id": "first"}, {"id": "second"}]
    result = await search_relevance.rank_search_candidates(
        candidates=candidates,
        candidate_projections=[{"title": "First"}, {"title": "Second"}],
        relevance_criteria="best evidence",
        search_parameters={"query": "topic"},
        profile="web",
        secrets_manager=None,
    )

    assert result.candidates == candidates
    assert result.applied is False
    assert result.fallback_reason in {
        "incomplete_response",
        "provider_failure",
        "unexpected_failure",
        "invalid_response",
    }


# contract-test: direct surface=rest_api assertions=app-skills.search-relevance.optional-and-inferred,app-skills.search-relevance.bounded-and-conditional
@pytest.mark.anyio
async def test_blank_criteria_skips_jev_and_projection_payloads_are_bounded(monkeypatch) -> None:
    calls = 0

    class FakeClient:
        def __init__(self, *, secrets_manager):
            pass

        async def evaluate(self, *, state, questions):
            nonlocal calls
            calls += 1
            assert len(json.dumps(state["candidates"][0], ensure_ascii=False)) <= search_relevance.MAX_CANDIDATE_PROJECTION_CHARS + 100
            return DecisionResponse.model_validate({
                "model": "jev",
                "answers": {"candidate_000": _score(3.0)},
                "usage": {},
            })

    monkeypatch.setattr(search_relevance, "JevDecisionClient", FakeClient)
    candidates = [{"id": 1}]
    skipped = await search_relevance.rank_search_candidates(
        candidates=candidates,
        candidate_projections=[{"description": "x" * 20_000}],
        relevance_criteria="   ",
        search_parameters={},
        profile="news",
        secrets_manager=None,
    )
    ranked = await search_relevance.rank_search_candidates(
        candidates=candidates,
        candidate_projections=[{"description": "x" * 20_000}],
        relevance_criteria="important material coverage",
        search_parameters={"query": "topic"},
        profile="news",
        secrets_manager=None,
    )

    assert skipped.candidates == candidates and skipped.applied is False
    assert ranked.candidates == candidates and ranked.applied is True
    assert calls == 1


# contract-test: direct surface=rest_api assertions=app-skills.search-relevance.optional-and-inferred,app-skills.search-relevance.bounded-and-conditional
def test_criteria_validation_and_stable_deduplication() -> None:
    assert search_relevance.normalize_relevance_criteria(None) is None
    assert search_relevance.normalize_relevance_criteria("  useful   goal  ") == "useful goal"
    with pytest.raises(ValueError):
        search_relevance.normalize_relevance_criteria("x" * 1001)
    with pytest.raises(ValueError):
        search_relevance.normalize_relevance_criteria(12)

    candidates = [
        {"url": "https://Example.com/path/"},
        {"url": "https://example.com/path"},
        {"url": "https://example.com/other"},
    ]
    assert search_relevance.stable_deduplicate_candidates(
        candidates,
        key=lambda item: search_relevance.normalize_url_for_deduplication(item["url"]),
    ) == [candidates[0], candidates[2]]


# contract-test: direct surface=rest_api assertions=app-skills.search-relevance.optional-and-inferred,health-search-appointments.availability.window-order
def test_search_tool_schemas_expose_optional_criteria_and_keep_health_excluded() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    expected_limits = {
        "web": ("count", 20),
        "news": ("count", 20),
        "events": ("count", 50),
        "home": ("max_results", 20),
    }
    for app_id, (limit_field, maximum) in expected_limits.items():
        app = yaml.safe_load((backend_root / "apps" / app_id / "app.yml").read_text())
        skill = next(item for item in app["skills"] if item["id"] == "search")
        item_schema = skill["tool_schema"]["properties"]["requests"]["items"]
        properties = item_schema["properties"]
        assert properties["relevance_criteria"]["type"] == "string"
        assert properties["relevance_criteria"]["maxLength"] == 1000
        assert "relevance_criteria" not in item_schema.get("required", [])
        assert properties[limit_field]["default"] == 10
        assert properties[limit_field]["maximum"] == maximum
        assert "relevance_criteria" in skill["preprocessor_hint"]

    health = yaml.safe_load((backend_root / "apps" / "health" / "app.yml").read_text())
    health_skill = next(item for item in health["skills"] if item["id"] == "search_appointments")
    health_properties = health_skill["tool_schema"]["properties"]["requests"]["items"]["properties"]
    assert "relevance_criteria" not in health_properties


def _reversed_ranking(candidates):
    return search_relevance.SearchRelevanceRankingResult(
        candidates=list(reversed(candidates)),
        applied=True,
        input_tokens=100,
        output_tokens=10,
    )


# contract-test: direct surface=rest_api assertions=web-search.relevance.bounded-ranking,web-search.relevance.safe-fallback,web-search.results.bounded
@pytest.mark.anyio
async def test_web_ranked_search_uses_two_pages_but_returns_only_count(monkeypatch) -> None:
    from backend.apps.web.skills import search_skill as web_search

    provider_calls = []
    ranked_pool_sizes = []
    ranking_fails = False

    async def fake_provider(**kwargs):
        provider_calls.append({"count": kwargs["count"], "offset": kwargs["offset"]})
        offset = kwargs["offset"]
        return {"results": [
            {
                "title": f"page-{offset}-result-{index}",
                "url": f"https://example.test/{offset}/{index}",
                "description": "Evidence",
            }
            for index in range(20)
        ]}

    async def fake_rank(**kwargs):
        ranked_pool_sizes.append(len(kwargs["candidates"]))
        if ranking_fails:
            return search_relevance.SearchRelevanceRankingResult(
                candidates=list(kwargs["candidates"]),
                applied=False,
                fallback_reason="provider_failure",
            )
        return _reversed_ranking(kwargs["candidates"])

    async def allow_rate_limit(**_kwargs):
        return True, None

    monkeypatch.setattr(web_search, "search_web", fake_provider)
    monkeypatch.setattr(web_search, "rank_search_candidates", fake_rank)
    monkeypatch.setattr(web_search, "check_rate_limit", allow_rate_limit)
    monkeypatch.setattr(web_search, "load_tabloid_blocklist", lambda: set())
    skill = web_search.SearchSkill(
        app=None,
        app_id="web",
        skill_id="search",
        skill_name="Search",
        skill_description="Search",
    )

    _, ranked_results, error = await skill._process_single_search_request(
        {
            "query": "AI tools",
            "count": 10,
            "filter_tabloids": False,
            "relevance_criteria": "tools suitable for privacy-conscious teams",
        },
        "ranked",
        secrets_manager=object(),
        cache_service=object(),
    )
    assert error is None
    assert provider_calls == [{"count": 20, "offset": 0}, {"count": 20, "offset": 1}]
    assert ranked_pool_sizes == [40]
    assert len(ranked_results) == 10
    assert ranked_results[0]["title"] == "page-1-result-19"

    ranking_fails = True
    provider_calls.clear()
    _, fallback_results, error = await skill._process_single_search_request(
        {
            "query": "AI tools",
            "count": 4,
            "filter_tabloids": False,
            "relevance_criteria": "tools suitable for privacy-conscious teams",
        },
        "fallback",
        secrets_manager=object(),
        cache_service=object(),
    )
    assert error is None
    assert provider_calls == [{"count": 20, "offset": 0}, {"count": 20, "offset": 1}]
    assert len(fallback_results) == 4
    assert fallback_results[0]["title"] == "page-0-result-0"

    provider_calls.clear()
    _, plain_results, error = await skill._process_single_search_request(
        {"query": "AI tools", "count": 3, "filter_tabloids": False},
        "plain",
        secrets_manager=object(),
        cache_service=object(),
    )
    assert error is None and len(plain_results) == 3
    assert provider_calls == [{"count": 3, "offset": 0}]
    assert ranked_pool_sizes == [40, 40]


# contract-test: supporting surface=rest_api assertions=app-skills.search-relevance.bounded-and-conditional,app-skills.search-relevance.safe-finalization
@pytest.mark.anyio
async def test_news_ranked_search_uses_one_forty_candidate_call_and_returns_only_count(monkeypatch) -> None:
    from backend.apps.news.skills import search_skill as news_search

    provider_counts = []
    ranked_pool_sizes = []
    ranking_fails = False

    async def fake_provider(**kwargs):
        provider_counts.append(kwargs["count"])
        return {
            "sanitize_output": False,
            "results": [
                {
                    "title": f"news-{index}",
                    "url": f"https://news.example/{index}",
                    "description": "Material reporting",
                    "profile": {"name": "Example News"},
                }
                for index in range(kwargs["count"])
            ],
        }

    async def fake_rank(**kwargs):
        ranked_pool_sizes.append(len(kwargs["candidates"]))
        if ranking_fails:
            return search_relevance.SearchRelevanceRankingResult(
                candidates=list(kwargs["candidates"]),
                applied=False,
                fallback_reason="invalid_response",
            )
        return _reversed_ranking(kwargs["candidates"])

    async def allow_rate_limit(**_kwargs):
        return True, None

    monkeypatch.setattr(news_search, "search_news", fake_provider)
    monkeypatch.setattr(news_search, "rank_search_candidates", fake_rank)
    monkeypatch.setattr(news_search, "check_rate_limit", allow_rate_limit)
    monkeypatch.setattr(news_search, "load_tabloid_blocklist", lambda: set())
    skill = news_search.SearchSkill(
        app=None,
        app_id="news",
        skill_id="search",
        skill_name="Search",
        skill_description="Search",
    )

    _, results, error = await skill._process_single_search_request(
        {
            "query": "AI policy",
            "count": 10,
            "relevance_criteria": "material changes for small European software companies",
        },
        "news",
        secrets_manager=object(),
        cache_service=object(),
    )

    assert error is None
    assert provider_counts == [40]
    assert ranked_pool_sizes == [40]
    assert len(results) == 10
    assert results[0]["title"] == "news-39"

    ranking_fails = True
    _, fallback_results, error = await skill._process_single_search_request(
        {
            "query": "AI policy",
            "count": 4,
            "relevance_criteria": "material changes for small European software companies",
        },
        "news-fallback",
        secrets_manager=object(),
        cache_service=object(),
    )
    assert error is None
    assert provider_counts == [40, 40]
    assert ranked_pool_sizes == [40, 40]
    assert len(fallback_results) == 4
    assert fallback_results[0]["title"] == "news-0"


# contract-test: direct surface=rest_api assertions=events-search.relevance.bounded-candidates,events-search.relevance.safe-fallback,events-search.results.actionable
@pytest.mark.anyio
async def test_events_ranked_search_keeps_candidate_pool_internal(monkeypatch) -> None:
    from backend.apps.events.skills import search_skill as events_search

    provider_counts = []
    ranked_pool_sizes = []
    ranking_fails = False

    async def fake_luma(self, *, query, location_str, count, proxy_url=None):
        provider_counts.append(count)
        return ([
            {
                "id": f"event-{index}",
                "provider": "luma",
                "title": f"Event {index}",
                "description": "Founder networking and talks",
                "url": f"https://lu.ma/event-{index}",
                "date_start": f"2026-10-{(index % 28) + 1:02d}T18:00:00+02:00",
                "venue": {"name": f"Venue {index}", "city": "Berlin"},
            }
            for index in range(count)
        ], count, None)

    async def fake_rank(**kwargs):
        ranked_pool_sizes.append(len(kwargs["candidates"]))
        if ranking_fails:
            return search_relevance.SearchRelevanceRankingResult(
                candidates=list(kwargs["candidates"]),
                applied=False,
                fallback_reason="unexpected_failure",
            )
        return _reversed_ranking(kwargs["candidates"])

    monkeypatch.setattr(events_search.SearchSkill, "_search_luma", fake_luma)
    monkeypatch.setattr(events_search, "rank_search_candidates", fake_rank)
    skill = object.__new__(events_search.SearchSkill)

    _, results, error, _total, _providers, _warnings = await skill._process_single_search_request(
        {
            "query": "AI meetup",
            "location": "Berlin",
            "lat": 52.52,
            "lon": 13.405,
            "provider": "luma",
            "count": 10,
            "relevance_criteria": "events where I can promote my AI software and potentially give a future talk",
        },
        "events",
        secrets_manager=object(),
    )

    assert error is None
    assert provider_counts == [40]
    assert ranked_pool_sizes == [40]
    assert len(results) == 10
    assert results[0]["title"] == "Event 39"

    ranking_fails = True
    _, fallback_results, error, _total, _providers, _warnings = await skill._process_single_search_request(
        {
            "query": "AI meetup",
            "location": "Berlin",
            "lat": 52.52,
            "lon": 13.405,
            "provider": "luma",
            "count": 4,
            "relevance_criteria": "events where I can promote my AI software and potentially give a future talk",
        },
        "events-fallback",
        secrets_manager=object(),
    )
    assert error is None
    assert provider_counts == [40, 40]
    assert ranked_pool_sizes == [40, 40]
    assert len(fallback_results) == 4
    assert fallback_results[0]["title"] == "Event 0"


# contract-test: supporting surface=rest_api assertions=app-skills.search-relevance.bounded-and-conditional,app-skills.search-relevance.safe-finalization
@pytest.mark.anyio
async def test_home_ranked_search_geocodes_and_returns_only_max_results(monkeypatch) -> None:
    from backend.apps.home.skills import search_skill as home_search

    provider_limits = []
    geocoded_counts = []
    ranked_pool_sizes = []
    ranking_fails = False

    def provider(name, offset):
        async def search(**kwargs):
            provider_limits.append(kwargs["max_results"])
            return [
                {
                    "id": f"{name}-{index}",
                    "provider": name,
                    "title": f"Listing {offset + index}",
                    "address": f"Street {offset + index}, Berlin",
                    "price": 800 + offset + index,
                    "rooms": 2,
                    "size_sqm": 50,
                    "url": f"https://housing.example/{name}/{index}",
                }
                for index in range(kwargs["max_results"])
            ]
        return search

    async def fake_geocode(listings, city):
        geocoded_counts.append(len(listings))

    async def fake_rank(**kwargs):
        ranked_pool_sizes.append(len(kwargs["candidates"]))
        if ranking_fails:
            return search_relevance.SearchRelevanceRankingResult(
                candidates=list(kwargs["candidates"]),
                applied=False,
                fallback_reason="provider_failure",
            )
        return _reversed_ranking(kwargs["candidates"])

    monkeypatch.setattr(home_search, "PROVIDER_MAP", {
        "ImmoScout24": provider("ImmoScout24", 0),
        "Kleinanzeigen": provider("Kleinanzeigen", 100),
        "WG-Gesucht": provider("WG-Gesucht", 200),
    })
    monkeypatch.setattr(home_search, "rank_search_candidates", fake_rank)
    skill = object.__new__(home_search.SearchSkill)
    monkeypatch.setattr(skill, "_geocode_listings", fake_geocode)

    _, results, error, _warnings = await skill._process_single_request(
        {
            "query": "Berlin",
            "max_results": 10,
            "relevance_criteria": "quiet two-room apartment with explicit evidence of a balcony",
        },
        "home",
        secrets_manager=object(),
    )

    assert error is None
    assert provider_limits == [14, 14, 14]
    assert ranked_pool_sizes == [40]
    assert geocoded_counts == [10]
    assert len(results) == 10

    ranking_fails = True
    _, fallback_results, error, _warnings = await skill._process_single_request(
        {
            "query": "Berlin",
            "max_results": 4,
            "relevance_criteria": "quiet two-room apartment with explicit evidence of a balcony",
        },
        "home-fallback",
        secrets_manager=object(),
    )
    assert error is None
    assert provider_limits == [14, 14, 14, 14, 14, 14]
    assert ranked_pool_sizes == [40, 40]
    assert geocoded_counts == [10, 4]
    assert len(fallback_results) == 4
    assert fallback_results[0]["title"] == "Listing 0"
