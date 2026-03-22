#!/usr/bin/env python3
"""
scripts/ci/aggregate_results.py

Aggregates test results from GitHub Actions artifacts and reports via webhook.

After aggregation:
1. Always: POSTs run summary to /v1/webhooks/incoming (creates a chat on the server)
   - On failure: message includes failure details + link to GH Actions run
   - On success: brief "all tests passed" message
2. The webhook handler on the server takes care of email notification + OpenObserve push

Environment variables:
    OPENMATES_API_URL     — Base URL (e.g., https://api.dev.openmates.org)
    OPENMATES_WEBHOOK_KEY — Webhook key (wh-...) for triggering analysis chat
    GIT_SHA               — Git commit SHA
    GIT_BRANCH            — Git branch name
    GITHUB_RUN_ID         — GitHub Actions run ID
    GITHUB_REPOSITORY     — Repository (e.g., glowingkitty/OpenMates)
    GITHUB_SERVER_URL     — GitHub URL (https://github.com by default)

Usage (called by GitHub Actions report job):
    python3 scripts/ci/aggregate_results.py
"""

import glob
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

MAX_ERROR_SNIPPET_LEN = 600


def main():
    artifacts_dir = os.environ.get("ARTIFACTS_DIR", ".")
    api_url = os.environ.get("OPENMATES_API_URL", "").rstrip("/")
    webhook_key = os.environ.get("OPENMATES_WEBHOOK_KEY", "")
    git_sha = os.environ.get("GIT_SHA", "unknown")
    git_branch = os.environ.get("GIT_BRANCH", "dev")
    run_id = os.environ.get("GITHUB_RUN_ID", datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"))
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    server_url = os.environ.get("GITHUB_SERVER_URL", "https://github.com")

    # Build GH Actions run URL for the email/chat link
    if repo and run_id:
        run_url = f"{server_url}/{repo}/actions/runs/{run_id}"
    else:
        run_url = ""

    # --- Load all result files ---
    suites = {}

    pytest_files = glob.glob(os.path.join(artifacts_dir, "pytest-results*", "pytest.json"))
    if pytest_files:
        suites["pytest_unit"] = _parse_pytest(pytest_files[0])

    vitest_files = glob.glob(os.path.join(artifacts_dir, "vitest-results*", "vitest.json"))
    if vitest_files:
        suites["vitest"] = _parse_vitest(vitest_files[0])

    pw_files = sorted(glob.glob(os.path.join(artifacts_dir, "playwright-results-*", "playwright-*.json")))
    if pw_files:
        suites["playwright"] = _merge_playwright(pw_files)
    elif glob.glob(os.path.join(artifacts_dir, "playwright-results-*")):
        # Artifact dirs exist but no JSON files — Playwright ran but produced no output
        print("WARNING: Playwright artifact dirs found but no JSON results", file=sys.stderr)
        suites["playwright"] = {"status": "error", "tests": [], "duration_seconds": 0}

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

    print(f"Aggregated: {total} tests ({passed} passed, {failed} failed, {skipped} skipped)")
    if not suites:
        print("No test result artifacts found — skipping report")
        # Don't exit 1: no artifacts means the suites were skipped intentionally
        return

    # --- Count flaky tests ---
    flaky_count = 0
    for suite_data in suites.values():
        for t in suite_data.get("tests", []):
            if t.get("flaky"):
                flaky_count += 1

    # --- Write aggregate result ---
    os.makedirs("test-results", exist_ok=True)
    result = {
        "run_id": run_id,
        "git_sha": git_sha,
        "git_branch": git_branch,
        "duration_seconds": 0,
        "summary": {
            "total": total, "passed": passed, "failed": failed,
            "skipped": skipped, "flaky": flaky_count,
        },
        "suites": suites,
        "environment": "development",
    }
    with open("test-results/last-run.json", "w") as f:
        json.dump(result, f, indent=2)

    # --- Update flaky history ---
    _update_flaky_history(suites)

    # --- Send webhook notification ---
    if api_url and webhook_key:
        message = _build_message(result, run_url)
        _send_webhook(api_url, webhook_key, message)

    # Fail if any suite produced 0 tests (status "error") — never silently pass with no results
    for suite_name, suite_data in suites.items():
        if suite_data.get("status") == "error":
            print(f"ERROR: Suite '{suite_name}' has 0 tests — marking run as failed", file=sys.stderr)
            failed += 1

    if failed > 0:
        sys.exit(1)


def _update_flaky_history(suites: dict) -> None:
    """Track flaky test occurrences over time in flaky-history.json."""
    history_path = "test-results/flaky-history.json"
    try:
        with open(history_path) as f:
            history = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        history = {"tests": {}}

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Track all Playwright tests in this run (for total_runs count)
    pw_suite = suites.get("playwright", {})
    for t in pw_suite.get("tests", []):
        key = f"{t.get('file', '?')}::{t.get('name', '?')}"
        entry = history["tests"].setdefault(key, {
            "flaky_count": 0, "total_runs": 0,
            "last_flaky_date": None, "last_error": None,
        })
        entry["total_runs"] += 1

        if t.get("flaky"):
            entry["flaky_count"] += 1
            entry["last_flaky_date"] = today
            entry["last_error"] = (t.get("flaky_error") or "")[:200]

    try:
        with open(history_path, "w") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        print(f"WARNING: Failed to write flaky history: {e}", file=sys.stderr)


def _build_message(result: dict, run_url: str) -> str:
    """Build a concise message for the webhook chat."""
    summary = result["summary"]
    sha_short = result["git_sha"][:12] if result["git_sha"] != "unknown" else "unknown"
    branch = result["git_branch"]
    run_link = f"\nRun: {run_url}" if run_url else ""

    # Collect flaky tests across all suites
    flaky_lines = []
    for suite_name, suite_data in result["suites"].items():
        for t in suite_data.get("tests", []):
            if t.get("flaky"):
                name = t.get("file") or t.get("name") or "?"
                retries = t.get("retries", 1)
                flaky_lines.append(f"- [{suite_name}] {name} (passed after {retries} retry)")

    flaky_suffix = ""
    if flaky_lines:
        flaky_suffix = f"\n\nFlaky tests ({len(flaky_lines)}):\n" + "\n".join(flaky_lines[:10])

    if summary["failed"] == 0:
        suites_ran = list(result["suites"].keys())
        return (
            f"Daily test run passed: {summary['passed']}/{summary['total']} tests passed. "
            f"Suites: {', '.join(suites_ran)}. "
            f"Commit: {sha_short} on {branch}.{run_link}{flaky_suffix}"
        )

    # Build failure details
    failed_lines = []
    for suite_name, suite_data in result["suites"].items():
        for t in suite_data.get("tests", []):
            if t.get("status") == "failed":
                name = t.get("file") or t.get("name") or "?"
                err = (t.get("error") or "no error message")[:200]
                failed_lines.append(f"- [{suite_name}] {name}: {err}")

    return (
        f"Daily test run FAILED: {summary['failed']} of {summary['total']} tests failed. "
        f"Commit: {sha_short} on {branch}.{run_link}\n\n"
        f"Failed tests:\n" + "\n".join(failed_lines[:30]) + flaky_suffix
    )


def _send_webhook(api_url: str, webhook_key: str, message: str) -> None:
    """Send message to the OpenMates webhook endpoint."""
    url = f"{api_url}/v1/webhooks/incoming"
    try:
        body = json.dumps({"message": message}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {webhook_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_body = resp.read().decode("utf-8", errors="replace")
            print(f"  Webhook: OK — {resp_body[:100]}")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:400] if e.fp else ""
        print(f"  Webhook: HTTP {e.code} — {err_body}", file=sys.stderr)
    except Exception as e:
        print(f"  Webhook: {e}", file=sys.stderr)


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
                "error": (
                    test.get("call", {}).get("longrepr", "")[:MAX_ERROR_SNIPPET_LEN]
                    if test.get("outcome") != "passed" else None
                ),
            })
        if not tests:
            status = "error"
        else:
            status = "passed" if all(t["status"] == "passed" for t in tests) else "failed"
        return {"status": status, "tests": tests, "duration_seconds": 0}
    except Exception as e:
        print(f"WARNING: Failed to parse pytest results: {e}", file=sys.stderr)
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
                    "name": " > ".join(
                        assertion.get("ancestorTitles", []) + [assertion.get("title", "")]
                    ),
                    "file": test_file.get("name", ""),
                    "status": "passed" if assertion.get("status") == "passed" else "failed",
                    "duration_seconds": round(assertion.get("duration", 0) / 1000, 2),
                    "error": (
                        "\n".join(assertion.get("failureMessages", []))[:MAX_ERROR_SNIPPET_LEN]
                        if assertion.get("status") != "passed" else None
                    ),
                })
        if not tests:
            status = "error"
        else:
            status = "passed" if all(t["status"] == "passed" for t in tests) else "failed"
        return {"status": status, "tests": tests, "duration_seconds": 0}
    except Exception as e:
        print(f"WARNING: Failed to parse vitest results: {e}", file=sys.stderr)
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
                            if isinstance(result.get("error"), dict):
                                error_msg = result["error"].get("message", "")[:MAX_ERROR_SNIPPET_LEN]
                            else:
                                error_msg = str(result.get("error", ""))[:MAX_ERROR_SNIPPET_LEN]
                            all_tests.append({
                                "name": spec.get("title", ""),
                                "file": spec.get("file", suite.get("title", "")),
                                "status": "passed" if result.get("status") in ("passed", "skipped") else "failed",
                                "duration_seconds": round(result.get("duration", 0) / 1000, 2),
                                "error": error_msg or None,
                            })
        except Exception as e:
            print(f"WARNING: Failed to parse Playwright results from {path}: {e}", file=sys.stderr)

    # Detect flaky tests and deduplicate retries.
    # When retries > 0, Playwright produces multiple results per test.
    # A test is "flaky" if it failed on first attempt but passed on retry.
    # Keep only the last result per (file, name) — the retry outcome is authoritative.
    results_by_key = {}
    for t in all_tests:
        key = (t["file"], t["name"])
        results_by_key.setdefault(key, []).append(t)

    deduped = []
    for key, results in results_by_key.items():
        final = results[-1]  # last result is authoritative
        if len(results) > 1:
            # Multiple results = test was retried
            first_failed = results[0]["status"] == "failed"
            final_passed = final["status"] == "passed"
            final["retries"] = len(results) - 1
            final["flaky"] = first_failed and final_passed
            if final["flaky"]:
                # Preserve the original error for flaky tracking
                final["flaky_error"] = results[0].get("error")
        deduped.append(final)

    if not deduped:
        status = "error"
    else:
        status = "passed" if all(t["status"] == "passed" for t in deduped) else "failed"
    return {"status": status, "tests": deduped, "duration_seconds": 0}


if __name__ == "__main__":
    main()
