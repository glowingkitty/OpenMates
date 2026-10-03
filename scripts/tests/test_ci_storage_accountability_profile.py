# contract-test-file: infrastructure
"""The selected Directus audit probe stays source-bound and provider-free."""

import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
SOURCE = "a" * 40


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _environment():
    return _load(SCRIPTS / "ci_environment.py", "_accountability_environment")


def _runner(monkeypatch):
    environment = _environment()
    monkeypatch.setitem(sys.modules, "ci_environment", environment)
    repository = next(parent for parent in SCRIPTS.parents
                      if (parent / "scripts/ci_pytest_targets.py").is_file())
    monkeypatch.syspath_prepend(str(repository))
    return _load(SCRIPTS / "ci_run_tests.py", "_accountability_runner")


def test_accountability_profile_is_api_only_internal_with_exact_database_guard():
    profile = _environment().compose_profile(SOURCE, storage_accountability=True)
    services = profile["services"]
    api = services["api"]
    assert profile["networks"]["default"]["internal"] is True
    assert not {"ai-worker", "object-storage", "uploads"}.intersection(services)
    assert "S3_ENDPOINT_URL" not in api["environment"]
    assert "HTTPS_PROXY" not in api["environment"]
    assert api["environment"]["OPENMATES_CI_ISOLATED"] == "1"
    assert api["environment"]["OPENMATES_CI_STORAGE_ACCOUNTABILITY"] == "1"
    assert api["environment"]["BUILD_COMMIT_SHA"] == SOURCE
    assert tuple(api["environment"][key] for key in ("DB_HOST", "DB_DATABASE", "DB_USER")) == (
        "cms-database", "openmates", "openmates",
    )
    assert api["environment"]["DATABASE_ADMIN_EMAIL"] == "runtime@example.com"
    assert any(str(mount).endswith("/app/ci-accountability") for mount in api["volumes"])
    assert all("OPENMATES_CI_STORAGE_ACCOUNTABILITY" not in service.get("environment", {})
               for name, service in services.items() if name != "api")


@pytest.mark.parametrize("conflict", ["ai_fixtures", "object_storage", "public_provider", "workflows"])
def test_accountability_profile_rejects_other_actors(conflict):
    with pytest.raises(ValueError, match="standalone zero-provider"):
        _environment().compose_profile(SOURCE, storage_accountability=True, **{conflict: True})


def test_accountability_selector_is_private_source_bound_and_fails_closed(tmp_path, monkeypatch):
    runner = _runner(monkeypatch)
    profile = _environment().compose_profile(SOURCE, storage_accountability=True)
    private = tmp_path / "accountability"
    private.mkdir(mode=0o700)
    compose_path = tmp_path / "compose.json"
    compose_path.write_text(json.dumps(profile))
    monkeypatch.setattr(runner, "COMPOSE_PATH", compose_path)
    monkeypatch.setattr(runner, "require_runner", lambda: None)
    env = runner.prepare_storage_accountability_selector()
    selector = json.loads((private / "selector.json").read_text())
    assert selector["schema"] == "storage-accountability-selector-v1"
    assert selector["source_commit"] == SOURCE
    assert re.fullmatch(r"ci-accountability/[0-9a-f-]{36}", selector["fixture_prefix"])
    assert (private / "selector.json").stat().st_mode & 0o777 == 0o600
    assert private.stat().st_mode & 0o777 == 0o700
    assert env["E2E_STORAGE_ACCOUNTABILITY"] == "1"
    assert env["E2E_STORAGE_ACCOUNTABILITY_SOURCE_COMMIT"] == SOURCE
    assert env["E2E_STORAGE_ACCOUNTABILITY_SELECTOR_FILE"] == "/app/ci-accountability/selector.json"
    with pytest.raises(FileExistsError):
        runner.prepare_storage_accountability_selector()
    (private / "selector.json").unlink()
    profile["services"]["api"]["environment"]["DB_HOST"] = "other-database"
    compose_path.write_text(json.dumps(profile))
    with pytest.raises(RuntimeError, match="exact isolated zero-provider profile"):
        runner.prepare_storage_accountability_selector()
    assert not (private / "selector.json").exists()


def test_accountability_cleanup_uses_exact_command_and_private_failure(tmp_path, monkeypatch):
    runner = _runner(monkeypatch)
    private = tmp_path / "accountability"
    private.mkdir(mode=0o700)
    (private / "selector.json").write_text("{}")
    monkeypatch.setattr(runner, "COMPOSE_PATH", tmp_path / "compose.json")
    calls = []
    monkeypatch.setattr(runner, "compose", lambda *args, **kwargs: (
        calls.append(args) or SimpleNamespace(stdout='{"cleaned":true}')
    ))
    runner.cleanup_storage_accountability_selector()
    assert calls == [("exec", "-T", "api", "python",
                      "/app/backend/scripts/storage_accountability_integration.py", "cleanup",
                      "--selector-file", "/app/ci-accountability/selector.json")]

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args, stderr="private-account-token")

    monkeypatch.setattr(runner, "compose", fail)
    with pytest.raises(RuntimeError, match="private diagnostics retained") as error:
        runner.cleanup_storage_accountability_selector()
    assert "private-account-token" not in str(error.value)
    log = private / "cleanup.stderr.log"
    assert log.read_text() == "private-account-token"
    assert log.stat().st_mode & 0o777 == 0o600


def test_accountability_selector_skips_browser_install_and_web_build():
    workflow = (SCRIPTS.parent / ".github/workflows/isolated-tests.yml").read_text()
    assert "inputs.mode == 'e2e' && !contains(inputs.specs_json, 'storage-accountability-integration.spec.ts')" in workflow
    manifest = json.loads((SCRIPTS / "ci_coverage_manifest.json").read_text())
    assert manifest["groups"]["storage_accountability_integration"]["specs"] == [
        "storage-accountability-integration.spec.ts",
    ]


def test_accountability_runner_executes_node_spec_without_browser_or_accounts(tmp_path, monkeypatch):
    runner = _runner(monkeypatch)
    web = tmp_path / "web"
    (web / "tests").mkdir(parents=True)
    (web / "tests" / runner.ACCOUNTABILITY_SPEC).write_text("test('probe', () => {})")
    results = tmp_path / "results"
    results.mkdir()
    profile = _environment().compose_profile(SOURCE, storage_accountability=True)
    compose_path = tmp_path / "compose.json"
    compose_path.write_text(json.dumps(profile))
    monkeypatch.setattr(runner, "WEB", web)
    monkeypatch.setattr(runner, "RESULTS", results)
    monkeypatch.setattr(runner, "COMPOSE_PATH", compose_path)
    calls = []
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("browser started"))
    monkeypatch.setattr(runner, "provision_account", lambda *args, **kwargs: pytest.fail("account created"))
    monkeypatch.setattr(runner, "prepare_storage_accountability_selector", lambda: {"E2E_STORAGE_ACCOUNTABILITY": "1"})
    monkeypatch.setattr(runner, "cleanup_storage_accountability_selector", lambda: calls.append("cleanup"))

    def run(command, **kwargs):
        calls.append("spec")
        assert command[0:4] == ["pnpm", "exec", "playwright", "test"]
        assert kwargs["env"]["E2E_STORAGE_ACCOUNTABILITY"] == "1"
        (results / "ci-spec-0.json").write_text(json.dumps({"stats": {"expected": 1, "unexpected": 0,
                                                               "flaky": 0, "skipped": 0}}))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner.subprocess, "run", run)
    outcome = runner.run_e2e([runner.ACCOUNTABILITY_SPEC])
    assert calls == ["spec", "cleanup"]
    assert outcome[0]["exit_code"] == 0
    assert outcome[0]["accounts"]["provisioning"] == "none"


def test_accountability_runner_keeps_spec_and_cleanup_failures_separate(tmp_path, monkeypatch):
    runner = _runner(monkeypatch)
    web = tmp_path / "web"
    (web / "tests").mkdir(parents=True)
    (web / "tests" / runner.ACCOUNTABILITY_SPEC).write_text("test('probe', () => {})")
    results = tmp_path / "results"
    results.mkdir()
    profile = _environment().compose_profile(SOURCE, storage_accountability=True)
    compose_path = tmp_path / "compose.json"
    compose_path.write_text(json.dumps(profile))
    monkeypatch.setattr(runner, "WEB", web)
    monkeypatch.setattr(runner, "RESULTS", results)
    monkeypatch.setattr(runner, "COMPOSE_PATH", compose_path)
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("browser started"))
    monkeypatch.setattr(runner, "prepare_storage_accountability_selector", lambda: {"E2E_STORAGE_ACCOUNTABILITY": "1"})
    monkeypatch.setattr(runner, "cleanup_storage_accountability_selector", lambda: (_ for _ in ()).throw(RuntimeError("private-token")))

    def run(command, **kwargs):
        (results / "ci-spec-0.json").write_text(json.dumps({"stats": {"expected": 1, "unexpected": 0,
                                                               "flaky": 0, "skipped": 0}}))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner.subprocess, "run", run)
    outcome = runner.run_e2e([runner.ACCOUNTABILITY_SPEC])
    assert outcome[0]["spec"] == runner.ACCOUNTABILITY_SPEC
    assert outcome[0]["exit_code"] == 0
    assert outcome[1]["suite"] == "storage-accountability-cleanup"
    assert outcome[1]["exit_code"] == 1
    assert "private-token" not in json.dumps(outcome)
