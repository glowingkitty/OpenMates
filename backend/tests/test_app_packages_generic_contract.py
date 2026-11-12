"""Instance app packages: the generic ``skill.requests@1`` contract for paused skills.

Covers target eligibility, the metadata overlay class swap, the delegate skill
(validation, provider selection, round-robin merge, failures), the flat-schema
delegate (whole tool input as one item, original response shape), the generic
result validator, optional secrets and the billing exemption. The runner is
faked at the client boundary; runner isolation is covered by
test_app_packages_runner.py.
Architecture: docs/architecture/apps/instance-app-packages.md ("Generic contract").
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
import yaml

from backend.apps.base_app import BaseApp
from backend.core.api.app.routes import apps_api
from backend.shared.app_packages import (
    billing, contracts, delegate_flat_skill, delegate_skill, loader, overlay, provider_dispatch,
)
from backend.shared.app_packages.delegate_flat_skill import InstalledProviderFlatSkill
from backend.shared.app_packages.delegate_skill import InstalledProviderSkill
from backend.shared.app_packages.generic_contract import (
    DELEGATE_CLASS_PATH, FLAT_DELEGATE_CLASS_PATH, SKILL_REQUESTS_V1, accepts_generic_contract,
    validate_generic_result,
)
from backend.shared.app_packages.runner_client import RunnerResult
from backend.shared.python_schemas.app_metadata_schemas import AppSkillDefinition, skill_has_provider_support
from backend.tests.app_packages_test_support import enable, manifest, write_package, write_registry

APP, SKILL = "health", "search_appointments"
APP_DIR = loader.BUILTIN_APPS_DIR / APP
PACKAGE = "my.package"
FIRST, SECOND = "my_provider", "my_other_provider"
FIRST_NAME, SECOND_NAME = "Example provider", "Other example provider"
HINT = "Use for appointments offered by the example provider."
VALID_ITEM = {"speciality": "dentist", "city": "Example City"}


def _entry(provider_id: str = FIRST, name: str = FIRST_NAME, **overrides: Any) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "app": APP, "skill": SKILL, "contract": SKILL_REQUESTS_V1, "id": provider_id, "name": name,
        "runtime": "executable", "entrypoint": "bin/provider",
    }
    entry.update(overrides)
    return entry


def _install(root: Path, providers: List[Dict[str, Any]], package_id: str = PACKAGE) -> None:
    sha = write_package(root, manifest(package_id=package_id, providers=providers), package_id=package_id)
    write_registry(root, {package_id: {"version": "1.0.0", "sha256": sha}})


def _raw_health() -> Dict[str, Any]:
    return yaml.safe_load((APP_DIR / "app.yml").read_text(encoding="utf-8"))


def _skill_of(config: Dict[str, Any]) -> Dict[str, Any]:
    return next(s for s in config["skills"] if s["id"] == SKILL)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    for name in ("SECRET__MY_PROVIDER__PROXY_URL", "SECRET__MY_PROVIDER__API_KEY"):
        monkeypatch.delenv(name, raising=False)
    loader.reset_installed_packages_cache()
    delegate_skill.resolve_original_skill_models.cache_clear()
    delegate_flat_skill.resolve_flat_skill_models.cache_clear()
    yield
    loader.reset_installed_packages_cache()


@pytest.fixture
def two_providers(monkeypatch, tmp_path):
    _install(tmp_path, [_entry(skill_hint=HINT), _entry(SECOND, SECOND_NAME)])
    enable(monkeypatch, tmp_path)
    return tmp_path


def _fake_runner(monkeypatch, outcomes: Dict[str, RunnerResult]) -> List[Dict[str, Any]]:
    calls: List[Dict[str, Any]] = []

    async def fake_run_provider(provider, input_item, secrets, **_kwargs):
        calls.append({"provider": provider.provider_id, "contract": provider.contract,
                      "input": input_item, "secrets": secrets})
        return outcomes[provider.provider_id]

    monkeypatch.setattr(provider_dispatch, "run_provider", fake_run_provider)
    return calls


def _delegate() -> InstalledProviderSkill:
    original = str(_skill_of(_raw_health())["class_path"]).strip()
    skill = object.__new__(InstalledProviderSkill)
    skill.app_id, skill.skill_id = APP, SKILL
    skill.app = SimpleNamespace(get_skill_by_id=lambda _sid: SimpleNamespace(delegated_class_path=original))
    return skill


def _result(title: str, **extra: Any) -> Dict[str, Any]:
    return {"title": title, "url": f"https://example.org/{title}", **extra}


# --------------------------------------------------------------------------- eligibility (loader)

def _synthetic_apps(tmp_path: Path) -> Path:
    requests_schema = {"type": "object", "properties": {"requests": {"type": "array", "items": {"type": "object"}}}}
    base = {"name_translation_key": "x", "description_translation_key": "x", "class_path": "my.skills.Skill"}
    skills = [
        {**base, "id": "paused", "provider_required": True, "providers": [], "tool_schema": requests_schema},
        {**base, "id": "with_builtin", "provider_required": True, "providers": [{"name": "my_builtin"}],
         "tool_schema": requests_schema},
        {**base, "id": "local", "tool_schema": requests_schema},
        {**base, "id": "flat", "provider_required": True, "providers": [],
         "tool_schema": {"type": "object", "properties": {"query": {"type": "string"}}}},
        {**base, "id": "no_schema", "provider_required": True, "providers": []},
        {**base, "id": "requests_not_array", "provider_required": True, "providers": [],
         "tool_schema": {"type": "object", "properties": {"requests": {"type": "string"}}}},
        {**base, "id": "declared", "provider_required": True, "providers": [],
         "provider_contract": "myapp.declared@1", "tool_schema": requests_schema},
    ]
    apps_dir = tmp_path / "apps"
    (apps_dir / "myapp").mkdir(parents=True)
    (apps_dir / "myapp" / "app.yml").write_text(yaml.safe_dump({"id": "myapp", "skills": skills}), encoding="utf-8")
    return apps_dir


# contract-test: direct surface=rest_api assertions=instance-app-packages.manifest-validation
@pytest.mark.parametrize("skill_id, accepted", [
    ("paused", True), ("with_builtin", False), ("local", False), ("flat", True), ("no_schema", False),
    ("requests_not_array", False), ("declared", False),
])
def test_generic_contract_target_eligibility(tmp_path, skill_id, accepted):
    apps_dir = _synthetic_apps(tmp_path)
    root = tmp_path / "root"
    _install(root, [_entry(app="myapp", skill=skill_id)])
    loaded = loader.load_installed_packages(root, apps_dir=apps_dir)
    assert bool(loaded.for_skill("myapp", skill_id)) is accepted


# contract-test: direct surface=rest_api assertions=instance-app-packages.manifest-validation
def test_real_paused_skills_are_eligible_and_contract_skills_are_not():
    assert accepts_generic_contract(_skill_of(_raw_health()))
    events = yaml.safe_load((loader.BUILTIN_APPS_DIR / "events" / "app.yml").read_text(encoding="utf-8"))
    assert not accepts_generic_contract(next(s for s in events["skills"] if s["id"] == "search"))


# contract-test: direct surface=rest_api assertions=instance-app-packages.manifest-validation,instance-app-packages.operator-secrets
@pytest.mark.parametrize("bad", [
    _entry(id="auto"), _entry(id="all"), _entry(id="openai"),
    _entry(secrets=["api_key"], optional_secrets=["api_key"]),
    _entry(optional_secrets=["Proxy-URL"]), _entry(optional_secrets=["proxy_url", "proxy_url"]),
])
def test_generic_contract_rejects_reserved_ids_and_bad_optional_secrets(tmp_path, caplog, bad):
    _install(tmp_path, [bad])
    with caplog.at_level(logging.ERROR):
        assert loader.load_installed_packages(tmp_path).providers == ()
    assert "Rejected package" in caplog.text


# contract-test: direct surface=rest_api assertions=instance-app-packages.manifest-validation
def test_generic_provider_ids_are_unique_across_packages(tmp_path):
    sha_a = write_package(tmp_path, manifest(package_id="my.package", providers=[_entry()]), package_id="my.package")
    sha_b = write_package(tmp_path, manifest(package_id="my.second", providers=[_entry()]), package_id="my.second")
    write_registry(tmp_path, {"my.package": {"version": "1.0.0", "sha256": sha_a},
                              "my.second": {"version": "1.0.0", "sha256": sha_b}})
    (provider,) = loader.load_installed_packages(tmp_path).for_skill(APP, SKILL)
    assert provider.package_id == "my.package"


# --------------------------------------------------------------------------- overlay

# contract-test: direct surface=rest_api assertions=instance-app-packages.instance-availability
def test_overlay_swaps_class_and_keeps_original(two_providers):
    raw = _raw_health()
    original = str(_skill_of(raw)["class_path"]).strip()
    result = overlay.apply_app_package_overlay(APP, raw)
    skill = _skill_of(result)
    assert _skill_of(raw)["class_path"].strip() == original  # input never mutated
    assert skill["class_path"] == DELEGATE_CLASS_PATH and skill["delegated_class_path"] == original
    assert [p["id"] for p in skill["providers"]] == [FIRST, SECOND]
    assert skill["preprocessor_hint"] == HINT and "default_enabled" not in skill
    definition = AppSkillDefinition(**skill)
    assert skill_has_provider_support(definition) and definition.delegated_class_path == original
    # Idempotent: the overlaid skill has providers and is no longer eligible.
    assert overlay.apply_app_package_overlay(APP, result) is result


# contract-test: direct surface=rest_api assertions=instance-app-packages.instance-availability
def test_overlay_without_hint_drops_paused_hint(monkeypatch, tmp_path):
    _install(tmp_path, [_entry()])
    enable(monkeypatch, tmp_path)
    assert "preprocessor_hint" not in _skill_of(overlay.apply_app_package_overlay(APP, _raw_health()))


# contract-test: direct surface=rest_api assertions=instance-app-packages.instance-availability
def test_flag_off_metadata_is_byte_identical(monkeypatch, tmp_path):
    _install(tmp_path, [_entry()])
    monkeypatch.delenv(loader.ENABLED_ENV, raising=False)
    monkeypatch.setenv(loader.MOUNT_ENV, str(tmp_path))
    raw = _raw_health()
    before = json.dumps(raw, sort_keys=True)
    assert overlay.apply_app_package_overlay(APP, raw) is raw
    assert json.dumps(raw, sort_keys=True) == before
    assert billing.served_only_by_installed_providers(APP, SKILL) is False


# contract-test: direct surface=rest_api assertions=instance-app-packages.instance-availability
def test_base_app_resolves_delegate_and_dispatches(monkeypatch, two_providers):
    calls = _fake_runner(monkeypatch, {FIRST: RunnerResult(ok=True, results=[_result("a")]),
                                       SECOND: RunnerResult(ok=True, results=[])})
    app = BaseApp(app_dir=str(APP_DIR), register_http_routes=False,
                  preloaded_config_dict=overlay.apply_app_package_overlay(APP, _raw_health()))
    assert app.skill_classes[SKILL] is InstalledProviderSkill
    import asyncio
    response = asyncio.run(app.dispatch_skill(SKILL, {"requests": [VALID_ITEM]}))
    assert response["results"][0]["results"][0]["provider_id"] == FIRST
    assert {call["provider"] for call in calls} == {FIRST, SECOND}


# --------------------------------------------------------------------------- delegate execution

# contract-test: direct surface=rest_api assertions=instance-app-packages.provider-contract
@pytest.mark.anyio
async def test_delegate_stamps_validates_and_interleaves(monkeypatch, two_providers):
    first = [_result("a1", provider="spoofed", provider_id=SECOND, credits_charged=0),
             "not an object", _result("a2"), _result("a3")]
    calls = _fake_runner(monkeypatch, {FIRST: RunnerResult(ok=True, results=first),
                                       SECOND: RunnerResult(ok=True, results=[_result("b1")])})
    response = await _delegate().execute([{"id": "r1", **VALID_ITEM}])
    (group,) = response["results"]
    assert group["id"] == "r1" and "error" not in group
    assert [r["title"] for r in group["results"]] == ["a1", "b1", "a2", "a3"]
    a1 = group["results"][0]
    assert (a1["provider"], a1["provider_id"]) == (FIRST_NAME, FIRST) and "credits_charged" not in a1
    assert group["providers"] == [FIRST, SECOND]
    assert response["provider"] == f"{FIRST_NAME}, {SECOND_NAME}" and response["error"] is None
    # Original response model defaults are kept.
    assert "visit_motive_id" in response["ignore_fields_for_inference"]
    assert {c["contract"] for c in calls} == {SKILL_REQUESTS_V1}
    assert calls[0]["input"]["speciality"] == "dentist" and calls[0]["input"]["max_doctors"] == 10


# contract-test: direct surface=rest_api assertions=instance-app-packages.provider-contract
@pytest.mark.anyio
async def test_delegate_isolates_provider_failure(monkeypatch, two_providers):
    _fake_runner(monkeypatch, {FIRST: RunnerResult(ok=False, error_code="TIMEOUT", message="internal detail"),
                               SECOND: RunnerResult(ok=True, results=[_result("b1")])})
    response = await _delegate().execute([VALID_ITEM])
    (group,) = response["results"]
    assert [r["provider_id"] for r in group["results"]] == [SECOND]
    assert group["warnings"] == [f"{FIRST_NAME} did not respond in time."] and "error" not in group
    assert response["error"] is None and "internal detail" not in json.dumps(response)


# contract-test: direct surface=rest_api assertions=instance-app-packages.provider-contract
@pytest.mark.anyio
async def test_delegate_all_providers_fail(monkeypatch, two_providers):
    _fake_runner(monkeypatch, {FIRST: RunnerResult(ok=False, error_code="EXECUTION_FAILED"),
                               SECOND: RunnerResult(ok=False, error_code="PROVIDER_ERROR", message="x")})
    response = await _delegate().execute([VALID_ITEM])
    (group,) = response["results"]
    assert group["results"] == [] and group["providers"] == []
    assert group["error"] == f"{FIRST_NAME} failed. {SECOND_NAME} reported an error."
    assert response["error"] == group["error"]


# contract-test: direct surface=rest_api assertions=instance-app-packages.provider-contract
@pytest.mark.anyio
@pytest.mark.parametrize("selector", [{"provider": SECOND}, {"providers": [SECOND]},
                                      {"provider_platform": SECOND_NAME.upper()}])
async def test_delegate_runs_only_selected_provider(monkeypatch, two_providers, selector):
    calls = _fake_runner(monkeypatch, {FIRST: RunnerResult(ok=True, results=[_result("a")]),
                                       SECOND: RunnerResult(ok=True, results=[_result("b")])})
    # The health item model has no ``providers`` field; selectors are read from the raw item.
    group = (await _delegate().execute([{**VALID_ITEM, **selector}]))["results"][0]
    assert [c["provider"] for c in calls] == [SECOND] and group["providers"] == [SECOND]


# contract-test: direct surface=rest_api assertions=instance-app-packages.provider-contract
def test_overlay_declares_provider_filter_in_request_item_schema():
    item = {"type": "object", "properties": {"query": {"type": "string"}}}
    skill = {"tool_schema": {"type": "object", "properties": {"requests": {"type": "array", "items": item}}}}
    overlay.ensure_provider_selector(skill, [FIRST, SECOND])
    declared = item["properties"]["providers"]
    assert declared["type"] == "array" and declared["items"] == {"type": "string", "enum": [FIRST, SECOND]}
    flat = {"tool_schema": {"type": "object", "properties": {"query": {"type": "string"}}}}
    overlay.ensure_provider_selector(flat, [FIRST])
    assert flat["tool_schema"]["properties"]["providers"]["items"]["enum"] == [FIRST]
    # A schema that already has a selector is left as authored.
    authored = {"tool_schema": {"type": "object", "properties": {"provider": {"type": "string"}}}}
    overlay.ensure_provider_selector(authored, [FIRST])
    assert list(authored["tool_schema"]["properties"]) == ["provider"]


# contract-test: direct surface=rest_api assertions=instance-app-packages.provider-contract
@pytest.mark.anyio
async def test_delegate_returns_duplicate_results_once(monkeypatch, two_providers):
    keyed = {"dedupe_key": "Listing-1", "dedupe_priority": 0}
    first = [_result("same"), _result("same"), {**_result("a without price"), **keyed}]
    second = [_result("same"), {**_result("b with price"), **keyed, "dedupe_priority": 5,
                                "dedupe_key": "listing-1"}, _result("only b")]
    _fake_runner(monkeypatch, {FIRST: RunnerResult(ok=True, results=first),
                               SECOND: RunnerResult(ok=True, results=second)})
    group = (await _delegate().execute([VALID_ITEM]))["results"][0]
    assert [(r["title"], r["provider_id"]) for r in group["results"]] == [
        ("same", FIRST), ("b with price", SECOND), ("only b", SECOND)]
    assert all("dedupe_key" not in r and "dedupe_priority" not in r for r in group["results"])


# contract-test: direct surface=rest_api assertions=instance-app-packages.provider-contract
@pytest.mark.anyio
async def test_delegate_unknown_selector_runs_every_provider(monkeypatch, two_providers):
    calls = _fake_runner(monkeypatch, {FIRST: RunnerResult(ok=True, results=[]),
                                       SECOND: RunnerResult(ok=True, results=[])})
    response = await _delegate().execute([{**VALID_ITEM, "provider_platform": "auto"}])
    assert sorted(c["provider"] for c in calls) == sorted([FIRST, SECOND])
    assert response["results"][0]["results"] == [] and "error" not in response["results"][0]


# contract-test: direct surface=rest_api assertions=instance-app-packages.provider-contract
@pytest.mark.anyio
async def test_delegate_invalid_item_is_a_group_error_without_runner_call(monkeypatch, two_providers):
    calls = _fake_runner(monkeypatch, {FIRST: RunnerResult(ok=True, results=[_result("a")]),
                                       SECOND: RunnerResult(ok=True, results=[])})
    response = await _delegate().execute([{"city": "Example City"}, VALID_ITEM])
    bad, good = response["results"]
    assert bad["id"] == 1 and bad["error"].startswith("Invalid request: speciality")
    assert good["id"] == 2 and good["results"][0]["title"] == "a"
    assert len(calls) == 2 and response["error"] is None


# contract-test: direct surface=rest_api assertions=instance-app-packages.provider-contract
def test_null_optional_fields_use_model_defaults():
    models = delegate_skill.resolve_original_skill_models(str(_skill_of(_raw_health())["class_path"]))
    contract_input, error = delegate_skill.validate_request_item(
        models.item_model, {**VALID_ITEM, "language": None, "telehealth": None},
    )
    assert error is None and contract_input is not None
    assert contract_input["telehealth"] is False and "language" not in contract_input


# contract-test: direct surface=rest_api assertions=instance-app-packages.provider-contract
def test_provider_list_follows_the_original_response_model():
    travel = yaml.safe_load((APP_DIR.parent / "travel" / "app.yml").read_text(encoding="utf-8"))
    class_path = next(s for s in travel["skills"] if s["id"] == "search_connections")["class_path"]
    models = delegate_skill.resolve_original_skill_models(str(class_path).strip())
    assert models.provider_objects is True
    provider = SimpleNamespace(provider_id="my_provider", name="My provider")
    group = {"id": 1, "results": [{"title": "a"}], "providers": ["my_provider"]}
    response = delegate_skill.build_response([group], [provider], models.response_defaults, models.provider_objects)
    assert response["providers"] == [{"id": "my_provider", "name": "My provider"}]
    plain = delegate_skill.build_response([group], [provider], {})
    assert plain["providers"] == ["my_provider"]


# contract-test: direct surface=rest_api assertions=instance-app-packages.provider-contract
def test_original_models_are_resolved_from_skill_module():
    models = delegate_skill.resolve_original_skill_models(str(_skill_of(_raw_health())["class_path"]))
    assert models.item_model.__name__ == "SearchAppointmentsRequestItem"
    assert models.response_defaults["provider"] == "Unavailable"
    with pytest.raises(delegate_skill.DelegateConfigurationError):
        delegate_skill.resolve_original_skill_models("backend.apps.missing_module.Skill")


# --------------------------------------------------------------------------- flat-schema delegate

FLAT_APP, FLAT_SKILL = "business", "search_trademarks"
FLAT_APP_DIR = loader.BUILTIN_APPS_DIR / FLAT_APP
FLAT_INPUT = {"queries": ["Example name"], "regions": ["US", "EU"], "match": "exact"}


def _raw_flat_app() -> Dict[str, Any]:
    return yaml.safe_load((FLAT_APP_DIR / "app.yml").read_text(encoding="utf-8"))


def _flat_skill_of(config: Dict[str, Any]) -> Dict[str, Any]:
    return next(s for s in config["skills"] if s["id"] == FLAT_SKILL)


@pytest.fixture
def flat_providers(monkeypatch, tmp_path):
    flat = {"app": FLAT_APP, "skill": FLAT_SKILL}
    _install(tmp_path, [_entry(skill_hint=HINT, **flat), _entry(SECOND, SECOND_NAME, **flat)])
    enable(monkeypatch, tmp_path)
    return tmp_path


def _flat_delegate() -> InstalledProviderFlatSkill:
    raw = _flat_skill_of(_raw_flat_app())
    skill = object.__new__(InstalledProviderFlatSkill)
    skill.app_id, skill.skill_id = FLAT_APP, FLAT_SKILL
    definition = SimpleNamespace(delegated_class_path=str(raw["class_path"]).strip(), tool_schema=raw["tool_schema"])
    skill.app = SimpleNamespace(get_skill_by_id=lambda _sid: definition)
    return skill


# contract-test: direct surface=rest_api assertions=instance-app-packages.manifest-validation,instance-app-packages.instance-availability
def test_flat_paused_skill_accepts_generic_contract_and_overlays_flat_delegate(flat_providers):
    raw = _raw_flat_app()
    assert accepts_generic_contract(_flat_skill_of(raw))
    (provider, _second) = loader.get_installed_providers(FLAT_APP, FLAT_SKILL)
    assert provider.contract == SKILL_REQUESTS_V1 and provider.skill_hint == HINT
    skill = _flat_skill_of(overlay.apply_app_package_overlay(FLAT_APP, raw))
    assert skill["class_path"] == FLAT_DELEGATE_CLASS_PATH
    assert skill["delegated_class_path"] == str(_flat_skill_of(raw)["class_path"]).strip()
    assert skill["preprocessor_hint"] == HINT and [p["id"] for p in skill["providers"]] == [FIRST, SECOND]
    assert skill_has_provider_support(AppSkillDefinition(**skill))


# contract-test: direct surface=rest_api assertions=instance-app-packages.provider-contract
@pytest.mark.anyio
async def test_flat_delegate_passes_whole_input_and_keeps_original_shape(monkeypatch, flat_providers):
    calls = _fake_runner(monkeypatch, {FIRST: RunnerResult(ok=True, results=[_result("a1"), _result("a2")]),
                                       SECOND: RunnerResult(ok=True, results=[_result("b1")])})
    response = await _flat_delegate().execute(
        secrets_manager=None, user_id="user-1", chat_id="chat-1", nice_classes=None, **FLAT_INPUT,
    )
    expected_input = {"queries": ["Example name"], "regions": ["US", "EU"], "nice_classes": [],
                      "status": "active", "match": "exact", "max_results": 10}
    assert [c["input"] for c in calls] == [expected_input, expected_input]
    assert {c["contract"] for c in calls} == {SKILL_REQUESTS_V1}
    # Original response model: results live in its first list-of-objects field, never a top-level results array.
    assert "results" not in response
    assert [r["title"] for r in response["matches"]] == ["a1", "b1", "a2"]
    assert response["matches"][0]["provider_id"] == FIRST and response["result_count"] == 3
    assert response["query"] == "Example name" and response["regions"] == ["US", "EU"]
    assert response["match"] == "exact" and response["status"] == "finished"
    assert response["success"] is True and response["error"] is None and response["coverage"] == []
    assert response["provider"] == f"{FIRST_NAME}, {SECOND_NAME}" and response["providers"] == [FIRST, SECOND]
    assert response["limitation"]


# contract-test: direct surface=rest_api assertions=instance-app-packages.provider-contract
@pytest.mark.anyio
async def test_flat_delegate_validation_selection_and_failures(monkeypatch, flat_providers):
    calls = _fake_runner(monkeypatch, {FIRST: RunnerResult(ok=False, error_code="TIMEOUT", message="internal"),
                                       SECOND: RunnerResult(ok=True, results=[_result("b1")])})
    invalid = await _flat_delegate().execute(queries=[], regions=["US"])
    assert calls == [] and invalid["success"] is False and invalid["error"].startswith("Invalid request: queries")
    selected = await _flat_delegate().execute(provider=SECOND, **FLAT_INPUT)
    assert [c["provider"] for c in calls] == [SECOND] and selected["providers"] == [SECOND]
    both = await _flat_delegate().execute(**FLAT_INPUT)
    assert both["warnings"] == [f"{FIRST_NAME} did not respond in time."] and both["partial"] is True
    assert both["error"] is None and "internal" not in json.dumps(both)


# contract-test: direct surface=rest_api assertions=instance-app-packages.instance-availability,instance-app-packages.no-installed-provider-charges
def test_flat_base_app_dispatch_is_never_charged(monkeypatch, flat_providers):
    calls = _fake_runner(monkeypatch, {FIRST: RunnerResult(ok=True, results=[_result("a")]),
                                       SECOND: RunnerResult(ok=True, results=[])})
    app = BaseApp(app_dir=str(FLAT_APP_DIR), register_http_routes=False,
                  preloaded_config_dict=overlay.apply_app_package_overlay(FLAT_APP, _raw_flat_app()))
    assert app.skill_classes[FLAT_SKILL] is InstalledProviderFlatSkill
    import asyncio
    response = asyncio.run(app.dispatch_skill(FLAT_SKILL, dict(FLAT_INPUT)))
    assert response["matches"][0]["provider_id"] == FIRST and calls[0]["input"]["queries"] == ["Example name"]
    assert apps_api.chargeable_skill_units(FLAT_APP, FLAT_SKILL, dict(FLAT_INPUT), response) == 0
    assert billing.even_request_charge_items(FLAT_APP, FLAT_SKILL, dict(FLAT_INPUT), response, 10) == []


# --------------------------------------------------------------------------- optional secrets

# contract-test: direct surface=rest_api assertions=instance-app-packages.operator-secrets
@pytest.mark.anyio
@pytest.mark.parametrize("proxy", [None, "http://proxy.example.org:3128"])
async def test_optional_secret_is_passed_only_when_set(monkeypatch, tmp_path, proxy):
    _install(tmp_path, [_entry(optional_secrets=["proxy_url"])])
    enable(monkeypatch, tmp_path)
    if proxy:
        monkeypatch.setenv("SECRET__MY_PROVIDER__PROXY_URL", proxy)
    calls = _fake_runner(monkeypatch, {FIRST: RunnerResult(ok=True, results=[_result("a")])})
    response = await _delegate().execute([VALID_ITEM])
    assert response["results"][0]["results"]
    assert calls[0]["secrets"] == ({"proxy_url": proxy} if proxy else {})
    from backend.shared.app_packages.secrets import installed_provider_ready
    assert await installed_provider_ready(APP, SKILL, FIRST, None) is True


# --------------------------------------------------------------------------- generic validator

# contract-test: direct surface=rest_api assertions=instance-app-packages.provider-contract
def test_generic_validator_bounds_and_drops():
    deep: Dict[str, Any] = {"v": 1}
    for _ in range(10):
        deep = {"n": deep}
    raw = {
        "title": "x" * 30000, "url": "javascript:alert(1)", "image_url": "https://example.org/i.png",
        "count": 2 ** 60, "score": float("nan"), "ok": True, "_internal": 1, "bad-key": 1,
        "nested": {"link_url": "ftp://example.org", "name": "n"}, "deep": deep,
        "list": list(range(500)), "embed_id": "e", "provider": "spoofed",
    }
    result = validate_generic_result(raw)
    assert len(result["title"]) == 20000 and "url" not in result and result["image_url"].startswith("https://")
    assert "count" not in result and "score" not in result and result["ok"] is True
    assert not {"_internal", "bad-key", "embed_id", "provider"} & set(result)
    assert result["nested"] == {"name": "n"} and len(result["list"]) == 100
    def depth(value: Any) -> int:
        return 1 + max((depth(v) for v in value.values()), default=0) if isinstance(value, dict) else 0
    assert depth(result) == 6  # the result object is depth 1; deeper values are dropped
    assert validate_generic_result(["not", "object"]) is None and validate_generic_result({"_x": 1}) is None


# contract-test: direct surface=rest_api assertions=instance-app-packages.provider-contract
def test_generic_results_are_count_and_size_bounded():
    many = [{"title": str(i)} for i in range(80)]
    stamped = contracts.validate_contract_results(SKILL_REQUESTS_V1, many, provider_id=FIRST, provider_name=FIRST_NAME)
    assert len(stamped) == contracts.MAX_RESULTS_PER_CALL
    big = [{"text": "x" * 19000, "more": "y" * 19000, "extra": "z" * 19000, "last": "w" * 19000}]
    assert contracts.validate_contract_results(SKILL_REQUESTS_V1, big, provider_id=FIRST, provider_name=FIRST_NAME) == []


# --------------------------------------------------------------------------- billing

# contract-test: direct surface=rest_api assertions=instance-app-packages.no-installed-provider-charges
def test_delegate_groups_are_never_charged(two_providers):
    two = {"requests": [{"id": 1}, {"id": 2}]}
    served = {"id": 1, "results": [{"provider_id": FIRST}], "providers": [FIRST]}
    failed = {"id": 2, "results": [], "providers": [], "error": "Example provider failed."}
    result = {"results": [served, failed]}
    assert billing.served_only_by_installed_providers(APP, SKILL) is True
    assert billing.is_installed_only_group(APP, SKILL, failed) is True
    assert apps_api.chargeable_skill_units(APP, SKILL, two, result) == 0
    assert billing.even_request_charge_items(APP, SKILL, two, result, 40) == []
    assert billing.all_groups_installed_only(APP, SKILL, 2, result) is True
    # Group-count mismatch still charges nothing: the skill has no built-in provider.
    assert billing.chargeable_request_indices(APP, SKILL, 3, result) == []
    # Other skills keep the built-in rule.
    assert billing.chargeable_request_indices("events", "search", 2, result) == [0, 1]


# contract-test: direct surface=rest_api assertions=instance-app-packages.no-installed-provider-charges
def test_flag_off_paused_skill_billing_unchanged(monkeypatch, tmp_path):
    _install(tmp_path, [_entry()])
    monkeypatch.delenv(loader.ENABLED_ENV, raising=False)
    two = {"requests": [{"id": 1}, {"id": 2}]}
    result = {"results": [{"id": 1, "results": [{"provider_id": FIRST}], "providers": [FIRST]}, {"id": 2}]}
    assert apps_api.chargeable_skill_units(APP, SKILL, two, result) == 2
    assert os.getenv(loader.ENABLED_ENV) is None
