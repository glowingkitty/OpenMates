#!/usr/bin/env python3
"""
scripts/_daily_runner_helper.py

Internal helper for run-tests-daily.sh.
Handles the Python-heavy steps of the daily test run:
  - split-results: parse last-run.json, write last-passed-tests.json and last-failed-tests.json
  - dispatch-email: read last-run.json, dispatch the summary email Celery task

Not intended to be called directly by users; use run-tests-daily.sh instead.
"""

import json
import os
import sys

# Maximum error snippet length per failed test entry (characters)
MAX_ERROR_SNIPPET_LEN = 600


def _load_last_run(results_dir: str) -> dict:
    path = os.path.join(results_dir, "last-run.json")
    with open(path) as f:
        return json.load(f)


def split_results() -> None:
    """
    Parse last-run.json and write:
      - last-passed-tests.json  (tests with status == 'passed')
      - last-failed-tests.json  (tests with status == 'failed', with error snippet)
    """
    results_dir = os.environ.get("RESULTS_DIR", "test-results")
    data = _load_last_run(results_dir)

    passed_tests = []
    failed_tests = []

    for suite_name, suite_data in data.get("suites", {}).items():
        if not isinstance(suite_data, dict):
            continue
        for t in suite_data.get("tests", []):
            entry = {
                "suite": suite_name,
                "name": t.get("name", ""),
                "status": t.get("status", ""),
                "duration_seconds": t.get("duration_seconds", 0),
                "file": t.get("file", ""),
            }
            status = t.get("status", "")
            if status == "passed":
                passed_tests.append(entry)
            elif status == "failed":
                error = t.get("error", "") or ""
                entry["error"] = error[:MAX_ERROR_SNIPPET_LEN] if error else None
                failed_tests.append(entry)

    run_id = data.get("run_id", "")

    passed_path = os.path.join(results_dir, "last-passed-tests.json")
    failed_path = os.path.join(results_dir, "last-failed-tests.json")

    with open(passed_path, "w") as f:
        json.dump({"run_id": run_id, "tests": passed_tests}, f, indent=2)

    with open(failed_path, "w") as f:
        json.dump({"run_id": run_id, "tests": failed_tests}, f, indent=2)

    print(
        f"[daily-runner] Saved {len(passed_tests)} passed, "
        f"{len(failed_tests)} failed tests to test-results/."
    )


def dispatch_email() -> None:
    """
    Read last-run.json and dispatch the Celery test_run_summary email task.

    Uses the CELERY_BROKER_URL env var (default: redis://cache:6379/0) to
    connect to the same Dragonfly/Redis broker the Docker workers use.
    The task is queued on the 'email' queue, picked up by task-worker.
    """
    results_dir = os.environ.get("RESULTS_DIR", "test-results")
    admin_email = os.environ.get("SERVER_OWNER_EMAIL", "")
    broker_url = os.environ.get("CELERY_BROKER_URL", "redis://cache:6379/0")

    if not admin_email:
        print("[daily-runner] ERROR: SERVER_OWNER_EMAIL not set — cannot dispatch email.", file=sys.stderr)
        sys.exit(1)

    data = _load_last_run(results_dir)
    summary = data.get("summary", {})
    total = summary.get("total", 0)
    passed = summary.get("passed", 0)
    failed = summary.get("failed", 0)
    skipped = summary.get("skipped", 0)
    not_started = summary.get("not_started", 0)

    # Build suite summaries for the email template
    suites = []
    for suite_name, suite_data in data.get("suites", {}).items():
        if not isinstance(suite_data, dict):
            continue
        tests = suite_data.get("tests", [])
        suite_passed = sum(1 for t in tests if t.get("status") == "passed")
        suite_failed = sum(1 for t in tests if t.get("status") == "failed")
        suite_not_started = sum(1 for t in tests if t.get("status") == "not_started")
        suites.append({
            "name": suite_name,
            "total": len(tests),
            "passed": suite_passed,
            "failed": suite_failed,
            "not_started": suite_not_started,
            "status": suite_data.get("status", "unknown"),
        })

    # Build failed test entries for the email (one row per failing test)
    failed_tests = []
    for suite_name, suite_data in data.get("suites", {}).items():
        if not isinstance(suite_data, dict):
            continue
        for t in suite_data.get("tests", []):
            if t.get("status") == "failed":
                error = t.get("error", "") or ""
                failed_tests.append({
                    "suite": suite_name,
                    "name": t.get("name", t.get("file", "")),
                    "error": error[:MAX_ERROR_SNIPPET_LEN] if error else None,
                })

    # Dispatch the Celery task
    try:
        from celery import Celery  # available in the project venv
        celery_app = Celery(broker=broker_url)
        celery_app.send_task(
            name="app.tasks.email_tasks.test_run_summary_email_task.send_test_run_summary",
            args=[
                admin_email,
                data.get("run_id", ""),
                data.get("git_sha", ""),
                data.get("git_branch", ""),
                int(data.get("duration_seconds", 0)),
                total,
                passed,
                failed,
                skipped,
                not_started,
                suites,
                failed_tests,
            ],
            queue="email",
        )
        print(
            f"[daily-runner] Email task dispatched successfully "
            f"(failed={failed}, total={total}, recipient={admin_email})"
        )
    except Exception as e:
        print(f"[daily-runner] ERROR dispatching Celery email task: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <split-results|dispatch-email>", file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]
    if command == "split-results":
        split_results()
    elif command == "dispatch-email":
        dispatch_email()
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)
