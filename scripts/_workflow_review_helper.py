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
MIN_TRANSCRIPT_EVIDENCE_BYTES = 4_096


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


def _truncate_json(value: Any, max_chars: int, truncated: dict[str, bool]) -> Any:
    if isinstance(value, str):
        if len(value) > max_chars:
            truncated["fields"] = True
            return value[:max_chars] + "...[truncated]"
        return value
    if isinstance(value, list):
        return [_truncate_json(item, max_chars, truncated) for item in value]
    if isinstance(value, dict):
        return {str(key): _truncate_json(item, max_chars, truncated) for key, item in value.items()}
    return value


def _decode_bounded_json(raw: str, max_chars: int, truncated: dict[str, bool]) -> Any:
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        value = str(raw)
    return _truncate_json(value, max_chars, truncated)


def _project_message_data(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {"value": data}
    projected = {
        key: data[key]
        for key in ("role", "agent", "mode", "modelID", "providerID", "finish")
        if key in data
    }
    model = data.get("model")
    if isinstance(model, dict):
        projected["model"] = {
            key: model[key]
            for key in ("providerID", "modelID", "variant")
            if key in model
        }
    return projected


def _project_part_data(data: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return {"type": "unknown", "value": data}
    part_type = str(data.get("type") or "unknown")
    if part_type in {"reasoning", "step-start", "step-finish", "snapshot"}:
        return None
    if part_type == "text":
        return {"type": "text", "text": data.get("text", "")}
    if part_type == "tool":
        state = data.get("state") if isinstance(data.get("state"), dict) else {}
        return {
            "type": "tool",
            "tool": data.get("tool", "unknown"),
            "status": state.get("status", "unknown"),
            "input": state.get("input"),
            "output": state.get("output"),
            "error": state.get("error"),
        }
    if part_type in {"file", "image", "attachment"}:
        return {
            "type": part_type,
            "filename": data.get("filename") or data.get("name"),
            "mime": data.get("mime") or data.get("mimeType"),
            "content_omitted": True,
        }
    return {"type": part_type, "status": data.get("status")}


def collect_transcript_evidence(
    period_start: str,
    period_end: str,
    *,
    project_directory: Path | None = None,
    exclude_session_ids: set[str] | None = None,
    exclude_title_prefixes: tuple[str, ...] = ("opencode improvement research ",),
    max_sessions: int = 100,
    max_messages: int = 2_000,
    max_parts: int = 2_000,
    max_field_chars: int = 4_000,
    max_total_bytes: int = 500_000,
    max_parts_per_message: int = 4,
) -> dict[str, Any]:
    """Collect bounded local transcript evidence for repository workflow research."""
    if min(max_sessions, max_messages, max_parts, max_field_chars, max_parts_per_message) <= 0:
        raise ValueError("transcript evidence limits must be positive")
    if max_total_bytes < MIN_TRANSCRIPT_EVIDENCE_BYTES:
        raise ValueError(f"max_total_bytes must be at least {MIN_TRANSCRIPT_EVIDENCE_BYTES}")
    start_ms = _epoch_ms(period_start)
    end_ms = _epoch_ms(period_end)
    if start_ms >= end_ms:
        raise ValueError("period_start must be earlier than period_end")

    excluded = exclude_session_ids or set()
    directory = str((project_directory or PROJECT_ROOT).resolve())
    worktree_pattern = f"{directory}/.openmates-agent-worktrees/%"
    exclusion_clauses: list[str] = []
    exclusion_parameters: list[Any] = []
    if excluded:
        placeholders = ", ".join("?" for _ in excluded)
        exclusion_clauses.append(f"id NOT IN ({placeholders})")
        exclusion_parameters.extend(sorted(excluded))
    normalized_prefixes = tuple(prefix.casefold() for prefix in exclude_title_prefixes)
    for prefix in normalized_prefixes:
        exclusion_clauses.append("LOWER(title) NOT LIKE ?")
        exclusion_parameters.append(prefix.replace("%", "\\%").replace("_", "\\_") + "%")
    exclusion_sql = "" if not exclusion_clauses else " AND " + " AND ".join(exclusion_clauses)
    truncated = {"sessions": False, "messages": False, "parts": False, "fields": False, "total_bytes": False}
    try:
        with _readonly_connection() as connection:
            query = (
                """
                SELECT id, parent_id, title, time_created, time_updated
                FROM session
                WHERE (directory = ? OR directory LIKE ?)
                  AND time_created < ? AND time_updated >= ?
                """
                + exclusion_sql
                + """
                ORDER BY time_updated ASC, id ASC
                LIMIT ?
                """
            )
            session_rows = connection.execute(
                query,
                (directory, worktree_pattern, end_ms, start_ms, *exclusion_parameters, max_sessions + 1),
            ).fetchall()
    except (OSError, sqlite3.Error) as exc:
        return {
            "status": "unavailable",
            "error": type(exc).__name__,
            "session_count": 0,
            "message_count": 0,
            "part_count": 0,
            "sessions": [],
            "limits": {
                "max_sessions": max_sessions,
                "max_messages": max_messages,
                "max_parts": max_parts,
                "max_field_chars": max_field_chars,
                "max_total_bytes": max_total_bytes,
                "max_parts_per_message": max_parts_per_message,
            },
            "truncated": truncated,
        }

    if len(session_rows) > max_sessions:
        truncated["sessions"] = True
        session_rows = session_rows[:max_sessions]
    parent_by_id = {
        str(session_id): str(parent_id) if parent_id else None
        for session_id, parent_id, _title, _created, _updated in session_rows
    }
    pending_parent_ids = {parent for parent in parent_by_id.values() if parent and parent not in parent_by_id}
    with _readonly_connection() as connection:
        while pending_parent_ids:
            parent_id = pending_parent_ids.pop()
            row = connection.execute("SELECT parent_id FROM session WHERE id = ?", (parent_id,)).fetchone()
            parent = str(row[0]) if row and row[0] else None
            parent_by_id[parent_id] = parent
            if parent and parent not in parent_by_id:
                pending_parent_ids.add(parent)

    def root_session_id(session_id: str) -> str:
        current = session_id
        seen = {current}
        while parent := parent_by_id.get(current):
            if parent in seen:
                break
            current = parent
            seen.add(current)
        return current

    def session_depth(session_id: str) -> int:
        current = session_id
        seen = {current}
        depth = 0
        while parent := parent_by_id.get(current):
            if parent in seen:
                break
            current = parent
            seen.add(current)
            depth += 1
        return depth

    selected_rows = [
        row
        for row in session_rows
        if str(row[0]) not in excluded
        and not str(row[2]).casefold().startswith(normalized_prefixes)
    ]
    selected_rows.sort(key=lambda row: (root_session_id(str(row[0])), session_depth(str(row[0])), int(row[4]), str(row[0])))
    sessions: list[dict[str, Any]] = []
    total_parts = 0
    total_messages = 0
    total_bytes = 0
    session_byte_budget = max(1, max_total_bytes // max(len(selected_rows), 1))
    session_message_budget = max(1, max_messages // max(len(selected_rows), 1))
    with _readonly_connection() as connection:
        for session_id, parent_id, title, time_created, time_updated in selected_rows:
            session_id = str(session_id)
            remaining_parts = max_parts - total_parts
            if remaining_parts <= 0:
                truncated["parts"] = True
                break
            message_rows = connection.execute(
                """
                SELECT id, time_created, data
                FROM message
                WHERE session_id = ? AND time_created < ? AND time_updated >= ?
                ORDER BY time_created ASC, id ASC
                LIMIT ?
                """,
                (session_id, end_ms, start_ms, session_message_budget + 1),
            ).fetchall()
            if len(message_rows) > session_message_budget:
                truncated["messages"] = True
                message_rows = message_rows[:session_message_budget]
            if len(message_rows) > 1:
                message_rows = [message_rows[0], *reversed(message_rows[1:])]
            messages: list[dict[str, Any]] = []
            session_bytes = 0
            for message_id, message_created, message_data in message_rows:
                part_rows = connection.execute(
                    """
                    SELECT time_created, data
                    FROM part
                    WHERE session_id = ? AND message_id = ? AND time_created < ? AND time_updated >= ?
                    ORDER BY time_created ASC, id ASC
                    LIMIT ?
                    """,
                    (
                        session_id,
                        str(message_id),
                        end_ms,
                        start_ms,
                        max(min(remaining_parts, max_parts_per_message), 1),
                    ),
                ).fetchall()
                parts = []
                for part_created, part_data in part_rows:
                    decoded_part = _decode_bounded_json(str(part_data), max_field_chars, truncated)
                    projected_part = _project_part_data(decoded_part)
                    if projected_part is not None:
                        parts.append({"time_created": int(part_created), "data": projected_part})
                decoded_message = _decode_bounded_json(str(message_data), max_field_chars, truncated)
                message = {
                    "time_created": int(message_created),
                    "data": _project_message_data(decoded_message),
                    "parts": parts,
                }
                candidate_bytes = len(json.dumps(message, ensure_ascii=False).encode("utf-8"))
                if session_bytes + candidate_bytes > session_byte_budget:
                    truncated["total_bytes"] = True
                    break
                messages.append(message)
                session_bytes += candidate_bytes
                total_bytes += candidate_bytes
                total_parts += len(parts)
                total_messages += 1
                remaining_parts = max_parts - total_parts
                if remaining_parts <= 0:
                    truncated["parts"] = True
                    break
            sessions.append(
                {
                    "session_id": session_id,
                    "parent_session_id": str(parent_id) if parent_id else None,
                    "root_session_id": root_session_id(session_id),
                    "title": _truncate_json(str(title), min(max_field_chars, 500), truncated),
                    "time_created": int(time_created),
                    "time_updated": int(time_updated),
                    "messages": messages,
                }
            )
            if truncated["parts"]:
                break

    result = {
        "status": "ok",
        "period": {"start": period_start, "end": period_end},
        "session_count": len(sessions),
        "message_count": total_messages,
        "part_count": total_parts,
        "sessions": sessions,
        "limits": {
            "max_sessions": max_sessions,
            "max_messages": max_messages,
            "max_parts": max_parts,
            "max_field_chars": max_field_chars,
            "max_total_bytes": max_total_bytes,
            "max_session_bytes": session_byte_budget,
            "max_session_messages": session_message_budget,
            "max_parts_per_message": max_parts_per_message,
        },
        "truncated": truncated,
    }
    while len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > max_total_bytes:
        session_with_messages = max(sessions, key=lambda item: len(item["messages"]), default=None)
        if session_with_messages and session_with_messages["messages"]:
            removed = session_with_messages["messages"].pop()
            total_messages -= 1
            total_parts -= len(removed["parts"])
            result["message_count"] = total_messages
            result["part_count"] = total_parts
            truncated["total_bytes"] = True
            continue
        if sessions:
            sessions.pop()
            result["session_count"] = len(sessions)
            truncated["sessions"] = True
            continue
        break
    if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > max_total_bytes:
        raise ValueError("transcript evidence envelope exceeds max_total_bytes")
    return result


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
