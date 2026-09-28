# contract-test-file: tooling
"""Tooling contract for source-bound nightly reporting and channel retries."""

from datetime import date, datetime, timezone
import json
from pathlib import Path
import sqlite3

from scripts import daily_ci_notification as notice


def fixture_job(root: Path, *, day: date, job_id: str, mode: str, source: str, state: str, run_id: int):
    database = root / "logs/ci-coordinator/queue.sqlite3"
    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS jobs (id TEXT, owner TEXT, source TEXT, mode TEXT, state TEXT, run_id INTEGER, url TEXT, created REAL)"
        )
        connection.execute(
            "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)",
            (job_id, "daily", source, mode, state, run_id, f"https://example.test/runs/{run_id}",
             datetime(day.year, day.month, day.day, 3, tzinfo=timezone.utc).timestamp()),
        )


def fixture_receipt(root: Path, job_id: str, source: str, run_id: int, results: list[dict]):
    path = root / "test-results/ci-runs" / job_id / "receipt.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "id": job_id, "source_commit": source, "run_id": run_id,
        "report": {"results": results},
    }))


def test_aborted_selection_reports_actual_unit_failures_without_inventing_browser_counts(tmp_path, monkeypatch):
    day = date(2026, 9, 28)
    source = "a" * 40
    fixture_job(tmp_path, day=day, job_id="pytest", mode="pytest", source=source, state="failure", run_id=11)
    fixture_job(tmp_path, day=day, job_id="vitest", mode="vitest", source=source, state="failure", run_id=12)
    fixture_receipt(tmp_path, "pytest", source, 11, [{
        "suite": "pytest", "exit_code": 1,
        "failed_tests": ["tests/test_workflow.py::test_a", "tests/test_workflow.py::test_b"],
    }])
    pytest_report = tmp_path / "test-results/ci-runs/pytest/test-results/ci-pytest.json"
    pytest_report.parent.mkdir(parents=True, exist_ok=True)
    pytest_report.write_text(json.dumps({"summary": {"total": 3, "passed": 1, "failed": 2, "skipped": 0}}))
    fixture_receipt(tmp_path, "vitest", source, 12, [
        {"suite": "frontend/apps/web_app", "exit_code": 1},
        {"suite": "cli-accounts", "exit_code": 0},
    ])
    monkeypatch.setattr(notice, "selection_diagnostic", lambda *_: "Unclassified AI spec: new.spec.ts")
    report = notice.build_report(tmp_path, day, datetime(2026, 9, 28, 4, tzinfo=timezone.utc))
    assert report["status"] == "blocked" and not report["ready"]
    assert report["source_commit"] == source
    assert report["selected_specs"] is None and report["held_specs"] is None
    assert report["admitted_specs"] == 0
    assert report["job_states"] == {"failure": 2}
    assert report["failed_case_count"] == 2
    assert report["known_total_tests"] == 3 and report["known_failed_tests"] == 2
    assert report["failed_case_files"] == [("test_workflow.py", 2)]
    assert report["failing_vitest_workspaces"] == ["frontend/apps/web_app"]
    assert "Web spec inventory: unknown" in notice.format_report(report)[1]
    assert report["areas"]["unit"]["executed"] == 3
    assert report["apple_e2e"]["status"] == "not_scheduled"


def test_notification_retries_only_failed_channel_for_same_revision(tmp_path, monkeypatch):
    report = {"date": "2026-09-28", "status": "blocked", "source_commit": "a" * 40,
              "manifest_present": False, "admitted_specs": 0,
              "selection_error": "selection failed", "selected_specs": None, "held_specs": None,
              "job_count": 0, "job_states": {}, "job_modes": {}, "failed_case_count": 0,
              "failed_case_files": [], "failing_vitest_workspaces": [], "failed_specs": [],
              "missing_receipts": [], "run_links": []}
    calls = {"email": 0, "discord": 0}

    def email(*_args):
        calls["email"] += 1
        return {"status": "failed" if calls["email"] == 1 else "provider_accepted"}

    def discord(*_args):
        calls["discord"] += 1
        return {"status": "provider_accepted", "message_id": "discord-id"}

    monkeypatch.setattr(notice, "deliver_email", email)
    monkeypatch.setattr(notice, "deliver_discord", discord)
    assert notice.send_report(tmp_path, report)["channels"]["email"]["status"] == "failed"
    assert notice.send_report(tmp_path, report)["channels"]["email"]["status"] == "provider_accepted"
    notice.send_report(tmp_path, report)
    assert calls == {"email": 2, "discord": 1}


def test_receipt_with_wrong_source_does_not_supply_failure_counts(tmp_path, monkeypatch):
    day = date(2026, 9, 28)
    fixture_job(tmp_path, day=day, job_id="pytest", mode="pytest", source="a" * 40, state="failure", run_id=11)
    fixture_receipt(tmp_path, "pytest", "b" * 40, 11, [{"suite": "pytest", "failed_tests": ["secret"]}])
    monkeypatch.setattr(notice, "selection_diagnostic", lambda *_: "selection failed")
    report = notice.build_report(tmp_path, day)
    assert report["failed_case_count"] == 0
    assert report["missing_receipts"] == ["pytest"]


def test_email_dispatch_uses_internal_vault_backed_task_and_confirms_result(tmp_path, monkeypatch):
    report = {
        "date": "2026-09-28", "status": "blocked", "source_commit": "a" * 40,
        "job_count": 2, "job_states": {"failure": 2},
        "known_total_tests": 3, "known_passed_tests": 1,
        "known_failed_tests": 2, "known_skipped_tests": 0,
    }
    monkeypatch.setattr(notice, "configured_value", lambda _root, key: {
        "ADMIN_NOTIFY_EMAIL": "admin@example.test",
        "INTERNAL_API_SHARED_TOKEN": "test-token",
    }.get(key, ""))
    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b'{"status":"dispatched","task_id":"12345678-1234-1234-1234-123456789abc"}'

    def open_request(request, **_kwargs):
        seen["url"] = request.full_url
        seen["payload"] = json.loads(request.data)
        return Response()

    monkeypatch.setattr(notice.urllib.request, "urlopen", open_request)
    monkeypatch.setattr(notice, "email_task_status", lambda *_args: {
        "status": "provider_accepted", "task_id": "12345678-1234-1234-1234-123456789abc",
    })
    result = notice.deliver_email(tmp_path, "Daily CI blocked", "real report body", report)
    assert result["status"] == "provider_accepted"
    assert seen["url"].endswith("/internal/dispatch-test-summary-email")
    assert seen["payload"]["total"] == 3 and seen["payload"]["failed"] == 2
    assert seen["payload"]["daily_digest"]["rows"][2]["name"] == "Web E2E"
    assert "failure_groups" not in seen["payload"]


def test_rollup_separates_skips_and_flaky_execution() -> None:
    rows = [
        {"total": 5, "passed": 2, "failed": 1, "skipped": 2},
        {"total": 4, "passed": 1, "failed": 1, "skipped": 1, "flaky": 1},
    ]
    assert notice.rollup(rows) == {
        "collected": 9, "executed": 6, "passed": 3,
        "failed": 2, "skipped": 3, "flaky": 1,
    }


def test_apple_receipt_requires_exact_source_and_case_arithmetic(tmp_path) -> None:
    day = date(2026, 9, 28)
    path = tmp_path / "test-results/daily-runs/apple/2026-09-28.json"
    path.parent.mkdir(parents=True)
    payload = {"date": day.isoformat(), "source_commit": "a" * 40, "status": "passed",
               "targets": [{"platform": "ios", "counts": {"total": 4, "passed": 3, "failed": 0, "skipped": 1}}]}
    path.write_text(json.dumps(payload))
    assert notice.apple_daily_result(tmp_path, day, "b" * 40)["status"] == "invalid_receipt"
    assert notice.apple_daily_result(tmp_path, day, "a" * 40)["counts"]["executed"] == 3
    payload["targets"][0]["counts"]["total"] = 5
    path.write_text(json.dumps(payload))
    assert notice.apple_daily_result(tmp_path, day, "a" * 40)["status"] == "invalid_receipt"


def test_finalizer_waits_for_apple_or_deadline_and_counts_native_failure(tmp_path):
    day = date(2026, 9, 28)
    source = "a" * 40
    daily = tmp_path / "test-results/daily-runs"
    daily.mkdir(parents=True)
    (daily / "run.json").write_text(json.dumps({
        "created": datetime(2026, 9, 28, 3, tzinfo=timezone.utc).timestamp(),
        "run_date": day.isoformat(), "source_commit": source, "jobs": ["pytest"],
        "selected_specs": [], "held_specs": [],
    }))
    fixture_job(tmp_path, day=day, job_id="pytest", mode="pytest", source=source, state="success", run_id=11)
    fixture_receipt(tmp_path, "pytest", source, 11, [])
    early = notice.build_report(tmp_path, day, datetime(2026, 9, 28, 4, tzinfo=timezone.utc))
    assert early["status"] == "incomplete" and not early["ready"]
    apple_path = daily / "apple/2026-09-28.json"
    apple_path.parent.mkdir()
    apple_path.write_text(json.dumps({
        "date": day.isoformat(), "source_commit": source, "status": "failed",
        "targets": [{"platform": "ios", "counts": {"total": 2, "passed": 1, "failed": 1, "skipped": 0}}],
    }))
    final = notice.build_report(tmp_path, day, datetime(2026, 9, 28, 4, tzinfo=timezone.utc))
    assert final["status"] == "failed_or_held" and final["ready"]
    assert final["apple_e2e"]["counts"]["executed"] == 2
