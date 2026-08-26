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

    def fake_run_batch(specs, batch_idx):
        assert batch_idx == 0
        return [
            run_tests.SpecResult(name=specs[0], file=specs[0], status="failed"),
            run_tests.SpecResult(name=specs[1], file=specs[1], status="passed"),
        ]

    runner._run_batch = fake_run_batch

    result = runner.run_all_batches()

    assert result.status == "failed"
    assert len(callbacks) == 1
    statuses = {test["file"]: test["status"] for test in callbacks[0].tests}
    assert statuses == {"a.spec.ts": "failed", "b.spec.ts": "passed", "c.spec.ts": "not_started"}


def test_batch_runner_accounts_for_crashed_batch_and_continues_without_fail_fast():
    run_tests = load_run_tests_module()
    callbacks = []
    runner = run_tests.BatchRunner(
        client=object(),
        specs=["a.spec.ts", "b.spec.ts", "c.spec.ts"],
        batch_size=2,
        fail_fast=False,
        normal_account_slots=(1, 2),
        progress_callback=callbacks.append,
    )
    batches = []

    def fake_run_batch(specs, batch_idx):
        batches.append((batch_idx, list(specs)))
        if batch_idx == 0:
            runner._batch_runs_terminal = True
            raise RuntimeError("artifact collection exploded")
        return [run_tests.SpecResult(name=specs[0], file=specs[0], status="passed")]

    runner._run_batch = fake_run_batch

    result = runner.run_all_batches()

    assert batches == [(0, ["a.spec.ts", "b.spec.ts"]), (1, ["c.spec.ts"])]
    assert len(callbacks) == 2
    assert {test["file"]: test["status"] for test in result.tests} == {
        "a.spec.ts": "result_unknown",
        "b.spec.ts": "result_unknown",
        "c.spec.ts": "passed",
    }
    assert all(
        test.get("error") == "Batch 1 collection failed: artifact collection exploded"
        for test in result.tests[:2]
    )


def test_batch_runner_drains_active_runs_before_reusing_accounts():
    run_tests = load_run_tests_module()
    drained = []

    class FakeClient:
        def wait_for_runs(self, run_ids, fail_fast):
            drained.append((list(run_ids), fail_fast))
            return {run_id: {"status": "completed", "conclusion": "success"} for run_id in run_ids}

    runner = run_tests.BatchRunner(
        client=FakeClient(),
        specs=["a.spec.ts", "b.spec.ts", "c.spec.ts"],
        batch_size=2,
        fail_fast=False,
        normal_account_slots=(1, 2),
    )
    batches = []

    def fake_run_batch(specs, batch_idx):
        batches.append((batch_idx, list(specs)))
        if batch_idx == 0:
            runner._active_batch_run_ids = [101]
            raise RuntimeError("dispatch connection reset")
        return [run_tests.SpecResult(name=specs[0], file=specs[0], status="passed")]

    runner._run_batch = fake_run_batch

    result = runner.run_all_batches()

    assert drained == [([101], False)]
    assert batches == [(0, ["a.spec.ts", "b.spec.ts"]), (1, ["c.spec.ts"])]
    assert [test["status"] for test in result.tests] == ["result_unknown", "result_unknown", "passed"]


def test_batch_runner_accounts_for_remaining_specs_when_active_run_drain_fails():
    run_tests = load_run_tests_module()
    callbacks = []

    class FakeClient:
        def wait_for_runs(self, _run_ids, _fail_fast):
            raise RuntimeError("GitHub unavailable")

    runner = run_tests.BatchRunner(
        client=FakeClient(),
        specs=["a.spec.ts", "b.spec.ts", "c.spec.ts"],
        batch_size=2,
        fail_fast=False,
        normal_account_slots=(1, 2),
        progress_callback=callbacks.append,
    )
    batches = []

    def fake_run_batch(specs, batch_idx):
        batches.append((batch_idx, list(specs)))
        runner._active_batch_run_ids = [101]
        raise RuntimeError("polling failed")

    runner._run_batch = fake_run_batch

    result = runner.run_all_batches()

    assert batches == [(0, ["a.spec.ts", "b.spec.ts"])]
    assert [test["status"] for test in result.tests] == ["result_unknown", "result_unknown", "not_started"]
    assert len(callbacks) == 1
    assert "Could not drain active workflows: GitHub unavailable" in result.tests[0]["error"]


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
    def send_summary_email(_self, result):
        notifications.append(result)
        result.flags["notification_channels"] = {
            "email": {"configured": True, "status": "failed", "transport": "brevo"},
            "discord": {"configured": True, "status": "failed", "transport": "webhook"},
        }
        return False

    orchestrator.notification = type(
        "FakeNotification",
        (),
        {"send_summary_email": send_summary_email},
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
    archives = list(tmp_path.glob("daily-run-*.json"))
    assert len(archives) == 1
    archived = json.loads(archives[0].read_text(encoding="utf-8"))
    assert archived["flags"]["notifications_complete"] is False
    assert archived["flags"]["notification_channels"]["discord"]["status"] == "failed"


def test_daily_archive_includes_terminal_notification_outcomes(monkeypatch, tmp_path):
    run_tests = load_run_tests_module()
    monkeypatch.setattr(run_tests, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(run_tests, "record_flake_history", lambda _data: None)
    monkeypatch.setattr(run_tests, "_record_unified_test_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(run_tests.ReportGenerator, "generate", lambda *_args: None)
    monkeypatch.setattr(run_tests.TestRecordingPublisher, "publish", lambda *_args: None)

    class FakeNotification:
        def split_results(self):
            return None

        def push_to_openobserve(self, _result):
            return None

        def send_summary_email(self, result):
            result.flags["notification_channels"] = {
                "email": {
                    "configured": True,
                    "status": "provider_accepted",
                    "transport": "brevo",
                },
                "discord": {
                    "configured": True,
                    "status": "provider_accepted",
                    "transport": "webhook",
                },
            }
            return True

    orchestrator = run_tests.TestOrchestrator.__new__(run_tests.TestOrchestrator)
    orchestrator.notification = FakeNotification()
    orchestrator._sync_obsidian_test_results = lambda: None
    result = run_tests.RunResult(
        run_id="2026-08-26T03:00:05Z",
        git_sha="abc123def",
        git_branch="dev",
        environment="development",
        duration_seconds=1,
        summary={
            "total": 1,
            "passed": 1,
            "failed": 0,
            "dispatch_error": 0,
            "timeout": 0,
            "result_unknown": 0,
            "skipped": 0,
            "not_started": 0,
        },
        suites={},
        flags={"daily": True, "suite": "all"},
    )

    orchestrator._daily_post_run(result)

    archives = list(tmp_path.glob("daily-run-*.json"))
    assert len(archives) == 1
    archived = json.loads(archives[0].read_text(encoding="utf-8"))
    assert archived["flags"]["notifications_complete"] is True
    assert archived["flags"]["notification_channels"]["email"]["status"] == "provider_accepted"


def test_daily_archive_retention_keeps_newest_seven(monkeypatch, tmp_path):
    run_tests = load_run_tests_module()
    monkeypatch.setattr(run_tests, "RESULTS_DIR", tmp_path)
    (tmp_path / "last-run.json").write_text('{"run_id":"latest"}\n', encoding="utf-8")
    for day in range(1, 9):
        (tmp_path / f"daily-run-2000-01-{day:02d}.json").write_text("{}\n", encoding="utf-8")

    orchestrator = run_tests.TestOrchestrator.__new__(run_tests.TestOrchestrator)
    orchestrator._archive_daily_result()

    archives = sorted(path.name for path in tmp_path.glob("daily-run-*.json"))
    assert len(archives) == run_tests.DAILY_ARTIFACT_RETENTION_DAYS
    assert "daily-run-2000-01-01.json" not in archives
    assert "daily-run-2000-01-02.json" not in archives


def test_daily_terminal_result_and_notification_precede_optional_publication(monkeypatch, tmp_path):
    run_tests = load_run_tests_module()
    monkeypatch.setattr(run_tests, "RESULTS_DIR", tmp_path)
    events = []

    monkeypatch.setattr(run_tests.ResultAggregator, "save", lambda _result: events.append("save"))
    monkeypatch.setattr(run_tests.ReportGenerator, "generate", lambda *_args: events.append("report"))
    monkeypatch.setattr(run_tests.TestRecordingPublisher, "publish", lambda *_args: events.append("s3"))

    class FakeNotification:
        def split_results(self):
            events.append("split")

        def push_to_openobserve(self, _result):
            events.append("openobserve")

        def send_summary_email(self, result):
            events.append("notify")
            result.flags["notification_channels"] = {
                "email": {"configured": True, "status": "provider_accepted", "transport": "brevo"},
                "discord": {"configured": True, "status": "provider_accepted", "transport": "webhook"},
            }
            return True

    orchestrator = run_tests.TestOrchestrator.__new__(run_tests.TestOrchestrator)
    orchestrator.daily = True
    orchestrator.dry_run = False
    orchestrator.suite = "apple"
    orchestrator.spec = None
    orchestrator.account = None
    orchestrator.create_account_slot = None
    orchestrator.only_failed = False
    orchestrator.fail_fast = False
    orchestrator.use_mocks = True
    orchestrator.record_live_fixtures = False
    orchestrator.git_sha = "abc123def"
    orchestrator.git_branch = "dev"
    orchestrator.environment = "development"
    orchestrator.run_id = "2026-08-26T03:00:05Z"
    orchestrator.current_phase = "starting"
    orchestrator.notification = FakeNotification()
    orchestrator._daily_gate = lambda: True
    orchestrator._start_daily_status_updates = lambda _start: None
    orchestrator._stop_daily_status_updates = lambda: None
    orchestrator._save_progress_snapshot = lambda *_args: None
    orchestrator._run_apple_remote_nightly = lambda: run_tests.SuiteResult(
        status="passed",
        tests=[{"name": "apple", "status": "passed"}],
        duration_seconds=1,
    )
    orchestrator._sync_obsidian_test_results = lambda: events.append("obsidian")
    orchestrator._archive_daily_result = lambda: events.append("archive")
    orchestrator._print_summary = lambda _result: None

    assert orchestrator._run() == 0

    assert events == [
        "save",
        "notify",
        "save",
        "archive",
        "report",
        "s3",
        "openobserve",
        "split",
        "obsidian",
    ]


def test_non_daily_run_keeps_existing_publication_order(monkeypatch, tmp_path):
    run_tests = load_run_tests_module()
    monkeypatch.setattr(run_tests, "RESULTS_DIR", tmp_path)
    events = []

    monkeypatch.setattr(run_tests.ResultAggregator, "save", lambda _result: events.append("save"))
    monkeypatch.setattr(run_tests.ReportGenerator, "generate", lambda *_args: events.append("report"))
    monkeypatch.setattr(run_tests.TestRecordingPublisher, "publish", lambda *_args: events.append("s3"))

    orchestrator = run_tests.TestOrchestrator.__new__(run_tests.TestOrchestrator)
    orchestrator.daily = False
    orchestrator.dry_run = False
    orchestrator.suite = "apple"
    orchestrator.spec = None
    orchestrator.account = None
    orchestrator.create_account_slot = None
    orchestrator.only_failed = False
    orchestrator.fail_fast = False
    orchestrator.use_mocks = True
    orchestrator.record_live_fixtures = False
    orchestrator.git_sha = "abc123def"
    orchestrator.git_branch = "dev"
    orchestrator.environment = "development"
    orchestrator.run_id = "2026-08-26T03:00:05Z"
    orchestrator.current_phase = "starting"
    orchestrator._save_progress_snapshot = lambda *_args: None
    orchestrator._run_apple_remote_nightly = lambda: run_tests.SuiteResult(
        status="passed",
        tests=[{"name": "apple", "status": "passed"}],
        duration_seconds=1,
    )
    orchestrator._sync_obsidian_test_results = lambda: events.append("obsidian")
    orchestrator._print_summary = lambda _result: None

    assert orchestrator._run() == 0
    assert events == ["save", "report", "s3", "obsidian"]
