#!/usr/bin/env python3
"""
scripts/ci/aggregate_results.py

Aggregates test results from GitHub Actions artifacts into the unified
last-run.json format used by the existing reporting infrastructure.

After aggregation:
1. POSTs to /internal/dispatch-test-summary-email (email notification)
2. POSTs to /internal/openobserve/push-test-run (observability)
3. If failures: POSTs to /v1/webhooks/incoming (triggers analysis chat)

Environment variables:
    OPENMATES_API_URL          — Base URL (e.g., https://api.dev.openmates.org)
    INTERNAL_API_SHARED_TOKEN  — Auth token for /internal/* endpoints
    ADMIN_NOTIFY_EMAIL         — Email recipient for test summary
    OPENMATES_WEBHOOK_KEY      — Webhook key for triggering analysis chat
    GIT_SHA                    — Git commit SHA
    GIT_BRANCH                 — Git branch name
    GITHUB_RUN_ID              — GitHub Actions run ID

Usage (called by GitHub Actions report job):
    python3 scripts/ci/aggregate_results.py
"""

import glob
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

MAX_ERROR_SNIPPET_LEN = 600


def main():
    artifacts_dir = os.environ.get("ARTIFACTS_DIR", ".")
    api_url = os.environ.get("OPENMATES_API_URL", "").rstrip("/")
    internal_token = os.environ.get("INTERNAL_API_SHARED_TOKEN", "")
    admin_email = os.environ.get("ADMIN_NOTIFY_EMAIL", "")
    webhook_key = os.environ.get("OPENMATES_WEBHOOK_KEY", "")
    git_sha = os.environ.get("GIT_SHA", "unknown")
    git_branch = os.environ.get("GIT_BRANCH", "dev")
    run_id = os.environ.get("GITHUB_RUN_ID", datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"))

    # --- Load all result files ---
    suites = {}

    # pytest results
    pytest_files = glob.glob(os.path.join(artifacts_dir, "pytest-results*", "pytest.json"))
    if pytest_files:
        suites["pytest_unit"] = _parse_pytest(pytest_files[0])

    # vitest results
    vitest_files = glob.glob(os.path.join(artifacts_dir, "vitest-results*", "vitest.json"))
    if vitest_files:
        suites["vitest"] = _parse_vitest(vitest_files[0])

    # Playwright results (multiple batches)
    pw_files = sorted(glob.glob(os.path.join(artifacts_dir, "playwright-results-*", "playwright-*.json")))
    if pw_files:
        suites["playwright"] = _merge_playwright(pw_files)

    # --- Compute summary ---
    total = passed = failed = skipped = 0
    for suite_data in suites.values():
        for t in suite_data.get("tests", []):
            total += 1
            s = t.get("status", "")
            if s == "passed":
                passed += 1
            elif s == "failed":
                failed += 1
            else:
                skipped += 1

    result = {
        "run_id": run_id,
        "git_sha": git_sha,
        "git_branch": git_branch,
        "duration_seconds": 0,  # Not tracked at aggregate level
        "summary": {"total": total, "passed": passed, "failed": failed, "skipped": skipped},
        "suites": suites,
        "environment": "development",
    }

    # Write aggregate result
    os.makedirs("test-results", exist_ok=True)
    with open("test-results/last-run.json", "w") as f:
        json.dump(result, f, indent=2)

    print(f"Aggregated: {total} tests ({passed} passed, {failed} failed, {skipped} skipped)")

    # --- Report to dev server ---
    if api_url and internal_token:
        _report_email(api_url, internal_token, admin_email, result)
        _report_openobserve(api_url, internal_token, result)

    # --- Trigger analysis chat on failures ---
    if failed > 0 and api_url and webhook_key:
        _trigger_analysis_chat(api_url, webhook_key, result)

    if failed > 0:
        sys.exit(1)


def _parse_pytest(path: str) -> dict:
    """Parse pytest-json-report output into our suite format."""
    try:
        with open(path) as f:
            data = json.load(f)
        tests = []
        for test in data.get("tests", []):
            tests.append({
                "name": test.get("nodeid", ""),
                "file": test.get("nodeid", "").split("::")[0],
                "status": "passed" if test.get("outcome") == "passed" else "failed",
                "duration_seconds": round(test.get("duration", 0), 2),
                "error": test.get("call", {}).get("longrepr", "")[:MAX_ERROR_SNIPPET_LEN] if test.get("outcome") != "passed" else None,
            })
        status = "passed" if all(t["status"] == "passed" for t in tests) else "failed"
        return {"status": status, "tests": tests, "duration_seconds": 0}
    except Exception as e:
        print(f"WARNING: Failed to parse pytest results from {path}: {e}", file=sys.stderr)
        return {"status": "error", "tests": [], "duration_seconds": 0}


def _parse_vitest(path: str) -> dict:
    """Parse vitest JSON reporter output into our suite format."""
    try:
        with open(path) as f:
            data = json.load(f)
        tests = []
        for test_file in data.get("testResults", []):
            for assertion in test_file.get("assertionResults", []):
                tests.append({
                    "name": " > ".join(assertion.get("ancestorTitles", []) + [assertion.get("title", "")]),
                    "file": test_file.get("name", ""),
                    "status": "passed" if assertion.get("status") == "passed" else "failed",
                    "duration_seconds": round(assertion.get("duration", 0) / 1000, 2),
                    "error": "\n".join(assertion.get("failureMessages", []))[:MAX_ERROR_SNIPPET_LEN] if assertion.get("status") != "passed" else None,
                })
        status = "passed" if all(t["status"] == "passed" for t in tests) else "failed"
        return {"status": status, "tests": tests, "duration_seconds": 0}
    except Exception as e:
        print(f"WARNING: Failed to parse vitest results from {path}: {e}", file=sys.stderr)
        return {"status": "error", "tests": [], "duration_seconds": 0}


def _merge_playwright(paths: list) -> dict:
    """Merge multiple Playwright JSON reporter outputs into one suite."""
    all_tests = []
    for path in paths:
        try:
            with open(path) as f:
                data = json.load(f)
            for suite in data.get("suites", []):
                for spec in suite.get("specs", []):
                    for test in spec.get("tests", []):
                        for result in test.get("results", []):
                            error_msg = ""
                            if result.get("status") != "passed":
                                error_msg = result.get("error", {}).get("message", "")[:MAX_ERROR_SNIPPET_LEN] if isinstance(result.get("error"), dict) else str(result.get("error", ""))[:MAX_ERROR_SNIPPET_LEN]
                            all_tests.append({
                                "name": spec.get("title", ""),
                                "file": spec.get("file", suite.get("title", "")),
                                "status": "passed" if result.get("status") in ("passed", "skipped") else "failed",
                                "duration_seconds": round(result.get("duration", 0) / 1000, 2),
                                "error": error_msg or None,
                            })
        except Exception as e:
            print(f"WARNING: Failed to parse Playwright results from {path}: {e}", file=sys.stderr)

    status = "passed" if all(t["status"] == "passed" for t in all_tests) else "failed"
    return {"status": status, "tests": all_tests, "duration_seconds": 0}


def _post_json(url: str, data: dict, headers: dict, label: str) -> bool:
    """POST JSON to a URL. Returns True on success."""
    try:
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
        print(f"  {label}: OK")
        return True
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:300] if e.fp else ""
        print(f"  {label}: HTTP {e.code} — {err_body}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"  {label}: {e}", file=sys.stderr)
        return False


def _report_email(api_url: str, token: str, admin_email: str, result: dict) -> None:
    """Dispatch test summary email via internal API."""
    if not admin_email:
        return
    payload = {
        "recipient_email": admin_email,
        "environment": result.get("environment", "development"),
        "run_id": result["run_id"],
        "git_sha": result["git_sha"],
        "git_branch": result["git_branch"],
        "total": result["summary"]["total"],
        "passed": result["summary"]["passed"],
        "failed": result["summary"]["failed"],
        "skipped": result["summary"]["skipped"],
        "duration_seconds": result["duration_seconds"],
        "suites": [],
        "failed_tests": [],
        "all_tests": [],
    }
    _post_json(
        f"{api_url}/internal/dispatch-test-summary-email",
        payload,
        {"Content-Type": "application/json", "X-Internal-Service-Token": token},
        "Email dispatch",
    )


def _report_openobserve(api_url: str, token: str, result: dict) -> None:
    """Push test run summary to OpenObserve via internal API."""
    _post_json(
        f"{api_url}/internal/openobserve/push-test-run",
        result,
        {"Content-Type": "application/json", "X-Internal-Service-Token": token},
        "OpenObserve push",
    )


def _trigger_analysis_chat(api_url: str, webhook_key: str, result: dict) -> None:
    """Trigger an analysis chat via the webhook API on test failures."""
    failed_tests = []
    for suite_name, suite_data in result.get("suites", {}).items():
        for t in suite_data.get("tests", []):
            if t.get("status") == "failed":
                failed_tests.append(f"- [{suite_name}] {t.get('file', t.get('name', '?'))}: {(t.get('error') or 'no error message')[:200]}")

    if not failed_tests:
        return

    summary = result["summary"]
    message = (
        f"Daily test run failed: {summary['failed']} of {summary['total']} tests failed.\n"
        f"Git: {result['git_sha']} on {result['git_branch']}\n"
        f"Run ID: {result['run_id']}\n\n"
        f"Failed tests:\n" + "\n".join(failed_tests[:30])
    )

    _post_json(
        f"{api_url}/v1/webhooks/incoming",
        {"message": message},
        {"Content-Type": "application/json", "Authorization": f"Bearer {webhook_key}"},
        "Webhook analysis chat",
    )


if __name__ == "__main__":
    main()
