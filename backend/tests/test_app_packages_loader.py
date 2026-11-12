"""Instance app packages: registry loader, metadata overlay, secrets, contract and billing rule.

Architecture: docs/architecture/apps/instance-app-packages.md
"""
from __future__ import annotations

import json
import logging

import httpx
import pytest
import yaml

from backend.shared.app_packages import billing, contracts, loader, overlay, runner_client, secrets
from backend.tests.app_packages_test_support import (
    PACKAGE_ID, PROVIDER_ID, PROVIDER_NAME, VERSION, FakeSecretsManager, configured_secrets, enable,
    install_example, manifest, provider_entry, write_package, write_registry,
)

EVENTS_APP_YML = loader.BUILTIN_APPS_DIR / "events" / "app.yml"


@pytest.fixture(autouse=True)
def _reset_loader_cache():
    loader.reset_installed_packages_cache()
    yield
    loader.reset_installed_packages_cache()


def _events_raw():
    return yaml.safe_load(EVENTS_APP_YML.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- loader

# contract-test: direct surface=rest_api assertions=instance-app-packages.instance-availability
def test_flag_off_reads_nothing(monkeypatch, tmp_path):
    install_example(tmp_path)
    monkeypatch.delenv(loader.ENABLED_ENV, raising=False)
    monkeypatch.setenv(loader.MOUNT_ENV, str(tmp_path))
    assert loader.get_installed_packages().providers == ()
    assert loader.is_installed_provider("events", "search", PROVIDER_ID) is False


# contract-test: direct surface=rest_api assertions=instance-app-packages.instance-availability
@pytest.mark.parametrize("registry", [None, "not json", json.dumps({"format": 2, "active": {}})])
def test_missing_or_invalid_registry_loads_nothing_with_error(tmp_path, caplog, registry):
    if registry is not None:
        (tmp_path / "registry.json").write_text(registry, encoding="utf-8")
    with caplog.at_level(logging.ERROR):
        assert loader.load_installed_packages(tmp_path).providers == ()
    assert any(record.levelno == logging.ERROR for record in caplog.records)


# contract-test: direct surface=rest_api assertions=instance-app-packages.instance-availability
def test_valid_package_loads_with_registry_identity(tmp_path):
    install_example(tmp_path)
    packages = loader.load_installed_packages(tmp_path)
    (provider,) = packages.for_skill("events", "search")
    assert (provider.package_id, provider.package_version, provider.provider_id) == (PACKAGE_ID, VERSION, PROVIDER_ID)
    assert provider.name == PROVIDER_NAME and provider.secrets == ("api_key",)
    assert provider.contract == contracts.EVENTS_SEARCH_V1


# contract-test: direct surface=rest_api assertions=instance-app-packages.instance-availability
def test_one_provider_id_may_serve_several_skills_of_a_package(tmp_path):
    jobs = provider_entry(app="jobs", contract=contracts.JOBS_SEARCH_V1, name="Example site jobs")
    install_example(tmp_path, manifest(providers=[provider_entry(), jobs]))
    packages = loader.load_installed_packages(tmp_path)
    (events_provider,) = packages.for_skill("events", "search")
    (jobs_provider,) = packages.for_skill("jobs", "search")
    assert events_provider.provider_id == jobs_provider.provider_id == PROVIDER_ID
    assert events_provider.secrets == jobs_provider.secrets == ("api_key",)


def _builtin_provider_id() -> str:
    skill = next(s for s in _events_raw()["skills"] if s["id"] == "search")
    first = skill["providers"][0]
    return str(first["name"] if isinstance(first, dict) else first).lower()


@pytest.mark.parametrize("bad_manifest", [
    lambda: manifest(providers=[provider_entry(contract="events.search@2")]),
    lambda: manifest(providers=[provider_entry(skill="does_not_exist")]),
    lambda: manifest(providers=[provider_entry(id=_builtin_provider_id())]),
    lambda: manifest(contributes={"providers": [provider_entry()], "skills": [{"id": "x"}]}),
    lambda: manifest(format_version=2),
    lambda: manifest(providers=[provider_entry(entrypoint="../escape")]),
    lambda: manifest(providers=[provider_entry(runtime="docker")]),
    lambda: manifest(providers=[provider_entry(secrets=["API KEY"])]),
    lambda: manifest(version="9.9.9"),
])
# contract-test: direct surface=rest_api assertions=instance-app-packages.instance-availability
def test_invalid_package_is_rejected_whole(tmp_path, caplog, bad_manifest):
    install_example(tmp_path, bad_manifest())
    with caplog.at_level(logging.ERROR):
        assert loader.load_installed_packages(tmp_path).providers == ()
    assert any("Rejected package" in record.getMessage() for record in caplog.records)


# contract-test: direct surface=rest_api assertions=instance-app-packages.instance-availability
def test_install_record_must_match_active_version(tmp_path):
    write_package(tmp_path, manifest())
    write_registry(tmp_path, {PACKAGE_ID: {"version": VERSION, "sha256": "0" * 64}})
    assert loader.load_installed_packages(tmp_path).providers == ()


# contract-test: direct surface=rest_api assertions=instance-app-packages.instance-availability
def test_duplicate_provider_id_across_packages_keeps_first_only(tmp_path):
    # Packages load in package-id order; a later package reusing a provider id is rejected.
    other_id = "org.example.zz-second-site"
    sha_a = write_package(tmp_path, manifest())
    sha_b = write_package(tmp_path, manifest(package_id=other_id), package_id=other_id)
    write_registry(tmp_path, {PACKAGE_ID: {"version": VERSION, "sha256": sha_a},
                              other_id: {"version": VERSION, "sha256": sha_b}})
    providers = loader.load_installed_packages(tmp_path).providers
    assert [p.package_id for p in providers] == [PACKAGE_ID]


def _flat_paused_apps(tmp_path):
    # A paused, provider-less skill with a flat tool schema (no top-level requests array).
    skill = {"id": "lookup", "name_translation_key": "x", "description_translation_key": "x",
             "class_path": "my.skills.LookupSkill", "provider_required": True, "providers": [],
             "tool_schema": {"type": "object", "properties": {"queries": {"type": "array"}}}}
    apps_dir = tmp_path / "apps"
    (apps_dir / "myapp").mkdir(parents=True)
    (apps_dir / "myapp" / "app.yml").write_text(yaml.safe_dump({"id": "myapp", "skills": [skill]}), encoding="utf-8")
    return apps_dir


# contract-test: direct surface=rest_api assertions=instance-app-packages.manifest-validation
@pytest.mark.parametrize("contract, accepted", [("skill.requests@1", True), ("myapp.lookup@1", False)])
def test_flat_paused_skill_accepts_only_the_generic_contract(tmp_path, contract, accepted):
    apps_dir = _flat_paused_apps(tmp_path)
    root = tmp_path / "root"
    entry = provider_entry(app="myapp", skill="lookup", contract=contract, id="my_provider", name="My provider",
                           secrets=[], skill_hint="Use for lookups on example.org.")
    install_example(root, manifest(providers=[entry]))
    providers = loader.load_installed_packages(root, apps_dir=apps_dir).for_skill("myapp", "lookup")
    assert [p.provider_id for p in providers] == (["my_provider"] if accepted else [])
    if accepted:
        assert providers[0].skill_hint == "Use for lookups on example.org."


# Built-in ids from other apps, provider configs, Vault paths and selector values.
COLLIDING_PROVIDER_IDS = ["openai", "brave", "google_maps", "stripe", "pretalx", "auto", "none", "39c3", "gpn24"]


# contract-test: direct surface=rest_api assertions=instance-app-packages.operator-secrets
def test_builtin_provider_namespace_is_derived_from_source():
    namespace = loader._BuiltinTargets(loader.BUILTIN_APPS_DIR).global_provider_ids()
    # app.yml providers of other apps, provider configs and Vault provider paths.
    assert {"openai", "brave", "google_maps", "stripe", "anthropic", "pretalx"} <= namespace
    assert PROVIDER_ID not in namespace
    reserved = contracts.reserved_provider_ids(contracts.EVENTS_SEARCH_V1)
    assert {"auto", "none", "pretalx", "39c3"} <= reserved and PROVIDER_ID not in reserved


# contract-test: direct surface=rest_api assertions=instance-app-packages.operator-secrets
@pytest.mark.anyio
@pytest.mark.parametrize("colliding_id", COLLIDING_PROVIDER_IDS)
async def test_colliding_provider_id_is_rejected_and_secrets_never_resolve(monkeypatch, tmp_path, colliding_id):
    install_example(tmp_path, manifest(providers=[provider_entry(id=colliding_id)]))
    enable(monkeypatch, tmp_path)
    assert loader.get_installed_packages().providers == ()
    assert loader.is_installed_provider("events", "search", colliding_id) is False
    sm = FakeSecretsManager({(f"kv/data/providers/{colliding_id}", "api_key"): "placeholder-value"})
    assert await secrets.installed_provider_ready("events", "search", colliding_id, sm) is False
    assert await secrets.ready_installed_provider_ids(sm) == set()
    assert sm.calls == []


# contract-test: direct surface=rest_api assertions=instance-app-packages.server-install
def test_manifest_is_read_from_digest_covered_files(tmp_path):
    install_example(tmp_path)
    version_dir = tmp_path / "packages" / PACKAGE_ID / VERSION
    # The uncovered copy at the version root is ignored.
    (version_dir / "manifest.yml").write_text(
        yaml.safe_dump(manifest(name="Not what runs")), encoding="utf-8")
    (provider,) = loader.load_installed_packages(tmp_path).providers
    assert provider.provider_id == PROVIDER_ID


# contract-test: direct surface=rest_api assertions=instance-app-packages.server-install
def test_manifest_digest_mismatch_rejects_package(tmp_path, caplog):
    install_example(tmp_path)
    tampered = manifest(providers=[provider_entry(id="example_other_site", secrets=["api_key", "token"])])
    (tmp_path / "packages" / PACKAGE_ID / VERSION / "files" / "manifest.yml").write_text(
        yaml.safe_dump(tampered), encoding="utf-8")
    with caplog.at_level(logging.ERROR):
        assert loader.load_installed_packages(tmp_path).providers == ()
    assert any("digest" in record.getMessage() for record in caplog.records)


# --------------------------------------------------------------------------- overlay

# contract-test: direct surface=rest_api assertions=instance-app-packages.instance-availability
def test_overlay_appends_provider_and_lifts_default_enabled(monkeypatch, tmp_path):
    install_example(tmp_path)
    enable(monkeypatch, tmp_path)
    raw = _events_raw()
    raw["default_enabled"] = False
    next(s for s in raw["skills"] if s["id"] == "search")["default_enabled"] = False
    result = overlay.apply_app_package_overlay("events", raw)
    assert result is not raw and raw["default_enabled"] is False  # input never mutated
    skill = next(s for s in result["skills"] if s["id"] == "search")
    assert "default_enabled" not in result and "default_enabled" not in skill
    entry = skill["providers"][-1]
    assert entry == {"name": PROVIDER_ID, "id": PROVIDER_ID, "display_name": PROVIDER_NAME,
                     "no_api_key": False, "installed": True}
    # The provider's own hint comes first; the event search also names its public web source.
    assert skill["preprocessor_hint"] == f'{provider_entry()["skill_hint"]} {overlay.WEB_SOURCE_HINTS[("events", "search")]}'


# contract-test: direct surface=rest_api assertions=instance-app-packages.instance-availability
def test_overlay_extends_provider_enums(monkeypatch, tmp_path):
    install_example(tmp_path)
    enable(monkeypatch, tmp_path)
    schema = {"type": "object", "properties": {
        "provider": {"type": "string", "enum": ["auto"]},
        "requests": {"type": "array", "items": {"type": "object", "properties": {
            "providers": {"type": "array", "items": {"type": "string", "enum": ["auto"]}}}}}}}
    overlay.extend_provider_enums(schema, [PROVIDER_ID])
    assert schema["properties"]["provider"]["enum"] == ["auto", PROVIDER_ID]
    nested = schema["properties"]["requests"]["items"]["properties"]["providers"]["items"]["enum"]
    assert nested == ["auto", PROVIDER_ID]


# contract-test: direct surface=rest_api assertions=instance-app-packages.instance-availability
def test_overlay_is_noop_when_disabled_or_app_untargeted(monkeypatch, tmp_path):
    install_example(tmp_path)
    raw = _events_raw()
    monkeypatch.delenv(loader.ENABLED_ENV, raising=False)
    assert overlay.apply_app_package_overlay("events", raw) is raw
    enable(monkeypatch, tmp_path)
    other = {"id": "web", "skills": [{"id": "search", "providers": []}]}
    assert overlay.apply_app_package_overlay("web", other) is other


# contract-test: direct surface=rest_api assertions=instance-app-packages.instance-availability
def test_events_search_declares_provider_contract():
    skill = next(s for s in _events_raw()["skills"] if s["id"] == "search")
    assert skill["provider_contract"] == contracts.EVENTS_SEARCH_V1


# --------------------------------------------------------------------------- secrets

# contract-test: direct surface=rest_api assertions=instance-app-packages.operator-secrets
@pytest.mark.anyio
async def test_declared_secret_resolution(monkeypatch, tmp_path):
    install_example(tmp_path)
    enable(monkeypatch, tmp_path)
    monkeypatch.delenv(secrets.provider_secret_env_var(PROVIDER_ID, "api_key"), raising=False)
    assert await secrets.installed_provider_ready("events", "search", PROVIDER_ID, FakeSecretsManager()) is False
    sm = configured_secrets()
    assert await secrets.installed_provider_ready("events", "search", PROVIDER_ID, sm) is True
    assert sm.calls == [(f"kv/data/providers/{PROVIDER_ID}", "api_key")]
    assert await secrets.ready_installed_provider_ids(sm) == {PROVIDER_ID}


# contract-test: direct surface=rest_api assertions=instance-app-packages.provider-contract
@pytest.mark.anyio
async def test_env_fallback_ignores_vault_import_placeholder(monkeypatch, tmp_path):
    install_example(tmp_path)
    enable(monkeypatch, tmp_path)
    env = secrets.provider_secret_env_var(PROVIDER_ID, "api_key")
    assert env == "SECRET__EXAMPLE_SITE_EVENTS__API_KEY"
    monkeypatch.setenv(env, "IMPORTED_TO_VAULT")
    assert await secrets.installed_provider_ready("events", "search", PROVIDER_ID, None) is False
    monkeypatch.setenv(env, "placeholder-value")
    assert await secrets.installed_provider_ready("events", "search", PROVIDER_ID, None) is True


# --------------------------------------------------------------------------- contract

# contract-test: direct surface=rest_api assertions=instance-app-packages.provider-contract
def test_contract_validation_drops_invalid_and_stamps_attribution():
    raw = [
        {"title": "Open day", "url": "https://events.example.org/open-day", "date_start": "2030-05-01T10:00:00Z",
         "venue": {"name": "Hall", "lat": 52.5, "lon": "x"}, "organizer": {"name": "Example org"},
         "provider": "spoofed", "provider_id": "spoofed", "free": True, "unknown": "dropped"},
        {"title": "No url", "date_start": "2030-05-01"},
        {"title": "Bad scheme", "url": "javascript:alert(1)", "date_start": "2030-05-01"},
        {"title": "Bad date", "url": "https://events.example.org/x", "date_start": "soon"},
        "not a dict",
    ]
    accepted = contracts.validate_contract_results(contracts.EVENTS_SEARCH_V1, raw,
                                                   provider_id=PROVIDER_ID, provider_name=PROVIDER_NAME)
    assert len(accepted) == 1
    event = accepted[0]
    assert event["provider_id"] == PROVIDER_ID and event["provider"] == PROVIDER_NAME
    assert event["venue"] == {"name": "Hall", "lat": 52.5}
    assert event["organizer"] == "Example org"
    assert "free" not in event and "unknown" not in event
    assert contracts.validate_contract_results("unknown.contract@1", raw, provider_id="a", provider_name="A") == []


# contract-test: direct surface=rest_api assertions=instance-app-packages.provider-contract
def test_contract_input_projection():
    projected = contracts.events_search_input({"id": 1, "query": "open day", "count": 5, "provider": "auto",
                                               "lat": None, "relevance_criteria": "x"})
    assert projected == {"query": "open day", "count": 5}


# --------------------------------------------------------------------------- runner client

def _provider(tmp_path, monkeypatch):
    install_example(tmp_path)
    enable(monkeypatch, tmp_path)
    return loader.get_installed_provider("events", "search", PROVIDER_ID)


# contract-test: direct surface=rest_api assertions=instance-app-packages.instance-availability
@pytest.mark.anyio
async def test_runner_client_sends_registry_identity_and_maps_errors(monkeypatch, tmp_path):
    provider = _provider(tmp_path, monkeypatch)
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"ok": False, "error": "TIMEOUT", "message": "x" * 500})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await runner_client.run_provider(provider, {"query": "q"}, {"api_key": "placeholder-value"},
                                                  client=client)
    assert seen["package_id"] == PACKAGE_ID and seen["version"] == VERSION
    assert seen["provider_id"] == PROVIDER_ID and seen["contract"] == contracts.EVENTS_SEARCH_V1
    assert (seen["app_id"], seen["skill_id"]) == ("events", "search")
    assert result.ok is False and result.error_code == "TIMEOUT" and len(result.message) == 300

    async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"ok": False, "error": "WHATEVER"}))) as client:
        unknown = await runner_client.run_provider(provider, {}, {}, client=client)
    assert unknown.error_code == runner_client.RUNNER_UNAVAILABLE

    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(broken)) as client:
        down = await runner_client.run_provider(provider, {}, {}, client=client)
    assert down.ok is False and down.error_code == runner_client.RUNNER_UNAVAILABLE


# --------------------------------------------------------------------------- billing rule

def _event(provider_id):
    return {"title": "t", "url": "https://events.example.org/t", "provider_id": provider_id}


@pytest.fixture
def installed(monkeypatch, tmp_path):
    install_example(tmp_path)
    enable(monkeypatch, tmp_path)


# contract-test: direct surface=rest_api assertions=instance-app-packages.no-installed-provider-charges
def test_installed_only_group_is_free(installed):
    group = {"id": 1, "results": [_event(PROVIDER_ID)], "providers": [PROVIDER_ID]}
    assert billing.is_installed_only_group("events", "search", group) is True
    assert billing.chargeable_request_units("events", "search", 1, {"results": [group]}) == 0


# contract-test: direct surface=rest_api assertions=instance-app-packages.no-installed-provider-charges
def test_mixed_group_is_charged(installed):
    builtin = _builtin_provider_id()
    group = {"id": 1, "results": [_event(PROVIDER_ID), _event(builtin)], "providers": [PROVIDER_ID, builtin]}
    assert billing.is_installed_only_group("events", "search", group) is False
    two = {"results": [group, {"id": 2, "results": [_event(PROVIDER_ID)], "providers": [PROVIDER_ID]}]}
    assert billing.chargeable_request_units("events", "search", 2, two) == 1


# contract-test: direct surface=rest_api assertions=instance-app-packages.provider-contract
def test_builtin_only_and_empty_groups_unchanged(installed):
    builtin = _builtin_provider_id()
    groups = {"data": {"results": [
        {"id": 1, "results": [_event(builtin)], "providers": [builtin]},
        {"id": 2, "results": [], "providers": [PROVIDER_ID]},
    ]}}
    assert billing.chargeable_request_units("events", "search", 2, groups) == 2


@pytest.mark.parametrize("group", [
    # Output flags never exempt a group.
    {"results": [{**_event("anything"), "free": True, "installed": True}], "providers": ["anything"], "free": True},
    # An id that the registry does not list for this skill.
    {"results": [_event("not_installed")], "providers": ["not_installed"]},
    # Results missing or contradicting the group's provider list.
    {"results": [{"title": "t"}], "providers": [PROVIDER_ID]},
    {"results": [_event(PROVIDER_ID)], "providers": []},
])
# contract-test: direct surface=rest_api assertions=instance-app-packages.no-installed-provider-charges
def test_spoofed_exemption_signals_are_ignored(installed, group):
    assert billing.is_installed_only_group("events", "search", group) is False
    assert billing.is_installed_only_group("web", "search", {"results": [_event(PROVIDER_ID)],
                                                             "providers": [PROVIDER_ID]}) is False


# contract-test: direct surface=rest_api assertions=instance-app-packages.no-installed-provider-charges
def test_flag_off_charges_everything(monkeypatch, tmp_path):
    install_example(tmp_path)
    monkeypatch.delenv(loader.ENABLED_ENV, raising=False)
    group = {"results": [_event(PROVIDER_ID)], "providers": [PROVIDER_ID]}
    assert billing.chargeable_request_units("events", "search", 1, {"results": [group]}) == 1



HOSTED_FLAG_CASES = [
    ("", "production", True),
    ("self_host", "production", True),
    ("official_cloud", "development", True),
    ("official_cloud", "production", False),
    ("official_cloud", "", False),
]


# contract-test: direct surface=rest_api assertions=instance-app-packages.instance-availability
@pytest.mark.parametrize(("mode", "environment", "expected"), HOSTED_FLAG_CASES)
def test_flag_is_ignored_on_a_hosted_production_server(monkeypatch, mode, environment, expected):
    monkeypatch.setenv(loader.ENABLED_ENV, "true")
    monkeypatch.setenv("OPENMATES_DEPLOYMENT_MODE", mode)
    monkeypatch.setenv("SERVER_ENVIRONMENT", environment)
    assert loader.app_packages_enabled() is expected
