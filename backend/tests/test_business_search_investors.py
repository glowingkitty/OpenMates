"""business.search_investors: request schema, unavailable boundary and flat delegate shape.

The skill ships paused with no built-in provider; installed providers serve it
through the generic ``skill.requests@1`` flat contract. The runner is faked.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
import yaml
from pydantic import ValidationError

from backend.apps.business.skills.search_investors import (
    InvestorSearchRequest,
    InvestorSearchResponse,
    SearchInvestorsSkill,
)
from backend.shared.app_packages import delegate_flat_skill, loader, provider_dispatch
from backend.shared.app_packages.delegate_flat_skill import InstalledProviderFlatSkill
from backend.shared.app_packages.generic_contract import SKILL_REQUESTS_V1, accepts_generic_contract
from backend.shared.app_packages.runner_client import RunnerResult
from backend.tests.app_packages_test_support import enable, manifest, write_package, write_registry

APP, SKILL = "business", "search_investors"
FIRST, SECOND = "my_provider", "my_other_provider"


def _skill_definition() -> Dict[str, Any]:
    config = yaml.safe_load((loader.BUILTIN_APPS_DIR / APP / "app.yml").read_text(encoding="utf-8"))
    return next(item for item in config["skills"] if item["id"] == SKILL)


def _entry(provider_id: str, name: str, **extra: Any) -> Dict[str, Any]:
    return {"app": APP, "skill": SKILL, "contract": SKILL_REQUESTS_V1, "id": provider_id, "name": name,
            "runtime": "executable", "entrypoint": "bin/provider", **extra}


@pytest.fixture(autouse=True)
def _reset():
    loader.reset_installed_packages_cache()
    delegate_flat_skill.resolve_flat_skill_models.cache_clear()
    yield
    loader.reset_installed_packages_cache()


def _delegate() -> InstalledProviderFlatSkill:
    raw = _skill_definition()
    skill = object.__new__(InstalledProviderFlatSkill)
    skill.app_id, skill.skill_id = APP, SKILL
    definition = SimpleNamespace(delegated_class_path=str(raw["class_path"]).strip(), tool_schema=raw["tool_schema"])
    skill.app = SimpleNamespace(get_skill_by_id=lambda _sid: definition)
    return skill


def _fake_runner(monkeypatch, outcomes: Dict[str, RunnerResult]) -> List[Dict[str, Any]]:
    calls: List[Dict[str, Any]] = []

    async def fake_run_provider(provider, input_item, secrets, **_kwargs):
        calls.append({"provider": provider.provider_id, "input": input_item})
        return outcomes[provider.provider_id]

    monkeypatch.setattr(provider_dispatch, "run_provider", fake_run_provider)
    return calls


def _install(monkeypatch, tmp_path, providers: List[Dict[str, Any]]) -> None:
    sha = write_package(tmp_path, manifest(package_id="my.package", providers=providers), package_id="my.package")
    write_registry(tmp_path, {"my.package": {"version": "1.0.0", "sha256": sha}})
    enable(monkeypatch, tmp_path)


def _investor(name: str) -> Dict[str, Any]:
    return {"name": name, "investor_type": "angel", "profile_url": f"https://example.org/{name}"}


# contract-test: supporting surface=rest_api assertions=investors.request
def test_request_defaults_and_worldwide():
    request = InvestorSearchRequest(query="climate software", regions=["DE", "WORLDWIDE"])
    assert request.currency == "EUR" and request.max_results == 15 and request.investor_types == []
    assert InvestorSearchRequest(query="x", regions=["US"], ticket_min=10000.5, max_results=30).max_results == 30


@pytest.mark.parametrize("payload", [
    {"query": "", "regions": ["DE"]},
    {"query": "x" * 201, "regions": ["DE"]},
    {"query": "x", "regions": []},
    {"query": "x", "regions": ["DE"] * 11},
    {"query": "x", "regions": ["Germany"]},
    {"query": "x", "regions": ["de"]},
    {"query": "x", "regions": ["DE"], "max_results": 31},
    {"query": "x", "regions": ["DE"], "max_results": 0},
    {"query": "x", "regions": ["DE"], "stages": ["ipo"]},
    {"query": "x", "regions": ["DE"], "currency": "euro"},
    {"query": "x", "regions": ["DE"], "unknown": 1},
])
# contract-test: supporting surface=rest_api assertions=investors.request
def test_request_rejects_invalid_input(payload):
    with pytest.raises(ValidationError):
        InvestorSearchRequest(**payload)


# contract-test: supporting surface=rest_api assertions=investors.unavailable
@pytest.mark.anyio
async def test_unavailable_response():
    response = await SearchInvestorsSkill.execute(object.__new__(SearchInvestorsSkill))
    assert response.error_code == "provider_unavailable" and response.success is False
    assert response.investors == [] and "not a recommendation" in response.limitation
    assert InvestorSearchResponse.model_validate({}).skill_id == SKILL


# contract-test: supporting surface=rest_api assertions=investors.unavailable
def test_skill_definition_accepts_generic_contract():
    definition = _skill_definition()
    assert accepts_generic_contract(definition)
    assert definition["providers"] == [] and definition["provider_required"] is True
    assert "requests" not in definition["tool_schema"]["properties"]


# contract-test: supporting surface=rest_api assertions=investors.results
@pytest.mark.anyio
async def test_flat_delegate_fills_one_investors_list(monkeypatch, tmp_path):
    _install(monkeypatch, tmp_path, [_entry(FIRST, "Example provider"), _entry(SECOND, "Other provider")])
    calls = _fake_runner(monkeypatch, {
        FIRST: RunnerResult(ok=True, results=[_investor("a1"), _investor("a2")]),
        SECOND: RunnerResult(ok=True, results=[_investor("b1")]),
    })
    response = await _delegate().execute(secrets_manager=None, user_id="u", query="climate software",
                                         regions=["DE", "AT"], stages=["seed"])
    assert [c["provider"] for c in calls] == [FIRST, SECOND]
    assert calls[0]["input"]["currency"] == "EUR" and calls[0]["input"]["max_results"] == 15
    assert "results" not in response
    assert [i["name"] for i in response["investors"]] == ["a1", "b1", "a2"]
    assert response["result_count"] == 3 and response["success"] is True and response["error"] is None
    assert response["query"] == "climate software" and response["regions"] == ["DE", "AT"]
    assert response["providers"] == [FIRST, SECOND] and response["limitation"]


# contract-test: supporting surface=rest_api assertions=investors.request
@pytest.mark.anyio
async def test_flat_delegate_invalid_region_and_no_provider(monkeypatch, tmp_path):
    _install(monkeypatch, tmp_path, [_entry(FIRST, "Example provider")])
    calls = _fake_runner(monkeypatch, {})
    invalid = await _delegate().execute(query="x", regions=["Germany"])
    assert calls == [] and invalid["success"] is False and invalid["error"].startswith("Invalid request")
    loader.reset_installed_packages_cache()
    monkeypatch.setenv("OPENMATES_APP_PACKAGES_ENABLED", "false")
    none = await _delegate().execute(query="x", regions=["DE"])
    assert calls == [] and none["success"] is False and none["error"]


# contract-test: supporting surface=rest_api assertions=investors.regions,instance-app-packages.provider-contract
@pytest.mark.anyio
async def test_region_specific_provider_is_skipped_outside_its_regions(monkeypatch, tmp_path):
    _install(monkeypatch, tmp_path, [_entry(FIRST, "Example provider", regions=["DE", "AT"]),
                                     _entry(SECOND, "Other provider")])
    calls = _fake_runner(monkeypatch, {SECOND: RunnerResult(ok=True, results=[_investor("b1")])})
    response = await _delegate().execute(query="developer tools", regions=["US"])
    assert [c["provider"] for c in calls] == [SECOND]
    assert [i["name"] for i in response["investors"]] == ["b1"]
    assert response["warnings"] == ["Example provider was not searched: it does not cover US."]
    assert response["partial"] is True and response["error"] is None


# contract-test: supporting surface=rest_api assertions=investors.regions,instance-app-packages.provider-contract
@pytest.mark.anyio
async def test_region_specific_provider_runs_for_its_region_and_worldwide(monkeypatch, tmp_path):
    _install(monkeypatch, tmp_path, [_entry(FIRST, "Example provider", regions=["DE"])])
    calls = _fake_runner(monkeypatch, {FIRST: RunnerResult(ok=True, results=[_investor("a1")])})
    for regions in (["DE", "US"], ["WORLDWIDE"]):
        response = await _delegate().execute(query="x", regions=regions)
        assert response["investors"][0]["name"] == "a1" and not response["warnings"]
    assert [c["provider"] for c in calls] == [FIRST, FIRST]


# contract-test: supporting surface=rest_api assertions=investors.regions,instance-app-packages.provider-contract
@pytest.mark.anyio
async def test_no_provider_covers_the_region(monkeypatch, tmp_path):
    _install(monkeypatch, tmp_path, [_entry(FIRST, "Example provider", regions=["DE"])])
    calls = _fake_runner(monkeypatch, {})
    response = await _delegate().execute(query="x", regions=["US", "CA"])
    assert calls == [] and response["success"] is False
    assert response["error"] == "No installed provider covers US, CA."


# contract-test: supporting surface=rest_api assertions=instance-app-packages.provider-contract
@pytest.mark.parametrize("regions", [[], ["de"], ["DEU"], ["DE", "DE"], ["DE"] * 61, "DE"])
def test_manifest_rejects_invalid_regions(monkeypatch, tmp_path, regions):
    _install(monkeypatch, tmp_path, [_entry(FIRST, "Example provider", regions=regions)])
    assert loader.get_installed_packages().for_skill(APP, SKILL) == []


# contract-test: supporting surface=rest_api assertions=instance-app-packages.provider-contract
def test_manifest_accepts_regions(monkeypatch, tmp_path):
    _install(monkeypatch, tmp_path, [_entry(FIRST, "Example provider", regions=["DE", "AT"])])
    [provider] = loader.get_installed_packages().for_skill(APP, SKILL)
    assert provider.regions == ("DE", "AT")
