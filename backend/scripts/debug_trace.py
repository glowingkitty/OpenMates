#!/usr/bin/env python3
"""
Distributed Trace CLI — OpenTelemetry trace inspection via OpenObserve.

Provides 7 subcommands for querying OTLP trace data stored in OpenObserve:
  request   — Single trace by trace ID
  errors    — Recent error traces (optionally filtered by route/fingerprint)
  task      — Celery task execution trace by task UUID
  session   — All traces for a user within a time window
  slow      — Traces exceeding a latency threshold
  login     — Login flow trace for a specific user
  recent    — All recent traces in a time window (not just errors)

All subcommands fetch full span trees via the SQL _search API and render
hierarchical output with Unicode box-drawing characters.

Architecture context: docs/architecture/admin-console-log-forwarding.md
Tests: backend/tests/test_tracing/test_debug_trace.py
"""

import argparse
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

# ── Path bootstrap ────────────────────────────────────────────────────────────
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

# ── Constants ─────────────────────────────────────────────────────────────────

# Duration multipliers for parse_duration
_DURATION_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_DURATION_RE = re.compile(r"^(\d+)([smhd])$")

# Short trace ID length (first 12 hex chars)
SHORT_TRACE_ID_LEN = 12

# Default OpenObserve connection settings
LOCAL_BASE_URL = "http://openobserve:5080"
PROD_BASE_URL = "http://openobserve-prod:5080"
OPENOBSERVE_ORG = "default"

# OTLP trace stream name in OpenObserve.
# NOTE: Exact stream name depends on OpenObserve OTLP ingestion config.
# Common names: "default" (catch-all), "traces" (dedicated OTLP stream).
# May need runtime discovery via /api/{org}/streams endpoint — see RESEARCH.md
# Open Question 2. Using "default" as initial assumption.
TRACE_STREAM = "default"

# Maximum results per query
DEFAULT_QUERY_LIMIT = 50
SESSION_QUERY_LIMIT = 100
RECENT_DEFAULT_LIMIT = 25

# Unicode box-drawing characters for span tree rendering
TREE_BRANCH = "\u251c\u2500"   # ├─  (middle child)
TREE_LAST = "\u2514\u2500"     # └─  (last child)
TREE_PIPE = "\u2502  "         # │   (vertical continuation)
TREE_SPACE = "   "             # spaces (no continuation)


# ── Duration parsing ─────────────────────────────────────────────────────────


def parse_duration(s: str) -> int:
    """Parse a duration string like '1h', '30m', '2d', '15s' into seconds.

    Args:
        s: Duration string matching pattern '<number><s|m|h|d>'.

    Returns:
        Duration in seconds.

    Raises:
        ValueError: If the string does not match the expected pattern.
    """
    match = _DURATION_RE.match(s)
    if not match:
        raise ValueError(
            f"Invalid duration '{s}'. Expected format: <number><s|m|h|d> "
            f"(e.g. '1h', '30m', '2d', '15s')"
        )
    value = int(match.group(1))
    unit = match.group(2)
    return value * _DURATION_UNITS[unit]


# ── Trace ID helpers ─────────────────────────────────────────────────────────


def short_trace_id(trace_id: str) -> str:
    """Return the first 12 characters of a trace ID for display."""
    return trace_id[:SHORT_TRACE_ID_LEN]


# ── Argument parsing ─────────────────────────────────────────────────────────


def parse_args(argv: List[str]) -> argparse.Namespace:
    """Parse trace CLI arguments into a Namespace.

    Args:
        argv: Argument list (without the 'trace' prefix from debug.py).

    Returns:
        Parsed argparse.Namespace with 'command' attribute and
        subcommand-specific fields.
    """
    parser = argparse.ArgumentParser(
        prog="debug.py trace",
        description="Distributed trace inspection (OpenTelemetry via OpenObserve)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ── request ───────────────────────────────────────────────────────────
    req = subparsers.add_parser("request", help="Single trace by trace ID")
    req.add_argument("--id", dest="trace_id", required=True, help="Trace ID (full or prefix)")
    req.add_argument("--json", dest="json_output", action="store_true", help="JSON output")
    req.add_argument("--production", action="store_true", help="Query production OpenObserve")

    # ── errors ────────────────────────────────────────────────────────────
    err = subparsers.add_parser("errors", help="Recent error traces")
    err.add_argument("--last", required=True, help="Time window (e.g. 1h, 30m, 2d)")
    err.add_argument("--route", help="Filter by route pattern")
    err.add_argument("--fingerprint", help="Filter by error fingerprint hash")
    err.add_argument("--json", dest="json_output", action="store_true", help="JSON output")
    err.add_argument("--production", action="store_true", help="Query production OpenObserve")

    # ── task ──────────────────────────────────────────────────────────────
    tsk = subparsers.add_parser("task", help="Celery task execution trace")
    tsk.add_argument("--id", dest="task_id", required=True, help="Celery task UUID")
    tsk.add_argument("--json", dest="json_output", action="store_true", help="JSON output")
    tsk.add_argument("--production", action="store_true", help="Query production OpenObserve")

    # ── session ───────────────────────────────────────────────────────────
    ses = subparsers.add_parser("session", help="User session traces")
    ses.add_argument("--user", required=True, help="User email")
    ses.add_argument("--last", required=True, help="Time window (e.g. 2h, 1d)")
    ses.add_argument("--json", dest="json_output", action="store_true", help="JSON output")
    ses.add_argument("--production", action="store_true", help="Query production OpenObserve")

    # ── slow ──────────────────────────────────────────────────────────────
    slw = subparsers.add_parser("slow", help="Slow traces above threshold")
    slw.add_argument("--threshold", type=int, required=True, help="Threshold in milliseconds")
    slw.add_argument("--last", required=True, help="Time window (e.g. 1h, 30m)")
    slw.add_argument("--json", dest="json_output", action="store_true", help="JSON output")
    slw.add_argument("--production", action="store_true", help="Query production OpenObserve")

    # ── login ─────────────────────────────────────────────────────────────
    lgn = subparsers.add_parser("login", help="Login flow trace for a user")
    lgn.add_argument("--user", required=True, help="User email")
    lgn.add_argument("--json", dest="json_output", action="store_true", help="JSON output")
    lgn.add_argument("--production", action="store_true", help="Query production OpenObserve")

    # ── recent ────────────────────────────────────────────────────────────
    rec = subparsers.add_parser("recent", help="All recent traces (not just errors)")
    rec.add_argument("--last", required=True, help="Time window (e.g. 5m, 1h)")
    rec.add_argument("--limit", type=int, default=RECENT_DEFAULT_LIMIT, help="Max traces to show")
    rec.add_argument("--json", dest="json_output", action="store_true", help="JSON output")
    rec.add_argument("--production", action="store_true", help="Query production OpenObserve")

    return parser.parse_args(argv)


# ── OpenObserve connection ───────────────────────────────────────────────────


def _get_base_url(production: bool = False) -> str:
    """Return the OpenObserve base URL for local or production environment.

    Args:
        production: If True, use production endpoint.

    Returns:
        Base URL string (no trailing slash).
    """
    if production:
        return os.getenv("OPENOBSERVE_PROD_URL", PROD_BASE_URL)
    return os.getenv("OPENOBSERVE_URL", LOCAL_BASE_URL)


def _get_auth(production: bool = False) -> Tuple[str, str]:
    """Return (email, password) credentials for OpenObserve Basic auth.

    Args:
        production: If True, use production credentials env vars.

    Returns:
        Tuple of (email, password).
    """
    if production:
        return (
            os.getenv("OPENOBSERVE_PROD_EMAIL", ""),
            os.getenv("OPENOBSERVE_PROD_PASSWORD", ""),
        )
    return (
        os.getenv("OPENOBSERVE_ROOT_EMAIL", ""),
        os.getenv("OPENOBSERVE_ROOT_PASSWORD", ""),
    )


def _get_latest_traces(
    start_time_us: int,
    end_time_us: int,
    base_url: str,
    auth: Tuple[str, str],
    size: int = DEFAULT_QUERY_LIMIT,
    filter_str: str = "",
) -> List[Dict[str, Any]]:
    """Fetch latest traces from OpenObserve traces/latest API.

    This endpoint returns trace-level summaries (not individual spans).
    Each result contains a trace_id that can be used with
    _get_full_trace_spans to fetch the complete span tree.

    Args:
        start_time_us: Query window start in microseconds since epoch.
        end_time_us: Query window end in microseconds since epoch.
        base_url: OpenObserve base URL.
        auth: Tuple of (email, password) for Basic auth.
        size: Number of traces to return.
        filter_str: Optional filter query string for traces.

    Returns:
        List of trace dicts from the response. Empty list on error.
    """
    import httpx
    from urllib.parse import quote

    url = (
        f"{base_url}/api/{OPENOBSERVE_ORG}/{TRACE_STREAM}/traces/latest"
        f"?start_time={start_time_us}&end_time={end_time_us}"
        f"&from=0&size={size}&filter={quote(filter_str)}"
    )

    try:
        response = httpx.get(url, auth=auth, timeout=30.0)
        if response.status_code == 200:
            data = response.json()
            return data.get("hits", [])
        else:
            print(
                f"OpenObserve trace query failed (status={response.status_code}): "
                f"{response.text[:300]}",
                file=sys.stderr,
            )
            return []
    except Exception as exc:
        print(f"Error querying OpenObserve traces: {exc}", file=sys.stderr)
        return []


def _get_full_trace_spans(
    trace_id: str,
    start_time_us: int,
    end_time_us: int,
    base_url: str,
    auth: Tuple[str, str],
) -> List[Dict[str, Any]]:
    """Fetch ALL spans for a trace via the SQL _search API.

    Unlike _get_latest_traces (which returns trace summaries with only
    first_event metadata), this function returns every individual span
    for a given trace_id — enabling full hierarchical tree rendering.

    Args:
        trace_id: Full trace ID string.
        start_time_us: Query window start in microseconds since epoch.
        end_time_us: Query window end in microseconds since epoch.
        base_url: OpenObserve base URL.
        auth: Tuple of (email, password) for Basic auth.

    Returns:
        List of span dicts with span_id, parent_span_id, etc. Empty list on error.
    """
    import httpx

    url = f"{base_url}/api/{OPENOBSERVE_ORG}/_search?type=traces"
    sql = (
        f"SELECT * FROM {TRACE_STREAM} "
        f"WHERE trace_id = '{trace_id}' "
        f"ORDER BY start_time ASC"
    )
    body = {
        "query": {
            "sql": sql,
            "start_time": start_time_us,
            "end_time": end_time_us,
        }
    }

    try:
        response = httpx.post(url, json=body, auth=auth, timeout=30.0)
        if response.status_code == 200:
            data = response.json()
            return data.get("hits", [])
        else:
            print(
                f"OpenObserve span search failed (status={response.status_code}): "
                f"{response.text[:300]}",
                file=sys.stderr,
            )
            return []
    except Exception as exc:
        print(f"Error fetching spans for trace {trace_id}: {exc}", file=sys.stderr)
        return []


def _search_traces_sql(
    sql: str,
    start_time_us: int,
    end_time_us: int,
    base_url: str,
    auth: Tuple[str, str],
) -> List[Dict[str, Any]]:
    """Execute a SQL query against the trace stream via _search API.

    Used for direct span queries (errors, task lookup, session, etc.)
    where we need individual span records rather than trace summaries.

    Args:
        sql: SQL query string for OpenObserve.
        start_time_us: Query window start in microseconds since epoch.
        end_time_us: Query window end in microseconds since epoch.
        base_url: OpenObserve base URL.
        auth: Tuple of (email, password) for Basic auth.

    Returns:
        List of hit dicts from the search response. Empty list on error.
    """
    import httpx

    url = f"{base_url}/api/{OPENOBSERVE_ORG}/_search?type=traces"
    body = {
        "query": {
            "sql": sql,
            "start_time": start_time_us,
            "end_time": end_time_us,
        }
    }

    try:
        response = httpx.post(url, json=body, auth=auth, timeout=30.0)
        if response.status_code == 200:
            data = response.json()
            return data.get("hits", [])
        else:
            print(
                f"OpenObserve search failed (status={response.status_code}): "
                f"{response.text[:300]}",
                file=sys.stderr,
            )
            return []
    except Exception as exc:
        print(f"Error querying OpenObserve: {exc}", file=sys.stderr)
        return []


# Keep legacy name as alias for backwards compatibility
_search_traces_legacy = _search_traces_sql


def _collect_full_spans(
    traces: List[Dict[str, Any]],
    start_time_us: int,
    end_time_us: int,
    base_url: str,
    auth: Tuple[str, str],
) -> List[Dict[str, Any]]:
    """For each trace summary, fetch all spans via _get_full_trace_spans.

    This replaces the broken pattern of extracting first_event from trace
    summaries. Instead, we get the complete span tree for every trace.

    Args:
        traces: List of trace summary dicts from _get_latest_traces.
        start_time_us: Query window start in microseconds since epoch.
        end_time_us: Query window end in microseconds since epoch.
        base_url: OpenObserve base URL.
        auth: Tuple of (email, password) for Basic auth.

    Returns:
        List of all span dicts across all traces (ready for format_trace_timeline).
    """
    all_spans: List[Dict[str, Any]] = []
    seen_trace_ids: set = set()

    for trace in traces:
        # Extract trace_id from summary — may be top-level or inside first_event
        trace_id = trace.get("trace_id", "")
        if not trace_id:
            fe = trace.get("first_event", {})
            trace_id = fe.get("trace_id", "")
        if not trace_id or trace_id in seen_trace_ids:
            continue
        seen_trace_ids.add(trace_id)

        spans = _get_full_trace_spans(
            trace_id, start_time_us, end_time_us, base_url, auth
        )
        all_spans.extend(spans)

    return all_spans


# ── Timeline formatter ──────────────────────────────────────────────────────


def format_trace_timeline(spans: List[Dict[str, Any]]) -> str:
    """Format spans into a Unicode tree timeline grouped by trace.

    Builds a parent-child hierarchy using span_id / parent_span_id,
    then renders each span with Unicode box-drawing characters showing
    the tree structure. Each span line shows service.operation (duration) status.

    Output format per D-03:
        Trace abc123 -- GET /v1/chats (234ms) OK
          ├─ directus.get_chats (45ms) OK
          ├─ redis.get cache:chats (2ms) OK
          └─ httpx.post app-ai (180ms) OK
              └─ celery.task ask_skill (170ms) OK

    Args:
        spans: List of span dicts from OpenObserve search results.

    Returns:
        Formatted multi-line string showing the trace timeline.
    """
    if not spans:
        return "No trace data found."

    # Group spans by trace_id
    traces: Dict[str, List[Dict[str, Any]]] = {}
    for span in spans:
        tid = span.get("trace_id", "unknown")
        traces.setdefault(tid, []).append(span)

    output_lines: List[str] = []

    for trace_id, trace_spans in traces.items():
        # Build span lookup and child map
        span_map: Dict[str, Dict[str, Any]] = {}
        children: Dict[str, List[str]] = {}
        root_ids: List[str] = []

        for span in trace_spans:
            sid = span.get("span_id", "")
            parent = span.get("parent_span_id", "")
            span_map[sid] = span

            if not parent or parent not in {s.get("span_id") for s in trace_spans}:
                root_ids.append(sid)
            else:
                children.setdefault(parent, []).append(sid)

        # Calculate total trace duration from root spans
        all_starts = [s.get("start_time", 0) for s in trace_spans]
        all_ends = [s.get("end_time", s.get("start_time", 0)) for s in trace_spans]
        total_duration_us = max(all_ends) - min(all_starts) if all_starts else 0
        total_duration_ms = total_duration_us / 1000.0

        # Determine overall status (ERROR if any span has error)
        overall_status = "OK"
        for span in trace_spans:
            if span.get("span_status", "").upper() == "ERROR":
                overall_status = "ERROR"
                break

        # Find root span operation name for trace header
        root_operation = "unknown"
        if root_ids:
            root_span = span_map.get(root_ids[0], {})
            root_operation = root_span.get(
                "operation_name", root_span.get("name", "unknown")
            )

        # Trace header with root operation name (per D-03)
        output_lines.append(
            f"Trace {short_trace_id(trace_id)} -- "
            f"{root_operation} ({total_duration_ms:.0f}ms) {overall_status}"
        )

        # Sort root spans by start_time
        root_ids.sort(key=lambda sid: span_map[sid].get("start_time", 0))

        # Recursive depth-first render with Unicode tree characters
        def _render_span(sid: str, prefix: str, is_last: bool) -> None:
            """Render a single span and its children with tree connectors.

            Args:
                sid: Span ID to render.
                prefix: Accumulated prefix string for indentation/tree lines.
                is_last: Whether this span is the last sibling at its level.
            """
            span = span_map.get(sid)
            if not span:
                return

            duration_us = span.get("duration", 0)
            duration_ms = duration_us / 1000.0
            service = span.get("service_name", span.get("service", "???"))
            operation = span.get("operation_name", span.get("name", "???"))
            status = span.get("span_status", "OK")

            # Choose connector: └─ for last child, ├─ for middle children
            connector = TREE_LAST if is_last else TREE_BRANCH

            output_lines.append(
                f"{prefix}{connector} {service}.{operation} "
                f"({duration_ms:.0f}ms) {status}"
            )

            # Build prefix for children: │ continues if not last, spaces if last
            child_prefix = prefix + (TREE_SPACE if is_last else TREE_PIPE)

            # Render children sorted by start_time
            child_ids = children.get(sid, [])
            child_ids.sort(key=lambda cid: span_map[cid].get("start_time", 0))
            for i, child_id in enumerate(child_ids):
                _render_span(child_id, child_prefix, is_last=(i == len(child_ids) - 1))

        for i, root_id in enumerate(root_ids):
            _render_span(root_id, "  ", is_last=(i == len(root_ids) - 1))

        output_lines.append("")  # Blank line between traces

    return "\n".join(output_lines).rstrip()


def format_json(spans: List[Dict[str, Any]]) -> str:
    """Format spans as pretty-printed JSON.

    Args:
        spans: List of span dicts from OpenObserve search results.

    Returns:
        JSON string.
    """
    return json.dumps(spans, indent=2, default=str)


# ── Command dispatch ─────────────────────────────────────────────────────────


def _time_range(duration_s: int) -> Tuple[int, int]:
    """Calculate (start_time_us, end_time_us) for a lookback window.

    Args:
        duration_s: Lookback duration in seconds.

    Returns:
        Tuple of (start_time_us, end_time_us) in microseconds since epoch.
    """
    now_us = int(time.time() * 1_000_000)
    start_us = now_us - (duration_s * 1_000_000)
    return start_us, now_us


def main(argv: Optional[List[str]] = None) -> None:
    """Entry point for the trace CLI subcommand.

    Parses arguments, executes the appropriate OpenObserve query,
    and prints formatted output to stdout. All commands fetch full
    span trees via the SQL _search API for hierarchical display.

    Args:
        argv: Argument list. If None, uses sys.argv[1:].
    """
    if argv is None:
        argv = sys.argv[1:]

    args = parse_args(argv)
    base_url = _get_base_url(args.production)
    auth = _get_auth(args.production)
    use_json = getattr(args, "json_output", False)

    if args.production and (not auth[0] or not auth[1]):
        print(
            "Production OpenObserve not configured. "
            "Set OPENOBSERVE_PROD_URL, OPENOBSERVE_PROD_EMAIL, "
            "OPENOBSERVE_PROD_PASSWORD env vars.",
            file=sys.stderr,
        )
        print("No trace data found.")
        return

    # Default lookback for commands that don't have --last
    default_lookback_s = 3600  # 1 hour

    if args.command == "request":
        # Fetch all spans for a specific trace ID via SQL _search
        start_us, end_us = _time_range(7 * 86400)  # 7-day window
        spans = _get_full_trace_spans(args.trace_id, start_us, end_us, base_url, auth)

    elif args.command == "errors":
        duration_s = parse_duration(args.last)
        start_us, end_us = _time_range(duration_s)
        # Get error trace summaries, then fetch full span trees for each
        filter_parts = ["span_status = 'ERROR'"]
        if getattr(args, "route", None):
            filter_parts.append(f"operation_name LIKE '%{args.route}%'")
        traces = _get_latest_traces(
            start_us, end_us, base_url, auth,
            filter_str=" AND ".join(filter_parts),
        )
        spans = _collect_full_spans(traces, start_us, end_us, base_url, auth)

    elif args.command == "task":
        # Celery task lookup — get trace summaries, then full span trees.
        # OTel Celery instrumentor stores the task UUID as messaging_message_id
        # (not celery_task_id). OpenObserve flattens dotted OTel attribute
        # names to underscores, so celery.task_id → celery_task_id, but that
        # field is only set on some span types. messaging_message_id is the
        # reliable field present on all celery run/apply_async spans.
        start_us, end_us = _time_range(7 * 86400)
        traces = _get_latest_traces(
            start_us, end_us, base_url, auth,
            filter_str=f"messaging_message_id = '{args.task_id}'",
        )
        spans = _collect_full_spans(traces, start_us, end_us, base_url, auth)

    elif args.command == "session":
        duration_s = parse_duration(args.last)
        start_us, end_us = _time_range(duration_s)
        # OpenObserve flattens dotted attribute names: enduser.id → enduser_id
        traces = _get_latest_traces(
            start_us, end_us, base_url, auth,
            filter_str=f"enduser_id LIKE '%{args.user}%'",
        )
        spans = _collect_full_spans(traces, start_us, end_us, base_url, auth)

    elif args.command == "slow":
        duration_s = parse_duration(args.last)
        threshold_us = args.threshold * 1000  # ms to us
        start_us, end_us = _time_range(duration_s)
        traces = _get_latest_traces(
            start_us, end_us, base_url, auth,
            filter_str=f"duration > {threshold_us}",
        )
        spans = _collect_full_spans(traces, start_us, end_us, base_url, auth)

    elif args.command == "login":
        start_us, end_us = _time_range(default_lookback_s)
        traces = _get_latest_traces(
            start_us, end_us, base_url, auth,
            filter_str=f"enduser.id LIKE '%{args.user}%' AND operation_name LIKE '%login%'",
        )
        spans = _collect_full_spans(traces, start_us, end_us, base_url, auth)

    elif args.command == "recent":
        duration_s = parse_duration(args.last)
        start_us, end_us = _time_range(duration_s)
        limit = getattr(args, "limit", RECENT_DEFAULT_LIMIT)
        traces = _get_latest_traces(
            start_us, end_us, base_url, auth, size=limit,
        )
        spans = _collect_full_spans(traces, start_us, end_us, base_url, auth)

    else:
        print(f"Unknown trace command: {args.command}", file=sys.stderr)
        sys.exit(1)

    # Format and print output
    if use_json:
        print(format_json(spans))
    else:
        print(format_trace_timeline(spans))


if __name__ == "__main__":
    main()
