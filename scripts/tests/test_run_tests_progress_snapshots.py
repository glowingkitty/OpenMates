"""Regression tests for durable test-run progress snapshots.

The daily runner can take hours and may be killed before final aggregation.
These tests keep completed suite and Playwright batch results flowing into the
same local/Directus control plane while a run is still active.

Run: python3 -m pytest scripts/tests/test_run_tests_progress_snapshots.py.
"""

# contract-test-file: tooling

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUN_TESTS_PATH = ROOT / "scripts/run_tests.py"


def load_run_tests_module():
    spec = importlib.util.spec_from_file_location("openmates_run_tests_progress", RUN_TESTS_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_daily_dry_run_does_not_start_notification_thread() -> None:
    source = RUN_TESTS_PATH.read_text(encoding="utf-8")

    assert "if self.daily and not self.dry_run:\n            self._start_daily_status_updates" in source


def test_save_progress_writes_progress_file_and_daily_running_state(monkeypatch, tmp_path):
    run_tests = load_run_tests_module()
    monkeypatch.setattr(run_tests, "RESULTS_DIR", tmp_path)
    calls = []

    def fake_record(data, *, source="scripts_tests", workflow=""):
        calls.append((data, source, workflow))

    monkeypatch.setattr(run_tests, "_record_unified_test_state", fake_record)

    result = run_tests.RunResult(
        run_id="2026-08-22T03:00:02Z",
        git_sha="abc123def",
        git_branch="dev",
        environment="development",
        duration_seconds=12.3,
        summary={"total": 1, "passed": 1, "failed": 0, "dispatch_error": 0, "timeout": 0, "result_unknown": 0, "skipped": 0, "not_started": 0},
        suites={"vitest": {"status": "passed", "tests": [{"name": "unit", "status": "passed"}], "duration_seconds": 12.3}},
        flags={"suite": "all", "daily": True},
    )

    run_tests.ResultAggregator.save_progress(result)

    progress = json.loads((tmp_path / "last-run-progress.json").read_text(encoding="utf-8"))
    assert progress["flags"]["in_progress"] is True
    assert not (tmp_path / "last-run.json").exists()
    assert calls == [(progress, "daily_runner", "daily")]


def test_final_save_removes_stale_progress_and_records_completed_daily(monkeypatch, tmp_path):
    run_tests = load_run_tests_module()
    monkeypatch.setattr(run_tests, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(run_tests, "record_flake_history", lambda _data: None)
    (tmp_path / "last-run-progress.json").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "last-run-progress.json").write_text("{}", encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        run_tests,
        "_record_unified_test_state",
        lambda data, *, source="scripts_tests", workflow="": calls.append((data, source, workflow)),
    )

    result = run_tests.RunResult(
        run_id="2026-08-22T03:00:02Z",
        git_sha="abc123def",
        git_branch="dev",
        environment="development",
        duration_seconds=12.3,
        summary={"total": 1, "passed": 1, "failed": 0, "dispatch_error": 0, "timeout": 0, "result_unknown": 0, "skipped": 0, "not_started": 0},
        suites={"vitest": {"status": "passed", "tests": [{"name": "unit", "status": "passed"}], "duration_seconds": 12.3}},
        flags={"suite": "all", "daily": True},
    )

    run_tests.ResultAggregator.save(result)

    assert not (tmp_path / "last-run-progress.json").exists()
    assert (tmp_path / "last-run.json").exists()
    assert calls[0][1:] == ("daily_runner", "daily")
    assert calls[0][0]["flags"].get("in_progress") is None


def test_batch_runner_progress_callback_receives_cumulative_fail_fast_results():
    run_tests = load_run_tests_module()
    callbacks = []
    runner = run_tests.BatchRunner(
        client=object(),
        specs=["a.spec.ts", "b.spec.ts", "c.spec.ts"],
        batch_size=2,
        fail_fast=True,
        normal_account_slots=(1, 2),
        progress_callback=callbacks.append,
    )

    def fake_run_batch(specs, batch_idx, account_overrides=None):
        assert len(specs) == 1
        assert account_overrides in ([1], [2])
        return [
            run_tests.SpecResult(
                name=specs[0],
                file=specs[0],
                status="failed" if specs[0] == "a.spec.ts" else "passed",
            ),
        ]

    runner._run_batch = fake_run_batch

    result = runner.run_all_batches()

    assert result.status == "failed"
    assert callbacks
    statuses = {test["file"]: test["status"] for test in result.tests}
    assert statuses["a.spec.ts"] == "failed"
    assert set(statuses) == {"a.spec.ts", "b.spec.ts", "c.spec.ts"}
    assert statuses["c.spec.ts"] in {"passed", "not_started"}


def test_daily_runner_exception_persists_and_notifies_terminal_failure(monkeypatch, tmp_path):
    run_tests = load_run_tests_module()
    monkeypatch.setattr(run_tests, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(run_tests, "record_flake_history", lambda _data: None)
    monkeypatch.setattr(run_tests, "_record_unified_test_state", lambda *_args, **_kwargs: None)
    notifications = []

    orchestrator = run_tests.TestOrchestrator.__new__(run_tests.TestOrchestrator)
    orchestrator.daily = True
    orchestrator.dry_run = False
    orchestrator.suite = "all"
    orchestrator.only_failed = False
    orchestrator.fail_fast = False
    orchestrator.use_mocks = True
    orchestrator.record_live_fixtures = False
    orchestrator.run_id = "2026-08-24T03:00:03Z"
    orchestrator.git_sha = "abc123def"
    orchestrator.git_branch = "dev"
    orchestrator.environment = "development"
    orchestrator._progress_suites = {
        "vitest": run_tests.SuiteResult(
            status="passed",
            tests=[{"name": "unit", "status": "passed"}],
            duration_seconds=1,
        )
    }
    orchestrator._progress_start_time = 100.0
    orchestrator._daily_status_stop = run_tests.threading.Event()
    orchestrator._daily_status_thread = None
    orchestrator.notification = type(
        "FakeNotification",
        (),
        {"send_summary_email": lambda _self, result: notifications.append(result)},
    )()
    monkeypatch.setattr(orchestrator, "_run", lambda: (_ for _ in ()).throw(RuntimeError("artifact collection exploded")))
    monkeypatch.setattr(run_tests.time, "time", lambda: 130.0)

    assert orchestrator.run() == 1

    result = json.loads((tmp_path / "last-run.json").read_text(encoding="utf-8"))
    assert result["flags"]["runner_crashed"] is True
    assert result["flags"]["notifications_complete"] is False
    assert result["summary"]["failed"] == 1
    assert result["suites"]["vitest"]["tests"][0]["status"] == "passed"
    assert result["suites"]["orchestration"]["tests"][0]["status"] == "failed"
    assert "artifact collection exploded" in result["suites"]["orchestration"]["tests"][0]["error"]
    assert len(notifications) == 1
