"""Focused contracts for optional Jev-backed search relevance ranking."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from backend.shared.providers.typesafe.client import DecisionProviderUnavailable
from backend.shared.providers.typesafe.models import DecisionResponse
from backend.shared.python_utils import search_relevance
from backend.shared.providers.models3d_catalogs import Model3DProviderResult
from backend.scripts.test_search_relevance_ranking import _candidate_summary


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
    assert result.scores == [4.0, 4.0, 1.0]
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


# contract-test: direct surface=rest_api assertions=events-search.relevance.evidence-ranking
def test_events_profile_requires_query_topic_fit_and_defensible_relevance() -> None:
    profile = search_relevance.SEARCH_RELEVANCE_PROFILES["events"]

    assert "search_parameters.query" in profile.instructions
    assert "weak but defensible" in profile.instructions
    assert "neither relationship" in profile.instructions
    assert profile.criteria[0].startswith("No credible relationship")


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


# contract-test: direct surface=rest_api assertions=app-skills.search-relevance.bounded-and-conditional,app-skills.search-relevance.safe-finalization
def test_repository_and_models3d_profiles_use_evidence_only_rubrics_and_default_pool() -> None:
    repository_profile = search_relevance.SEARCH_RELEVANCE_PROFILES["code_repositories"]
    repository_instructions = repository_profile.instructions.lower()
    assert all(
        term in repository_instructions
        for term in ("use case", "technology", "license", "date")
    )
    assert "popularity" in repository_instructions
    assert all(
        term in repository_instructions
        for term in ("security", "health", "documentation", "api compatibility")
    )

    models_profile = search_relevance.SEARCH_RELEVANCE_PROFILES["models3d"]
    models_instructions = models_profile.instructions.lower()
    assert all(
        term in models_instructions
        for term in ("function", "feature", "license", "file", "price")
    )
    assert "engagement" in models_instructions
    assert all(
        term in models_instructions
        for term in ("geometry", "printability", "device compatibility")
    )

    assert search_relevance.relevance_candidate_target(
        10, profile="code_repositories"
    ) == 40
    assert search_relevance.relevance_candidate_target(10, profile="models3d") == 40


# contract-test: supporting surface=rest_api assertions=app-skills.search-relevance.safe-finalization
def test_real_ranking_summary_supports_models3d_pydantic_candidates() -> None:
    candidate = Model3DProviderResult(
        title="Foldable travel phone stand",
        provider="Printables",
        provider_kind="reverse_engineered_browser_api",
        provider_item_id="123",
        source_page_url="https://www.printables.com/model/123-phone-stand",
    )

    assert _candidate_summary(candidate) == {
        "title": "Foldable travel phone stand",
        "host": "www.printables.com",
    }


# contract-test: direct surface=rest_api assertions=app-skills.search-relevance.optional-and-inferred,health-search-appointments.availability.window-order
def test_search_tool_schemas_expose_optional_criteria_and_keep_health_excluded() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    expected_limits = {
        ("web", "search"): ("count", 10, 20),
        ("news", "search"): ("count", 10, 20),
        ("events", "search"): ("count", 10, 50),
        ("home", "search"): ("max_results", 10, 20),
        ("maps", "search"): ("pageSize", 10, 20),
        ("shopping", "search_products"): ("max_results", 10, 20),
        ("travel", "search_stays"): ("max_results", 10, 20),
        ("videos", "search"): ("count", 6, 20),
        ("fitness", "search_locations"): ("limit", 10, 50),
        ("fitness", "search_classes"): ("limit", 10, 50),
        ("code", "search_repos"): ("count", 10, 10),
        ("models3d", "search"): ("count", 10, 20),
    }
    for (app_id, skill_id), (limit_field, default, maximum) in expected_limits.items():
        app = yaml.safe_load((backend_root / "apps" / app_id / "app.yml").read_text())
        skill = next(item for item in app["skills"] if item["id"] == skill_id)
        item_schema = skill["tool_schema"]["properties"]["requests"]["items"]
        properties = item_schema["properties"]
        assert properties["relevance_criteria"]["type"] == "string"
        assert properties["relevance_criteria"]["maxLength"] == 1000
        assert "relevance_criteria" not in item_schema.get("required", [])
        assert properties[limit_field]["default"] == default
        if maximum is not None:
            assert properties[limit_field]["maximum"] == maximum
        hint = skill["preprocessor_hint"]
        description = properties["relevance_criteria"]["description"]
        hint_lower = hint.lower()
        description_lower = description.lower()
        assert "relevance_criteria" in hint_lower
        assert "query" in hint_lower
        assert "even if" in hint_lower or "explicit user-stated" in hint_lower
        assert "neutral" in hint_lower and "omit" in hint_lower
        assert "separate from" in description_lower
        assert "neutral" in description_lower and "omit" in description_lower

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


# contract-test: direct surface=rest_api assertions=events-search.relevance.evidence-ranking,events-search.relevance.bounded-candidates
@pytest.mark.anyio
async def test_events_ranked_search_omits_zero_score_instead_of_padding(monkeypatch) -> None:
    from backend.apps.events.skills import search_skill as events_search

    candidates = [
        {
            "id": "robotics",
            "provider": "luma",
            "title": "Hands-on Robotics Lab",
            "description": "Build a mobile robot with engineers.",
            "url": "https://lu.ma/robotics",
            "date_start": "2026-10-01T18:00:00+02:00",
        },
        {
            "id": "embodied-ai",
            "provider": "luma",
            "title": "Embodied AI Engineering",
            "description": "AI systems that perceive and act in the physical world.",
            "url": "https://lu.ma/embodied-ai",
            "date_start": "2026-10-02T18:00:00+02:00",
        },
        {
            "id": "film",
            "provider": "luma",
            "title": "AI Consciousness Film Night",
            "description": "A speculative cinema screening.",
            "url": "https://lu.ma/film",
            "date_start": "2026-10-03T18:00:00+02:00",
        },
    ]

    async def fake_luma(self, **kwargs):
        return candidates, len(candidates), None

    async def fake_rank(**kwargs):
        return search_relevance.SearchRelevanceRankingResult(
            candidates=list(kwargs["candidates"]),
            applied=True,
            scores=[4.0, 1.0, 0.0],
        )

    monkeypatch.setattr(events_search.SearchSkill, "_search_luma", fake_luma)
    monkeypatch.setattr(events_search, "rank_search_candidates", fake_rank)
    skill = object.__new__(events_search.SearchSkill)

    _, results, error, _total, _providers, _warnings = await skill._process_single_search_request(
        {
            "query": "robotics",
            "location": "Berlin",
            "lat": 52.52,
            "lon": 13.405,
            "provider": "luma",
            "count": 10,
            "relevance_criteria": "engineering events for people building robots",
        },
        "events-floor",
        secrets_manager=object(),
    )

    assert error is None
    assert [result["id"] for result in results] == ["robotics", "embodied-ai"]


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


# contract-test: direct surface=rest_api assertions=app-skills.search-relevance.bounded-and-conditional,app-skills.search-relevance.safe-finalization
@pytest.mark.anyio
async def test_maps_relevance_uses_one_twenty_candidate_call_and_clips_fallback(monkeypatch) -> None:
    from backend.apps.maps.skills import search_skill as maps_search

    provider_sizes = []
    rank_calls = []
    ranking_fails = False

    async def fake_provider(**kwargs):
        provider_sizes.append(kwargs["page_size"])
        return {"results": [
            {
                "place_id": f"place-{index}",
                "name": f"Place {index}",
                "formatted_address": f"Street {index}, Berlin",
                "description": "Cafe with explicit Wi-Fi details",
            }
            for index in range(kwargs["page_size"])
        ]}

    async def allow_rate_limit(**_kwargs):
        return True, None

    async def passthrough_sanitizer(*, payload, **_kwargs):
        return payload

    async def passthrough_enrichment(*, previews, **_kwargs):
        return previews, {"geoapify_requested": False}

    async def fake_rank(**kwargs):
        rank_calls.append(len(kwargs["candidates"]))
        if ranking_fails:
            return search_relevance.SearchRelevanceRankingResult(
                candidates=list(kwargs["candidates"]),
                applied=False,
                fallback_reason="provider_failure",
            )
        return _reversed_ranking(kwargs["candidates"])

    monkeypatch.setattr(maps_search, "search_places", fake_provider)
    monkeypatch.setattr(maps_search, "check_rate_limit", allow_rate_limit)
    monkeypatch.setattr(maps_search, "sanitize_long_text_fields_in_payload", passthrough_sanitizer)
    monkeypatch.setattr(maps_search, "rank_search_candidates", fake_rank)
    skill = object.__new__(maps_search.SearchSkill)
    monkeypatch.setattr(skill, "_apply_geoapify_enrichment", passthrough_enrichment)

    _, ranked, error, _metadata = await skill._process_single_search_request(
        {
            "query": "cafes in Berlin",
            "pageSize": 10,
            "relevance_criteria": "quiet laptop-friendly cafe with explicit Wi-Fi evidence",
            "osmEnrichment": "disabled",
        },
        "maps-ranked",
        secrets_manager=object(),
        cache_service=object(),
    )
    assert error is None
    assert provider_sizes == [20]
    assert len(ranked) == 10 and ranked[0]["name"] == "Place 19"

    ranking_fails = True
    _, fallback, error, _metadata = await skill._process_single_search_request(
        {
            "query": "cafes in Berlin",
            "pageSize": 4,
            "relevance_criteria": "quiet laptop-friendly cafe",
            "osmEnrichment": "disabled",
        },
        "maps-fallback",
        secrets_manager=object(),
        cache_service=object(),
    )
    assert error is None
    assert provider_sizes == [20, 20]
    assert len(fallback) == 4 and fallback[0]["name"] == "Place 0"

    _, plain, error, _metadata = await skill._process_single_search_request(
        {"query": "cafes in Berlin", "pageSize": 3, "osmEnrichment": "disabled"},
        "maps-plain",
        secrets_manager=object(),
        cache_service=object(),
    )
    assert error is None and len(plain) == 3
    assert provider_sizes == [20, 20, 3]
    assert rank_calls == [20, 20]


# contract-test: direct surface=rest_api assertions=app-skills.search-relevance.bounded-and-conditional,app-skills.search-relevance.safe-finalization
@pytest.mark.anyio
async def test_shopping_relevance_uses_twenty_candidates_without_extra_page(monkeypatch) -> None:
    from backend.apps.shopping.skills import search_products as shopping_search

    provider_sizes = []
    rank_calls = []

    class FakeProduct:
        def __init__(self, index):
            self.index = index

        def to_result_dict(self):
            return {
                "product_id": f"product-{self.index}",
                "title": f"Product {self.index}",
                "description": "Explicit product facts",
                "price": self.index + 1,
            }

    async def fake_provider(**kwargs):
        provider_sizes.append(kwargs["max_results"])
        return [FakeProduct(index) for index in range(kwargs["max_results"])], {
            "totalResultCount": 100,
        }

    async def passthrough_sanitizer(*, payload, **_kwargs):
        return payload

    async def failed_rank(**kwargs):
        rank_calls.append(len(kwargs["candidates"]))
        return search_relevance.SearchRelevanceRankingResult(
            candidates=list(kwargs["candidates"]),
            applied=False,
            fallback_reason="invalid_response",
        )

    monkeypatch.setattr(shopping_search, "rewe_search", fake_provider)
    monkeypatch.setattr(shopping_search, "sanitize_long_text_fields_in_payload", passthrough_sanitizer)
    monkeypatch.setattr(shopping_search, "rank_search_candidates", failed_rank)
    skill = object.__new__(shopping_search.SearchProductsSkill)

    _, fallback, error = await skill._process_single_request(
        {
            "query": "protein snack",
            "category": "grocery",
            "max_results": 4,
            "relevance_criteria": "high protein with low added sugar based on explicit product facts",
        },
        "shopping-fallback",
        secrets_manager=object(),
    )
    assert error is None
    assert provider_sizes == [20]
    assert len(fallback) == 4 and fallback[0]["title"] == "Product 0"

    _, plain, error = await skill._process_single_request(
        {"query": "protein snack", "category": "grocery", "max_results": 3},
        "shopping-plain",
        secrets_manager=object(),
    )
    assert error is None and len(plain) == 3
    assert provider_sizes == [20, 3]
    assert rank_calls == [20]


# contract-test: direct surface=rest_api assertions=app-skills.search-relevance.bounded-and-conditional,app-skills.search-relevance.safe-finalization
@pytest.mark.anyio
async def test_stay_relevance_keeps_serpapi_to_one_twenty_result_request(monkeypatch) -> None:
    from backend.apps.travel.skills import search_stays as stay_search

    provider_sizes = []
    rank_calls = []

    class FakeStay:
        def __init__(self, index):
            self.index = index
            self.name = f"Stay {index}"
            self.extracted_rate_per_night = 100 + index
            self.gps_coordinates = {"latitude": 52.5, "longitude": 13.4 + index / 1000}

        def to_dict(self):
            return {
                "property_token": f"stay-{self.index}",
                "name": self.name,
                "description": "Explicit amenities and location facts",
                "extracted_rate_per_night": self.extracted_rate_per_night,
                "amenities": ["Wi-Fi"],
            }

    async def fake_provider(**kwargs):
        provider_sizes.append(kwargs["max_results"])
        return [FakeStay(index) for index in range(kwargs["max_results"])]

    async def passthrough_sanitizer(*, payload, **_kwargs):
        return payload

    async def failed_rank(**kwargs):
        rank_calls.append(len(kwargs["candidates"]))
        return search_relevance.SearchRelevanceRankingResult(
            candidates=list(kwargs["candidates"]),
            applied=False,
            fallback_reason="provider_failure",
        )

    monkeypatch.setattr(stay_search, "search_hotels", fake_provider)
    monkeypatch.setattr(stay_search, "sanitize_long_text_fields_in_payload", passthrough_sanitizer)
    monkeypatch.setattr(stay_search, "rank_search_candidates", failed_rank)
    skill = object.__new__(stay_search.SearchStaysSkill)

    _, fallback, error = await skill._process_single_request(
        {
            "query": "Berlin hotel",
            "check_in_date": "2026-10-10",
            "check_out_date": "2026-10-12",
            "max_results": 4,
            "relevance_criteria": "quiet work-friendly stay with explicit desk and Wi-Fi evidence",
        },
        "stay-fallback",
        secrets_manager=object(),
    )
    assert error is None
    assert provider_sizes == [20]
    assert len(fallback) == 4 and fallback[0]["name"] == "Stay 0"

    _, plain, error = await skill._process_single_request(
        {
            "query": "Berlin hotel",
            "check_in_date": "2026-10-10",
            "check_out_date": "2026-10-12",
            "max_results": 3,
        },
        "stay-plain",
        secrets_manager=object(),
    )
    assert error is None and len(plain) == 3
    assert provider_sizes == [20, 3]
    assert rank_calls == [20]


# contract-test: direct surface=rest_api assertions=app-skills.search-relevance.bounded-and-conditional,app-skills.search-relevance.safe-finalization
@pytest.mark.anyio
async def test_video_relevance_uses_one_forty_result_brave_call_and_clips_fallback(monkeypatch) -> None:
    from backend.apps.videos.skills import search_skill as video_search

    provider_sizes = []
    rank_calls = []

    async def fake_provider(**kwargs):
        provider_sizes.append(kwargs["count"])
        return {
            "sanitize_output": False,
            "results": [
                {
                    "title": f"Video {index}",
                    "url": f"https://videos.example/{index}",
                    "description": "Explicit tutorial scope",
                }
                for index in range(kwargs["count"])
            ],
        }

    async def allow_rate_limit(**_kwargs):
        return True, None

    async def failed_rank(**kwargs):
        rank_calls.append(len(kwargs["candidates"]))
        return search_relevance.SearchRelevanceRankingResult(
            candidates=list(kwargs["candidates"]),
            applied=False,
            fallback_reason="provider_failure",
        )

    monkeypatch.setattr(video_search, "search_videos", fake_provider)
    monkeypatch.setattr(video_search, "check_rate_limit", allow_rate_limit)
    monkeypatch.setattr(video_search, "rank_search_candidates", failed_rank)
    skill = object.__new__(video_search.SearchSkill)

    _, fallback, error = await skill._process_single_search_request(
        {
            "query": "advanced local AI tutorial",
            "count": 4,
            "relevance_criteria": "hands-on advanced tutorial for an experienced Python developer",
        },
        "videos-fallback",
        secrets_manager=object(),
        cache_service=object(),
    )
    assert error is None
    assert provider_sizes == [40]
    assert len(fallback) == 4 and fallback[0]["title"] == "Video 0"

    _, plain, error = await skill._process_single_search_request(
        {"query": "advanced local AI tutorial", "count": 3},
        "videos-plain",
        secrets_manager=object(),
        cache_service=object(),
    )
    assert error is None and len(plain) == 3
    assert provider_sizes == [40, 8]
    assert rank_calls == [40]


# contract-test: direct surface=rest_api assertions=app-skills.search-relevance.bounded-and-conditional,app-skills.search-relevance.safe-finalization
@pytest.mark.anyio
@pytest.mark.parametrize(
    ("module_name", "class_name", "client_method", "detail_url_field"),
    [
        ("search_locations", "SearchLocationsSkill", "search_locations", "url"),
        ("search_classes", "SearchClassesSkill", "search_classes", "detail_url"),
    ],
)
async def test_fitness_relevance_uses_existing_forty_candidate_pool_and_clips_fallback(
    monkeypatch,
    module_name,
    class_name,
    client_method,
    detail_url_field,
) -> None:
    if module_name == "search_locations":
        from backend.apps.fitness.skills import search_locations as fitness_search
    else:
        from backend.apps.fitness.skills import search_classes as fitness_search

    provider_sizes = []
    rank_calls = []

    class FakeClient:
        async def search_locations(self, **kwargs):
            return await self._results(**kwargs)

        async def search_classes(self, **kwargs):
            return await self._results(**kwargs)

        async def _results(self, **kwargs):
            provider_sizes.append(kwargs["limit"])
            return [
                {
                    "id": f"fitness-{index}",
                    detail_url_field: f"https://fitness.example/{index}",
                    "name": f"Fitness result {index}",
                    "city": "Berlin",
                }
                for index in range(kwargs["limit"])
            ]

    async def failed_rank(**kwargs):
        rank_calls.append(len(kwargs["candidates"]))
        return search_relevance.SearchRelevanceRankingResult(
            candidates=list(kwargs["candidates"]),
            applied=False,
            fallback_reason="provider_failure",
        )

    monkeypatch.setattr(fitness_search, "rank_search_candidates", failed_rank)
    skill_class = getattr(fitness_search, class_name)
    skill = object.__new__(skill_class)
    skill.client = FakeClient()

    payload = {
        "requests": [{
            "query": "yoga",
            "city": "Berlin",
            "limit": 4,
            "relevance_criteria": "beginner-friendly evening option with explicit availability evidence",
        }],
    }
    response = await skill.execute(payload, secrets_manager=object())
    group = response["results"][0]
    assert provider_sizes == [40]
    assert group["result_count"] == 4
    assert group["results"][0]["name"] == "Fitness result 0"

    plain_response = await skill.execute(
        {"requests": [{"query": "yoga", "city": "Berlin", "limit": 3}]},
        secrets_manager=object(),
    )
    assert provider_sizes == [40, 3]
    assert plain_response["results"][0]["result_count"] == 3
    assert rank_calls == [40]
