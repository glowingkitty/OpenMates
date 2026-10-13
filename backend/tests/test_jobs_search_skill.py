"""Jobs search routing, result truthfulness, and grouped embed contract."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator

from backend.apps.jobs.skills import search_skill as jobs_search
from backend.apps.jobs.skills.search_skill import SearchSkill
from backend.apps.ai.utils.app_skill_result_groups import jobs_result_parent_metadata
from backend.shared.providers.jobs.common import ProviderError
from backend.shared.python_utils.search_relevance import (
    SEARCH_RELEVANCE_PROFILES,
    SearchRelevanceRankingResult,
)


def _skill() -> SearchSkill:
    return SearchSkill(
        app=None, app_id="jobs", skill_id="search", skill_name="Search jobs",
        skill_description="Find public jobs.",
    )


def _job(id: str, *, url: str | None = None, **changes: Any) -> dict[str, Any]:
    return {
        "id": id, "title": f"Engineer {id}", "company": "Example Org",
        "url": url or f"https://example.org/jobs/{id}", "apply_url": None,
        "location": "Berlin", "country": "DE", "remote": None,
        "employment_type": "full_time", "published_at": None,
        "description": "Build useful software.", "salary_min": None,
        "salary_max": None, "salary_currency": None, "salary_period": None,
        "provider": "ignored",
        **changes,
    }


@pytest.fixture(autouse=True)
def _block_live_impact_boards(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests never reach a public impact board accidentally."""
    async def empty(**kwargs: Any) -> list[dict[str, Any]]:
        return []

    monkeypatch.setitem(jobs_search.PROVIDER_SEARCH, "eighty_thousand_hours", empty)
    if "hard_problems" in jobs_search.PROVIDER_SEARCH:
        monkeypatch.setitem(jobs_search.PROVIDER_SEARCH, "hard_problems", empty)


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
def test_pending_preview_metadata_is_lightweight_and_country_routed() -> None:
    assert SearchSkill.resolve_preview_metadata({"query": "engineer"}) == {
        "query": "engineer", "country": "DE", "countries": ["DE"],
        "providers": ["arbeitsagentur", "arbeitnow", "eighty_thousand_hours", "hard_problems"],
        "provider": "arbeitsagentur, arbeitnow, eighty_thousand_hours, hard_problems",
    }
    assert SearchSkill.resolve_preview_metadata({"requests": [
        {"query": "analyst", "country": "SE"},
        {"query": "engineer", "country": "DE", "provider": "Arbeitnow"},
    ]}) == {"providers": ["jobtech", "eighty_thousand_hours", "hard_problems", "arbeitnow"],
           "provider": "jobtech, eighty_thousand_hours, hard_problems, arbeitnow", "countries": ["SE", "DE"]}
    assert SearchSkill.resolve_preview_metadata({
        "countries": ["SE"], "requests": [{"query": "analyst"}],
    }) == {"query": "analyst", "country": "SE", "countries": ["SE"],
           "providers": ["jobtech", "eighty_thousand_hours", "hard_problems"],
           "provider": "jobtech, eighty_thousand_hours, hard_problems"}
    assert SearchSkill.resolve_preview_metadata({
        "countries": ["DE", "SE"], "requests": [{"query": "engineer"}],
    }) == {
        "query": "engineer", "country": None, "countries": ["DE", "SE"],
        "providers": ["arbeitsagentur", "arbeitnow", "eighty_thousand_hours", "hard_problems", "jobtech"],
        "provider": "arbeitsagentur, arbeitnow, eighty_thousand_hours, hard_problems, jobtech",
    }


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
def test_grouped_jobs_parent_uses_only_its_own_sources_and_redacts_query_logs() -> None:
    group = {
        "id": "private-career-request", "query": "private career plan", "country": "SE",
        "providers": ["jobtech"], "warnings": [], "results": [_job("one")],
    }
    metadata = jobs_result_parent_metadata(group)
    assert metadata == {
        "country": "SE", "providers": ["jobtech"], "provider": "jobtech", "warnings": [],
    }
    assert jobs_result_parent_metadata({
        "country": None, "countries": ["DE", "SE"], "providers": ["arbeitsagentur", "jobtech"],
    }) == {
        "country": None, "countries": ["DE", "SE"],
        "providers": ["arbeitsagentur", "jobtech"], "provider": "arbeitsagentur, jobtech",
    }
    assert "query" not in metadata and "results" not in metadata and "id" not in metadata

    source = (Path(__file__).resolve().parents[1] / "apps" / "ai" / "processing" / "main_processor.py").read_text()
    grouped = source.split("if is_multiple_requests:", 1)[1].split(
        "# Single request: Update the existing placeholder embed", 1,
    )[0]
    assert 'redact_group_ids = app_id in {"hosting", "jobs"}' in grouped
    assert 'request_metadata_with_provider.update(jobs_result_parent_metadata(grouped_result))' in grouped
    assert "if app_id == 'hosting' else request_metadata.get('query'" not in grouped
    assert "if app_id == 'hosting' else fallback_value" not in grouped


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
@pytest.mark.asyncio
async def test_default_germany_auto_groups_and_deduplicates(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    async def ba(**kwargs: Any) -> list[dict[str, Any]]:
        calls.append(("arbeitsagentur", kwargs))
        return [_job("ba-1", url="https://example.org/jobs/shared?utm_source=x")]

    async def arbeitnow(**kwargs: Any) -> list[dict[str, Any]]:
        calls.append(("arbeitnow", kwargs))
        return [_job("an-1", url="https://example.org/jobs/shared?utm_source=y")]

    monkeypatch.setitem(jobs_search.PROVIDER_SEARCH, "arbeitsagentur", ba)
    monkeypatch.setitem(jobs_search.PROVIDER_SEARCH, "arbeitnow", arbeitnow)
    payload = (await _skill().execute(requests=[{"id": "r1", "query": "engineer"}])).model_dump()

    assert payload["success"] is True
    assert payload["partial"] is False
    assert payload["result_count"] == 1
    assert payload["error"] is None
    assert payload["providers"] == ["arbeitsagentur", "arbeitnow", "eighty_thousand_hours", "hard_problems"]
    assert payload["results"][0]["id"] == "r1"
    assert payload["results"][0]["country"] == "DE"
    assert payload["results"][0]["countries"] == ["DE"]
    assert payload["results"][0]["result_count"] == 1
    child = payload["results"][0]["results"][0]
    assert child["type"] == "job_result"
    assert child["parent_app_skill_type"] == "app_skill_use"
    assert child["remote"] is None and child["salary_min"] is None
    assert [name for name, _ in calls] == ["arbeitsagentur", "arbeitnow"]
    assert all(call["country"] == "DE" and call["limit"] == 10 for _, call in calls)


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
@pytest.mark.asyncio
async def test_swedish_auto_uses_only_relevant_sources_and_empty_is_success(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    async def jobtech(**kwargs: Any) -> list[dict[str, Any]]:
        calls.append(kwargs)
        return []

    monkeypatch.setitem(jobs_search.PROVIDER_SEARCH, "jobtech", jobtech)
    payload = (await _skill().execute(requests=[{"query": "analyst", "country": "SE"}])).model_dump()

    assert payload["success"] is True
    assert payload["result_count"] == 0
    assert payload["results"][0]["results"] == []
    assert payload["providers"] == ["jobtech", "eighty_thousand_hours", "hard_problems"]
    assert payload["results"][0]["countries"] == ["SE"]
    assert len(calls) == 1 and calls[0]["country"] == "SE"


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
@pytest.mark.asyncio
async def test_selected_de_and_se_sources_start_in_parallel_and_keep_country_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: set[tuple[str, str]] = set()
    release = asyncio.Event()
    expected_pairs = {(name, country) for name, coverage in jobs_search.PROVIDER_COUNTRIES.items() for country in coverage}

    def source(name: str):
        async def search(**kwargs: Any) -> list[dict[str, Any]]:
            country = kwargs["country"]
            assert country in jobs_search.PROVIDER_COUNTRIES[name]
            started.add((name, country))
            if started == expected_pairs:
                release.set()
            await asyncio.wait_for(release.wait(), timeout=2)
            return [_job(f"{name}-{country}", country=country)]
        return search

    for name in jobs_search.PROVIDER_COUNTRIES:
        monkeypatch.setitem(jobs_search.PROVIDER_SEARCH, name, source(name))
    payload = (await _skill().execute(
        countries=["DE", "SE"], requests=[{"id": "both", "query": "engineer", "limit": 10}],
    )).model_dump()

    assert started == expected_pairs
    assert payload["success"] is True and payload["partial"] is False
    group = payload["results"][0]
    assert group["countries"] == ["DE", "SE"] and group["country"] is None
    assert group["providers"] == ["arbeitsagentur", "arbeitnow", "eighty_thousand_hours", "hard_problems", "jobtech"]
    assert [(job["provider"], job["country"]) for job in group["results"]] == [
        (name, country) for country in ["DE", "SE"] for name in group["providers"]
        if country in jobs_search.PROVIDER_COUNTRIES[name]
    ]


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
@pytest.mark.asyncio
async def test_one_cross_country_source_gets_parallel_country_calls_without_leaking_listings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: set[str] = set()
    release = asyncio.Event()

    async def cross_country(**kwargs: Any) -> list[dict[str, Any]]:
        country = kwargs["country"]
        started.add(country)
        if len(started) == 2:
            release.set()
        await asyncio.wait_for(release.wait(), timeout=2)
        other = "SE" if country == "DE" else "DE"
        return [_job(country, country=country), _job(f"leak-{country}", country=other)]

    monkeypatch.setitem(jobs_search.PROVIDER_COUNTRIES, "cross_country", frozenset({"DE", "SE"}))
    monkeypatch.setitem(jobs_search.PROVIDER_ALIASES, "cross country", "cross_country")
    monkeypatch.setitem(jobs_search.PROVIDER_SEARCH, "cross_country", cross_country)
    payload = (await _skill().execute(
        countries=["DE", "SE"], requests=[{
            "query": "analyst", "provider": "Cross Country", "limit": 1,
        }],
    )).model_dump()

    assert started == {"DE", "SE"}
    assert payload["providers"] == payload["results"][0]["providers"] == ["cross_country"]
    assert payload["result_count"] == 1
    assert [(job["id"], job["country"]) for job in payload["results"][0]["results"]] == [("DE", "DE")]


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
@pytest.mark.asyncio
async def test_cross_country_listing_keeps_each_verified_country_fact(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def board(**kwargs: Any) -> list[dict[str, Any]]:
        country = kwargs["country"]
        calls.append(country)
        return [_job("same-board-id", url="https://example.org/jobs/both", country=country)]

    monkeypatch.setitem(jobs_search.PROVIDER_SEARCH, "eighty_thousand_hours", board)
    payload = (await _skill().execute(countries=["DE", "SE"], requests=[{
        "query": "analyst", "provider": "80k",
    }])).model_dump()

    assert calls == ["DE", "SE"]
    assert [(job["country"], job["url"]) for job in payload["results"][0]["results"]] == [
        ("DE", "https://example.org/jobs/both"), ("SE", "https://example.org/jobs/both"),
    ]


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
@pytest.mark.asyncio
async def test_impact_board_filter_compatibility_is_explicit_and_never_calls_irrelevant_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    def source(name: str):
        async def search(**kwargs: Any) -> list[dict[str, Any]]:
            calls.append((name, kwargs["country"]))
            return []
        return search

    for name in jobs_search.PROVIDER_SEARCH:
        monkeypatch.setitem(jobs_search.PROVIDER_SEARCH, name, source(name))

    explicit = (await _skill().execute(requests=[
        {"id": "80k-remote", "query": "analyst", "provider": "80.000 Hours", "remote": True},
        {"id": "hard-onsite", "query": "analyst", "provider": "Hard Problems", "remote": False},
        {"id": "hard-contract", "query": "analyst", "provider": "HardProblems", "employment_type": "contract"},
    ])).model_dump()
    assert calls == []
    assert all(group["error"] and group["results"] == [] for group in explicit["results"])

    remote = (await _skill().execute(countries=["DE", "SE"], requests=[{
        "query": "analyst", "remote": True,
    }])).model_dump()
    assert calls == [
        ("arbeitsagentur", "DE"), ("arbeitnow", "DE"), ("hard_problems", "DE"),
        ("hard_problems", "SE"), ("jobtech", "SE"),
    ]
    assert "eighty_thousand_hours" not in remote["providers"]
    calls.clear()

    internship = (await _skill().execute(countries=["SE"], requests=[{
        "query": "analyst", "employment_type": "internship",
    }])).model_dump()
    assert calls == [("eighty_thousand_hours", "SE")]
    assert internship["success"] is True


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
@pytest.mark.asyncio
async def test_country_inheritance_alias_and_explicit_country_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    def source(name: str):
        async def search(**kwargs: Any) -> list[dict[str, Any]]:
            country = kwargs["country"]
            calls.append((name, country))
            return [_job(f"{name}-{country}", country=country)]
        return search

    for name in jobs_search.PROVIDER_COUNTRIES:
        monkeypatch.setitem(jobs_search.PROVIDER_SEARCH, name, source(name))

    inherited = (await _skill().execute(countries=["SE"], requests=[{"query": "analyst"}])).model_dump()
    assert calls == [("jobtech", "SE"), ("eighty_thousand_hours", "SE"), ("hard_problems", "SE")]
    assert inherited["results"][0]["country"] == "SE"
    calls.clear()

    aliased = (await _skill().execute(countries=["SE"], requests=[{
        "query": "engineer", "country": "DE",
    }])).model_dump()
    assert calls == [("arbeitsagentur", "DE"), ("arbeitnow", "DE"),
                     ("eighty_thousand_hours", "DE"), ("hard_problems", "DE")]
    assert aliased["results"][0]["countries"] == ["DE"]
    calls.clear()

    overridden = (await _skill().execute(countries=["DE"], requests=[{
        "query": "analyst", "countries": ["SE"],
    }])).model_dump()
    assert calls == [("jobtech", "SE"), ("eighty_thousand_hours", "SE"), ("hard_problems", "SE")]
    assert overridden["results"][0]["country"] == "SE"
    calls.clear()

    invalid_mixed = (await _skill().execute(countries=["DE"], requests=[{
        "query": "engineer", "providers": ["JobTech", "Arbeitnow"],
    }])).model_dump()
    assert calls == []
    assert invalid_mixed["success"] is False
    assert "jobtech" in invalid_mixed["results"][0]["error"]
    assert invalid_mixed["results"][0]["results"] == []

    valid_mixed = (await _skill().execute(countries=["DE", "SE"], requests=[{
        "query": "engineer", "providers": ["JobTech", "Arbeitnow"],
    }])).model_dump()
    assert calls == [("arbeitnow", "DE"), ("jobtech", "SE")]
    assert valid_mixed["results"][0]["providers"] == ["jobtech", "arbeitnow"]
    assert [(job["country"], job["provider"]) for job in valid_mixed["results"][0]["results"]] == [
        ("DE", "arbeitnow"), ("SE", "jobtech"),
    ]


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
@pytest.mark.asyncio
async def test_typed_rest_request_null_optionals_inherit_top_level_countries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def jobtech(**kwargs: Any) -> list[dict[str, Any]]:
        calls.append(kwargs["country"])
        return [_job("sweden", country="SE")]

    monkeypatch.setitem(jobs_search.PROVIDER_SEARCH, "jobtech", jobtech)
    payload = (await _skill().execute(countries=["SE"], requests=[{
        "query": "developer", "provider": "JobTech", "country": None,
        "countries": None, "remote": None, "employment_type": None,
    }])).model_dump()

    assert calls == ["SE"]
    assert payload["success"] is True
    assert payload["results"][0]["countries"] == ["SE"]
    assert payload["results"][0]["results"][0]["country"] == "SE"


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
@pytest.mark.asyncio
async def test_invalid_country_selections_and_uncovered_sources_never_call_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def unexpected(**kwargs: Any) -> list[dict[str, Any]]:
        calls.append(kwargs["country"])
        return []

    for name in jobs_search.PROVIDER_SEARCH:
        monkeypatch.setitem(jobs_search.PROVIDER_SEARCH, name, unexpected)
    for top_level in ([], ["US"], ["DE", "US"]):
        response = (await _skill().execute(countries=top_level, requests=[{"query": "engineer"}])).model_dump()
        assert response["success"] is False and response["error"] and response["results"] == []

    response = (await _skill().execute(requests=[
        {"id": "empty", "query": "engineer", "countries": []},
        {"id": "conflict", "query": "engineer", "country": "DE", "countries": ["SE"]},
        {"id": "unsupported", "query": "engineer", "countries": ["US"]},
        {"id": "uncovered", "query": "engineer", "countries": ["DE", "SE"], "provider": "JobTech"},
        {"id": "radius", "query": "engineer", "countries": ["DE", "SE"],
         "location": "Berlin", "radius_km": 20},
    ])).model_dump()
    assert [group["id"] for group in response["results"]] == [
        "empty", "conflict", "unsupported", "uncovered", "radius",
    ]
    assert all(group["error"] and group["results"] == [] for group in response["results"])
    assert "country or countries" in response["results"][1]["error"]
    assert "covers DE" in response["results"][3]["error"]
    assert calls == []


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
@pytest.mark.asyncio
async def test_explicit_source_and_radius_errors_are_visible_without_broadening(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []

    async def unexpected(**kwargs: Any) -> list[dict[str, Any]]:
        called.append("provider")
        return []

    for name in jobs_search.PROVIDER_SEARCH:
        monkeypatch.setitem(jobs_search.PROVIDER_SEARCH, name, unexpected)
    payload = (await _skill().execute(requests=[
        {"id": "unknown", "query": "analyst", "provider": "not-a-source"},
        {"id": "country", "query": "analyst", "country": "SE", "provider": "Arbeitnow"},
        {"id": "radius", "query": "analyst", "country": "SE", "location": "Stockholm", "radius_km": 20},
        {"id": "unsupported", "query": "analyst", "location": "Berlin", "radius_km": 20, "provider": "Arbeitnow"},
    ])).model_dump()

    assert payload["success"] is False
    assert called == []
    assert [group["id"] for group in payload["results"]] == ["unknown", "country", "radius", "unsupported"]
    assert all(group["results"] == [] and group["error"] for group in payload["results"])
    assert "Unsupported jobs provider" in payload["results"][0]["error"]


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
@pytest.mark.asyncio
async def test_batch_preserves_partial_provider_failure_and_request_independence(monkeypatch: pytest.MonkeyPatch) -> None:
    async def ba(**kwargs: Any) -> list[dict[str, Any]]:
        return [_job("ba-1")]

    async def arbeitnow(**kwargs: Any) -> list[dict[str, Any]]:
        raise ProviderError("rate_limited", "Arbeitnow is temporarily rate limited.")

    monkeypatch.setitem(jobs_search.PROVIDER_SEARCH, "arbeitsagentur", ba)
    monkeypatch.setitem(jobs_search.PROVIDER_SEARCH, "arbeitnow", arbeitnow)
    payload = (await _skill().execute(requests=[
        {"id": "ok", "query": "engineer"},
        {"id": "bad", "query": "engineer", "country": "US"},
    ])).model_dump()

    assert payload["success"] is True
    assert payload["partial"] is True
    assert payload["result_count"] == 1
    assert payload["results"][0]["results"][0]["title"] == "Engineer ba-1"
    assert payload["results"][1]["error"]
    assert payload["warnings"] == [{
        "request_id": "ok", "provider": "arbeitnow", "code": "rate_limited",
        "message": "Arbeitnow is temporarily rate limited.", "country": "DE",
    }]


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
@pytest.mark.asyncio
async def test_provider_outage_never_exposes_exception_details(monkeypatch: pytest.MonkeyPatch) -> None:
    async def failed(**kwargs: Any) -> list[dict[str, Any]]:
        raise RuntimeError("private token sk-provider-secret")

    monkeypatch.setitem(jobs_search.PROVIDER_SEARCH, "jobtech", failed)
    payload = (await _skill().execute(requests=[{
        "id": "outage", "query": "analyst", "country": "SE", "provider": "JobTech",
    }])).model_dump()

    assert payload["success"] is False
    assert payload["partial"] is False
    assert payload["results"][0]["error"] == "All requested job sources failed."
    assert payload["warnings"][0]["code"] == "unavailable"
    assert "sk-provider-secret" not in str(payload)


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
@pytest.mark.asyncio
async def test_nonempty_unusable_provider_response_is_an_error_not_no_results(monkeypatch: pytest.MonkeyPatch) -> None:
    async def malformed(**kwargs: Any) -> list[dict[str, Any]]:
        return [{"title": "Missing safe URL", "country": "SE"}]

    monkeypatch.setitem(jobs_search.PROVIDER_SEARCH, "jobtech", malformed)
    payload = (await _skill().execute(requests=[{
        "query": "analyst", "country": "SE", "provider": "JobTech",
    }])).model_dump()

    assert payload["success"] is False
    assert payload["results"][0]["error"] == "All requested job sources failed."
    assert payload["warnings"][0]["code"] == "invalid_response"


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
@pytest.mark.asyncio
async def test_radius_routes_only_to_agency_and_keeps_strict_remote(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    async def ba(**kwargs: Any) -> list[dict[str, Any]]:
        calls.append(kwargs)
        return [_job("unknown-remote"), _job("remote", remote=True)]

    monkeypatch.setitem(jobs_search.PROVIDER_SEARCH, "arbeitsagentur", ba)
    payload = (await _skill().execute(requests=[{
        "query": "engineer", "location": "Berlin", "radius_km": 25, "remote": True,
    }])).model_dump()

    assert payload["providers"] == ["arbeitsagentur"]
    assert calls[0]["radius_km"] == 25
    assert [job["id"] for job in payload["results"][0]["results"]] == ["remote"]


# contract-test: supporting surface=rest_api assertions=app-skills.search-relevance.bounded-and-conditional
@pytest.mark.asyncio
async def test_user_criteria_rank_bounded_pool_without_changing_provider_facts(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    rank_calls: list[dict[str, Any]] = []

    async def ba(**kwargs: Any) -> list[dict[str, Any]]:
        calls.append(kwargs)
        return [_job("generic"), _job("impact", description="Build clean-energy software.")]

    async def rank(**kwargs: Any) -> SearchRelevanceRankingResult[dict[str, Any]]:
        rank_calls.append(kwargs)
        return SearchRelevanceRankingResult(candidates=list(reversed(kwargs["candidates"])), applied=True)

    monkeypatch.setitem(jobs_search.PROVIDER_SEARCH, "arbeitsagentur", ba)
    monkeypatch.setattr(jobs_search, "rank_search_candidates", rank)
    payload = (await _skill().execute(requests=[{
        "query": "engineer", "provider": "Arbeitsagentur", "limit": 1,
        "relevance_criteria": "Work directly on clean energy",
    }])).model_dump()

    assert calls[0]["limit"] == 40
    assert rank_calls[0]["profile"] == "jobs"
    assert rank_calls[0]["relevance_criteria"] == "Work directly on clean energy"
    assert payload["results"][0]["results"][0]["id"] == "impact"
    assert "remote" in SEARCH_RELEVANCE_PROFILES["jobs"].instructions
    assert "impact" in SEARCH_RELEVANCE_PROFILES["jobs"].instructions


# contract-test: supporting surface=rest_api assertions=app-skills.search-relevance.safe-finalization
@pytest.mark.asyncio
@pytest.mark.parametrize("failure_mode", ["fallback", "exception"])
async def test_ranking_unavailable_keeps_strict_provider_results_and_warns(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, failure_mode: str,
) -> None:
    provider_calls: list[dict[str, Any]] = []
    ranking_calls: list[dict[str, Any]] = []

    async def ba(**kwargs: Any) -> list[dict[str, Any]]:
        provider_calls.append(kwargs)
        return [_job("first", remote=True), _job("unknown", remote=None), _job("second", remote=True)]

    async def rank(**kwargs: Any) -> SearchRelevanceRankingResult[dict[str, Any]]:
        ranking_calls.append(kwargs)
        if failure_mode == "exception":
            raise RuntimeError("private-ranking-error-token")
        return SearchRelevanceRankingResult(
            candidates=list(reversed(kwargs["candidates"])), applied=False,
            fallback_reason="provider_failure",
        )

    monkeypatch.setitem(jobs_search.PROVIDER_SEARCH, "arbeitsagentur", ba)
    monkeypatch.setattr(jobs_search, "rank_search_candidates", rank)
    payload = (await _skill().execute(requests=[{
        "id": "goal", "query": "engineer", "provider": "Arbeitsagentur", "remote": True,
        "relevance_criteria": "private-career-goal-token",
    }])).model_dump()

    assert len(provider_calls) == len(ranking_calls) == 1
    assert provider_calls[0]["remote"] is True
    assert [job["id"] for job in ranking_calls[0]["candidates"]] == ["first", "second"]
    assert [job["id"] for job in payload["results"][0]["results"]] == ["first", "second"]
    assert payload["success"] is True and payload["partial"] is True and payload["error"] is None
    warning = {
        "request_id": "goal", "provider": "ranking", "code": "ranking_unavailable",
        "message": jobs_search.RANKING_UNAVAILABLE_MESSAGE,
    }
    assert payload["warnings"] == payload["results"][0]["warnings"] == [warning]
    assert "private-career-goal-token" not in caplog.text
    assert "private-ranking-error-token" not in caplog.text
    assert "private-ranking-error-token" not in str(payload)


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity,workflows.surface.semantic-parity
def test_jobs_skill_metadata_declares_bounded_workflow_contract() -> None:
    app_file = Path(__file__).resolve().parents[1] / "apps/jobs/app.yml"
    data = yaml.safe_load(app_file.read_text(encoding="utf-8"))
    skill = next(item for item in data["skills"] if item["id"] == "search")
    assert skill["external_data"] is True
    assert skill["workflow"]["binding_requirements"] == ["none"]
    assert skill["workflow"]["effect"] == "read"
    top_countries = skill["tool_schema"]["properties"]["countries"]
    assert top_countries["default"] == ["DE"]
    assert top_countries["minItems"] == 1 and top_countries["maxItems"] == 2
    assert top_countries["items"]["enum"] == ["DE", "SE"]
    assert top_countries["x-ui"]["basic"] is True
    workflow_result = skill["workflow"]["output_schema"]["properties"]["results"]["items"]["properties"]
    sdk_group = skill["sdk_output_schema"]["properties"]["results"]["items"]["properties"]
    assert workflow_result["title"]["type"] == "string"
    assert "results" not in workflow_result
    assert "title" not in sdk_group
    assert sdk_group["country"]["type"] == ["string", "null"]
    assert sdk_group["countries"]["items"]["type"] == "string"
    assert sdk_group["results"]["items"]["properties"]["title"]["type"] == "string"
    listing = sdk_group["results"]["items"]["properties"]
    for field, value_type in {
        "company": "string", "apply_url": "string", "location": "string",
        "remote": "boolean", "employment_type": "string", "published_at": "string",
        "description": "string", "salary_min": "number", "salary_max": "number",
        "salary_currency": "string", "salary_period": "string",
    }.items():
        assert listing[field]["type"] == [value_type, "null"]
        assert workflow_result[field]["type"] == [value_type, "null"]
    assert skill["sdk_output_schema"]["properties"]["error"]["type"] == ["string", "null"]
    sample = _job("nullable", company=None, apply_url=None, location=None,
                  employment_type=None, description=None)
    Draft202012Validator(skill["sdk_output_schema"]).validate({
        "success": True, "error": None,
        "results": [{"id": 1, "country": None, "countries": ["DE", "SE"], "results": [sample]}],
    })
    Draft202012Validator(skill["workflow"]["output_schema"]).validate({"results": [sample]})
    request_item = skill["tool_schema"]["properties"]["requests"]["items"]
    assert request_item["properties"]["provider"]["enum"] == [
        "auto", "Arbeitnow", "Arbeitsagentur", "JobTech", "80,000 Hours", "Hard Problems",
    ]
    assert request_item["properties"]["providers"]["items"]["enum"] == [
        "Arbeitnow", "Arbeitsagentur", "JobTech", "80,000 Hours", "Hard Problems",
    ]
    assert [provider["name"] for provider in skill["providers"]] == [
        "Bundesagentur für Arbeit", "Arbeitnow", "JobTech", "80,000 Hours", "Hard Problems",
    ]
    assert all(provider["no_api_key"] is True and set(provider) == {"name", "no_api_key"}
               for provider in skill["providers"])
    assert request_item["properties"]["limit"]["maximum"] == 50
    assert "default" not in request_item["properties"]["country"]
    assert request_item["properties"]["country"]["x-ui"]["basic"] is False
    assert request_item["properties"]["countries"]["x-ui"]["basic"] is False
