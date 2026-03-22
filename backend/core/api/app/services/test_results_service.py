# backend/core/api/app/services/test_results_service.py
# Reads test result JSON files from disk for the status page API.
# Architecture: See docs/architecture/status-page.md
# Tests: N/A — covered by status API integration tests

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, timedelta
from glob import glob
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Default path inside Docker container (volume-mounted from host)
TEST_RESULTS_DIR = os.getenv("TEST_RESULTS_DIR", "/app/test-results")

# In-memory cache with TTL
_cache: Dict[str, Any] = {}
_cache_timestamps: Dict[str, float] = {}
CACHE_TTL_SECONDS = 60
NO_RUN_STATUS = "not_run"
NOT_RUN_TONE_WEIGHT = 0.5


def _get_cached(key: str) -> Optional[Any]:
    """Return cached value if within TTL, else None."""
    ts = _cache_timestamps.get(key)
    if ts and (time.time() - ts) < CACHE_TTL_SECONDS:
        return _cache.get(key)
    return None


def _set_cached(key: str, value: Any) -> None:
    """Store value in cache with current timestamp."""
    _cache[key] = value
    _cache_timestamps[key] = time.time()


def _generate_date_range(days: int) -> List[str]:
    """Generate the last N calendar dates, oldest first."""
    today = date.today()
    return [(today - timedelta(days=days - 1 - index)).isoformat() for index in range(days)]


def _extract_daily_run_date(filepath: str) -> str:
    """Extract the YYYY-MM-DD date from a daily run filename."""
    return Path(filepath).stem.replace("daily-run-", "")


def _load_daily_runs(days: int) -> List[Dict[str, Any]]:
    """Load daily run files and normalize them into a fixed date window."""
    pattern = os.path.join(TEST_RESULTS_DIR, "daily-run-*.json")
    files = sorted(glob(pattern), reverse=True)[:days]
    runs_by_date: Dict[str, Dict[str, Any]] = {}

    for filepath in files:
        data = _read_json_file(filepath)
        if not data:
            continue
        date_str = _extract_daily_run_date(filepath)
        runs_by_date[date_str] = {
            "date": date_str,
            "data": data,
            "run_at": data.get("run_id"),
        }

    return [
        {
            "date": date_str,
            "data": runs_by_date.get(date_str, {}).get("data"),
            "run_at": runs_by_date.get(date_str, {}).get("run_at"),
        }
        for date_str in _generate_date_range(days)
    ]


def _normalize_test_status(status: Optional[str]) -> str:
    """Normalize test statuses for timeline rendering."""
    if status == "passed":
        return "passed"
    if status == "failed":
        return "failed"
    return NO_RUN_STATUS


def _compute_tone_score(passed: int, failed: int, not_run: int) -> Optional[int]:
    """Return a 0-100 green-to-red score, with not-run lighter than failed."""
    expected_total = passed + failed + not_run
    observed_total = passed + failed
    if expected_total <= 0 or observed_total <= 0:
        return None
    severity = (failed + (not_run * NOT_RUN_TONE_WEIGHT)) / expected_total
    bounded = max(0.0, min(1.0, 1.0 - severity))
    return round(bounded * 100)


def _read_json_file(path: str) -> Optional[Dict[str, Any]]:
    """Read and parse a JSON file, returning None on failure."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as e:
        logger.warning(f"[TEST_RESULTS] Failed to read {path}: {e}")
        return None


def get_latest_run_summary() -> Optional[Dict[str, Any]]:
    """
    Read last-run.json and return summary-level data only.
    No individual test details — just counts per suite.
    """
    cached = _get_cached("latest_run_summary")
    if cached is not None:
        return cached

    data = _read_json_file(os.path.join(TEST_RESULTS_DIR, "last-run.json"))
    if not data:
        return None

    # Build suite summaries without individual test rows
    suites_summary = []
    for suite_name, suite_data in data.get("suites", {}).items():
        tests = suite_data.get("tests", [])
        passed = sum(1 for t in tests if t.get("status") == "passed")
        failed = sum(1 for t in tests if t.get("status") == "failed")
        skipped = sum(1 for t in tests if t.get("status") in ("skipped", "not_started"))
        flaky = sum(1 for t in tests if t.get("status") == "flaky")
        total = len(tests)
        status = "failing" if failed > 0 else "passing"

        suites_summary.append({
            "name": suite_name,
            "status": status,
            "total": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "flaky": flaky,
        })

    summary = data.get("summary", {})
    overall_failed = summary.get("failed", 0)

    result = {
        "overall_status": "failing" if overall_failed > 0 else "passing",
        "latest_run": {
            "run_id": data.get("run_id", ""),
            "git_sha": data.get("git_sha", ""),
            "git_branch": data.get("git_branch", ""),
            "timestamp": data.get("run_id", ""),  # run_id is the ISO timestamp
            "duration_seconds": data.get("duration_seconds", 0),
            "summary": summary,
        },
        "suites": suites_summary,
    }

    _set_cached("latest_run_summary", result)
    return result


def get_latest_run_detail(suite_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Read last-run.json and return full test details including individual tests.
    Optionally filter by suite name.
    """
    cache_key = f"latest_run_detail:{suite_name or 'all'}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    data = _read_json_file(os.path.join(TEST_RESULTS_DIR, "last-run.json"))
    if not data:
        return None

    suites_detail = {}
    for sname, suite_data in data.get("suites", {}).items():
        if suite_name and sname != suite_name:
            continue

        tests = suite_data.get("tests", [])
        suites_detail[sname] = {
            "status": suite_data.get("status", "unknown"),
            "tests": [
                {
                    "name": t.get("name", ""),
                    "file": t.get("file", ""),
                    "status": t.get("status", "unknown"),
                    "duration_seconds": t.get("duration_seconds", 0),
                    "error": t.get("error"),
                    "run_id": t.get("run_id"),
                }
                for t in tests
            ],
        }

    result = {
        "run_id": data.get("run_id", ""),
        "git_sha": data.get("git_sha", ""),
        "timestamp": data.get("run_id", ""),
        "summary": data.get("summary", {}),
        "suites": suites_detail,
    }

    _set_cached(cache_key, result)
    return result


def get_daily_trend(days: int = 14) -> List[Dict[str, Any]]:
    """
    Read daily-run-*.json files and return pass rate per day for charting.
    Returns list of {date, total, passed, failed, skipped} sorted by date.
    """
    cached = _get_cached(f"daily_trend:{days}")
    if cached is not None:
        return cached

    trend = []
    for run in _load_daily_runs(days):
        data = run["data"]
        if not data:
            trend.append({
                "date": run["date"],
                "total": 0,
                "passed": 0,
                "failed": 0,
                "skipped": 0,
                "has_run": False,
                "run_at": None,
            })
            continue

        summary = data.get("summary", {})

        trend.append({
            "date": run["date"],
            "total": summary.get("total", 0),
            "passed": summary.get("passed", 0),
            "failed": summary.get("failed", 0),
            "skipped": summary.get("skipped", 0),
            "has_run": summary.get("total", 0) > 0,
            "run_at": run.get("run_at"),
        })

    _set_cached(f"daily_trend:{days}", trend)
    return trend


def get_per_suite_daily_history(days: int = 30) -> Dict[str, List[Dict[str, Any]]]:
    """
    Build per-suite 30-day pass rate history from daily run files.
    Returns { "playwright": [{date, pass_rate, passed, failed, total}, ...], ... }
    """
    cached = _get_cached(f"per_suite_history:{days}")
    if cached is not None:
        return cached

    latest_run = _read_json_file(os.path.join(TEST_RESULTS_DIR, "last-run.json")) or {}
    expected_totals = {
        suite_name: len((suite_data or {}).get("tests", []))
        for suite_name, suite_data in latest_run.get("suites", {}).items()
    }

    history: Dict[str, List[Dict[str, Any]]] = {}

    for run in _load_daily_runs(days):
        data = run["data"]
        daily_suites = data.get("suites", {}) if data else {}
        for suite_name in expected_totals:
            suite_data = daily_suites.get(suite_name)
            tests = suite_data.get("tests", []) if suite_data else []
            passed = sum(1 for t in tests if t.get("status") == "passed")
            failed = sum(1 for t in tests if t.get("status") == "failed")
            observed_total = len(tests)
            expected_total = expected_totals.get(suite_name, observed_total)
            not_run = max(expected_total - observed_total, 0)
            pass_rate = round(passed / observed_total * 100) if observed_total > 0 else 0

            if suite_name not in history:
                history[suite_name] = []
            history[suite_name].append({
                "date": run["date"],
                "pass_rate": pass_rate,
                "passed": passed,
                "failed": failed,
                "total": observed_total,
                "not_run": not_run,
                "has_run": observed_total > 0,
                "run_at": run.get("run_at") if observed_total > 0 else None,
            })

    _set_cached(f"per_suite_history:{days}", history)
    return history


def get_flaky_tests() -> List[Dict[str, Any]]:
    """Read flaky-history.json and return flaky test data."""
    cached = _get_cached("flaky_tests")
    if cached is not None:
        return cached

    data = _read_json_file(os.path.join(TEST_RESULTS_DIR, "flaky-history.json"))
    if not data:
        return []

    # flaky-history.json is a dict keyed by test name
    flaky_list = []
    for test_name, info in data.items():
        if not isinstance(info, dict):
            continue
        flaky_list.append({
            "name": test_name,
            "flaky_count": info.get("flaky_count", 0),
            "total_runs": info.get("total_runs", 0),
            "last_flaky": info.get("last_flaky"),
            "error": info.get("error"),
        })

    # Sort by flaky count descending
    flaky_list.sort(key=lambda x: x.get("flaky_count", 0), reverse=True)

    _set_cached("flaky_tests", flaky_list)
    return flaky_list


def get_per_test_history(days: int = 30) -> Dict[str, List[Dict[str, Any]]]:
    """
    Build per-test pass/fail history across daily run files.
    Returns dict keyed by test name, value is list of {date, status} sorted oldest-first.
    Used for the 30-day colored timeline per test.
    """
    cached = _get_cached(f"per_test_history:{days}")
    if cached is not None:
        return cached

    latest_run = _read_json_file(os.path.join(TEST_RESULTS_DIR, "last-run.json")) or {}
    expected_tests: Dict[str, None] = {}
    for suite_data in latest_run.get("suites", {}).values():
        for test in suite_data.get("tests", []):
            test_key = test.get("file") or test.get("name", "")
            if test_key:
                expected_tests[test_key] = None

    history: Dict[str, List[Dict[str, Any]]] = {test_key: [] for test_key in expected_tests}

    for run in _load_daily_runs(days):
        daily_statuses: Dict[str, str] = {}
        if run["data"]:
            for suite_data in run["data"].get("suites", {}).values():
                for test in suite_data.get("tests", []):
                    test_key = test.get("file") or test.get("name", "")
                    if test_key:
                        expected_tests.setdefault(test_key, None)
                        history.setdefault(test_key, [])
                        daily_statuses[test_key] = _normalize_test_status(test.get("status"))

        for test_key in expected_tests:
            history.setdefault(test_key, []).append({
                "date": run["date"],
                "status": daily_statuses.get(test_key, NO_RUN_STATUS),
                "has_run": test_key in daily_statuses,
                "run_at": run.get("run_at") if test_key in daily_statuses else None,
            })

    _set_cached(f"per_test_history:{days}", history)
    return history


# Test categories based on spec naming conventions
TEST_CATEGORIES = {
    "Auth & Signup": ["account-recovery", "backup-code", "multi-session", "recovery-key", "signup", "session-revoke"],
    "Chat": ["chat-flow", "chat-management", "chat-scroll", "chat-search", "daily-inspiration-chat", "fork-conversation", "hidden-chats", "import-chats", "message-sync", "background-chat"],
    "Payment": ["buy-credits", "saved-payment", "settings-buy-credits"],
    "Search & AI": ["code-generation", "focus-mode", "follow-up-suggestions"],
    "Media & Embeds": ["audio-recording", "embed-", "file-attachment", "pdf-flow"],
    "Settings & Security": ["api-keys", "incognito", "language-settings", "location-security", "mention-dropdown", "model-override", "pii-detection"],
    "Infrastructure": ["app-load", "connection-resilience", "dev-preview", "preview-error", "seo-demo", "shared-chat"],
    "Reminders": ["reminder-"],
    "Skills": ["skill-"],
    "Accessibility": ["a11y-"],
}


def categorize_test(test_name: str) -> str:
    """Determine which category a test belongs to based on its name."""
    name_lower = test_name.lower()
    for category, prefixes in TEST_CATEGORIES.items():
        for prefix in prefixes:
            if prefix.lower() in name_lower:
                return category
    return "Other"


def get_categorized_test_summary(is_admin: bool = False) -> Dict[str, Any]:
    """
    Get test results organized by category.
    Non-admin: category-level counts only.
    Admin: includes individual test names.
    """
    cached_key = f"categorized_tests:{is_admin}"
    cached = _get_cached(cached_key)
    if cached is not None:
        return cached

    data = _read_json_file(os.path.join(TEST_RESULTS_DIR, "last-run.json"))
    if not data:
        return {"categories": {}, "suites": {}}

    per_test_hist = get_per_test_history(days=30)

    categories: Dict[str, Dict[str, Any]] = {}
    suites_info: Dict[str, Dict[str, Any]] = {}

    for suite_name, suite_data in data.get("suites", {}).items():
        tests = suite_data.get("tests", [])
        suite_passed = sum(1 for t in tests if t.get("status") == "passed")
        suite_failed = sum(1 for t in tests if t.get("status") == "failed")
        suite_total = len(tests)

        suites_info[suite_name] = {
            "total": suite_total,
            "passed": suite_passed,
            "failed": suite_failed,
            "status": "failing" if suite_failed > 0 else "passing",
        }

        for test in tests:
            # Use file as canonical name for Playwright, name for others
            test_key = test.get("file") or test.get("name", "")
            display_name = test.get("name") or test.get("file", "")
            category = categorize_test(test_key)
            status = test.get("status", "unknown")

            if category not in categories:
                categories[category] = {
                    "total": 0, "passed": 0, "failed": 0, "skipped": 0,
                    "tests": [] if is_admin else None,
                    "history": [],  # 30-day pass rate per day
                }

            cat = categories[category]
            cat["total"] += 1
            if status == "passed":
                cat["passed"] += 1
            elif status == "failed":
                cat["failed"] += 1
            else:
                cat["skipped"] += 1

            if is_admin:
                test_entry = {
                    "name": display_name,
                    "file": test_key,
                    "suite": suite_name,
                    "status": status,
                    "error": test.get("error"),
                    "last_run": data.get("run_id", ""),
                    "history_30d": per_test_hist.get(test_key, []),
                }
                cat["tests"].append(test_entry)

    # Compute per-category 30-day pass rate history
    for cat_name, cat_data in categories.items():
        # Collect all test keys in this category
        cat_test_names = []
        for suite_name, suite_data in data.get("suites", {}).items():
            for test in suite_data.get("tests", []):
                test_key = test.get("file") or test.get("name", "")
                if categorize_test(test_key) == cat_name:
                    cat_test_names.append(test_key)

        # Build per-day pass rate
        day_stats: Dict[str, Dict[str, int]] = {}
        for tname in cat_test_names:
            for entry in per_test_hist.get(tname, []):
                d = entry["date"]
                if d not in day_stats:
                    day_stats[d] = {"passed": 0, "failed": 0, "total": 0}
                if entry["status"] == "passed":
                    day_stats[d]["total"] += 1
                    day_stats[d]["passed"] += 1
                elif entry["status"] == "failed":
                    day_stats[d]["total"] += 1
                    day_stats[d]["failed"] += 1

        category_history = []
        for date_str in _generate_date_range(30):
            stats = day_stats.get(date_str, {"passed": 0, "failed": 0, "total": 0})
            expected_total = len(cat_test_names)
            observed_total = stats["total"]
            not_run = max(expected_total - observed_total, 0)
            run_at = None
            for test_name in cat_test_names:
                for entry in per_test_hist.get(test_name, []):
                    if entry.get("date") == date_str and entry.get("run_at"):
                        run_at = entry["run_at"]
                        break
                if run_at:
                    break

            category_history.append({
                "date": date_str,
                "pass_rate": round(stats["passed"] / expected_total * 100) if expected_total > 0 else 0,
                "total": expected_total,
                "passed": stats["passed"],
                "failed": stats["failed"],
                "not_run": not_run,
                "has_run": observed_total > 0,
                "run_at": run_at,
                "tone": _compute_tone_score(stats["passed"], stats["failed"], not_run),
            })

        cat_data["history"] = category_history

        # Compute overall pass_rate for color
        if cat_data["total"] > 0:
            cat_data["pass_rate"] = round(cat_data["passed"] / cat_data["total"] * 100)
        else:
            cat_data["pass_rate"] = 0

        # Remove tests list for non-admin
        if not is_admin:
            cat_data.pop("tests", None)

    result = {
        "categories": categories,
        "suites": suites_info,
        "run_id": data.get("run_id", ""),
        "timestamp": data.get("run_id", ""),
        "git_sha": data.get("git_sha", ""),
    }

    _set_cached(cached_key, result)
    return result
