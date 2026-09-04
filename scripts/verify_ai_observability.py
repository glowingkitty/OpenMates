#!/usr/bin/env python3
"""Verify deployed privacy-safe AI observability infrastructure.

The verifier checks OpenObserve retention and aggregate trace completeness from
the live dev containers without printing credentials or request identifiers.
Dashboard and alert verification remain blocked until the baseline passes.
Architecture: contracts/architecture/ai-request-observability/contract.yml
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import subprocess
import sys
from typing import Any


EXPECTED_RETENTION_DAYS = 14
MAX_RETENTION_DAYS = 30
OPENOBSERVE_CONTAINER = "openobserve"
API_CONTAINER = "api"
TRACE_STREAM = "default"
BASELINE_PAGE_SIZE = 1000
BASELINE_MAX_PAGES = 100
REQUIRED_PHASES = frozenset({
    "ai.queue",
    "ai.prepare",
    "ai.preprocess",
    "ai.main",
    "ai.main.iteration",
    "ai.provider",
    "ai.finalize.billing",
    "ai.finalize.persistence",
    "ai.finalize.validation",
    "ai.finalize.marker",
    "ai.postprocess",
})


def _run(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "command failed").strip())
    return result.stdout.strip()


def _container_config() -> dict[str, Any]:
    raw = _run(["docker", "inspect", OPENOBSERVE_CONTAINER])
    records = json.loads(raw)
    if len(records) != 1:
        raise RuntimeError("OpenObserve container inspection returned an unexpected result")
    return records[0].get("Config") or {}


def _global_retention_days(config: dict[str, Any]) -> int:
    prefix = "ZO_COMPACT_DATA_RETENTION_DAYS="
    values = [value[len(prefix):] for value in config.get("Env") or [] if value.startswith(prefix)]
    if len(values) != 1:
        raise RuntimeError("OpenObserve global retention is not configured exactly once")
    try:
        return int(values[0])
    except ValueError as exc:
        raise RuntimeError("OpenObserve global retention is not an integer") from exc


def _trace_stream_retention_days() -> int:
    probe = (
        "import json,os,httpx;"
        "r=httpx.get('http://openobserve:5080/api/default/streams',"
        "auth=(os.environ.get('OPENOBSERVE_ROOT_EMAIL',''),"
        "os.environ.get('OPENOBSERVE_ROOT_PASSWORD','')),timeout=30);"
        "r.raise_for_status();"
        "streams=[s for s in r.json().get('list',[]) "
        "if s.get('name')=='default' and s.get('stream_type')=='traces'];"
        "assert len(streams)==1, 'trace stream missing';"
        "print(int((streams[0].get('settings') or {}).get('data_retention') or 0))"
    )
    return int(_run(["docker", "exec", API_CONTAINER, "python", "-c", probe]))


def verify_retention() -> dict[str, Any]:
    config = _container_config()
    global_days = _global_retention_days(config)
    stream_days = _trace_stream_retention_days()
    effective_days = stream_days or global_days
    passed = effective_days == EXPECTED_RETENTION_DAYS and effective_days <= MAX_RETENTION_DAYS
    return {
        "status": "passed" if passed else "failed",
        "image": config.get("Image", "unknown"),
        "trace_stream": TRACE_STREAM,
        "stream_retention_days": stream_days,
        "inherits_global_retention": stream_days == 0,
        "global_retention_days": global_days,
        "effective_retention_days": effective_days,
        "policy_maximum_days": MAX_RETENTION_DAYS,
    }


def _baseline_probe(days: int, end_us: int) -> str:
    start_us = end_us - days * 24 * 60 * 60 * 1_000_000
    return f"""import json, os, httpx
auth = (os.environ.get("OPENOBSERVE_ROOT_EMAIL", ""), os.environ.get("OPENOBSERVE_ROOT_PASSWORD", ""))
url = "http://openobserve:5080/api/default/_search?type=traces"
sql = "SELECT _timestamp, trace_id, operation_name FROM default WHERE operation_name LIKE 'ai.%' ORDER BY _timestamp ASC"
rows = []
for page in range({BASELINE_MAX_PAGES}):
    body = {{"query": {{"sql": sql, "start_time": {start_us}, "end_time": {end_us}, "from": page * {BASELINE_PAGE_SIZE}, "size": {BASELINE_PAGE_SIZE}}}}}
    response = httpx.post(url, auth=auth, json=body, timeout=30)
    response.raise_for_status()
    page_rows = response.json().get("hits", [])
    rows.extend(page_rows)
    if len(page_rows) < {BASELINE_PAGE_SIZE}:
        break
else:
    raise RuntimeError("AI baseline exceeded the bounded 100,000-row query limit")
print(json.dumps(rows))
"""


def _evaluate_baseline(
    rows: list[dict[str, Any]],
    days: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    expected_days = [
        (current.date() - timedelta(days=offset)).isoformat()
        for offset in reversed(range(1, days + 1))
    ]
    traces_by_day: dict[str, dict[str, set[str]]] = {day: {} for day in expected_days}
    for row in rows:
        try:
            observed_at = datetime.fromtimestamp(int(row["_timestamp"]) / 1_000_000, timezone.utc)
        except (KeyError, TypeError, ValueError, OSError):
            continue
        day = observed_at.date().isoformat()
        if day not in traces_by_day:
            continue
        trace_id = str(row.get("trace_id") or "")
        operation = str(row.get("operation_name") or "")
        if trace_id and operation:
            traces_by_day[day].setdefault(trace_id, set()).add(operation)

    summaries = []
    complete_days = 0
    for day in expected_days:
        traces = traces_by_day[day]
        turn_traces = [phases for phases in traces.values() if "ai.turn" in phases]
        incomplete = sum(1 for phases in turn_traces if REQUIRED_PHASES - phases)
        complete = bool(turn_traces) and incomplete == 0
        complete_days += int(complete)
        summaries.append({
            "date": day,
            "turn_count": len(turn_traces),
            "incomplete_turn_count": incomplete,
            "complete": complete,
        })

    return {
        "status": "passed" if complete_days == days else "pending",
        "required_days": days,
        "complete_days": complete_days,
        "days": summaries,
    }


def verify_baseline(days: int) -> dict[str, Any]:
    window_end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    end_us = int(window_end.timestamp() * 1_000_000)
    probe = _baseline_probe(days, end_us)
    rows = json.loads(_run(["docker", "exec", API_CONTAINER, "python", "-c", probe]))
    return _evaluate_baseline(rows, days, now=window_end)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify AI observability infrastructure")
    parser.add_argument("command", choices=["retention", "baseline"])
    parser.add_argument("--target", choices=["dev"], default="dev")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args()

    try:
        if args.days < 1 or args.days > 30:
            raise ValueError("days must be between 1 and 30")
        result = verify_retention() if args.command == "retention" else verify_baseline(args.days)
    except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"AI observability verification failed: {exc}", file=sys.stderr)
        return 1

    if args.json_output:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        if args.command == "retention":
            print(
                f"{result['status'].upper()}: OpenObserve {result['image']} trace stream "
                f"retains data for {result['effective_retention_days']} days "
                f"(policy maximum {result['policy_maximum_days']} days)"
            )
        else:
            print(
                f"{result['status'].upper()}: {result['complete_days']}/"
                f"{result['required_days']} complete AI observability days"
            )
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
