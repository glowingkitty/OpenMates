"""Tests for Playwright backend live-mock preflight.

Purpose: default mocked Playwright dispatches must fail closed when the local
dev backend would ignore live-mock markers and spend real provider quota.
Run: python3 -m pytest scripts/tests/test_run_tests_backend_mock_preflight.py.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
RUN_TESTS_PATH = ROOT / "scripts/run_tests.py"


def load_run_tests_module():
    spec = importlib.util.spec_from_file_location("run_tests", RUN_TESTS_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_backend_live_mock_preflight_passes_when_all_containers_are_mocked(monkeypatch) -> None:
    run_tests = load_run_tests_module()

    def fake_env(_container: str, key: str):
        return ({"SERVER_ENVIRONMENT": "development", "MOCK_EXTERNAL_APIS": "true"}[key], None)

    monkeypatch.setattr(run_tests, "_docker_container_env", fake_env)

    assert run_tests._development_backend_live_mock_preflight_error() is None


def test_backend_live_mock_preflight_fails_when_container_would_ignore_markers(monkeypatch) -> None:
    run_tests = load_run_tests_module()

    def fake_env(container: str, key: str):
        if container == "task-worker" and key == "MOCK_EXTERNAL_APIS":
            return ("", "MOCK_EXTERNAL_APIS is unset")
        return ({"SERVER_ENVIRONMENT": "development", "MOCK_EXTERNAL_APIS": "true"}[key], None)

    monkeypatch.setattr(run_tests, "_docker_container_env", fake_env)

    error = run_tests._development_backend_live_mock_preflight_error()

    assert error is not None
    assert "task-worker" in error
    assert "MOCK_EXTERNAL_APIS" in error


def test_only_failed_synthetic_backend_preflight_records_pass_when_env_fixed(
    tmp_path,
    monkeypatch,
) -> None:
    run_tests = load_run_tests_module()
    monkeypatch.setattr(run_tests, "RESULTS_DIR", tmp_path)
    monkeypatch.setenv(
        "OPENMATES_ONLY_FAILED_FILES_JSON",
        json.dumps([run_tests.BACKEND_LIVE_MOCK_PREFLIGHT_FILE]),
    )
    monkeypatch.setattr(
        run_tests,
        "_development_backend_live_mock_preflight_error",
        lambda: None,
    )

    orchestrator = run_tests.TestOrchestrator(
        SimpleNamespace(
            suite="playwright",
            spec=None,
            only_failed=True,
            daily=False,
            force=False,
            environment="development",
            max_concurrent=1,
            account=None,
            create_account_slot=None,
            no_fail_fast=False,
            no_mocks=False,
            record_live_fixtures=False,
            dry_run=False,
        )
    )

    result = orchestrator._run_playwright()

    assert result.status == "passed"
    assert result.tests == [{
        "name": run_tests.BACKEND_LIVE_MOCK_PREFLIGHT_NAME,
        "file": run_tests.BACKEND_LIVE_MOCK_PREFLIGHT_FILE,
        "status": "passed",
        "duration_seconds": 0,
    }]
