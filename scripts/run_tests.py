#!/usr/bin/env python3
"""
scripts/run_tests.py

Unified test orchestrator for OpenMates.

Replaces: run-tests.sh, run-tests-daily.sh, run-tests-worker.sh,
          ci/trigger_parallel_specs.sh

Runs pytest and vitest locally (fast), dispatches Playwright E2E specs
to GitHub Actions via playwright-spec.yml in batches of N (default 20),
polls for completion, aggregates results, and sends notifications.

Usage:
    python3 scripts/run_tests.py                           # full suite
    python3 scripts/run_tests.py --spec chat-flow.spec.ts  # single spec
    python3 scripts/run_tests.py --only-failed             # rerun failures
    python3 scripts/run_tests.py --suite pytest             # just pytest
    python3 scripts/run_tests.py --suite vitest             # just vitest
    python3 scripts/run_tests.py --suite playwright         # just E2E
    python3 scripts/run_tests.py --daily                   # cron mode
    python3 scripts/run_tests.py --daily --force            # skip commit check
    python3 scripts/run_tests.py --max-concurrent 10       # override batch size
    python3 scripts/run_tests.py --no-fail-fast            # run all batches

Architecture: docs/architecture/test-orchestration.md
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = PROJECT_ROOT / "test-results"
SPEC_DIR = PROJECT_ROOT / "frontend" / "apps" / "web_app" / "tests"
LOCKFILE = Path("/tmp/openmates-daily-tests.lock")
WORKFLOW_NAME = "playwright-spec.yml"
GH_REPO = "glowingkitty/OpenMates"
GH_BRANCH = "dev"
MAX_ACCOUNTS = 20
POLL_INTERVAL = 15  # seconds between status checks
RUN_TIMEOUT = 1800  # 30 min max per batch
VITEST_TIMEOUT = 300  # seconds — vitest must complete in 5 min or be killed
MAX_ERROR_SNIPPET = 600
BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SpecResult:
    """Result of a single test (unit test or E2E spec)."""
    name: str
    status: str  # passed | failed | not_started | skipped | timeout | dispatch_error | result_unknown
    duration_seconds: float = 0.0
    error: Optional[str] = None
    file: Optional[str] = None
    run_id: Optional[int] = None
    account: Optional[int] = None
    retries: int = 0
    flaky: bool = False


@dataclass
class SuiteResult:
    """Result of a test suite (e.g., vitest, pytest, playwright)."""
    status: str  # passed | failed | error | skipped
    tests: list[dict] = field(default_factory=list)
    duration_seconds: float = 0.0
    reason: Optional[str] = None


@dataclass
class RunResult:
    """Aggregated results across all suites."""
    run_id: str
    git_sha: str
    git_branch: str
    environment: str
    duration_seconds: float
    summary: dict  # {total, passed, failed, skipped, not_started}
    suites: dict  # {suite_name: SuiteResult as dict}
    flags: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _print_flaky_report() -> None:
    """Print top flaky tests from flaky-history.json."""
    history_path = RESULTS_DIR / "flaky-history.json"
    if not history_path.is_file():
        print("No flaky history found (test-results/flaky-history.json)")
        return

    with open(history_path) as f:
        history = json.load(f)

    tests = history.get("tests", {})
    if not tests:
        print("No test history recorded yet.")
        return

    # Sort by flaky_count descending, then by flakiness rate
    ranked = []
    for key, entry in tests.items():
        total = entry.get("total_runs", 0)
        flaky = entry.get("flaky_count", 0)
        if total > 0 and flaky > 0:
            rate = flaky / total
            ranked.append((key, flaky, total, rate, entry.get("last_flaky_date", "?")))

    if not ranked:
        print("No flaky tests detected in history.")
        return

    ranked.sort(key=lambda x: (-x[3], -x[1]))  # rate desc, then count desc

    print(f"\nTop flaky tests ({len(ranked)} total):\n")
    print(f"{'Rate':>6}  {'Flaky/Total':>12}  {'Last Flaky':<12}  Test")
    print(f"{'─' * 6}  {'─' * 12}  {'─' * 12}  {'─' * 40}")
    for key, flaky, total, rate, last_date in ranked[:15]:
        print(f"{rate:5.0%}   {flaky:>4}/{total:<6}  {last_date:<12}  {key}")
    print()


def _log(msg: str, level: str = "INFO") -> None:
    """Print a timestamped log line."""
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    prefix = {"INFO": "  ", "WARN": "⚠ ", "ERROR": "✗ ", "OK": "✓ "}.get(level, "  ")
    print(f"[{ts}] {prefix}{msg}", flush=True)


def _git_info() -> tuple[str, str]:
    """Return (short_sha, branch)."""
    sha = "unknown"
    branch = "unknown"
    try:
        sha = subprocess.check_output(
            ["git", "-C", str(PROJECT_ROOT), "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
        branch = subprocess.check_output(
            ["git", "-C", str(PROJECT_ROOT), "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
    except Exception:
        pass
    return sha, branch


def _read_env_file() -> dict[str, str]:
    """Read .env file from project root."""
    env_path = PROJECT_ROOT / ".env"
    env_vars: dict[str, str] = {}
    if not env_path.is_file():
        return env_vars
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                # Strip surrounding quotes
                value = value.strip().strip("'\"")
                env_vars[key.strip()] = value
    return env_vars


def _get_env(key: str, dot_env: Optional[dict] = None, default: str = "") -> str:
    """Get env var from environment or .env fallback."""
    val = os.environ.get(key, "")
    if not val and dot_env:
        val = dot_env.get(key, "")
    return val or default


def _safe_write_json(path: Path, data: dict) -> None:
    """Write JSON, removing existing file first to avoid permission issues."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# GitHubActionsClient
# ---------------------------------------------------------------------------

class GitHubActionsClient:
    """Wraps the `gh` CLI for workflow dispatch and status polling."""

    def __init__(self) -> None:
        self._check_gh()

    def _check_gh(self) -> None:
        """Verify gh CLI is available and authenticated."""
        if not shutil.which("gh"):
            _log("gh CLI not found. Install: https://cli.github.com/", "ERROR")
            sys.exit(1)
        rc = subprocess.run(
            ["gh", "auth", "status"], capture_output=True, text=True,
        )
        if rc.returncode != 0:
            _log("gh not authenticated. Run: gh auth login", "ERROR")
            sys.exit(1)

    def dispatch_spec(self, spec: str, account: int, use_mocks: bool = True) -> Optional[int]:
        """
        Dispatch a single spec workflow run.
        Returns the run ID or None on failure.
        """
        # Record the latest run ID before dispatch so we can find the new one
        pre_ids = self._recent_run_ids(limit=5)

        # playwright-spec.yml: lightweight 1-job workflow per spec
        rc = subprocess.run(
            ["gh", "workflow", "run", WORKFLOW_NAME,
             "--repo", GH_REPO,
             "--ref", GH_BRANCH,
             "-f", f"spec={spec}",
             "-f", f"account={account}",
             "-f", f"use_mocks={'true' if use_mocks else 'false'}"],
            capture_output=True, text=True,
        )
        if rc.returncode != 0:
            _log(f"Dispatch failed for {spec}: {rc.stderr.strip()}", "ERROR")
            return None

        # Wait for GitHub to register the run, then find its ID
        for attempt in range(6):
            time.sleep(2)
            new_ids = self._recent_run_ids(limit=10)
            fresh = [rid for rid in new_ids if rid not in pre_ids]
            if fresh:
                return fresh[0]  # Most recent new run

        _log(f"Could not capture run ID for {spec} after dispatch", "WARN")
        return None

    def _recent_run_ids(self, limit: int = 5) -> list[int]:
        """Get the most recent run IDs for the workflow."""
        rc = subprocess.run(
            ["gh", "run", "list",
             "--repo", GH_REPO,
             "--workflow", WORKFLOW_NAME,
             "--limit", str(limit),
             "--json", "databaseId"],
            capture_output=True, text=True,
        )
        if rc.returncode != 0:
            return []
        try:
            return [r["databaseId"] for r in json.loads(rc.stdout)]
        except (json.JSONDecodeError, KeyError):
            return []

    def poll_run(self, run_id: int) -> dict:
        """Get status/conclusion for a single run."""
        rc = subprocess.run(
            ["gh", "run", "view", str(run_id),
             "--repo", GH_REPO,
             "--json", "status,conclusion,name,updatedAt"],
            capture_output=True, text=True,
        )
        if rc.returncode != 0:
            return {"status": "unknown", "conclusion": None}
        try:
            return json.loads(rc.stdout)
        except json.JSONDecodeError:
            return {"status": "unknown", "conclusion": None}

    def wait_for_runs(
        self, run_ids: list[int], fail_fast: bool = True,
        poll_interval: int = POLL_INTERVAL, timeout: int = RUN_TIMEOUT,
    ) -> dict[int, dict]:
        """
        Poll until all runs complete. Returns {run_id: {status, conclusion}}.

        With fail_fast=True (batch-level): waits for the entire batch to finish,
        then reports. Does NOT cancel mid-batch — just prevents next batch from
        starting if any failures occurred.
        """
        start = time.time()
        results: dict[int, dict] = {}

        while time.time() - start < timeout:
            all_done = True
            for rid in run_ids:
                if rid in results and results[rid].get("status") == "completed":
                    continue
                data = self.poll_run(rid)
                results[rid] = data
                if data.get("status") != "completed":
                    all_done = False

            if all_done:
                return results

            # Progress update
            completed = sum(1 for r in results.values() if r.get("status") == "completed")
            passed = sum(1 for r in results.values() if r.get("conclusion") == "success")
            failed = sum(1 for r in results.values() if r.get("conclusion") == "failure")
            print(
                f"\r  Polling: {completed}/{len(run_ids)} done "
                f"({passed} passed, {failed} failed)...",
                end="", flush=True,
            )
            time.sleep(poll_interval)

        # Timeout — cancel remaining runs
        print()
        _log(f"Batch timed out after {timeout}s", "WARN")
        for rid in run_ids:
            if results.get(rid, {}).get("status") != "completed":
                self.cancel_run(rid)
                results[rid] = {"status": "completed", "conclusion": "timed_out"}
        return results

    def cancel_run(self, run_id: int) -> None:
        """Cancel a workflow run."""
        subprocess.run(
            ["gh", "run", "cancel", str(run_id), "--repo", GH_REPO],
            capture_output=True,
        )

    def get_failed_job_error(self, run_id: int) -> Optional[str]:
        """Extract error details from a failed run's job logs via `gh run view --log-failed`.
        Returns a trimmed error snippet or None."""
        rc = subprocess.run(
            ["gh", "run", "view", str(run_id),
             "--repo", GH_REPO,
             "--log-failed"],
            capture_output=True, text=True,
            timeout=30,
        )
        if rc.returncode != 0 or not rc.stdout.strip():
            return None

        lines = rc.stdout.strip().splitlines()

        # Look for Playwright-style error lines (assertions, timeouts, etc.)
        error_lines: list[str] = []
        capture = False
        for line in lines:
            # Strip the GitHub Actions job/step prefix (e.g. "run-playwright\tRun tests\t")
            text = line.split("\t")[-1] if "\t" in line else line

            # Start capturing at error indicators
            if any(kw in text for kw in [
                "Error:", "FAILED", "expect(", "Timeout", "AssertionError",
                "Error: locator", "waiting for", "error TS",
                "Cannot find module", "ERR_MODULE_NOT_FOUND",
            ]):
                capture = True
            if capture:
                error_lines.append(text.strip())
                if len(error_lines) >= 15:
                    break

        if error_lines:
            return "\n".join(error_lines)[:MAX_ERROR_SNIPPET]

        # Fallback: return last N non-empty lines (usually contains the failure reason)
        tail = [ln.split("\t")[-1].strip() if "\t" in ln else ln.strip()
                for ln in lines[-20:] if ln.strip()]
        if tail:
            return "\n".join(tail[-10:])[:MAX_ERROR_SNIPPET]

        return None

    def download_artifact(self, run_id: int, artifact_name: str, dest_dir: Path) -> Optional[Path]:
        """Download a run's artifact. Returns path to downloaded dir or None."""
        dest = dest_dir / str(run_id)
        dest.mkdir(parents=True, exist_ok=True)
        rc = subprocess.run(
            ["gh", "run", "download", str(run_id),
             "--repo", GH_REPO,
             "--name", artifact_name,
             "--dir", str(dest)],
            capture_output=True, text=True,
        )
        if rc.returncode != 0:
            return None
        return dest


# ---------------------------------------------------------------------------
# BatchRunner
# ---------------------------------------------------------------------------

class BatchRunner:
    """Dispatches Playwright specs to GitHub Actions in batches."""

    def __init__(
        self,
        client: GitHubActionsClient,
        specs: list[str],
        batch_size: int = 20,
        fail_fast: bool = True,
        use_mocks: bool = True,
    ) -> None:
        self.client = client
        self.specs = specs
        self.batch_size = batch_size
        self.fail_fast = fail_fast
        self.use_mocks = use_mocks

    def run_all_batches(self) -> SuiteResult:
        """Execute all specs in batches. Returns aggregated SuiteResult."""
        if not self.specs:
            return SuiteResult(status="skipped", reason="no specs to run")

        all_results: list[SpecResult] = []
        total_batches = (len(self.specs) + self.batch_size - 1) // self.batch_size
        suite_start = time.time()

        for batch_idx in range(total_batches):
            start = batch_idx * self.batch_size
            end = min(start + self.batch_size, len(self.specs))
            batch_specs = self.specs[start:end]

            print()
            _log(f"Batch {batch_idx + 1}/{total_batches}: {len(batch_specs)} specs")

            batch_results = self._run_batch(batch_specs, batch_idx)
            all_results.extend(batch_results)

            # Check for failures (batch-level fail-fast)
            batch_failures = [r for r in batch_results if r.status == "failed"]
            if batch_failures and self.fail_fast and batch_idx < total_batches - 1:
                remaining_specs = self.specs[end:]
                _log(
                    f"{len(batch_failures)} failure(s) in batch {batch_idx + 1} — "
                    f"skipping {len(remaining_specs)} remaining specs (fail-fast)",
                    "WARN",
                )
                for spec in remaining_specs:
                    all_results.append(SpecResult(
                        name=spec, file=spec, status="not_started",
                        error=f"Skipped: fail-fast after batch {batch_idx + 1}",
                    ))
                break

        duration = time.time() - suite_start
        tests = [self._spec_result_to_dict(r) for r in all_results]
        has_failures = any(r.status == "failed" for r in all_results)

        return SuiteResult(
            status="failed" if has_failures else "passed",
            tests=tests,
            duration_seconds=round(duration, 1),
        )

    def _run_batch(self, specs: list[str], batch_idx: int) -> list[SpecResult]:
        """Dispatch and wait for a single batch of specs."""
        # Dispatch all specs in this batch
        dispatched: list[tuple[str, int, int]] = []  # (spec, account, run_id)
        dispatch_errors: list[SpecResult] = []

        for i, spec in enumerate(specs):
            account = (batch_idx * self.batch_size + i) % MAX_ACCOUNTS + 1
            _log(f"  Dispatching {spec} (account {account})")

            run_id = self.client.dispatch_spec(spec, account, self.use_mocks)
            if run_id is None:
                # Retry once
                time.sleep(5)
                run_id = self.client.dispatch_spec(spec, account, self.use_mocks)

            if run_id is None:
                dispatch_errors.append(SpecResult(
                    name=spec, file=spec, status="failed",
                    error="Failed to dispatch workflow after retry",
                ))
            else:
                dispatched.append((spec, account, run_id))

            # Small delay between dispatches to avoid rate limiting
            if (i + 1) % 5 == 0:
                time.sleep(1)

        if not dispatched:
            return dispatch_errors

        # Wait for all dispatched runs
        run_ids = [rid for _, _, rid in dispatched]
        _log(f"  Waiting for {len(run_ids)} runs...")
        statuses = self.client.wait_for_runs(run_ids, self.fail_fast)
        print()  # Clear the polling line

        # Collect results
        results: list[SpecResult] = list(dispatch_errors)
        artifact_dir = Path(tempfile.mkdtemp(prefix="pw-artifacts-"))

        for spec, account, rid in dispatched:
            status_data = statuses.get(rid, {})
            conclusion = status_data.get("conclusion", "unknown")

            if conclusion == "success":
                status = "passed"
                error = None
            elif conclusion == "timed_out":
                status = "timeout"
                error = "Run timed out"
            elif conclusion == "cancelled":
                status = "not_started"
                error = "Run was cancelled"
            else:
                status = "failed"
                error = f"GitHub Actions conclusion: {conclusion}"

            # Try to download artifact for error details + screenshots
            if status == "failed":
                # playwright-spec.yml artifact name: playwright-{spec}
                art_path = self.client.download_artifact(rid, f"playwright-{spec}", artifact_dir)
                if art_path:
                    pw_json = art_path / "playwright.json"
                    if pw_json.is_file():
                        error = self._extract_error_from_playwright_json(pw_json) or error
                    # Persist screenshots/traces for failed tests
                    self._persist_failure_artifacts(spec, art_path)

                # Fallback: fetch failed job logs if artifact didn't yield a real error
                if error == f"GitHub Actions conclusion: {conclusion}":
                    log_error = self.client.get_failed_job_error(rid)
                    if log_error:
                        error = log_error

            icon = {"passed": "✓", "failed": "✗", "timeout": "⏱", "not_started": "⊘"}.get(status, "?")
            _log(f"  {icon} {spec} (run {rid})", "OK" if status == "passed" else "ERROR")

            results.append(SpecResult(
                name=spec, file=spec, status=status,
                error=error, run_id=rid, account=account,
            ))

        # Cleanup artifact dir
        shutil.rmtree(artifact_dir, ignore_errors=True)
        return results

    def _extract_error_from_playwright_json(self, pw_json: Path) -> Optional[str]:
        """Extract the first error message from a Playwright JSON report."""
        try:
            with open(pw_json) as f:
                data = json.load(f)
            for suite in data.get("suites", []):
                for spec in suite.get("specs", []):
                    for test in spec.get("tests", []):
                        for result in test.get("results", []):
                            if result.get("status") != "passed":
                                # Check for error message
                                err = result.get("error", {})
                                if isinstance(err, dict):
                                    msg = err.get("message", "")
                                elif isinstance(err, str):
                                    msg = err
                                else:
                                    msg = ""
                                if msg:
                                    return msg[:MAX_ERROR_SNIPPET]
            # Check top-level errors
            for err in data.get("errors", []):
                msg = err.get("message", "")
                if msg:
                    return msg[:MAX_ERROR_SNIPPET]
        except Exception:
            pass
        return None

    @staticmethod
    def _persist_failure_artifacts(spec: str, art_path: Path) -> None:
        """Copy screenshots and traces from a failed test's artifacts to
        test-results/screenshots/{spec-name}/ for post-run debugging."""
        spec_name = spec.replace(".spec.ts", "")
        dest = RESULTS_DIR / "screenshots" / spec_name
        dest.mkdir(parents=True, exist_ok=True)
        copied = 0
        for root, _dirs, files in os.walk(art_path):
            for fname in files:
                if fname.endswith((".png", ".webp", ".zip", ".trace")):
                    src = Path(root) / fname
                    shutil.copy2(src, dest / fname)
                    copied += 1
        if copied:
            _log(f"    Saved {copied} artifact(s) to test-results/screenshots/{spec_name}/")

    @staticmethod
    def _spec_result_to_dict(r: SpecResult) -> dict:
        """Convert SpecResult to the dict format used in last-run.json."""
        d: dict = {
            "name": r.name,
            "status": r.status,
            "duration_seconds": r.duration_seconds,
        }
        if r.error:
            d["error"] = r.error
        if r.file:
            d["file"] = r.file
        if r.run_id:
            d["run_id"] = r.run_id
        if r.retries > 0:
            d["retries"] = r.retries
        if r.flaky:
            d["flaky"] = True
        return d


# ---------------------------------------------------------------------------
# ResultAggregator
# ---------------------------------------------------------------------------

class ResultAggregator:
    """Merges results from all suites into the standard last-run.json format."""

    @staticmethod
    def build_run_result(
        suites: dict[str, SuiteResult],
        run_id: str,
        git_sha: str,
        git_branch: str,
        environment: str,
        duration: float,
        flags: dict,
    ) -> RunResult:
        total = passed = failed = skipped = not_started = 0
        suites_dict = {}

        for name, suite in suites.items():
            suite_dict = {
                "status": suite.status,
                "tests": suite.tests,
                "duration_seconds": suite.duration_seconds,
            }
            if suite.reason:
                suite_dict["reason"] = suite.reason
            suites_dict[name] = suite_dict

            for t in suite.tests:
                total += 1
                st = t.get("status", "")
                if st == "passed":
                    passed += 1
                elif st == "failed":
                    failed += 1
                elif st == "not_started":
                    not_started += 1
                else:
                    skipped += 1

        return RunResult(
            run_id=run_id,
            git_sha=git_sha,
            git_branch=git_branch,
            environment=environment,
            duration_seconds=round(duration, 1),
            summary={"total": total, "passed": passed, "failed": failed,
                      "skipped": skipped, "not_started": not_started},
            suites=suites_dict,
            flags=flags,
        )

    @staticmethod
    def save(result: RunResult) -> None:
        """Save results to test-results/."""
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)

        data = {
            "run_id": result.run_id,
            "git_sha": result.git_sha,
            "git_branch": result.git_branch,
            "flags": result.flags,
            "duration_seconds": result.duration_seconds,
            "summary": result.summary,
            "suites": result.suites,
            "environment": result.environment,
        }

        # Write timestamped run file
        ts = result.run_id.replace(":", "").replace("-", "")
        run_file = RESULTS_DIR / f"run-{ts}.json"
        _safe_write_json(run_file, data)

        # Write last-run.json (always overwritten)
        _safe_write_json(RESULTS_DIR / "last-run.json", data)

        _log(f"Results saved to {run_file.name} and last-run.json")

    @staticmethod
    def load_failed_specs() -> list[str]:
        """Load previously failed spec files from last-run.json."""
        last_run = RESULTS_DIR / "last-run.json"
        if not last_run.is_file():
            _log("No last-run.json found — cannot use --only-failed", "ERROR")
            sys.exit(1)

        with open(last_run) as f:
            data = json.load(f)

        failed = []
        for suite_data in data.get("suites", {}).values():
            if not isinstance(suite_data, dict):
                continue
            for t in suite_data.get("tests", []):
                if t.get("status") == "failed":
                    f_name = t.get("file", t.get("name", ""))
                    if f_name:
                        failed.append(f_name)
        return failed


# ---------------------------------------------------------------------------
# NotificationService
# ---------------------------------------------------------------------------

class NotificationService:
    """Sends email notifications and pushes to OpenObserve."""

    def __init__(self) -> None:
        self.dot_env = _read_env_file()
        self.admin_email = _get_env("ADMIN_NOTIFY_EMAIL", self.dot_env)
        self.internal_token = _get_env("INTERNAL_API_SHARED_TOKEN", self.dot_env)
        self.brevo_api_key = _get_env("BREVO_API_KEY", self.dot_env)
        self.internal_api_url = _get_env(
            "INTERNAL_API_URL", self.dot_env, "http://localhost:8000"
        ).rstrip("/")

    def send_start_email(self, git_sha: str, git_branch: str, environment: str) -> None:
        """Notify admin that a test run has started."""
        if not self.admin_email:
            _log("ADMIN_NOTIFY_EMAIL not set — skipping start email", "WARN")
            return

        started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        subject = f"[OpenMates] Test run started ({environment})"
        body = (
            f"Test run started at {started_at}\n"
            f"Environment: {environment}\n"
            f"Git: {git_sha}@{git_branch}\n"
            f"Trigger: {'Scheduled (daily)' if os.environ.get('DAILY_RUN_ENVIRONMENT') else 'Manual'}"
        )

        if self.brevo_api_key:
            self._send_via_brevo(subject, body)
        elif self.internal_token:
            self._send_via_internal_api("dispatch-test-start-email", {
                "recipient_email": self.admin_email,
                "environment": environment,
                "trigger_type": "Scheduled (daily)",
                "git_sha": git_sha,
                "git_branch": git_branch,
                "started_at": started_at,
            })
        else:
            _log("No email credentials available — skipping start email", "WARN")

    def send_summary_email(self, result: RunResult) -> None:
        """Send test summary email after run completes."""
        if not self.admin_email:
            _log("ADMIN_NOTIFY_EMAIL not set — skipping summary email", "WARN")
            return

        s = result.summary
        status = "All tests passed" if s["failed"] == 0 else f"{s['failed']} of {s['total']} tests failed"
        subject = f"[OpenMates] {status} ({result.environment})"

        # Build HTML email body
        html = self._build_summary_html(result)
        text = self._build_summary_text(result)

        if self.brevo_api_key:
            self._send_via_brevo(subject, text, html)
        elif self.internal_token:
            # Fall back to internal API
            payload = self._build_internal_api_payload(result)
            self._send_via_internal_api("dispatch-test-summary-email", payload)
        else:
            _log("No email credentials available — skipping summary email", "WARN")

    def push_to_openobserve(self, result: RunResult) -> None:
        """Push test run summary to OpenObserve via internal API."""
        if not self.internal_token:
            _log("INTERNAL_API_SHARED_TOKEN not set — skipping OpenObserve push", "WARN")
            return

        payload = self._build_openobserve_payload(result)
        url = f"{self.internal_api_url}/internal/openobserve/push-test-run"

        try:
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=body, headers={
                "Content-Type": "application/json",
                "X-Internal-Service-Token": self.internal_token,
            }, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp.read()
            _log("OpenObserve push succeeded")
        except Exception as e:
            _log(f"OpenObserve push failed: {e} (non-fatal)", "WARN")

    def split_results(self) -> None:
        """Split last-run.json into passed/failed JSON files (reuses _daily_runner_helper)."""
        helper = PROJECT_ROOT / "scripts" / "_daily_runner_helper.py"
        if helper.is_file():
            subprocess.run(
                [sys.executable, str(helper), "split-results"],
                env={**os.environ, "RESULTS_DIR": str(RESULTS_DIR)},
            )

    # --- Private methods ---

    def _send_via_brevo(self, subject: str, text: str, html: Optional[str] = None) -> None:
        """Send email directly via Brevo API."""
        payload = {
            "sender": {"name": "OpenMates", "email": "noreply@openmates.org"},
            "to": [{"email": self.admin_email}],
            "subject": subject,
            "textContent": text,
            "headers": {
                "Precedence": "bulk",
                "Auto-Submitted": "auto-generated",
            },
        }
        if html:
            payload["htmlContent"] = html

        try:
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(BREVO_API_URL, data=body, headers={
                "accept": "application/json",
                "api-key": self.brevo_api_key,
                "content-type": "application/json",
            }, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp.read()
            _log(f"Email sent via Brevo to {self.admin_email}")
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
            _log(f"Brevo email failed: HTTP {e.code} — {err_body[:300]}", "ERROR")
        except Exception as e:
            _log(f"Brevo email failed: {e}", "ERROR")

    def _send_via_internal_api(self, endpoint: str, payload: dict) -> None:
        """Send via internal API as fallback."""
        url = f"{self.internal_api_url}/internal/{endpoint}"
        try:
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=body, headers={
                "Content-Type": "application/json",
                "X-Internal-Service-Token": self.internal_token,
            }, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp.read()
            _log(f"Email dispatched via internal API ({endpoint})")
        except Exception as e:
            _log(f"Internal API email dispatch failed: {e}", "WARN")

    def _build_summary_html(self, result: RunResult) -> str:
        """Build a simple HTML email for test results."""
        s = result.summary
        status_color = "#22c55e" if s["failed"] == 0 else "#ef4444"
        status_text = "ALL PASSED" if s["failed"] == 0 else f"{s['failed']} FAILED"

        # Collect failed tests
        failed_rows = ""
        for suite_name, suite_data in result.suites.items():
            for t in suite_data.get("tests", []):
                if t.get("status") == "failed":
                    error = (t.get("error") or "")[:300].replace("<", "&lt;")
                    name = t.get("file", t.get("name", "?"))
                    failed_rows += f"<tr><td style='padding:4px 8px'>{suite_name}</td><td style='padding:4px 8px'>{name}</td><td style='padding:4px 8px;font-size:12px;color:#888'>{error}</td></tr>"

        dur_min = int(result.duration_seconds // 60)
        dur_sec = int(result.duration_seconds % 60)

        html = f"""<html><body style="font-family:monospace;background:#1a1a2e;color:#e0e0e0;padding:20px">
<h2 style="color:{status_color}">{status_text}</h2>
<table style="border-collapse:collapse;margin:12px 0">
<tr><td style="padding:4px 12px 4px 0;color:#888">Total</td><td><b>{s['total']}</b></td></tr>
<tr><td style="padding:4px 12px 4px 0;color:#22c55e">Passed</td><td><b>{s['passed']}</b></td></tr>
<tr><td style="padding:4px 12px 4px 0;color:#ef4444">Failed</td><td><b>{s['failed']}</b></td></tr>
<tr><td style="padding:4px 12px 4px 0;color:#888">Skipped</td><td>{s['skipped']}</td></tr>
<tr><td style="padding:4px 12px 4px 0;color:#888">Not started</td><td>{s.get('not_started', 0)}</td></tr>
<tr><td style="padding:4px 12px 4px 0;color:#888">Duration</td><td>{dur_min}m {dur_sec}s</td></tr>
<tr><td style="padding:4px 12px 4px 0;color:#888">Git</td><td>{result.git_sha}@{result.git_branch}</td></tr>
<tr><td style="padding:4px 12px 4px 0;color:#888">Environment</td><td>{result.environment}</td></tr>
</table>"""

        if failed_rows:
            html += f"""<h3 style="color:#ef4444;margin-top:20px">Failed Tests</h3>
<table style="border-collapse:collapse;width:100%;font-size:13px">
<tr style="color:#888"><th style="text-align:left;padding:4px 8px">Suite</th><th style="text-align:left;padding:4px 8px">Test</th><th style="text-align:left;padding:4px 8px">Error</th></tr>
{failed_rows}
</table>"""

        html += "</body></html>"
        return html

    def _build_summary_text(self, result: RunResult) -> str:
        """Build plain-text email for test results."""
        s = result.summary
        dur_min = int(result.duration_seconds // 60)
        dur_sec = int(result.duration_seconds % 60)

        lines = [
            f"Test Run Summary ({result.environment})",
            f"{'=' * 40}",
            f"Total: {s['total']}  Passed: {s['passed']}  Failed: {s['failed']}  "
            f"Skipped: {s['skipped']}  Not started: {s.get('not_started', 0)}",
            f"Duration: {dur_min}m {dur_sec}s",
            f"Git: {result.git_sha}@{result.git_branch}",
            "",
        ]

        if s["failed"] > 0:
            lines.append("Failed Tests:")
            lines.append("-" * 40)
            for suite_name, suite_data in result.suites.items():
                for t in suite_data.get("tests", []):
                    if t.get("status") == "failed":
                        name = t.get("file", t.get("name", "?"))
                        error = (t.get("error") or "")[:200]
                        lines.append(f"  [{suite_name}] {name}")
                        if error:
                            lines.append(f"    {error}")
            lines.append("")

        return "\n".join(lines)

    def _build_internal_api_payload(self, result: RunResult) -> dict:
        """Build payload for /internal/dispatch-test-summary-email."""
        payload = self._build_openobserve_payload(result)
        payload["recipient_email"] = self.admin_email
        return payload

    def _build_openobserve_payload(self, result: RunResult) -> dict:
        """Build the normalized payload for OpenObserve."""
        s = result.summary
        suites_list = []
        failed_tests = []
        all_tests = []

        for suite_name, suite_data in result.suites.items():
            tests = suite_data.get("tests", [])
            suite_passed = sum(1 for t in tests if t.get("status") == "passed")
            suite_failed = sum(1 for t in tests if t.get("status") == "failed")
            suite_not_started = sum(1 for t in tests if t.get("status") == "not_started")
            suites_list.append({
                "name": suite_name,
                "total": len(tests),
                "passed": suite_passed,
                "failed": suite_failed,
                "not_started": suite_not_started,
                "status": suite_data.get("status", "unknown"),
            })
            for t in tests:
                all_tests.append({
                    "suite": suite_name,
                    "name": t.get("name", t.get("file", "")),
                    "status": t.get("status", "unknown"),
                    "duration_seconds": t.get("duration_seconds", 0),
                })
                if t.get("status") == "failed":
                    error = (t.get("error") or "")[:MAX_ERROR_SNIPPET]
                    failed_tests.append({
                        "suite": suite_name,
                        "name": t.get("name", t.get("file", "")),
                        "error": error or None,
                    })

        return {
            "environment": result.environment,
            "run_id": result.run_id,
            "git_sha": result.git_sha,
            "git_branch": result.git_branch,
            "duration_seconds": int(result.duration_seconds),
            "total": s["total"],
            "passed": s["passed"],
            "failed": s["failed"],
            "skipped": s["skipped"],
            "not_started": s.get("not_started", 0),
            "suites": suites_list,
            "failed_tests": failed_tests,
            "all_tests": all_tests,
        }


# ---------------------------------------------------------------------------
# Local suite runners
# ---------------------------------------------------------------------------

def run_vitest() -> SuiteResult:
    """Run vitest unit tests locally."""
    _log("Running vitest...")
    suite_start = time.time()

    # Find vitest directories
    ui_dir = PROJECT_ROOT / "frontend" / "packages" / "ui"
    vitest_runs: list[tuple[Path, str]] = []

    if (ui_dir / "vitest.simple.config.ts").is_file():
        vitest_runs.append((ui_dir, "--config vitest.simple.config.ts"))

    # Auto-discover additional vitest dirs
    for pkg_json_path in sorted((PROJECT_ROOT / "frontend").glob("**/package.json")):
        if "node_modules" in str(pkg_json_path):
            continue
        pkg_dir = pkg_json_path.parent
        if pkg_dir == ui_dir:
            continue
        try:
            with open(pkg_json_path) as f:
                pkg = json.load(f)
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            if "vitest" not in deps:
                continue
            # Check for test files
            test_files = list(pkg_dir.glob("src/**/*.test.ts"))
            if not test_files:
                continue
            config_flag = ""
            if (pkg_dir / "vitest.config.ts").is_file():
                config_flag = "--config vitest.config.ts"
            vitest_runs.append((pkg_dir, config_flag))
        except (json.JSONDecodeError, OSError):
            continue

    if not vitest_runs:
        return SuiteResult(status="skipped", reason="no vitest dirs found")

    all_tests: list[dict] = []
    overall_status = "passed"

    for vdir, config_flag in vitest_runs:
        rel = vdir.relative_to(PROJECT_ROOT)
        _log(f"  vitest in {rel}")

        cmd = f"npx vitest run {config_flag} --reporter=json".split()
        try:
            rc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(vdir), timeout=VITEST_TIMEOUT)
        except subprocess.TimeoutExpired:
            _log(f"  vitest timed out after {VITEST_TIMEOUT}s in {rel}", "WARN")
            overall_status = "failed"
            all_tests.append({
                "name": f"{rel}/vitest-timeout",
                "status": "failed",
                "duration_seconds": VITEST_TIMEOUT,
                "error": f"vitest timed out after {VITEST_TIMEOUT}s — likely a deadlock in crypto/jsdom tests",
            })
            continue

        # Parse JSON from output (may have non-JSON prefix)
        raw = rc.stdout
        json_start = raw.find("{")
        json_end = raw.rfind("}")

        if json_start >= 0 and json_end > json_start:
            try:
                data = json.loads(raw[json_start:json_end + 1])
                for tf in data.get("testResults", []):
                    for ar in tf.get("assertionResults", []):
                        name = ar.get("fullName", ar.get("title", "unknown"))
                        status = "passed" if ar.get("status") == "passed" else "failed"
                        test_dur = ar.get("duration", 0) / 1000.0
                        entry: dict = {
                            "name": name,
                            "status": status,
                            "duration_seconds": round(test_dur, 3),
                        }
                        if status == "failed":
                            overall_status = "failed"
                            msgs = ar.get("failureMessages", [])
                            if msgs:
                                entry["error"] = msgs[0][:MAX_ERROR_SNIPPET]
                        all_tests.append(entry)
            except json.JSONDecodeError:
                pass

        if not all_tests and rc.returncode != 0:
            overall_status = "failed"
            all_tests.append({
                "name": f"{rel}/vitest-run",
                "status": "failed",
                "duration_seconds": 0,
                "error": (rc.stderr or rc.stdout)[:MAX_ERROR_SNIPPET] or f"vitest exited with code {rc.returncode}",
            })

    duration = time.time() - suite_start
    _log(f"  vitest: {sum(1 for t in all_tests if t['status'] == 'passed')}/{len(all_tests)} passed ({duration:.1f}s)")

    return SuiteResult(
        status=overall_status,
        tests=all_tests,
        duration_seconds=round(duration, 1),
    )


def run_pytest(include_integration: bool = False) -> SuiteResult:
    """Run pytest unit tests locally."""
    _log("Running pytest...")
    suite_start = time.time()

    # Find pytest binary
    venv_python = PROJECT_ROOT / "backend" / ".venv" / "bin" / "python3"
    if not venv_python.is_file():
        venv_python = Path("/OpenMates/.venv/bin/python3")
    if not venv_python.is_file():
        return SuiteResult(status="error", reason="Python venv not found")

    marker_expr = "not benchmark"
    if not include_integration:
        marker_expr = "not integration and not benchmark"

    # Check if pytest-json-report is available
    json_report = Path(tempfile.mktemp(suffix=".json"))
    check_plugin = subprocess.run(
        [str(venv_python), "-c", "import pytest_jsonreport"],
        capture_output=True, text=True,
    )
    has_json_report = check_plugin.returncode == 0

    tests_dir = PROJECT_ROOT / "backend" / "tests"
    cmd = [
        str(venv_python), "-m", "pytest",
        str(tests_dir),
        "-m", marker_expr,
        "-v", "--tb=short", "--color=no",
        "--ignore=" + str(tests_dir / "fixtures"),
        "--ignore=" + str(tests_dir / "test_encryption_service.py"),
        "--ignore=" + str(tests_dir / "test_integration_encryption.py"),
    ]
    # Ignore model comparison tests that have broken imports (missing tiktoken)
    for p in tests_dir.glob("test_model_comparison_*.py"):
        cmd.append("--ignore=" + str(p))
    if has_json_report:
        cmd += [f"--json-report-file={json_report}", "--json-report"]

    rc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT))

    all_tests: list[dict] = []
    overall_status = "passed"

    # Try parsing JSON report (if pytest-json-report was available)
    if has_json_report and json_report.is_file():
        try:
            with open(json_report) as f:
                data = json.load(f)
            for t in data.get("tests", []):
                name = t.get("nodeid", "unknown")
                outcome = t.get("outcome", "")
                duration = t.get("duration", 0)
                entry: dict = {
                    "name": name,
                    "status": "passed" if outcome == "passed" else "failed" if outcome == "failed" else "skipped",
                    "duration_seconds": round(duration, 3),
                }
                if outcome == "failed":
                    overall_status = "failed"
                    call = t.get("call", {})
                    longrepr = call.get("longrepr", "")
                    if longrepr:
                        entry["error"] = str(longrepr)[:MAX_ERROR_SNIPPET]
                all_tests.append(entry)
        except (json.JSONDecodeError, OSError):
            pass
        finally:
            json_report.unlink(missing_ok=True)

    # Fallback: parse verbose pytest output (test::name PASSED/FAILED lines)
    if not all_tests:
        for line in rc.stdout.splitlines():
            # Match lines like: backend/tests/test_foo.py::test_bar PASSED
            m = re.match(r"^(\S+::\S+)\s+(PASSED|FAILED|SKIPPED|ERROR)", line)
            if m:
                name = m.group(1)
                result_str = m.group(2)
                status = "passed" if result_str == "PASSED" else "failed" if result_str in ("FAILED", "ERROR") else "skipped"
                entry = {"name": name, "status": status, "duration_seconds": 0}
                if status == "failed":
                    overall_status = "failed"
                all_tests.append(entry)

        # If still no tests parsed, create a single entry from exit code
        if not all_tests:
            if rc.returncode != 0:
                overall_status = "failed"
                all_tests.append({
                    "name": "pytest-run",
                    "status": "failed",
                    "duration_seconds": 0,
                    "error": (rc.stdout + "\n" + rc.stderr)[:MAX_ERROR_SNIPPET] or f"pytest exited with code {rc.returncode}",
                })
            else:
                all_tests.append({
                    "name": "pytest-unit-suite",
                    "status": "passed",
                    "duration_seconds": 0,
                })

    duration = time.time() - suite_start
    passed_count = sum(1 for t in all_tests if t["status"] == "passed")
    _log(f"  pytest: {passed_count}/{len(all_tests)} passed ({duration:.1f}s)")

    return SuiteResult(
        status=overall_status,
        tests=all_tests,
        duration_seconds=round(duration, 1),
    )


# ---------------------------------------------------------------------------
# TestOrchestrator
# ---------------------------------------------------------------------------

class TestOrchestrator:
    """Main orchestrator — coordinates all test suites."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.suite = args.suite
        self.spec = args.spec
        self.only_failed = args.only_failed
        self.daily = args.daily
        self.force = args.force
        self.environment = args.environment
        self.max_concurrent = args.max_concurrent
        self.fail_fast = not args.no_fail_fast
        self.use_mocks = not args.no_mocks
        self.dry_run = args.dry_run

        self.git_sha, self.git_branch = _git_info()
        self.run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.notification = NotificationService()

    def run(self) -> int:
        """Execute the test run. Returns exit code (0=pass, 1=fail)."""
        print()
        print("=" * 60)
        print("  OpenMates Test Orchestrator")
        print("=" * 60)
        _log(f"Suite: {self.suite} | Environment: {self.environment}")
        _log(f"Git: {self.git_sha}@{self.git_branch}")
        _log(f"Run ID: {self.run_id}")
        if self.spec:
            _log(f"Single spec: {self.spec}")
        if self.only_failed:
            _log("Mode: --only-failed (rerunning previous failures)")
        print()

        # Daily mode: commit gate + lockfile
        if self.daily:
            if not self._daily_gate():
                return 0

        # Send start notification
        if self.daily:
            self.notification.send_start_email(self.git_sha, self.git_branch, self.environment)

        start_time = time.time()
        suites: dict[str, SuiteResult] = {}

        # Clear previous failure screenshots before starting a new run
        screenshots_dir = RESULTS_DIR / "screenshots"
        if screenshots_dir.is_dir():
            shutil.rmtree(screenshots_dir, ignore_errors=True)
            _log("Cleared previous failure screenshots")

        # Run local suites first (fast)
        if self.suite in ("all", "vitest"):
            suites["vitest"] = run_vitest() if not self.dry_run else SuiteResult(status="skipped", reason="dry run")

        if self.suite in ("all", "pytest"):
            include_integration = self.environment != "production"
            suites["pytest_unit"] = run_pytest(include_integration) if not self.dry_run else SuiteResult(status="skipped", reason="dry run")

        # Run Playwright via GitHub Actions
        if self.suite in ("all", "playwright"):
            suites["playwright"] = self._run_playwright()

        # Aggregate results
        duration = time.time() - start_time
        flags = {
            "suite": self.suite,
            "only_failed": self.only_failed,
            "fail_fast": self.fail_fast,
            "use_mocks": self.use_mocks,
        }

        result = ResultAggregator.build_run_result(
            suites=suites,
            run_id=self.run_id,
            git_sha=self.git_sha,
            git_branch=self.git_branch,
            environment=self.environment,
            duration=duration,
            flags=flags,
        )

        # Save results
        if not self.dry_run:
            ResultAggregator.save(result)

        # Print summary
        self._print_summary(result)

        # Daily mode: post-run tasks
        if self.daily and not self.dry_run:
            self._daily_post_run(result)

        return 1 if result.summary["failed"] > 0 else 0

    def _run_playwright(self) -> SuiteResult:
        """Run Playwright specs via GitHub Actions."""
        specs = self._discover_specs()
        if not specs:
            return SuiteResult(status="skipped", reason="no specs to run")

        _log(f"Playwright: {len(specs)} spec(s) via GitHub Actions (batch size: {self.max_concurrent})")

        if self.dry_run:
            _log("Dry run — would dispatch these specs:")
            for s in specs:
                print(f"    {s}")
            return SuiteResult(status="skipped", reason="dry run")

        client = GitHubActionsClient()
        runner = BatchRunner(
            client=client,
            specs=specs,
            batch_size=self.max_concurrent,
            fail_fast=self.fail_fast,
            use_mocks=self.use_mocks,
        )
        return runner.run_all_batches()

    def _discover_specs(self) -> list[str]:
        """Find which specs to run."""
        if self.spec:
            return [self.spec]

        if self.only_failed:
            failed = ResultAggregator.load_failed_specs()
            # Filter to only .spec.ts files
            specs = [f for f in failed if f.endswith(".spec.ts")]
            if specs:
                _log(f"Found {len(specs)} previously failed spec(s)")
            return specs

        # All specs
        spec_files = sorted(SPEC_DIR.glob("*.spec.ts"))
        return [f.name for f in spec_files]

    def _daily_gate(self) -> bool:
        """Check if daily run should proceed. Returns False to skip."""
        # Env gate
        if _get_env("E2E_DAILY_RUN_ENABLED", self.notification.dot_env) != "true":
            _log("E2E_DAILY_RUN_ENABLED is not set — skipping test run")
            _log("Set E2E_DAILY_RUN_ENABLED=true on the dev server to enable tests")
            return False

        # Commit-activity gate
        if not self.force:
            try:
                commits = subprocess.check_output(
                    ["git", "-C", str(PROJECT_ROOT), "log", "--oneline", "--since=24 hours ago"],
                    stderr=subprocess.DEVNULL, text=True,
                ).strip()
                count = len(commits.splitlines()) if commits else 0
            except Exception:
                count = 0

            if count == 0:
                _log("No git commits in the last 24 hours — skipping test run")
                _log("Use --force to run regardless")
                return False
            _log(f"Found {count} commit(s) in last 24 hours — proceeding")

        return True

    def _daily_post_run(self, result: RunResult) -> None:
        """Post-run tasks for daily mode: split results, archive, notify."""
        # Split results
        self.notification.split_results()

        # Push to OpenObserve
        _log("Pushing to OpenObserve...")
        self.notification.push_to_openobserve(result)

        # Archive daily result
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        archive = RESULTS_DIR / f"daily-run-{today}.json"
        last_run = RESULTS_DIR / "last-run.json"
        if last_run.is_file():
            shutil.copy2(str(last_run), str(archive))
            _log(f"Archived to {archive.name}")

        # Prune old archives (keep last 30)
        archives = sorted(RESULTS_DIR.glob("daily-run-*.json"), reverse=True)
        for old in archives[30:]:
            old.unlink(missing_ok=True)

        # Start claude analysis on failures (reuse helper)
        if result.summary["failed"] > 0:
            helper = PROJECT_ROOT / "scripts" / "_daily_runner_helper.py"
            if helper.is_file():
                _log("Starting claude analysis for failures...")
                subprocess.run(
                    [sys.executable, str(helper), "start-claude-analysis"],
                    env={**os.environ, "RESULTS_DIR": str(RESULTS_DIR)},
                )

        # Send summary email
        _log("Sending summary email...")
        self.notification.send_summary_email(result)

    def _print_summary(self, result: RunResult) -> None:
        """Print a formatted summary."""
        s = result.summary
        dur_min = int(result.duration_seconds // 60)
        dur_sec = int(result.duration_seconds % 60)

        print()
        print("=" * 60)
        status_icon = "✓" if s["failed"] == 0 else "✗"
        print(f"  {status_icon} Summary")
        print("=" * 60)
        print(f"  Total: {s['total']}  Passed: {s['passed']}  Failed: {s['failed']}  "
              f"Skipped: {s['skipped']}  Not started: {s.get('not_started', 0)}")
        print(f"  Duration: {dur_min}m {dur_sec}s")
        print(f"  Git: {result.git_sha}@{result.git_branch}")

        if s["failed"] > 0:
            print()
            print("  Failed tests:")
            for suite_name, suite_data in result.suites.items():
                for t in suite_data.get("tests", []):
                    if t.get("status") == "failed":
                        name = t.get("file", t.get("name", "?"))
                        error = (t.get("error") or "")[:120]
                        print(f"    [{suite_name}] {name}: {error}")

        print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="OpenMates unified test orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--suite", choices=["all", "vitest", "pytest", "playwright"], default="all",
                        help="Suite to run (default: all)")
    parser.add_argument("--spec", type=str, default=None,
                        help="Run a single Playwright spec (e.g., chat-flow.spec.ts)")
    parser.add_argument("--only-failed", action="store_true",
                        help="Rerun only tests that failed in last-run.json")
    parser.add_argument("--daily", action="store_true",
                        help="Daily cron mode (commit gate, emails, OpenObserve)")
    parser.add_argument("--force", action="store_true",
                        help="Skip commit-activity check in --daily mode")
    parser.add_argument("--environment", choices=["development", "production"], default="development",
                        help="Target environment (default: development)")
    parser.add_argument("--max-concurrent", type=int, default=20,
                        help="Max concurrent GitHub Actions runners (default: 20)")
    parser.add_argument("--no-fail-fast", action="store_true",
                        help="Don't stop on first batch failure")
    parser.add_argument("--no-mocks", action="store_true",
                        help="Run with real LLM calls instead of mocks")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would run without executing")
    parser.add_argument("--flaky-report", action="store_true",
                        help="Show top flaky tests from history and exit")

    args = parser.parse_args()

    if args.flaky_report:
        _print_flaky_report()
        return 0

    # Daily mode: acquire lockfile
    lock_fd = None
    if args.daily:
        try:
            lock_fd = open(LOCKFILE, "w")
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (IOError, OSError):
            _log("Another instance is already running — exiting")
            return 0

        # Source .env if not already loaded
        dot_env = _read_env_file()
        for k, v in dot_env.items():
            if k not in os.environ:
                os.environ[k] = v

    try:
        orchestrator = TestOrchestrator(args)
        return orchestrator.run()
    finally:
        if lock_fd:
            lock_fd.close()


if __name__ == "__main__":
    sys.exit(main())
