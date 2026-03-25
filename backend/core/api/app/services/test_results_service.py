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
PLAYWRIGHT_SUITE_NAME = "playwright"


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


def get_intra_day_runs(target_date: str) -> List[Dict[str, Any]]:
    """
    Load all individual run-*.json files for a given date.
    Returns list of run summaries sorted by timestamp ascending.
    Used for the intra-day sub-timeline when clicking a day with multiple runs.

    Args:
        target_date: Date string in YYYY-MM-DD format.
    """
    cache_key = f"intra_day_runs:{target_date}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    # Match run files for this date: run-YYYYMMDDTHHMMSSZ.json
    date_compact = target_date.replace("-", "")
    pattern = os.path.join(TEST_RESULTS_DIR, f"run-{date_compact}T*.json")
    files = sorted(glob(pattern))

    runs = []
    for filepath in files:
        data = _read_json_file(filepath)
        if not data:
            continue
        run_id = data.get("run_id", "")
        summary = data.get("summary", {})
        runs.append({
            "run_id": run_id,
            "timestamp": run_id,
            "duration_seconds": data.get("duration_seconds", 0),
            "git_sha": data.get("git_sha", ""),
            "summary": {
                "total": summary.get("total", 0),
                "passed": summary.get("passed", 0),
                "failed": summary.get("failed", 0),
                "skipped": summary.get("skipped", 0),
            },
            "status": "failed" if summary.get("failed", 0) > 0 else "passed",
        })

    _set_cached(cache_key, runs)
    return runs


# Test categories based on spec naming conventions (Playwright E2E)
PLAYWRIGHT_CATEGORIES = {
    "Auth & Signup": ["account-recovery", "backup-code", "multi-session", "recovery-key", "signup", "session-revoke"],
    "Chat": ["chat-flow", "chat-management", "chat-scroll", "chat-search", "daily-inspiration-chat", "fork-conversation", "hidden-chats", "import-chats", "message-sync", "background-chat"],
    "Payment": ["buy-credits", "saved-payment", "settings-buy-credits"],
    "Search & AI": ["code-generation", "focus-mode", "follow-up-suggestions"],
    "Media & Embeds": ["audio-recording", "embed-", "file-attachment", "pdf-flow"],
    "Settings & Security": ["api-keys", "incognito", "language-settings", "location-security", "mention-dropdown", "model-override", "pii-detection"],
    "Infrastructure": ["app-load", "connection-resilience", "dev-preview", "preview-error", "seo-demo", "shared-chat", "status-page"],
    "Reminders": ["reminder-"],
    "Skills": ["skill-"],
    "Accessibility": ["a11y-"],
}

# Backward compatibility alias
TEST_CATEGORIES = PLAYWRIGHT_CATEGORIES

# Frontend unit test categories (vitest) based on file paths
VITEST_CATEGORIES = {
    "Components": ["components/"],
    "Stores": ["stores/"],
    "Services": ["services/"],
    "Utils": ["utils/"],
}

# Backend unit test categories (pytest) based on test file names
PYTEST_CATEGORIES = {
    "API": ["test_rest_api"],
    "Services": ["test_status_service", "test_cache", "test_health"],
    "AI & Models": ["test_model", "test_ai"],
}

# Suite name → category mapping
_SUITE_CATEGORIES: Dict[str, Dict[str, List[str]]] = {
    PLAYWRIGHT_SUITE_NAME: PLAYWRIGHT_CATEGORIES,
    "vitest": VITEST_CATEGORIES,
    "pytest_unit": PYTEST_CATEGORIES,
}


def categorize_test(test_name: str, suite_name: str = PLAYWRIGHT_SUITE_NAME) -> str:
    """Determine which category a test belongs to based on its name and suite."""
    categories = _SUITE_CATEGORIES.get(suite_name, PLAYWRIGHT_CATEGORIES)
    name_lower = test_name.lower()
    for category, prefixes in categories.items():
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

    # Track which suite each category belongs to (for history computation)
    category_suite_map: Dict[str, str] = {}

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

        # Categorize tests for ALL suites (not just playwright)
        for test in tests:
            # Use file as canonical name for Playwright, name for others
            test_key = test.get("file") or test.get("name", "")
            display_name = test.get("name") or test.get("file", "")
            category = categorize_test(test_key, suite_name)
            # Prefix category with suite for non-playwright to avoid name collisions
            full_cat_key = category if suite_name == PLAYWRIGHT_SUITE_NAME else f"{suite_name}:{category}"
            status = test.get("status", "unknown")

            if full_cat_key not in categories:
                categories[full_cat_key] = {
                    "total": 0, "passed": 0, "failed": 0, "skipped": 0,
                    "suite": suite_name,
                    "display_name": category,
                    "tests": [] if is_admin else None,
                    "history": [],  # 30-day pass rate per day
                }
                category_suite_map[full_cat_key] = suite_name

            cat = categories[full_cat_key]
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
        cat_suite = category_suite_map.get(cat_name, PLAYWRIGHT_SUITE_NAME)
        # Collect all test keys in this category
        cat_test_names = []
        for suite_name, suite_data in data.get("suites", {}).items():
            if suite_name != cat_suite:
                continue
            for test in suite_data.get("tests", []):
                test_key = test.get("file") or test.get("name", "")
                if categorize_test(test_key, suite_name) == cat_data.get("display_name", cat_name):
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


# ─── V2: Functionality-based summaries for new status page ───────────────────
# Maps test results into user-facing functionality groups (Signup, Login, Chat, etc.)
# with 30-day timelines and sub-category drill-down.


def _categorize_test_to_functionality(
    test_key: str,
    functionality_map: Dict[str, List[str]],
) -> Optional[str]:
    """Match a test file/name to a functionality group. Returns None if no match."""
    name_lower = test_key.lower()
    for func_name, patterns in functionality_map.items():
        for pattern in patterns:
            if pattern.lower() in name_lower:
                return func_name
    return None


def _categorize_test_to_sub_category(
    test_key: str,
    sub_categories: Dict[str, List[str]],
) -> Optional[str]:
    """Match a test file/name to a sub-category within a functionality."""
    name_lower = test_key.lower()
    for sub_name, patterns in sub_categories.items():
        for pattern in patterns:
            if pattern.lower() in name_lower:
                return sub_name
    return None


def get_functionality_summaries(days: int = 30) -> List[Dict[str, Any]]:
    """
    Build functionality-level summaries for the status page.

    Groups Playwright tests by user-facing functionality (Signup, Login, Chat, etc.)
    and computes 30-day timelines with pass rates per day.

    Returns list of {name, status, pass_rate, total, passed, failed, timeline_30d}.
    """
    from backend.core.api.app.services.status_aggregator import (
        FUNCTIONALITY_MAP,
        _pass_rate_to_status,
    )

    cache_key = f"functionality_summaries:{days}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    data = _read_json_file(os.path.join(TEST_RESULTS_DIR, "last-run.json"))
    if not data:
        return []

    per_test_hist = get_per_test_history(days=days)

    # Collect tests per functionality (only Playwright)
    func_tests: Dict[str, List[str]] = {name: [] for name in FUNCTIONALITY_MAP}
    func_current: Dict[str, Dict[str, int]] = {
        name: {"passed": 0, "failed": 0, "total": 0} for name in FUNCTIONALITY_MAP
    }

    playwright_suite = data.get("suites", {}).get(PLAYWRIGHT_SUITE_NAME)
    if playwright_suite:
        for test in playwright_suite.get("tests", []):
            test_key = test.get("file") or test.get("name", "")
            func_name = _categorize_test_to_functionality(test_key, FUNCTIONALITY_MAP)
            if func_name and func_name in func_tests:
                func_tests[func_name].append(test_key)
                func_current[func_name]["total"] += 1
                if test.get("status") == "passed":
                    func_current[func_name]["passed"] += 1
                elif test.get("status") == "failed":
                    func_current[func_name]["failed"] += 1

    # Build per-functionality 30-day timeline
    date_range = _generate_date_range(days)
    summaries = []

    for func_name in FUNCTIONALITY_MAP:
        test_keys = func_tests[func_name]
        current = func_current[func_name]

        if current["total"] == 0:
            continue

        pass_rate = round(current["passed"] / current["total"] * 100) if current["total"] > 0 else 0

        # Build daily timeline
        timeline = []
        for date_str in date_range:
            day_passed = 0
            day_failed = 0
            day_total = 0
            has_run = False
            run_at = None

            for tkey in test_keys:
                for entry in per_test_hist.get(tkey, []):
                    if entry.get("date") == date_str:
                        if entry.get("status") == "passed":
                            day_passed += 1
                            day_total += 1
                            has_run = True
                        elif entry.get("status") == "failed":
                            day_failed += 1
                            day_total += 1
                            has_run = True
                        if not run_at and entry.get("run_at"):
                            run_at = entry["run_at"]
                        break

            expected_total = len(test_keys)
            not_run = max(expected_total - day_total, 0)
            day_pass_rate = round(day_passed / expected_total * 100) if expected_total > 0 else 0

            timeline.append({
                "date": date_str,
                "pass_rate": day_pass_rate,
                "total": expected_total,
                "passed": day_passed,
                "failed": day_failed,
                "not_run": not_run,
                "has_run": has_run,
                "run_at": run_at,
                "tone": _compute_tone_score(day_passed, day_failed, not_run),
            })

        summaries.append({
            "name": func_name,
            "status": _pass_rate_to_status(pass_rate),
            "pass_rate": pass_rate,
            "total": current["total"],
            "passed": current["passed"],
            "failed": current["failed"],
            "timeline_30d": timeline,
        })

    _set_cached(cache_key, summaries)
    return summaries


def get_functionality_detail(
    name: str,
    is_admin: bool = False,
    days: int = 30,
) -> Optional[Dict[str, Any]]:
    """
    Build detailed functionality data for the /v1/status/functionalities?name=<name> endpoint.

    Returns sub-category timelines and individual tests per sub-category.
    """
    from backend.core.api.app.services.status_aggregator import (
        FUNCTIONALITY_MAP,
        FUNCTIONALITY_SUB_CATEGORIES,
        _pass_rate_to_status,
    )

    if name not in FUNCTIONALITY_MAP:
        return None

    cache_key = f"functionality_detail:{name}:{is_admin}:{days}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    data = _read_json_file(os.path.join(TEST_RESULTS_DIR, "last-run.json"))
    if not data:
        return None

    per_test_hist = get_per_test_history(days=days)
    patterns = FUNCTIONALITY_MAP[name]
    sub_cats = FUNCTIONALITY_SUB_CATEGORIES.get(name, {})
    date_range = _generate_date_range(days)

    # Collect tests matching this functionality
    func_tests: List[Dict[str, Any]] = []
    playwright_suite = data.get("suites", {}).get(PLAYWRIGHT_SUITE_NAME)
    if playwright_suite:
        for test in playwright_suite.get("tests", []):
            test_key = test.get("file") or test.get("name", "")
            matched = _categorize_test_to_functionality(test_key, {name: patterns})
            if matched:
                test_entry: Dict[str, Any] = {
                    "name": test.get("name") or test.get("file", ""),
                    "file": test_key,
                    "status": test.get("status", "unknown"),
                    "last_run": data.get("run_id", ""),
                    "history_30d": per_test_hist.get(test_key, []),
                }
                if is_admin:
                    test_entry["error"] = test.get("error")
                # Determine sub-category
                if sub_cats:
                    test_entry["sub_category"] = _categorize_test_to_sub_category(
                        test_key, sub_cats
                    ) or "Other"
                func_tests.append(test_entry)

    # Build sub-category timelines
    sub_category_data = []
    if sub_cats:
        for sub_name, sub_patterns in sub_cats.items():
            sub_test_keys = [
                t["file"] for t in func_tests
                if t.get("sub_category") == sub_name
            ]
            if not sub_test_keys:
                continue

            # Current stats
            sub_passed = sum(1 for t in func_tests if t.get("sub_category") == sub_name and t["status"] == "passed")
            sub_failed = sum(1 for t in func_tests if t.get("sub_category") == sub_name and t["status"] == "failed")
            sub_total = len(sub_test_keys)
            sub_pass_rate = round(sub_passed / sub_total * 100) if sub_total > 0 else 0

            # 30-day timeline for this sub-category
            sub_timeline = []
            for date_str in date_range:
                day_passed = 0
                day_failed = 0
                day_total_run = 0
                has_run = False
                run_at = None

                for tkey in sub_test_keys:
                    for entry in per_test_hist.get(tkey, []):
                        if entry.get("date") == date_str:
                            if entry.get("status") == "passed":
                                day_passed += 1
                                day_total_run += 1
                                has_run = True
                            elif entry.get("status") == "failed":
                                day_failed += 1
                                day_total_run += 1
                                has_run = True
                            if not run_at and entry.get("run_at"):
                                run_at = entry["run_at"]
                            break

                expected = len(sub_test_keys)
                not_run = max(expected - day_total_run, 0)
                day_pr = round(day_passed / expected * 100) if expected > 0 else 0

                sub_timeline.append({
                    "date": date_str,
                    "pass_rate": day_pr,
                    "total": expected,
                    "passed": day_passed,
                    "failed": day_failed,
                    "not_run": not_run,
                    "has_run": has_run,
                    "run_at": run_at,
                    "tone": _compute_tone_score(day_passed, day_failed, not_run),
                })

            sub_category_data.append({
                "name": sub_name,
                "pass_rate": sub_pass_rate,
                "total": sub_total,
                "passed": sub_passed,
                "failed": sub_failed,
                "status": _pass_rate_to_status(sub_pass_rate),
                "timeline_30d": sub_timeline,
            })

    # Overall summary for the functionality
    total = len(func_tests)
    passed = sum(1 for t in func_tests if t["status"] == "passed")
    failed = sum(1 for t in func_tests if t["status"] == "failed")
    pass_rate = round(passed / total * 100) if total > 0 else 0

    result: Dict[str, Any] = {
        "name": name,
        "status": _pass_rate_to_status(pass_rate),
        "pass_rate": pass_rate,
        "total": total,
        "passed": passed,
        "failed": failed,
        "tests": func_tests,
        "sub_categories": sub_category_data if sub_category_data else None,
    }

    _set_cached(cache_key, result)
    return result


def get_intra_day_runs_hourly(
    target_date: str,
    source: Optional[str] = None,
    source_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Load intra-day run data grouped by hour for the hourly sub-timeline.

    For functionality source: groups test runs by hour and computes per-hour aggregates.
    For service source: returns health check entries grouped by hour.

    Args:
        target_date: Date in YYYY-MM-DD format.
        source: "functionality" or "service" (optional filter context).
        source_id: Functionality name or service ID (optional filter context).
    """
    cache_key = f"intra_day_hourly:{target_date}:{source}:{source_id}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    # Load all runs for this date
    runs = get_intra_day_runs(target_date)

    # Group runs by hour
    hours_map: Dict[int, List[Dict[str, Any]]] = {}
    for run in runs:
        timestamp = run.get("timestamp", "")
        # Parse hour from ISO timestamp: "2026-03-22T03:00:00Z" → 3
        try:
            hour = int(timestamp[11:13]) if len(timestamp) >= 13 else 0
        except (ValueError, IndexError):
            hour = 0
        hours_map.setdefault(hour, []).append(run)

    # Build hourly aggregates
    hours = []
    for hour in sorted(hours_map.keys()):
        hour_runs = hours_map[hour]
        total = sum(r["summary"]["total"] for r in hour_runs)
        passed_count = sum(r["summary"]["passed"] for r in hour_runs)
        failed_count = sum(r["summary"]["failed"] for r in hour_runs)
        skipped_count = sum(r["summary"].get("skipped", 0) for r in hour_runs)

        hours.append({
            "hour": hour,
            "run_count": len(hour_runs),
            "summary": {
                "total": total,
                "passed": passed_count,
                "failed": failed_count,
                "skipped": skipped_count,
            },
            "runs": hour_runs,
        })

    result = {
        "date": target_date,
        "source": source,
        "id": source_id,
        "hours": hours,
    }

    _set_cached(cache_key, result)
    return result
