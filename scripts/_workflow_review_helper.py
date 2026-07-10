#!/usr/bin/env python3
"""Collect bounded OpenCode, git, and test evidence for explicit workflow review.

This collector never launches an agent, reads session prose, or runs on a
schedule. A maintainer explicitly requests a UTC interval, then optionally uses
the resulting report as input to a separate OpenCode conversation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OPENCODE_DB_PATH = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
REPORTS_DIR = PROJECT_ROOT / "test-results" / "workflow-review"
STATE_FILE = PROJECT_ROOT / "scripts" / ".workflow-review-state.json"


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("workflow review timestamps must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def _epoch_ms(value: str) -> int:
    return int(_parse_timestamp(value).timestamp() * 1000)


def _empty_state() -> dict[str, Any]:
    return {"schema_version": 2, "last_collection": None, "recommendation_fingerprints": {}}


def load_state() -> dict[str, Any]:
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _empty_state()
    if state.get("schema_version") != 2:
        return _empty_state()
    state.setdefault("recommendation_fingerprints", {})
    return state


def _save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(STATE_FILE)


def _readonly_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(f"{OPENCODE_DB_PATH.resolve().as_uri()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only = ON")
    return connection


def normalize_tool_failure(raw_error: str) -> str:
    value = raw_error.lower()
    if "timeout" in value:
        return "timeout"
    if "bad credentials" in value or "401" in value or "authentication" in value:
        return "authentication"
    if "file not found" in value or "no such file" in value:
        return "missing_file"
    if "apply_patch verification failed" in value:
        return "stale_patch_context"
    if "blocked:" in value or '"decision":"block"' in value:
        return "policy_block"
    return "other"


def collect_opencode_metadata(period_start: str, period_end: str) -> dict[str, Any]:
    start_ms = _epoch_ms(period_start)
    end_ms = _epoch_ms(period_end)
    where = "session.directory = ? AND session.time_created < ? AND session.time_updated >= ?"
    parameters = (str(PROJECT_ROOT), end_ms, start_ms)
    try:
        with _readonly_connection() as connection:
            top_level = connection.execute(
                f"SELECT COUNT(*) FROM session WHERE {where} AND COALESCE(parent_id, '') = ''", parameters
            ).fetchone()[0]
            subagents = connection.execute(
                f"SELECT COUNT(*) FROM session WHERE {where} AND COALESCE(parent_id, '') != ''", parameters
            ).fetchone()[0]
            rows = connection.execute(
                f"""
                SELECT part.data
                FROM session
                JOIN part ON part.session_id = session.id
                WHERE {where}
                  AND COALESCE(session.parent_id, '') = ''
                """,
                parameters,
            ).fetchall()
    except (OSError, sqlite3.Error):
        return {"top_level_sessions": 0, "subagents_excluded": 0, "tool_failures": []}

    failures: Counter[tuple[str, str]] = Counter()
    for (raw_data,) in rows:
        try:
            data = json.loads(raw_data)
        except (TypeError, json.JSONDecodeError):
            continue
        state = data.get("state") if isinstance(data, dict) else None
        if data.get("type") != "tool" or not isinstance(state, dict) or state.get("status") != "error":
            continue
        tool = str(data.get("tool") or "unknown")
        failures[(tool, normalize_tool_failure(str(state.get("error") or "")))] += 1

    return {
        "top_level_sessions": int(top_level),
        "subagents_excluded": int(subagents),
        "tool_failures": [
            {"tool": tool, "error_kind": error_kind, "count": count}
            for (tool, error_kind), count in sorted(failures.items())
        ],
    }


def collect_git_metadata(period_start: str, period_end: str) -> dict[str, Any]:
    command = [
        "git", "log", "HEAD", "--no-merges", "--format=%H%x09%ct", "--name-only",
        f"--since={period_start}", f"--before={period_end}",
    ]
    result = subprocess.run(command, cwd=PROJECT_ROOT, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return {"commits": [], "path_churn": []}

    commits: list[dict[str, Any]] = []
    churn: Counter[str] = Counter()
    current: dict[str, Any] | None = None
    for line in result.stdout.splitlines():
        if "\t" in line and len(line.split("\t", 1)[0]) >= 7:
            if current is not None:
                current["changed_file_count"] = len(current.pop("paths"))
                commits.append(current)
            sha, epoch = line.split("\t", 1)
            current = {"sha": sha, "timestamp": int(epoch), "paths": []}
        elif current is not None and line:
            current["paths"].append(line)
            churn[line] += 1
    if current is not None:
        current["changed_file_count"] = len(current.pop("paths"))
        commits.append(current)
    return {
        "commits": commits,
        "path_churn": [
            {"path": path, "count": count}
            for path, count in churn.most_common(30)
        ],
    }


def collect_test_metadata(period_start: str, period_end: str) -> dict[str, Any]:
    start = _parse_timestamp(period_start)
    end = _parse_timestamp(period_end)
    runs: list[dict[str, Any]] = []
    for path in [*sorted((PROJECT_ROOT / "test-results").glob("daily-run-*.json")), PROJECT_ROOT / "test-results" / "last-run.json"]:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            timestamp = _parse_timestamp(str(data.get("run_id", "")))
        except (json.JSONDecodeError, OSError, ValueError):
            continue
        if not start <= timestamp < end:
            continue
        runs.append({
            "git_sha": str(data.get("git_sha") or ""),
            "status": "failed" if int((data.get("summary") or {}).get("failed", 0)) else "passed",
        })
    return {
        "runs": runs,
        "flake_history_available": (PROJECT_ROOT / "test-results" / "flaky-history.json").is_file(),
    }


def correlate_evidence(git: dict[str, Any], tests: dict[str, Any]) -> list[dict[str, Any]]:
    test_counts = Counter(str(run.get("git_sha") or "") for run in tests.get("runs", []))
    return [
        {"git_sha": commit["sha"], "test_run_count": test_counts[commit["sha"]]}
        for commit in git.get("commits", [])
        if test_counts[commit["sha"]]
    ]


def fingerprint_recommendation(rule_id: str, target: str) -> str:
    canonical = f"{rule_id}\n{target}".encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def build_recommendations(tool_failures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    recommendations = []
    for failure in tool_failures:
        target = f"{failure['tool']}:{failure['error_kind']}"
        recommendations.append({
            "fingerprint": fingerprint_recommendation("repeated_tool_failure", target),
            "rule_id": "repeated_tool_failure",
            "target": target,
            "evidence": {"count": failure["count"]},
        })
    return recommendations


def _report_path(period_start: str, period_end: str) -> Path:
    return REPORTS_DIR / f"{period_start[:10]}_{period_end[:10]}.json"


def collect(period_start: str, period_end: str) -> dict[str, Any]:
    if _parse_timestamp(period_start) >= _parse_timestamp(period_end):
        raise ValueError("--since must be earlier than --until")
    opencode = collect_opencode_metadata(period_start, period_end)
    git = collect_git_metadata(period_start, period_end)
    tests = collect_test_metadata(period_start, period_end)
    recommendations = build_recommendations(opencode["tool_failures"])
    report = {
        "schema_version": 1,
        "period": {"start": period_start, "end": period_end},
        "sources": {"opencode": {key: opencode[key] for key in ("top_level_sessions", "subagents_excluded")}, "git": git, "tests": tests},
        "tool_failures": opencode["tool_failures"],
        "correlations": correlate_evidence(git, tests),
        "recommendations": recommendations,
    }
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = _report_path(period_start, period_end)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    state = load_state()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for recommendation in recommendations:
        existing = state["recommendation_fingerprints"].get(recommendation["fingerprint"], {})
        state["recommendation_fingerprints"][recommendation["fingerprint"]] = {
            "rule_id": recommendation["rule_id"], "target": recommendation["target"],
            "first_seen": existing.get("first_seen", now), "last_seen": now,
            "occurrences": int(existing.get("occurrences", 0)) + 1,
        }
    state["last_collection"] = {
        "period_start": period_start, "period_end": period_end,
        "report_path": str(report_path.relative_to(PROJECT_ROOT)) if report_path.is_relative_to(PROJECT_ROOT) else str(report_path),
        "report_fingerprint": f"sha256:{hashlib.sha256(report_path.read_bytes()).hexdigest()}",
    }
    _save_state(state)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect an explicit OpenCode-only workflow review report")
    subparsers = parser.add_subparsers(dest="command", required=True)
    collect_parser = subparsers.add_parser("collect", help="Collect a bounded workflow report without launching an agent")
    collect_parser.add_argument("--since", required=True, help="Inclusive UTC ISO timestamp")
    collect_parser.add_argument("--until", required=True, help="Exclusive UTC ISO timestamp")
    args = parser.parse_args()
    report = collect(args.since, args.until)
    print(_report_path(report["period"]["start"], report["period"]["end"]))


if __name__ == "__main__":
    main()
