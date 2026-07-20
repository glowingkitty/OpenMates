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

import pytest


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
    monkeypatch.setattr(module, "TEST_STORE", module.InMemoryTestControlStore())
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

    state = tests_control.load_state()
    assert state["latest_run_id"] == "2026-06-19T03:00:02Z"
    assert state["summary"]["failed"] == 2
    assert state["tests"]["playwright::chat-flow.spec.ts"]["status"] == "failed"
    assert state["tests"]["playwright::settings-flow.spec.ts"]["status"] == "passed"

    history = tests_control.load_history_events()
    assert len(history) == 3
    assert any(event["event"] == "failed" and event["test"] == "chat-flow.spec.ts" for event in history)
    assert not tests_control.STATE_FILE.exists()
    assert not (tests_control.RUNS_DIR / "20260619T030002Z.json").is_file()

    store = tests_control.get_store()
    assert "playwright::chat-flow.spec.ts" in store.test_catalog
    assert "2026-06-19T03:00:02Z" in store.test_runs
    assert any(result["test_key"] == "playwright::chat-flow.spec.ts" for result in store.test_results.values())


def test_record_run_preserves_passing_flake_metadata(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    run = sample_run()
    run["summary"] = {"total": 1, "passed": 1, "failed": 0, "skipped": 0}
    run["suites"] = {"playwright": {"status": "passed", "tests": [{
        "name": "chat-flow.spec.ts", "file": "chat-flow.spec.ts", "status": "passed",
        "flaky": True, "retries": 1, "attempt_statuses": ["failed", "passed"],
    }]}}

    tests_control.record_run_result(run)

    record = tests_control.load_state()["tests"]["playwright::chat-flow.spec.ts"]
    assert record["status"] == "passed"
    assert record["flaky"] is True
    assert record["retries"] == 1
    assert record["attempt_statuses"] == ["failed", "passed"]


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


def test_api_key_device_approval_is_environment_blocked(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)

    assert tests_control.classify_failure({
        "suite": "playwright",
        "test": "cli-skills-pdf.spec.ts",
        "error": "Locator: getByTestId('message-assistant')",
        "debug_output_summary": "A new device attempted to use your API key. Please review and approve it in Developer Settings.",
    }) == "environment_blocked"


def test_run_args_consume_expected_commit_before_forwarding(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)

    forwarded, expected = tests_control.parse_control_run_args([
        "--spec",
        "cli-skills-pdf.spec.ts",
        "--expected-commit",
        "abc123",
        "--no-fail-fast",
    ])

    assert forwarded == ["--spec", "cli-skills-pdf.spec.ts", "--no-fail-fast"]
    assert expected == "abc123"


def test_run_options_consume_gate_and_lease_flags(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)

    options = tests_control.parse_control_run_options([
        "--spec",
        "chat-flow.spec.ts",
        "--gate-deploy",
        "--lease-required",
        "--lease-id",
        "lease-chat-123",
        "--expected-commit=abc123",
    ])

    assert options.forwarded_args == ["--spec", "chat-flow.spec.ts"]
    assert options.gate_deploy is True
    assert options.lease_required is True
    assert options.lease_id == "lease-chat-123"
    assert options.expected_commit == "abc123"


def test_main_strips_run_passthrough_sentinel(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    seen_args = []

    def fake_command_run(args):
        seen_args.append(args)
        return 0

    monkeypatch.setattr(tests_control, "command_run", fake_command_run)

    assert tests_control.main(["run", "--", "--suite", "vitest"]) == 0
    assert seen_args == [["--suite", "vitest"]]


def test_commit_prefix_matching_accepts_short_or_long_sha(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)

    assert tests_control._matches_commit_prefix("abcdef123456", "abcdef1") is True
    assert tests_control._matches_commit_prefix("abcdef1", "abcdef123456") is True
    assert tests_control._matches_commit_prefix("abcdef123456", "1234567") is False


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

    leases = tests_control.get_store().list_claims()
    assert [lease["status"] for lease in leases] == ["active", "active"]
    assert not tests_control.LEASES_FILE.exists()


def test_complete_and_release_update_lease_status(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    tests_control.record_run_result(sample_run())
    first = tests_control.claim_next(session_id="s1")
    second = tests_control.claim_next(session_id="s2")

    tests_control.complete_lease(first["lease_id"], commit="abc123d")
    tests_control.release_lease(second["lease_id"], reason="blocked infra")

    claims = tests_control.get_store().list_claims()
    by_id = {lease["lease_id"]: lease for lease in claims}
    assert by_id[first["lease_id"]]["status"] == "completed"
    assert by_id[first["lease_id"]]["commit"] == "abc123d"
    assert by_id[second["lease_id"]]["status"] == "released"
    assert by_id[second["lease_id"]]["release_reason"] == "blocked infra"


def test_released_lease_blocks_same_test_until_expiry(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    run = sample_run()
    run["summary"] = {"total": 1, "passed": 0, "failed": 1, "skipped": 0}
    run["suites"]["playwright"]["tests"] = [run["suites"]["playwright"]["tests"][1]]
    tests_control.record_run_result(run)

    first = tests_control.claim_next(session_id="s1")
    assert first is not None
    tests_control.release_lease(first["lease_id"], reason="ignored elsewhere")

    assert tests_control.claim_next(session_id="s2") is None

    rerun = sample_run()
    rerun["run_id"] = "2026-06-19T04:00:02Z"
    rerun["summary"] = {"total": 1, "passed": 0, "failed": 1, "skipped": 0}
    rerun["suites"]["playwright"]["tests"] = [rerun["suites"]["playwright"]["tests"][1]]
    tests_control.record_run_result(rerun)

    assert tests_control.claim_next(session_id="s3") is None


def test_mark_running_adds_started_history_event(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)

    tests_control.mark_running(
        suite="playwright",
        tests=["chat-flow.spec.ts"],
        command=["python3", "scripts/tests.py", "run", "--spec", "chat-flow.spec.ts"],
    )

    state = tests_control.load_state()
    assert state["tests"]["playwright::chat-flow.spec.ts"]["status"] == "running"
    history = tests_control.load_history_events()
    assert any(event["event"] == "started" and event["test"] == "chat-flow.spec.ts" for event in history)


def test_mark_running_preserves_previous_stable_failure(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    tests_control.record_run_result(sample_run())

    tests_control.mark_running(
        suite="playwright",
        tests=["chat-flow.spec.ts"],
        command=["python3", "scripts/tests.py", "run", "--spec", "chat-flow.spec.ts"],
    )

    record = tests_control.load_state()["tests"]["playwright::chat-flow.spec.ts"]
    assert record["status"] == "failed"
    assert record["stable_status"] == "failed"
    assert record["active_status"] == "running"
    assert record["stable_run_id"] == "2026-06-19T03:00:02Z"
    assert record["active_run_id"].startswith("manual-")
    assert tests_control.get_store().test_runs[record["active_run_id"]]["status"] == "running"
    assert tests_control.load_state()["summary"]["failed"] == 2
    assert tests_control.load_state()["summary"]["running"] == 1


def test_record_run_clears_suite_running_marker_after_results(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    tests_control.mark_running(
        suite="pytest_unit",
        tests=[],
        command=["python3", "scripts/tests.py", "run", "--suite", "pytest"],
    )

    tests_control.record_run_result({
        "run_id": "2026-06-19T04:30:02Z",
        "git_sha": "def456abc",
        "git_branch": "dev",
        "environment": "development",
        "summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0},
        "suites": {"pytest_unit": {"status": "passed", "tests": [{"name": "tests/test_ok.py::test_ok", "status": "passed"}]}},
    })

    state = tests_control.load_state()
    assert state["tests"]["pytest_unit::pytest_unit"]["status"] == "passed"
    assert state["tests"]["pytest_unit::pytest_unit"]["active_status"] is None
    assert state["summary"]["running"] == 0


def test_passed_suite_without_rows_clears_stale_suite_failures(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    tests_control.record_run_result({
        "run_id": "2026-06-19T03:00:02Z",
        "git_sha": "abc123def",
        "git_branch": "dev",
        "environment": "development",
        "summary": {"total": 1, "passed": 0, "failed": 1, "skipped": 0},
        "suites": {"pytest_unit": {"status": "failed", "tests": [{"name": "tests/test_old.py::test_old", "status": "failed", "error": "old failure"}]}},
    })

    tests_control.record_run_result({
        "run_id": "2026-06-19T04:00:02Z",
        "git_sha": "def456abc",
        "git_branch": "dev",
        "environment": "development",
        "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
        "suites": {"pytest_unit": {"status": "passed", "tests": []}},
    })

    state = tests_control.load_state()
    record = state["tests"]["pytest_unit::tests/test_old.py::test_old"]
    assert record["status"] == "passed"
    assert record["error"] is None
    assert state["summary"]["failed"] == 0


def test_import_run_accepts_raw_pytest_json_report(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    report_path = tmp_path / "pytest-results.json"
    report_path.write_text(json.dumps({
        "created": 1784322951.0,
        "duration": 1.25,
        "summary": {"total": 2, "passed": 1, "failed": 1, "skipped": 0},
        "tests": [
            {"nodeid": "tests/test_ok.py::test_ok", "outcome": "passed", "duration": 0.1},
            {"nodeid": "tests/test_bad.py::test_bad", "outcome": "failed", "duration": 0.2, "call": {"longrepr": "assert False"}},
        ],
    }), encoding="utf-8")

    tests_control.import_run_artifact(report_path, source="github_actions", external_run_id="29613991033", workflow="pytest-unit.yml")

    state = tests_control.load_state()
    assert state["tests"]["pytest_unit::tests/test_ok.py::test_ok"]["status"] == "passed"
    failed = state["tests"]["pytest_unit::tests/test_bad.py::test_bad"]
    assert failed["status"] == "failed"
    assert failed["error"] == "assert False"
    assert tests_control.get_store().test_runs["29613991033"]["workflow"] == "pytest-unit.yml"


def test_full_unit_suite_retires_absent_stale_failures(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    tests_control.record_run_result({
        "run_id": "2026-06-19T03:00:02Z",
        "git_sha": "abc123def",
        "git_branch": "dev",
        "environment": "development",
        "summary": {"total": 1, "passed": 0, "failed": 1, "skipped": 0},
        "suites": {"pytest_unit": {"status": "failed", "tests": [{"name": "tests/test_old.py::test_old_name", "status": "failed", "error": "old failure"}]}},
    })

    tests_control.record_run_result({
        "run_id": "2026-06-19T04:00:02Z",
        "git_sha": "def456abc",
        "git_branch": "dev",
        "environment": "development",
        "flags": {"suite": "pytest", "only_failed": False},
        "summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0},
        "suites": {"pytest_unit": {"status": "passed", "tests": [{"name": "tests/test_old.py::test_new_name", "status": "passed"}]}},
    })

    state = tests_control.load_state()
    stale = state["tests"]["pytest_unit::tests/test_old.py::test_old_name"]
    assert stale["status"] == "not_started"
    assert stale["error"] is None
    assert state["tests"]["pytest_unit::tests/test_old.py::test_new_name"]["status"] == "passed"
    assert state["summary"]["failed"] == 0


def test_triage_supports_limit_category_and_suite_filters(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    tests_control.record_run_result(sample_run())

    triage = tests_control.build_triage(category_filter="chat_send_receive", suite_filter="playwright", limit=1)

    assert len(triage["entries"]) == 1
    assert triage["entries"][0]["category"] == "chat_send_receive"
    assert triage["entries"][0]["suite"] == "playwright"

    assert tests_control.build_triage(suite_filter="pytest")["entries"] == []


def test_require_active_lease_blocks_when_failures_exist(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    tests_control.record_run_result(sample_run())

    with pytest.raises(RuntimeError, match="No active failed-test lease"):
        tests_control.require_active_lease(session_id="s1")

    lease = tests_control.claim_next(session_id="s1")

    assert tests_control.require_active_lease(session_id="s1") is None
    assert tests_control.active_lease_for_session(lease_id=lease["lease_id"])["lease_id"] == lease["lease_id"]


def test_e2e_deploy_gate_checks_playwright_targets(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    options = tests_control.ControlRunOptions(forwarded_args=["--spec", "chat-flow.spec.ts"], gate_deploy=True)

    monkeypatch.setattr(tests_control, "current_git_sha", lambda: "abcdef123456")
    monkeypatch.setattr(tests_control, "check_vercel_ready_for_commit", lambda commit: [])
    monkeypatch.setattr(tests_control, "check_dev_health_urls", lambda: [])

    tests_control.run_e2e_deploy_gate(options)


def test_e2e_deploy_gate_blocks_stale_vercel_commit(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    options = tests_control.ControlRunOptions(
        forwarded_args=["--spec", "chat-flow.spec.ts"],
        expected_commit="abcdef1",
        gate_deploy=True,
    )

    monkeypatch.setattr(tests_control, "current_git_sha", lambda: "abcdef123456")
    monkeypatch.setattr(tests_control, "check_vercel_ready_for_commit", lambda commit: ["not deployed"])
    monkeypatch.setattr(tests_control, "check_dev_health_urls", lambda: [])

    with pytest.raises(RuntimeError, match="not deployed"):
        tests_control.run_e2e_deploy_gate(options)


def test_e2e_deploy_gate_skips_non_playwright_targets(tmp_path, monkeypatch, capsys):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    options = tests_control.ControlRunOptions(forwarded_args=["--suite", "pytest"], gate_deploy=True)

    tests_control.run_e2e_deploy_gate(options)

    assert "SKIPPED" in capsys.readouterr().out


def test_complete_lease_require_passing_blocks_active_failure_group(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    tests_control.record_run_result(sample_run())
    lease = tests_control.claim_next(session_id="s1")

    with pytest.raises(RuntimeError, match="still failing"):
        tests_control.complete_lease(lease["lease_id"], commit="abc123d", require_passing=True)

    fixed_run = {
        "run_id": "2026-06-19T04:00:02Z",
        "git_sha": "def456abc",
        "git_branch": "dev",
        "environment": "development",
        "summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0},
        "suites": {"playwright": {"status": "passed", "tests": [{"name": "account-recovery-flow.spec.ts", "file": "account-recovery-flow.spec.ts", "status": "passed"}]}},
    }
    tests_control.record_run_result(fixed_run)

    completed = tests_control.complete_lease(lease["lease_id"], commit="def456a", require_passing=True)

    assert completed["status"] == "completed"
    assert completed["completed_commit"] == "def456a"


def test_command_run_falls_back_to_timestamped_run_artifact(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    monkeypatch.setattr(tests_control, "RUN_TESTS_SCRIPT", tmp_path / "run_tests.py")

    run_data = {
        "run_id": "2026-06-19T05:00:02Z",
        "git_sha": "abc123def",
        "git_branch": "dev",
        "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
        "suites": {},
    }

    def fake_run(command, cwd=None):
        tests_control.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        (tests_control.RESULTS_DIR / "last-run.json").write_text(json.dumps(run_data), encoding="utf-8")
        (tests_control.RESULTS_DIR / "run-20260619T050002Z.json").write_text(json.dumps(run_data), encoding="utf-8")
        return tests_control.subprocess.CompletedProcess(command, 0)

    recorded_run_ids = []

    def fake_record_run_result(data):
        recorded_run_ids.append(data["run_id"])
        if len(recorded_run_ids) == 1:
            raise RuntimeError("temporary Directus failure")
        return {"summary": {}, "tests": {}}

    monkeypatch.setattr(tests_control.subprocess, "run", fake_run)
    monkeypatch.setattr(tests_control, "record_run_result", fake_record_run_result)

    assert tests_control.command_run(["--suite", "pytest"]) == 0
    assert recorded_run_ids == ["2026-06-19T05:00:02Z", "2026-06-19T05:00:02Z"]
