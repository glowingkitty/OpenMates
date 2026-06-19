#!/usr/bin/env python3
"""
Regression tests for the unified test control plane.

These tests exercise pure filesystem/state behavior only. They do not dispatch
GitHub Actions and do not run Playwright or Vitest locally; the control script
is responsible for wrapping those remote workflows in production use.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TESTS_CONTROL_PATH = PROJECT_ROOT / "scripts" / "tests.py"


def load_tests_control(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("openmates_tests_control", TESTS_CONTROL_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    results_dir = tmp_path / "test-results"
    monkeypatch.setattr(module, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(module, "STATE_FILE", results_dir / "tests-state.json")
    monkeypatch.setattr(module, "HISTORY_FILE", results_dir / "tests-history.jsonl")
    monkeypatch.setattr(module, "LEASES_FILE", results_dir / "failed-test-leases.json")
    monkeypatch.setattr(module, "TRIAGE_FILE", results_dir / "test-failure-triage.json")
    monkeypatch.setattr(module, "TEST_FILE_INDEX_FILE", results_dir / "test-file-index.json")
    monkeypatch.setattr(module, "RUNS_DIR", results_dir / "runs")
    monkeypatch.setattr(module, "LEASE_LOCK_FILE", tmp_path / "leases.lock")
    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(module, "SPEC_DIR", tmp_path / "frontend" / "apps" / "web_app" / "tests")
    return module


def sample_run() -> dict:
    return {
        "run_id": "2026-06-19T03:00:02Z",
        "git_sha": "abc123def",
        "git_branch": "dev",
        "environment": "development",
        "duration_seconds": 42.0,
        "flags": {"suite": "all"},
        "summary": {"total": 3, "passed": 1, "failed": 2, "skipped": 0},
        "suites": {
            "playwright": {
                "status": "failed",
                "duration_seconds": 40,
                "tests": [
                    {
                        "name": "chat-flow.spec.ts",
                        "file": "chat-flow.spec.ts",
                        "status": "failed",
                        "error": "Locator: locator('[data-action=\"send-message\"]') Expected: visible Error: element(s) not found",
                        "run_id": 123,
                    },
                    {
                        "name": "account-recovery-flow.spec.ts",
                        "file": "account-recovery-flow.spec.ts",
                        "status": "failed",
                        "error": "Reserved Playwright account slot 14 failed or was not configured in preflight",
                        "run_id": 124,
                    },
                    {
                        "name": "settings-flow.spec.ts",
                        "file": "settings-flow.spec.ts",
                        "status": "passed",
                    },
                ],
            }
        },
    }


def test_record_run_updates_state_history_and_run_archive(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)

    tests_control.record_run_result(sample_run())

    state = json.loads(tests_control.STATE_FILE.read_text(encoding="utf-8"))
    assert state["latest_run_id"] == "2026-06-19T03:00:02Z"
    assert state["summary"]["failed"] == 2
    assert state["tests"]["playwright::chat-flow.spec.ts"]["status"] == "failed"
    assert state["tests"]["playwright::settings-flow.spec.ts"]["status"] == "passed"

    history = tests_control.HISTORY_FILE.read_text(encoding="utf-8").splitlines()
    assert len(history) == 3
    assert any('"event": "failed"' in line and "chat-flow.spec.ts" in line for line in history)
    assert (tests_control.RUNS_DIR / "20260619T030002Z.json").is_file()


def test_triage_ranks_account_and_chat_failures_with_linked_files(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    spec_dir = tests_control.SPEC_DIR
    spec_dir.mkdir(parents=True)
    (spec_dir / "chat-flow.spec.ts").write_text("import { test } from '@playwright/test';\n", encoding="utf-8")

    component = tmp_path / "frontend" / "packages" / "ui" / "src" / "components" / "enter_message" / "MessageInput.svelte"
    component.parent.mkdir(parents=True)
    component.write_text('<button data-action="send-message">Send</button>\n', encoding="utf-8")

    tests_control.record_run_result(sample_run())
    triage = tests_control.build_triage()

    assert triage["summary"]["failed"] == 2
    entries = triage["entries"]
    assert entries[0]["category"] == "account_preflight"
    assert entries[1]["category"] == "chat_send_receive"
    assert "frontend/apps/web_app/tests/chat-flow.spec.ts" in entries[1]["linked_files"]
    assert "frontend/packages/ui/src/components/enter_message/MessageInput.svelte" in entries[1]["linked_files"]


def test_classification_avoids_authenticity_false_positive(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)

    assert tests_control.classify_failure({
        "suite": "playwright",
        "test": "demo-chat-embeds.spec.ts",
        "error": "image-authenticity-badge still contains {percentage}",
    }) == "embed_rendering"
    assert tests_control.classify_failure({
        "suite": "cli",
        "test": "cli-integration/code-docs/apps-code-get-docs",
        "error": "Skill execution failed: Not authenticated: provide a session cookie or API key",
    }) == "cli_auth"


def test_next_lease_claims_different_groups_for_parallel_workers(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    tests_control.record_run_result(sample_run())

    first = tests_control.claim_next(session_id="s1")
    second = tests_control.claim_next(session_id="s2")

    assert first is not None
    assert second is not None
    assert first["lease_id"] != second["lease_id"]
    assert first["group_id"] != second["group_id"]
    assert first["entry"]["test"] == "account-recovery-flow.spec.ts"
    assert second["entry"]["test"] == "chat-flow.spec.ts"

    leases = json.loads(tests_control.LEASES_FILE.read_text(encoding="utf-8"))["leases"]
    assert [lease["status"] for lease in leases] == ["active", "active"]


def test_complete_and_release_update_lease_status(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    tests_control.record_run_result(sample_run())
    first = tests_control.claim_next(session_id="s1")
    second = tests_control.claim_next(session_id="s2")

    tests_control.complete_lease(first["lease_id"], commit="abc123d")
    tests_control.release_lease(second["lease_id"], reason="blocked infra")

    leases = json.loads(tests_control.LEASES_FILE.read_text(encoding="utf-8"))["leases"]
    by_id = {lease["lease_id"]: lease for lease in leases}
    assert by_id[first["lease_id"]]["status"] == "completed"
    assert by_id[first["lease_id"]]["commit"] == "abc123d"
    assert by_id[second["lease_id"]]["status"] == "released"
    assert by_id[second["lease_id"]]["release_reason"] == "blocked infra"


def test_mark_running_adds_started_history_event(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)

    tests_control.mark_running(
        suite="playwright",
        tests=["chat-flow.spec.ts"],
        command=["python3", "scripts/run_tests.py", "--spec", "chat-flow.spec.ts"],
    )

    state = json.loads(tests_control.STATE_FILE.read_text(encoding="utf-8"))
    assert state["tests"]["playwright::chat-flow.spec.ts"]["status"] == "running"
    history = tests_control.HISTORY_FILE.read_text(encoding="utf-8")
    assert '"event": "started"' in history
    assert "chat-flow.spec.ts" in history
