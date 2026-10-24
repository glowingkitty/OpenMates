"""Jobs search routing, result truthfulness, and grouped embed contract."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from backend.apps.jobs.skills import search_skill as jobs_search
from backend.apps.jobs.skills.search_skill import SearchSkill


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
