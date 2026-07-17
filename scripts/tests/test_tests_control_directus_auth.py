#!/usr/bin/env python3
"""
Regression tests for host-side Directus auth used by scripts/tests.py.

Local operator shells often do not export DIRECTUS_TOKEN even though the running
api container has admin credentials. The test control plane must mint a
short-lived token instead of blocking test dispatch before it starts.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import urllib.error
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TESTS_CONTROL_PATH = PROJECT_ROOT / "scripts" / "tests.py"


def load_tests_control():
    spec = importlib.util.spec_from_file_location("openmates_tests_control_auth", TESTS_CONTROL_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_directus_store_mints_local_dev_token_when_env_token_missing(monkeypatch):
    tests_control = load_tests_control()
    monkeypatch.delenv("DIRECTUS_TOKEN", raising=False)
    monkeypatch.delenv("CMS_URL", raising=False)

    def fake_run(command, check, capture_output, text, timeout):
        assert command[:3] == ["docker", "exec", "api"]
        return subprocess.CompletedProcess(command, 0, stdout="short-lived-token\n", stderr="")

    monkeypatch.setattr(tests_control.subprocess, "run", fake_run)

    store = tests_control.DirectusTestControlStore()

    assert store.base_url == "http://127.0.0.1:8055"
    assert store.token == "short-lived-token"


def test_directus_request_refreshes_token_once_after_unauthorized(monkeypatch):
    tests_control = load_tests_control()
    monkeypatch.setenv("DIRECTUS_TOKEN", "expired-token")
    monkeypatch.setenv("CMS_URL", "http://directus.example")
    monkeypatch.setattr(tests_control.DirectusTestControlStore, "_mint_local_dev_token", lambda self: "fresh-token")

    seen_authorizations = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps({"data": [{"ok": True}]}).encode("utf-8")

    def fake_urlopen(request, timeout):
        seen_authorizations.append(request.headers.get("Authorization"))
        if len(seen_authorizations) == 1:
            raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)
        return FakeResponse()

    monkeypatch.setattr(tests_control.urllib.request, "urlopen", fake_urlopen)

    store = tests_control.DirectusTestControlStore()
    result = store._request("GET", "/items/test_current_state")

    assert result == [{"ok": True}]
    assert seen_authorizations == ["Bearer expired-token", "Bearer fresh-token"]
    assert store.token == "fresh-token"


def test_command_run_invokes_runner_without_env_directus_token(monkeypatch, tmp_path):
    tests_control = load_tests_control()
    monkeypatch.delenv("DIRECTUS_TOKEN", raising=False)
    monkeypatch.delenv("CMS_URL", raising=False)
    monkeypatch.setattr(tests_control, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(tests_control, "RESULTS_DIR", tmp_path / "test-results")
    monkeypatch.setattr(tests_control, "STATE_FILE", tmp_path / "test-results" / "tests-state.json")
    monkeypatch.setattr(tests_control, "HISTORY_FILE", tmp_path / "test-results" / "tests-history.jsonl")
    monkeypatch.setattr(tests_control, "LEASES_FILE", tmp_path / "test-results" / "failed-test-leases.json")
    monkeypatch.setattr(tests_control, "RUNS_DIR", tmp_path / "test-results" / "runs")
    monkeypatch.setattr(tests_control, "RUN_TESTS_SCRIPT", tmp_path / "run_tests.py")

    runner_calls = []

    def fake_run(command, check=False, capture_output=False, text=False, timeout=None, cwd=None):
        if command[:3] == ["docker", "exec", "api"]:
            return subprocess.CompletedProcess(command, 0, stdout="short-lived-token\n", stderr="")
        runner_calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    def fake_request(self, method, path, data=None, params=None):
        if method == "GET":
            return []
        return data or {}

    monkeypatch.setattr(tests_control.subprocess, "run", fake_run)
    monkeypatch.setattr(tests_control.DirectusTestControlStore, "_request", fake_request)

    result = tests_control.command_run(["--spec", "settings-privacy-pii-deep-link.spec.ts"])

    assert result == 0
    assert runner_calls == [[sys.executable, str(tmp_path / "run_tests.py"), "--spec", "settings-privacy-pii-deep-link.spec.ts"]]


def test_bulk_import_records_started_events_as_running_runs(monkeypatch):
    tests_control = load_tests_control()
    monkeypatch.setattr(tests_control.DirectusTestControlStore, "_mint_local_dev_token", lambda self: "token")
    store = tests_control.DirectusTestControlStore()

    rows = store._bulk_run_rows(
        None,
        {"updated_at": "2026-07-17T10:00:00Z", "summary": {"total": 1}},
        [{"event": "started", "run_id": "manual-1", "key": "playwright::x.spec.ts", "command": "python3 scripts/tests.py run --spec x.spec.ts"}],
        "scripts_tests",
        "",
        "",
        "snapshot-run",
    )

    assert rows == [{
        "run_key": "manual-1",
        "source": "scripts_tests",
        "external_run_id": "",
        "workflow": "",
        "status": "running",
        "git_sha": None,
        "git_branch": None,
        "environment": None,
        "requested_tests": ["playwright::x.spec.ts"],
        "summary": {},
        "record_json": {"events": [{"event": "started", "run_id": "manual-1", "key": "playwright::x.spec.ts", "command": "python3 scripts/tests.py run --spec x.spec.ts"}], "command": "python3 scripts/tests.py run --spec x.spec.ts"},
        "updated_at": "2026-07-17T10:00:00Z",
        "updated_at_unix": rows[0]["updated_at_unix"],
    }]


def test_directus_load_state_repairs_stale_problem_rows(monkeypatch):
    tests_control = load_tests_control()
    monkeypatch.setattr(tests_control.DirectusTestControlStore, "_mint_local_dev_token", lambda self: "token")
    store = tests_control.DirectusTestControlStore()

    stale_row = {
        "id": "row-1",
        "test_key": "pytest_unit::tests/test_workflow_key_boundary.py::test_workflow_blob_schema_stays_vault_not_client_wrapper",
        "suite": "pytest_unit",
        "test_name": "tests/test_workflow_key_boundary.py::test_workflow_blob_schema_stays_vault_not_client_wrapper",
        "stable_status": "failed",
        "stable_run_key": "old-run",
        "error_summary": "missing schema",
        "metadata": {"error": "missing schema", "status": "failed"},
    }
    fresh_row = {
        **stale_row,
        "stable_status": "passed",
        "stable_run_key": "new-run",
        "error_summary": None,
        "metadata": {"error": None, "status": "passed"},
    }

    def fake_items(collection, params=None):
        assert collection == "test_current_state"
        params = params or {}
        if "filter" not in params:
            return [stale_row]
        decoded_filter = json.loads(params["filter"])
        if decoded_filter.get("stable_status"):
            return [stale_row]
        if decoded_filter.get("test_key"):
            return [fresh_row]
        return []

    monkeypatch.setattr(store, "_items", fake_items)

    state = store.load_state()
    record = state["tests"][stale_row["test_key"]]

    assert record["status"] == "passed"
    assert record["run_id"] == "new-run"
    assert state["summary"]["failed"] == 0
