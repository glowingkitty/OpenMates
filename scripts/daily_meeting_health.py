#!/usr/bin/env python3
"""Reported issues and repeating errors of the production and dev servers for the daily meeting.

Both come from the existing admin debug tooling (`backend/scripts/debug.py` inside the `api`
container, which reaches production through the Admin Debug API):
  - `issue --list --json`: user and admin issue reports. Records also carry contact emails and
    share links with chat keys, so only the short id, title, age and status are kept here.
  - `logs --o2 --query-json`: ERROR/CRITICAL log rows of the last 24 h, grouped by message,
    then normalized (ids and numbers masked) so the same error counts once.
Docs: docs/contributing/guides/daily-meeting.md
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import html
import json
import re
import subprocess

DEBUG = ["docker", "exec", "api", "python", "/app/backend/scripts/debug.py"]
ISSUE_WINDOW_HOURS = 48
ISSUE_FETCH_LIMIT = 60
ROW_LIMIT = 1000
TOP_ERRORS = 10
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
TOKEN = re.compile(r"\b(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{12,}\b")
NUMBER = re.compile(r"\d+")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _run(args: list[str], timeout: int) -> str:
    return subprocess.run(DEBUG + args, capture_output=True, text=True, timeout=timeout, check=True).stdout


def _flags(production: bool) -> list[str]:
    return ["--production"] if production else ["--dev"]


def ago(moment: datetime, now: datetime) -> str:
    minutes = int((now - moment).total_seconds() // 60)
    if minutes < 90:
        return f"{max(minutes, 1)} min ago"
    if minutes < 48 * 60:
        return f"{minutes // 60} h ago"
    return f"{minutes // 1440} d ago"


def parse_issues(payload: dict, now: datetime, hours: int = ISSUE_WINDOW_HOURS) -> dict:
    """Recent issue reports (privacy-safe fields only) plus how many older ones are still open."""
    cutoff = now - timedelta(hours=hours)
    recent, older_open = [], 0
    for row in payload.get("issues", []):
        created = datetime.fromisoformat(str(row.get("created_at") or row.get("timestamp")))
        if created >= cutoff:
            title = re.sub(r"\s+", " ", EMAIL.sub("<email>", html.unescape(str(row.get("title") or "(no title)")))).strip()
            recent.append({"id": row.get("short_issue_id") or str(row.get("id", ""))[:8],
                           "title": title[:160], "age": ago(created, now), "created": created.isoformat(),
                           "processed": bool(row.get("processed")), "admin": bool(row.get("is_from_admin"))})
        elif not row.get("processed"):
            older_open += 1
    recent.sort(key=lambda item: item["created"], reverse=True)
    return {"recent": recent, "older_unprocessed_in_latest_batch": older_open}


def reported_issues(production: bool, gaps: list[str], now: datetime | None = None) -> dict | None:
    label = "production" if production else "dev"
    try:
        out = _run(["issue", "--list", "--json", "--list-limit", str(ISSUE_FETCH_LIMIT),
                    "--include-processed", *_flags(production)], timeout=120)
        payload = json.loads(out[out.index("{"):])
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        gaps.append(f"{label} reported issues unavailable ({type(error).__name__})")
        return None
    return parse_issues(payload, now or datetime.now(timezone.utc))


def normalize_error(row: dict) -> tuple[str, str, str]:
    """(service, logger, message) with ids and numbers masked so repeats group together."""
    raw = str(row.get("message", ""))
    logger_name, text = "", raw
    try:
        inner = json.loads(raw)
        if isinstance(inner, dict):
            logger_name, text = str(inner.get("name", "")), str(inner.get("message", raw))
    except ValueError:
        pass
    text = UUID.sub("<id>", text)
    text = TOKEN.sub("<id>", text)
    text = NUMBER.sub("<n>", text)
    text = EMAIL.sub("<email>", text)
    text = re.sub(r"\s+", " ", text).strip()
    short = ".".join(logger_name.split(".")[-2:]) if logger_name else ""
    return str(row.get("service", "")), short, text[:200]


def aggregate_errors(rows: list[dict], top: int = TOP_ERRORS) -> list[dict]:
    totals: Counter = Counter()
    for row in rows:
        totals[normalize_error(row)] += int(row.get("count", 1))
    return [{"count": count, "service": service, "where": where, "message": message}
            for (service, where, message), count in totals.most_common(top)]


def parse_query_rows(output: str) -> list[dict]:
    rows = []
    for line in output.splitlines():
        if line.startswith("- {"):
            try:
                rows.append(json.loads(line[2:]))
            except ValueError:
                continue
    return rows


def top_errors(production: bool, gaps: list[str]) -> dict | None:
    label = "production" if production else "dev"
    query = {"stream": "default", "mode": "count_by", "group_by": ["service", "message"],
             "filters": [{"field": "level", "op": "in", "value": ["ERROR", "CRITICAL"]}],
             "since_minutes": 1440, "limit": ROW_LIMIT}
    try:
        out = _run(["logs", *(["--prod"] if production else []), "--o2", "--raw",
                    "--query-json", json.dumps(query)], timeout=180)
    except (OSError, subprocess.SubprocessError) as error:
        gaps.append(f"{label} error log unavailable ({type(error).__name__})")
        return None
    rows = parse_query_rows(out)
    if not rows:
        return {"total": 0, "distinct": 0, "top": [], "truncated": False}
    top = aggregate_errors(rows)
    return {"total": sum(int(r.get("count", 1)) for r in rows),
            "distinct": len({normalize_error(r) for r in rows}), "top": top,
            "truncated": len(rows) >= ROW_LIMIT}


def collect_alerts(gaps: list[str]) -> dict:
    return {env: {"issues": reported_issues(env == "production", gaps),
                  "errors": top_errors(env == "production", gaps)} for env in ("production", "dev")}
