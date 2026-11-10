"""Instance app packages: jobs.search@1 dispatch to installed providers next to the built-in source.

Runs with the backend dependencies (api image). The runner is faked at the
client boundary; runner isolation itself is covered by
test_app_packages_runner.py. Provider ids and hosts are synthetic.
Architecture: docs/architecture/apps/instance-app-packages.md
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest
import yaml

from backend.apps.jobs.skills import search_skill as jobs_search
from backend.apps.jobs.skills.search_skill import SearchSkill
from backend.core.api.app.routes import apps_api
from backend.shared.app_packages import loader, provider_dispatch
from backend.shared.app_packages.contracts import (
    JOBS_SEARCH_V1, MAX_DESCRIPTION_CHARS, validate_contract_results, validate_jobs_search_result,
)
from backend.shared.app_packages.overlay import apply_app_package_overlay
from backend.shared.app_packages.runner_client import RunnerResult
from backend.shared.python_utils.search_relevance import SearchRelevanceRankingResult
from backend.tests.app_packages_test_support import (
    FakeSecretsManager, enable, manifest, provider_entry, write_package, write_registry,
)

PACKAGE_ID = "org.example.my-jobs"
VERSION = "1.0.0"
PROVIDER_ID = "my_provider"
PROVIDER_NAME = "My provider"


def _jobs_provider(**overrides: Any) -> Dict[str, Any]:
    entry = provider_entry(app="jobs", skill="search", contract=JOBS_SEARCH_V1, id=PROVIDER_ID,
                           name=PROVIDER_NAME, secrets=[], skill_hint="Search job listings.")
    entry.update(overrides)
    return entry


def _install(root, providers: List[Dict[str, Any]]) -> None:
    sha = write_package(root, manifest(package_id=PACKAGE_ID, version=VERSION, providers=providers),
                        package_id=PACKAGE_ID, version=VERSION)
    write_registry(root, {PACKAGE_ID: {"version": VERSION, "sha256": sha}})


@pytest.fixture(autouse=True)
def _installed(monkeypatch, tmp_path):
    _install(tmp_path, [_jobs_provider()])
    enable(monkeypatch, tmp_path)
    builtin_calls: List[Dict[str, Any]] = []

    async def builtin(**kwargs):
        builtin_calls.append(kwargs)
        return [_builtin_job("b1"), _builtin_job("b2")]

    monkeypatch.setitem(jobs_search.PROVIDER_SEARCH, "jobtech", builtin)
    yield builtin_calls
    loader.reset_installed_packages_cache()


def _skill() -> SearchSkill:
    return SearchSkill(app=None, app_id="jobs", skill_id="search", skill_name="Search jobs",
                       skill_description="Find public jobs.")


def _builtin_job(job_id: str, **changes: Any) -> Dict[str, Any]:
    return {"id": f"builtin:{job_id}", "title": f"Builtin {job_id}", "company": "Example Org",
            "url": f"https://jobs.example.org/{job_id}", "apply_url": None, "location": "Stockholm",
            "country": "SE", "remote": None, "employment_type": "full_time", "published_at": None,
            "description": "Built-in listing.", "provider": "jobtech", **changes}


def _package_job(job_id: str, **changes: Any) -> Dict[str, Any]:
    return {"id": job_id, "title": f"Package {job_id}", "url": f"https://listings.example.org/{job_id}",
            "company": "Example GmbH", "location": "Berlin", "country": "DE", "remote": True,
            "employment_type": "full_time",
            "description": "Full listing text.", "provider": "jobtech", "provider_id": "jobtech",
            "free": True, **changes}


def _fake_runner(monkeypatch, outcome: RunnerResult) -> List[Dict[str, Any]]:
    calls: List[Dict[str, Any]] = []

    async def fake_run_provider(provider, input_item, secrets, **kwargs):
        calls.append({"provider": provider.provider_id, "input": input_item, "secrets": secrets})
        return outcome

    monkeypatch.setattr(provider_dispatch, "run_provider", fake_run_provider)
    return calls


async def _run(**kwargs: Any) -> Dict[str, Any]:
    return (await _skill().execute(secrets_manager=FakeSecretsManager(), **kwargs)).model_dump()


# contract-test: direct surface=rest_api assertions=instance-app-packages.provider-contract
async def test_explicit_installed_provider_receives_one_item_and_results_are_attributed(monkeypatch, _installed):
    calls = _fake_runner(monkeypatch, RunnerResult(ok=True, results=[_package_job("p1"), {"title": "no url"}]))
    payload = await _run(countries=["DE"], requests=[{
        "id": "r1", "query": " climate policy analyst ", "location": " Berlin ", "remote": True,
        "employment_type": "Vollzeit", "provider": PROVIDER_NAME, "limit": 5,
    }])
    assert calls == [{"provider": PROVIDER_ID, "secrets": {}, "input": {
        "id": "r1", "query": "climate policy analyst", "countries": ["DE"], "location": "Berlin",
        "remote": True, "employment_type": "full_time", "limit": 5,
    }}]
    assert _installed == []
    assert payload["success"] is True and payload["error"] is None
    assert payload["providers"] == [PROVIDER_ID]
    group = payload["results"][0]
    assert group["providers"] == [PROVIDER_ID] and "error" not in group
    (job,) = group["results"]
    assert job["provider"] == PROVIDER_NAME and job["provider_id"] == PROVIDER_ID
    assert job["type"] == "job_result" and "free" not in job
    assert job["description"] == "Full listing text."


# contract-test: direct surface=rest_api assertions=instance-app-packages.provider-contract
async def test_auto_merges_builtin_and_installed_listings_interleaved_and_deduplicated(monkeypatch, _installed):
    duplicate = _package_job("dup", url="https://jobs.example.org/b1", country="SE")
    _fake_runner(monkeypatch, RunnerResult(ok=True, results=[_package_job("p1", country="SE"), duplicate,
                                                              _package_job("p2", country="SE")]))
    payload = await _run(countries=["SE"], requests=[{"id": "all", "query": "engineer"}])
    assert len(_installed) == 1
    group = payload["results"][0]
    assert group["providers"] == ["jobtech", PROVIDER_ID]
    assert [job["id"] for job in group["results"]] == ["builtin:b1", "p1", "builtin:b2", "p2"]
    assert payload["providers"] == ["jobtech", PROVIDER_ID]


# contract-test: direct surface=rest_api assertions=instance-app-packages.provider-contract
async def test_builtin_coverage_gap_does_not_block_installed_providers(monkeypatch, _installed):
    calls = _fake_runner(monkeypatch, RunnerResult(ok=True, results=[_package_job("p1")]))
    payload = await _run(countries=["DE"], requests=[
        {"id": "auto", "query": "engineer"},
        {"id": "explicit", "query": "engineer", "providers": ["JobTech", PROVIDER_ID]},
        {"id": "radius", "query": "engineer", "countries": ["SE"], "location": "Stockholm", "radius_km": 20},
    ])
    assert _installed == []
    assert len(calls) == 3 and sorted(call["input"].get("radius_km", 0) for call in calls) == [0, 0, 20]
    auto, explicit, radius = payload["results"]
    assert auto["providers"] == [PROVIDER_ID] and auto["warnings"] == [] and "error" not in auto
    assert [job["id"] for job in auto["results"]] == ["p1"]
    assert explicit["providers"] == [PROVIDER_ID] and "error" not in explicit
    assert [(w["provider"], w["code"]) for w in explicit["warnings"]] == [("jobtech", "coverage_gap")]
    assert radius["providers"] == [PROVIDER_ID]
    assert [(w["provider"], w["code"]) for w in radius["warnings"]] == [("jobtech", "unsupported_filter")]


# contract-test: direct surface=rest_api assertions=instance-app-packages.provider-contract
async def test_installed_results_pass_the_same_strict_filters_and_ranking(monkeypatch):
    _fake_runner(monkeypatch, RunnerResult(ok=True, results=[
        _package_job("remote", country="SE"), _package_job("onsite", country="SE", remote=False)]))
    ranked: List[List[str]] = []

    async def reverse_ranking(**kwargs):
        ranked.append([job["id"] for job in kwargs["candidates"]])
        return SearchRelevanceRankingResult(candidates=list(reversed(kwargs["candidates"])), applied=True)

    monkeypatch.setattr(jobs_search, "rank_search_candidates", reverse_ranking)
    payload = await _run(countries=["SE"], requests=[
        {"query": "engineer", "remote": True, "relevance_criteria": "climate impact", "provider": PROVIDER_ID}])
    assert ranked == [["remote"]]
    assert [job["id"] for job in payload["results"][0]["results"]] == ["remote"]


# contract-test: direct surface=rest_api assertions=instance-app-packages.provider-contract
async def test_installed_provider_failure_is_isolated_and_safe(monkeypatch):
    _fake_runner(monkeypatch, RunnerResult(ok=False, error_code="TIMEOUT", message="internal detail"))
    payload = await _run(countries=["SE"], requests=[{"id": "all", "query": "engineer"}])
    group = payload["results"][0]
    assert payload["success"] is True and "error" not in group
    assert [job["id"] for job in group["results"]] == ["builtin:b1", "builtin:b2"]
    assert {"request_id": "all", "provider": PROVIDER_ID, "code": "unavailable",
            "message": f"{PROVIDER_NAME} did not respond in time."} in group["warnings"]
    assert "internal detail" not in str(payload)

    only = await _run(countries=["DE"], requests=[{"id": "de", "query": "engineer"}])
    assert only["success"] is False and only["results"][0]["error"] == "All requested job sources failed."


# contract-test: direct surface=rest_api assertions=instance-app-packages.instance-availability
async def test_flag_off_keeps_builtin_behaviour(monkeypatch, _installed):
    monkeypatch.delenv(loader.ENABLED_ENV)
    loader.reset_installed_packages_cache()
    calls = _fake_runner(monkeypatch, RunnerResult(ok=True, results=[_package_job("p1")]))
    payload = await _run(countries=["DE"], requests=[
        {"id": "gap", "query": "engineer"},
        {"id": "installed", "query": "engineer", "provider": PROVIDER_ID},
        {"id": "se", "query": "engineer", "country": "SE"},
    ])
    gap, installed, sweden = payload["results"]
    assert gap["error"] == "No requested jobs provider covers DE."
    assert installed["error"] == "Unsupported jobs provider. Choose JobTech."
    assert sweden["providers"] == ["jobtech"] and len(sweden["results"]) == 2
    assert calls == [] and len(_installed) == 1


# --------------------------------------------------------------------------- contract validation

# contract-test: direct surface=rest_api assertions=instance-app-packages.provider-contract
def test_jobs_result_contract_validation():
    description = "x" * (MAX_DESCRIPTION_CHARS - 1000)
    raw = {**_package_job(7, url="http://listings.example.org/7"), "description": description,
           "apply_url": "javascript:alert(1)", "remote": "yes", "salary_min": float("inf"), "salary_max": 5000,
           "salary_currency": "EUR", "published_at": "2026-11-01", "valid_through": "soon", "extra": "dropped"}
    result = validate_jobs_search_result(raw)
    assert result["id"] == "7" and result["url"] == "http://listings.example.org/7"
    assert result["description"] == description
    assert result["salary_max"] == 5000 and result["published_at"] == "2026-11-01"
    for dropped in ("apply_url", "remote", "salary_min", "valid_through", "extra", "free", "provider", "provider_id"):
        assert dropped not in result
    for missing in ("id", "title", "url"):
        assert validate_jobs_search_result({**_package_job("x"), missing: None}) is None
    assert validate_jobs_search_result(_package_job("x", url="ftp://listings.example.org/x")) is None
    (stamped,) = validate_contract_results(JOBS_SEARCH_V1, [raw], provider_id=PROVIDER_ID, provider_name=PROVIDER_NAME)
    assert (stamped["provider"], stamped["provider_id"]) == (PROVIDER_NAME, PROVIDER_ID)
    assert len(validate_contract_results(JOBS_SEARCH_V1, [_package_job(str(i)) for i in range(80)],
                                         provider_id=PROVIDER_ID, provider_name=PROVIDER_NAME)) == 50


# --------------------------------------------------------------------------- manifest, overlay and preview

# contract-test: direct surface=rest_api assertions=instance-app-packages.manifest-validation
def test_loader_accepts_jobs_contract_and_rejects_reserved_selectors(tmp_path):
    assert [p.provider_id for p in loader.get_installed_providers("jobs", "search")] == [PROVIDER_ID]
    for reserved in ("auto", "jobtech", "jobtechdev"):
        root = tmp_path / reserved
        _install(root, [_jobs_provider(id=reserved)])
        assert loader.load_installed_packages(root).providers == ()
    wrong = tmp_path / "wrong"
    _install(wrong, [_jobs_provider(contract="events.search@1")])
    assert loader.load_installed_packages(wrong).providers == ()


# contract-test: direct surface=rest_api assertions=instance-app-packages.instance-availability
def test_overlay_adds_installed_provider_to_jobs_schema_and_preview():
    raw = yaml.safe_load((loader.BUILTIN_APPS_DIR / "jobs" / "app.yml").read_text(encoding="utf-8"))
    skill = next(s for s in apply_app_package_overlay("jobs", raw)["skills"] if s["id"] == "search")
    assert skill["provider_contract"] == JOBS_SEARCH_V1
    assert skill["providers"][-1]["installed"] is True and skill["providers"][-1]["id"] == PROVIDER_ID
    item_schema = skill["tool_schema"]["properties"]["requests"]["items"]["properties"]
    assert PROVIDER_ID in item_schema["provider"]["enum"] and PROVIDER_ID in item_schema["providers"]["items"]["enum"]
    assert skill["preprocessor_hint"] == "Search job listings."
    preview = SearchSkill.resolve_preview_metadata({"countries": ["DE"], "requests": [{"query": "engineer"}]})
    assert preview["providers"] == [PROVIDER_ID]


# --------------------------------------------------------------------------- billing

# contract-test: direct surface=rest_api assertions=instance-app-packages.no-installed-provider-charges
async def test_installed_only_groups_are_free_and_builtin_groups_are_charged(monkeypatch):
    _fake_runner(monkeypatch, RunnerResult(ok=True, results=[_package_job("p1", country="SE")]))
    body = {"countries": ["SE"], "requests": [
        {"query": "engineer", "provider": PROVIDER_ID}, {"query": "engineer"}, {"query": "engineer", "provider": "JobTech"}]}
    payload = await _run(**body)
    assert apps_api.chargeable_skill_units("jobs", "search", body, payload) == 2
    installed_only = {"countries": ["DE"], "requests": [{"query": "engineer"}]}
    assert apps_api.chargeable_skill_units("jobs", "search", installed_only, await _run(**installed_only)) == 0
    monkeypatch.delenv(loader.ENABLED_ENV)
    loader.reset_installed_packages_cache()
    assert apps_api.chargeable_skill_units("jobs", "search", body, payload) == 3
