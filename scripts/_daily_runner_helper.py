#!/usr/bin/env python3
"""
scripts/_daily_runner_helper.py

Internal helper for run-tests-daily.sh.
Handles the Python-heavy steps of the daily test run:
  - split-results: parse last-run.json, write last-passed-tests.json and last-failed-tests.json
  - dispatch-start-email: notify admin that the test run has started (before tests run)
  - dispatch-email: read last-run.json, dispatch the summary email via internal API

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


def _read_env_file(project_root: str) -> dict:
    """
    Read key=value pairs from .env file at project root.
    Returns a dict of env vars. Does not modify os.environ.
    """
    env_path = os.path.join(project_root, ".env")
    env_vars = {}
    if not os.path.isfile(env_path):
        return env_vars
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                env_vars[key.strip()] = value.strip()
    return env_vars


def dispatch_email() -> None:
    """
    Read last-run.json and dispatch the test run summary email via the
    internal API endpoint POST /internal/dispatch-test-summary-email.

    This script runs inside the admin-sidecar container (which does not have
    celery installed), so we use an HTTP call to the API container instead of
    importing celery directly. The API container dispatches the Celery email
    task on our behalf.

    Required env vars (read from .env if not in environment):
        ADMIN_NOTIFY_EMAIL          — recipient for the summary email
        INTERNAL_API_SHARED_TOKEN   — auth token for /internal/* endpoints
        DAILY_RUN_ENVIRONMENT       — "development" or "production" (set by run-tests-daily.sh)
    """
    import urllib.request
    import urllib.error

    results_dir = os.environ.get("RESULTS_DIR", "test-results")

    # Determine project root (parent of scripts/)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)

    # Read .env for values not already in the environment
    dot_env = _read_env_file(project_root)

    admin_email = os.environ.get("ADMIN_NOTIFY_EMAIL") or dot_env.get("ADMIN_NOTIFY_EMAIL", "")
    internal_token = os.environ.get("INTERNAL_API_SHARED_TOKEN") or dot_env.get("INTERNAL_API_SHARED_TOKEN", "")
    environment = os.environ.get("DAILY_RUN_ENVIRONMENT", "development")

    if not admin_email:
        print("[daily-runner] ERROR: ADMIN_NOTIFY_EMAIL not set — cannot dispatch email.", file=sys.stderr)
        sys.exit(1)

    if not internal_token:
        print("[daily-runner] ERROR: INTERNAL_API_SHARED_TOKEN not set — cannot dispatch email.", file=sys.stderr)
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

    # Dispatch via internal API endpoint.
    # When running on the host (via docker+chroot from admin-sidecar), use
    # localhost:8000 since port 8000 is forwarded from the API container.
    api_url = os.environ.get(
        "INTERNAL_API_URL",
        "http://localhost:8000",
    ).rstrip("/") + "/internal/dispatch-test-summary-email"
    payload = {
        "recipient_email": admin_email,
        "environment": environment,
        "run_id": data.get("run_id", ""),
        "git_sha": data.get("git_sha", ""),
        "git_branch": data.get("git_branch", ""),
        "duration_seconds": int(data.get("duration_seconds", 0)),
        "total": total,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "not_started": not_started,
        "suites": suites,
        "failed_tests": failed_tests,
    }

    try:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            api_url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Internal-Service-Token": internal_token,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()  # consume response body
            print(
                f"[daily-runner] Email task dispatched successfully via internal API "
                f"(failed={failed}, total={total}, recipient={admin_email})"
            )
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        print(
            f"[daily-runner] ERROR dispatching email via internal API: "
            f"HTTP {e.code} — {err_body[:500]}",
            file=sys.stderr,
        )
        sys.exit(1)
    except Exception as e:
        print(f"[daily-runner] ERROR dispatching email via internal API: {e}", file=sys.stderr)
        sys.exit(1)


def dispatch_start_email() -> None:
    """
    Notify the admin that a test run has just started by dispatching the
    test_run_started email via POST /internal/dispatch-test-start-email.

    Called by run-tests-daily.sh immediately after the commit-activity gate
    passes and the test run begins — before run-tests.sh is invoked.

    Required env vars (read from .env if not in environment):
        ADMIN_NOTIFY_EMAIL          — recipient for the notification email
        INTERNAL_API_SHARED_TOKEN   — auth token for /internal/* endpoints
        DAILY_RUN_ENVIRONMENT       — "development" or "production" (set by run-tests-daily.sh)
    """
    import subprocess
    import urllib.request
    import urllib.error
    from datetime import datetime, timezone

    # Determine project root (parent of scripts/)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)

    # Read .env for values not already in the environment
    dot_env = _read_env_file(project_root)

    admin_email = os.environ.get("ADMIN_NOTIFY_EMAIL") or dot_env.get("ADMIN_NOTIFY_EMAIL", "")
    internal_token = os.environ.get("INTERNAL_API_SHARED_TOKEN") or dot_env.get("INTERNAL_API_SHARED_TOKEN", "")
    environment = os.environ.get("DAILY_RUN_ENVIRONMENT", "development")

    if not admin_email:
        print("[daily-runner] WARNING: ADMIN_NOTIFY_EMAIL not set — skipping start email.", file=sys.stderr)
        return

    if not internal_token:
        print("[daily-runner] WARNING: INTERNAL_API_SHARED_TOKEN not set — skipping start email.", file=sys.stderr)
        return

    # Collect git info (best-effort — don't fail the run if git isn't available)
    git_sha = "unknown"
    git_branch = "unknown"
    try:
        git_sha = subprocess.check_output(
            ["git", "-C", project_root, "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        git_branch = subprocess.check_output(
            ["git", "-C", project_root, "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception as e:
        print(f"[daily-runner] WARNING: could not read git info for start email: {e}", file=sys.stderr)

    started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    api_url = os.environ.get(
        "INTERNAL_API_URL",
        "http://localhost:8000",
    ).rstrip("/") + "/internal/dispatch-test-start-email"

    payload = {
        "recipient_email": admin_email,
        "environment": environment,
        "trigger_type": "Scheduled (daily)",
        "git_sha": git_sha,
        "git_branch": git_branch,
        "started_at": started_at,
    }

    try:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            api_url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Internal-Service-Token": internal_token,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()  # consume response body
            print(
                f"[daily-runner] Test run start email dispatched "
                f"(recipient={admin_email}, git={git_sha}@{git_branch})"
            )
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        # Non-fatal: a missing start email must not abort the test run
        print(
            f"[daily-runner] WARNING: could not dispatch start email: "
            f"HTTP {e.code} — {err_body[:300]}",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"[daily-runner] WARNING: could not dispatch start email: {e}", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <split-results|dispatch-start-email|dispatch-email>", file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]
    if command == "split-results":
        split_results()
    elif command == "dispatch-start-email":
        dispatch_start_email()
    elif command == "dispatch-email":
        dispatch_email()
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)
