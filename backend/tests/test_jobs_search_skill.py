"""Jobs search routing, result truthfulness, and grouped embed contract."""

from __future__ import annotations

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


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
def test_pending_preview_metadata_is_lightweight_and_country_routed() -> None:
    assert SearchSkill.resolve_preview_metadata({"query": "engineer"}) == {
        "query": "engineer", "country": "DE",
        "providers": ["arbeitsagentur", "arbeitnow"],
        "provider": "arbeitsagentur, arbeitnow",
    }
    assert SearchSkill.resolve_preview_metadata({"requests": [
        {"query": "analyst", "country": "SE"},
        {"query": "engineer", "country": "DE", "provider": "Arbeitnow"},
    ]}) == {"providers": ["jobtech", "arbeitnow"], "provider": "jobtech, arbeitnow"}


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
    assert payload["providers"] == ["arbeitsagentur", "arbeitnow"]
    assert payload["results"][0]["id"] == "r1"
    assert payload["results"][0]["result_count"] == 1
    child = payload["results"][0]["results"][0]
    assert child["type"] == "job_result"
    assert child["parent_app_skill_type"] == "app_skill_use"
    assert child["remote"] is None and child["salary_min"] is None
    assert [name for name, _ in calls] == ["arbeitsagentur", "arbeitnow"]
    assert all(call["country"] == "DE" and call["limit"] == 10 for _, call in calls)


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
@pytest.mark.asyncio
async def test_swedish_auto_only_uses_jobtech_and_empty_is_success(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    async def jobtech(**kwargs: Any) -> list[dict[str, Any]]:
        calls.append(kwargs)
        return []

    monkeypatch.setitem(jobs_search.PROVIDER_SEARCH, "jobtech", jobtech)
    payload = (await _skill().execute(requests=[{"query": "analyst", "country": "SE"}])).model_dump()

    assert payload["success"] is True
    assert payload["result_count"] == 0
    assert payload["results"][0]["results"] == []
    assert payload["providers"] == ["jobtech"]
    assert len(calls) == 1 and calls[0]["country"] == "SE"


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
        "message": "Arbeitnow is temporarily rate limited.",
    }]


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
@pytest.mark.asyncio
async def test_provider_outage_never_exposes_exception_details(monkeypatch: pytest.MonkeyPatch) -> None:
    async def failed(**kwargs: Any) -> list[dict[str, Any]]:
        raise RuntimeError("private token sk-provider-secret")

    monkeypatch.setitem(jobs_search.PROVIDER_SEARCH, "jobtech", failed)
    payload = (await _skill().execute(requests=[{
        "id": "outage", "query": "analyst", "country": "SE",
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
    payload = (await _skill().execute(requests=[{"query": "analyst", "country": "SE"}])).model_dump()

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
    workflow_result = skill["workflow"]["output_schema"]["properties"]["results"]["items"]["properties"]
    sdk_group = skill["sdk_output_schema"]["properties"]["results"]["items"]["properties"]
    assert workflow_result["title"]["type"] == "string"
    assert "results" not in workflow_result
    assert "title" not in sdk_group
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
        "success": True, "error": None, "results": [{"id": 1, "results": [sample]}],
    })
    Draft202012Validator(skill["workflow"]["output_schema"]).validate({"results": [sample]})
    request_item = skill["tool_schema"]["properties"]["requests"]["items"]
    assert request_item["properties"]["limit"]["maximum"] == 50
    assert request_item["properties"]["country"]["default"] == "DE"


