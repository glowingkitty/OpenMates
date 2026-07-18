#!/usr/bin/env python3
"""
Regression tests for GitHub Actions ingestion into the test control plane.

The tests use the in-memory Directus-shaped store so no GitHub or Directus
network calls are needed.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TESTS_CONTROL_PATH = PROJECT_ROOT / "scripts" / "tests.py"


def load_tests_control(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("openmates_tests_control_github", TESTS_CONTROL_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(module, "TEST_STORE", module.InMemoryTestControlStore())
    return module


def github_run_payload() -> dict:
    return {
        "run_id": "gha-200",
        "git_sha": "def456",
        "git_branch": "dev",
        "environment": "development",
        "summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0},
        "suites": {
            "playwright": {
                "status": "passed",
                "tests": [{"name": "chat-flow.spec.ts", "file": "chat-flow.spec.ts", "status": "passed", "run_id": 200}],
            }
        },
    }


def test_ingest_github_actions_run_is_idempotent(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    payload = github_run_payload()

    first = tests_control.ingest_github_actions_run(payload, external_run_id="200", workflow="playwright-spec.yml")
    second = tests_control.ingest_github_actions_run(payload, external_run_id="200", workflow="playwright-spec.yml")

    store = tests_control.get_store()
    assert first["latest_run_id"] == "gha-200"
    assert second["latest_run_id"] == "gha-200"
    assert len(store.test_runs) == 1
    assert len(store.test_results) == 1
    assert store.test_runs["gha-200"]["source"] == "github_actions"
    assert store.test_runs["gha-200"]["external_run_id"] == "200"
    assert store.current_state["playwright::chat-flow.spec.ts"]["active_status"] is None


def test_completed_github_run_clears_active_running_state(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    tests_control.mark_running(
        suite="playwright",
        tests=["chat-flow.spec.ts"],
        command=["python3", "scripts/tests.py", "run", "--spec", "chat-flow.spec.ts"],
    )

    tests_control.ingest_github_actions_run(github_run_payload(), external_run_id="200", workflow="playwright-spec.yml")

    record = tests_control.load_state()["tests"]["playwright::chat-flow.spec.ts"]
    assert record["status"] == "passed"
    assert record["active_status"] is None
    assert record["stable_status"] == "passed"
