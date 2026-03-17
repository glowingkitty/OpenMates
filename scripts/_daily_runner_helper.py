#!/usr/bin/env python3
"""
scripts/_daily_runner_helper.py

Internal helper for run-tests-daily.sh.
Handles the Python-heavy steps of the daily test run:
  - split-results: parse last-run.json, write last-passed-tests.json and last-failed-tests.json
  - dispatch-start-email: notify admin that the test run has started (before tests run)
  - dispatch-email: read last-run.json, dispatch the summary email via internal API
  - dispatch-openobserve-test-run: push normalized run summary to OpenObserve via internal API

Not intended to be called directly by users; use run-tests-daily.sh instead.
"""

import json
import os
import sys
import urllib.error
import urllib.request

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

    # Remove files first to avoid PermissionError when a previous run
    # created them as a different user (e.g. root via cron, then superdev manually).
    for path in (passed_path, failed_path):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass

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


def _build_test_run_payload(results_dir: str, environment: str) -> dict:
    """
    Build the normalized daily test-run payload consumed by internal API bridges.

    Includes dev-run suites from last-run.json and optionally merges
    last-run-prod-smoke.json as a separate playwright_prod_smoke suite.
    """
    data = _load_last_run(results_dir)
    summary = data.get("summary", {})
    total = summary.get("total", 0)
    passed = summary.get("passed", 0)
    failed = summary.get("failed", 0)
    skipped = summary.get("skipped", 0)
    not_started = summary.get("not_started", 0)

    # Load prod smoke test results (if available) and merge as an extra suite.
    prod_smoke_path = os.path.join(results_dir, "last-run-prod-smoke.json")
    prod_smoke_suite = None
    if os.path.isfile(prod_smoke_path):
        try:
            with open(prod_smoke_path) as f:
                prod_smoke_data = json.load(f)
            prod_smoke_suite = prod_smoke_data.get("suites", {}).get("playwright")
            if prod_smoke_suite:
                for test_entry in prod_smoke_suite.get("tests", []):
                    total += 1
                    status = test_entry.get("status", "")
                    if status == "passed":
                        passed += 1
                    elif status == "failed":
                        failed += 1
                    elif status == "not_started":
                        not_started += 1
                    else:
                        skipped += 1
                print(
                    f"[daily-runner] Loaded prod smoke test results from {prod_smoke_path}"
                )
        except Exception as e:
            print(
                f"[daily-runner] WARNING: could not load prod smoke results: {e}",
                file=sys.stderr,
            )

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

    if prod_smoke_suite:
        ps_tests = prod_smoke_suite.get("tests", [])
        suites.append({
            "name": "playwright_prod_smoke",
            "total": len(ps_tests),
            "passed": sum(1 for t in ps_tests if t.get("status") == "passed"),
            "failed": sum(1 for t in ps_tests if t.get("status") == "failed"),
            "not_started": sum(1 for t in ps_tests if t.get("status") == "not_started"),
            "status": prod_smoke_suite.get("status", "unknown"),
        })

    failed_tests = []
    for suite_name, suite_data in data.get("suites", {}).items():
        if not isinstance(suite_data, dict):
            continue
        for test_entry in suite_data.get("tests", []):
            if test_entry.get("status") == "failed":
                error = test_entry.get("error", "") or ""
                failed_tests.append({
                    "suite": suite_name,
                    "name": test_entry.get("name", test_entry.get("file", "")),
                    "error": error[:MAX_ERROR_SNIPPET_LEN] if error else None,
                })

    if prod_smoke_suite:
        for test_entry in prod_smoke_suite.get("tests", []):
            if test_entry.get("status") == "failed":
                error = test_entry.get("error", "") or ""
                failed_tests.append({
                    "suite": "playwright_prod_smoke",
                    "name": test_entry.get("name", test_entry.get("file", "")),
                    "error": error[:MAX_ERROR_SNIPPET_LEN] if error else None,
                })

    # Build all_tests list — every individual test with suite, name, status, duration
    all_tests = []
    for suite_name, suite_data in data.get("suites", {}).items():
        if not isinstance(suite_data, dict):
            continue
        for test_entry in suite_data.get("tests", []):
            all_tests.append({
                "suite": suite_name,
                "name": test_entry.get("name", test_entry.get("file", "")),
                "status": test_entry.get("status", "unknown"),
                "duration_seconds": test_entry.get("duration_seconds", 0),
            })

    if prod_smoke_suite:
        for test_entry in prod_smoke_suite.get("tests", []):
            all_tests.append({
                "suite": "playwright_prod_smoke",
                "name": test_entry.get("name", test_entry.get("file", "")),
                "status": test_entry.get("status", "unknown"),
                "duration_seconds": test_entry.get("duration_seconds", 0),
            })

    return {
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
        "all_tests": all_tests,
    }


def dispatch_email() -> None:
    """
    Read last-run.json (and optionally last-run-prod-smoke.json) and dispatch
    the test run summary email via POST /internal/dispatch-test-summary-email.

    This script runs on the host (via crontab), so we use an HTTP call to the
    API container instead of importing celery directly. The API container
    dispatches the Celery email task on our behalf.

    Required env vars (read from .env if not in environment):
        ADMIN_NOTIFY_EMAIL          — recipient for the summary email
        INTERNAL_API_SHARED_TOKEN   — auth token for /internal/* endpoints
        DAILY_RUN_ENVIRONMENT       — "development" or "production" (set by run-tests-daily.sh)

    Optional: if test-results/last-run-prod-smoke.json exists, its playwright
    suite is merged into the email as a "playwright_prod_smoke" suite.
    """
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

    normalized_payload = _build_test_run_payload(results_dir, environment)

    # Include opencode analysis chat URL if one was produced during this run
    # (set by run-tests-daily.sh after calling start-opencode-analysis).
    opencode_chat_url = os.environ.get("OPENCODE_CHAT_URL", "").strip() or None

    # Dispatch via internal API endpoint.
    # When running on the host (via crontab), use localhost:8000 since
    # port 8000 is forwarded from the API container.
    api_url = os.environ.get(
        "INTERNAL_API_URL",
        "http://localhost:8000",
    ).rstrip("/") + "/internal/dispatch-test-summary-email"
    payload = {
        "recipient_email": admin_email,
        **normalized_payload,
        "opencode_chat_url": opencode_chat_url,
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
                f"(failed={normalized_payload['failed']}, total={normalized_payload['total']}, recipient={admin_email})"
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


def dispatch_openobserve_test_run() -> None:
    """
    Push the daily test-run result to OpenObserve via internal API bridge.

    This is intentionally non-fatal in run-tests-daily.sh so observability
    ingestion issues do not block test execution or email notifications.
    """
    results_dir = os.environ.get("RESULTS_DIR", "test-results")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    dot_env = _read_env_file(project_root)

    internal_token = os.environ.get("INTERNAL_API_SHARED_TOKEN") or dot_env.get("INTERNAL_API_SHARED_TOKEN", "")
    environment = os.environ.get("DAILY_RUN_ENVIRONMENT", "development")

    if not internal_token:
        print(
            "[daily-runner] ERROR: INTERNAL_API_SHARED_TOKEN not set — cannot push test run to OpenObserve.",
            file=sys.stderr,
        )
        sys.exit(1)

    payload = _build_test_run_payload(results_dir, environment)

    api_url = os.environ.get(
        "INTERNAL_API_URL",
        "http://localhost:8000",
    ).rstrip("/") + "/internal/openobserve/push-test-run"

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
            resp.read()
            print(
                "[daily-runner] OpenObserve test-runs push succeeded "
                f"(run_id={payload.get('run_id', '')}, failed={payload.get('failed', 0)}, total={payload.get('total', 0)})"
            )
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        print(
            f"[daily-runner] ERROR pushing test run to OpenObserve via internal API: "
            f"HTTP {e.code} — {err_body[:500]}",
            file=sys.stderr,
        )
        sys.exit(1)
    except Exception as e:
        print(f"[daily-runner] ERROR pushing test run to OpenObserve via internal API: {e}", file=sys.stderr)
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


def start_opencode_analysis() -> None:
    """
    Start an opencode analysis session for test failures.

    Reads the failed tests from last-failed-tests.json (written by split-results),
    loads the prompt template from scripts/prompts/test-failure-analysis.md,
    substitutes placeholders, then runs:

        opencode run --share --model anthropic/claude-sonnet-4-6 \
                     --title "test-failures YYYY-MM-DD" "<prompt>"

    The --share flag produces a shareable session URL. We capture it from stdout
    by looking for the "OPENCODE_URL:" prefix that this function emits.

    Output convention (for run-tests-daily.sh to capture):
        Prints "OPENCODE_URL:<url>" to stdout when a share URL is found.

    Only called when failed_count > 0. Non-fatal — does not abort the test run.
    """
    import subprocess
    from datetime import datetime, timezone

    results_dir = os.environ.get("RESULTS_DIR", "test-results")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)

    # Load failed tests
    failed_path = os.path.join(results_dir, "last-failed-tests.json")
    if not os.path.isfile(failed_path):
        print("[daily-runner] WARNING: last-failed-tests.json not found — skipping opencode analysis.", file=sys.stderr)
        return

    with open(failed_path) as f:
        failed_data = json.load(f)

    failed_tests = failed_data.get("tests", [])
    run_id = failed_data.get("run_id", "unknown")

    if not failed_tests:
        print("[daily-runner] No failed tests in last-failed-tests.json — skipping opencode analysis.", file=sys.stderr)
        return

    # Load last-run.json for git info
    last_run_path = os.path.join(results_dir, "last-run.json")
    git_sha = "unknown"
    git_branch = "unknown"
    total_count = 0
    if os.path.isfile(last_run_path):
        with open(last_run_path) as f:
            last_run = json.load(f)
        git_sha = last_run.get("git_sha", "unknown")
        git_branch = last_run.get("git_branch", "unknown")
        total_count = last_run.get("summary", {}).get("total", 0)

    failed_count = len(failed_tests)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Load prompt template
    prompt_template_path = os.path.join(script_dir, "prompts", "test-failure-analysis.md")
    if not os.path.isfile(prompt_template_path):
        print(
            f"[daily-runner] WARNING: prompt template not found at {prompt_template_path} — skipping opencode analysis.",
            file=sys.stderr,
        )
        return

    with open(prompt_template_path) as f:
        prompt_template = f.read()

    # Build a compact JSON representation of failures (cap at 20 to keep prompt size reasonable)
    MAX_FAILURES_IN_PROMPT = 20
    truncated = failed_tests[:MAX_FAILURES_IN_PROMPT]
    failed_tests_json = json.dumps(truncated, indent=2)

    # Substitute placeholders
    prompt = (
        prompt_template
        .replace("{{DATE}}", date_str)
        .replace("{{RUN_ID}}", run_id)
        .replace("{{GIT_SHA}}", git_sha)
        .replace("{{GIT_BRANCH}}", git_branch)
        .replace("{{FAILED_COUNT}}", str(failed_count))
        .replace("{{TOTAL_COUNT}}", str(total_count))
        .replace("{{FAILED_TESTS_JSON}}", failed_tests_json)
    )

    # Build opencode command
    session_title = f"test-failures {date_str}"
    cmd = [
        "opencode", "run",
        "--share",
        "--model", "anthropic/claude-sonnet-4-6",
        "--title", session_title,
        "--dir", project_root,
        prompt,
    ]

    print(f"[daily-runner] Running opencode analysis for {failed_count} failed test(s)...")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 minute max for the analysis session
        )

        combined_output = result.stdout + result.stderr

        # Extract share URL — opencode prints something like:
        #   Shared: https://opencode.ai/s/<session-id>
        # We look for that pattern and emit a parseable line.
        share_url = None
        for line in combined_output.splitlines():
            line_stripped = line.strip()
            # Match "Shared: https://..." or just a bare opencode.ai/s/ URL
            if "opencode.ai/s/" in line_stripped:
                # Extract the URL token
                for token in line_stripped.split():
                    if "opencode.ai/s/" in token:
                        share_url = token.lstrip("Shared:").strip()
                        break
            if share_url:
                break

        if share_url:
            # Emit parseable line for run-tests-daily.sh to capture
            print(f"OPENCODE_URL:{share_url}")
            print(f"[daily-runner] opencode analysis session shared: {share_url}")
        else:
            print(
                "[daily-runner] WARNING: opencode ran but no share URL found in output. "
                "Check that --share flag is supported and OPENCODE_* env vars are set.",
                file=sys.stderr,
            )
            # Still print the session output for the log
            if combined_output.strip():
                print(f"[daily-runner] opencode output (truncated):\n{combined_output[:2000]}", file=sys.stderr)

        if result.returncode != 0:
            print(
                f"[daily-runner] WARNING: opencode exited with code {result.returncode} (non-fatal)",
                file=sys.stderr,
            )

    except subprocess.TimeoutExpired:
        print("[daily-runner] WARNING: opencode analysis timed out after 10 minutes (non-fatal)", file=sys.stderr)
    except FileNotFoundError:
        print("[daily-runner] WARNING: opencode binary not found — skipping analysis.", file=sys.stderr)
    except Exception as e:
        print(f"[daily-runner] WARNING: opencode analysis failed: {e} (non-fatal)", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            f"Usage: {sys.argv[0]} <split-results|dispatch-start-email|dispatch-email|dispatch-openobserve-test-run|start-opencode-analysis>",
            file=sys.stderr,
        )
        sys.exit(1)

    command = sys.argv[1]
    if command == "split-results":
        split_results()
    elif command == "dispatch-start-email":
        dispatch_start_email()
    elif command == "dispatch-email":
        dispatch_email()
    elif command == "dispatch-openobserve-test-run":
        dispatch_openobserve_test_run()
    elif command == "start-opencode-analysis":
        start_opencode_analysis()
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)
