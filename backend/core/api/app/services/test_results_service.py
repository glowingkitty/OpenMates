# backend/core/api/app/services/test_results_service.py
# Reads test result JSON files from disk for the status page API.
# Architecture: See docs/architecture/status-page.md
# Tests: N/A — covered by status API integration tests

from __future__ import annotations

import json
import logging
import os
import time
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

    pattern = os.path.join(TEST_RESULTS_DIR, "daily-run-*.json")
    files = sorted(glob(pattern), reverse=True)[:days]

    trend = []
    for filepath in files:
        data = _read_json_file(filepath)
        if not data:
            continue

        # Extract date from filename: daily-run-2026-03-22.json
        filename = Path(filepath).stem  # daily-run-2026-03-22
        date_str = filename.replace("daily-run-", "")
        summary = data.get("summary", {})

        trend.append({
            "date": date_str,
            "total": summary.get("total", 0),
            "passed": summary.get("passed", 0),
            "failed": summary.get("failed", 0),
            "skipped": summary.get("skipped", 0),
        })

    # Sort oldest first for charting (left-to-right)
    trend.sort(key=lambda x: x["date"])

    _set_cached(f"daily_trend:{days}", trend)
    return trend


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
