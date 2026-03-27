"""
Tests for debug_trace.py — the trace CLI subcommand module.

Validates argument parsing for all 7 subcommands (request, errors, task,
session, slow, login, recent), duration parsing, trace ID shortening,
the Unicode box-drawing span tree formatter, and full span tree fetching
via the SQL _search API.

Bug history this test suite guards against:
  - Initial creation for Phase 06-04 (OTEL distributed trace CLI)
  - Phase 09-03: trace errors/recent showed bare root spans because
    _get_latest_traces only returns first_event metadata (SHA: pending)
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# ── Path bootstrap (mirrors debug_trace.py's own bootstrap) ──────────────────
_SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from debug_trace import (
    _get_full_trace_spans,
    format_trace_timeline,
    parse_args,
    parse_duration,
    short_trace_id,
)


# ── parse_args tests ─────────────────────────────────────────────────────────


class TestParseArgs:
    """Argument parsing for all trace subcommands."""

    def test_request_by_id(self):
        args = parse_args(["request", "--id", "abc123"])
        assert args.command == "request"
        assert args.trace_id == "abc123"

    def test_errors_with_last(self):
        args = parse_args(["errors", "--last", "1h"])
        assert args.command == "errors"
        assert args.last == "1h"

    def test_task_by_id(self):
        args = parse_args(["task", "--id", "celery-uuid-123"])
        assert args.command == "task"
        assert args.task_id == "celery-uuid-123"

    def test_session_with_user_and_last(self):
        args = parse_args(["session", "--user", "test@example.com", "--last", "2h"])
        assert args.command == "session"
        assert args.user == "test@example.com"
        assert args.last == "2h"

    def test_slow_with_threshold_and_last(self):
        args = parse_args(["slow", "--threshold", "500", "--last", "30m"])
        assert args.command == "slow"
        assert args.threshold == 500
        assert args.last == "30m"

    def test_json_flag(self):
        args = parse_args(["errors", "--last", "1h", "--json"])
        assert args.json_output is True

    def test_production_flag(self):
        args = parse_args(["errors", "--last", "1h", "--production"])
        assert args.production is True

    def test_login_with_user(self):
        args = parse_args(["login", "--user", "admin@example.com"])
        assert args.command == "login"
        assert args.user == "admin@example.com"


# ── parse_duration tests ─────────────────────────────────────────────────────


class TestParseDuration:
    """Duration string parsing into seconds."""

    def test_hours(self):
        assert parse_duration("1h") == 3600

    def test_minutes(self):
        assert parse_duration("30m") == 1800

    def test_days(self):
        assert parse_duration("2d") == 172800

    def test_seconds(self):
        assert parse_duration("15s") == 15

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_duration("abc")

    def test_no_unit_raises(self):
        with pytest.raises(ValueError):
            parse_duration("100")


# ── short_trace_id tests ─────────────────────────────────────────────────────


class TestShortTraceId:
    """Trace ID truncation to first 12 characters."""

    def test_long_id(self):
        assert short_trace_id("abc123def456789xyz") == "abc123def456"

    def test_exact_12(self):
        assert short_trace_id("abc123def456") == "abc123def456"

    def test_short_id(self):
        assert short_trace_id("abc") == "abc"


# ── format_trace_timeline tests ──────────────────────────────────────────────


class TestFormatTraceTimeline:
    """Indented span hierarchy text output."""

    def test_single_root_span(self):
        spans = [
            {
                "trace_id": "aaaa1111bbbb2222",
                "span_id": "span-root",
                "parent_span_id": "",
                "start_time": 1711500000000000,  # microseconds
                "end_time": 1711500000500000,
                "service_name": "api",
                "operation_name": "POST /v1/ws",
                "span_status": "OK",
                "duration": 500000,  # microseconds
            }
        ]
        output = format_trace_timeline(spans)
        assert "aaaa1111bbbb" in output  # short trace id
        assert "api" in output
        assert "POST /v1/ws" in output
        assert "OK" in output

    def test_parent_child_indentation(self):
        spans = [
            {
                "trace_id": "trace001",
                "span_id": "root",
                "parent_span_id": "",
                "start_time": 1000000,
                "end_time": 2000000,
                "service_name": "api",
                "operation_name": "handle_request",
                "span_status": "OK",
                "duration": 1000000,
            },
            {
                "trace_id": "trace001",
                "span_id": "child1",
                "parent_span_id": "root",
                "start_time": 1100000,
                "end_time": 1500000,
                "service_name": "api",
                "operation_name": "db_query",
                "span_status": "OK",
                "duration": 400000,
            },
        ]
        output = format_trace_timeline(spans)
        lines = [l for l in output.split("\n") if l.strip()]
        # Child span should be indented more than root span
        root_line = [l for l in lines if "handle_request" in l][0]
        child_line = [l for l in lines if "db_query" in l][0]
        root_indent = len(root_line) - len(root_line.lstrip())
        child_indent = len(child_line) - len(child_line.lstrip())
        assert child_indent > root_indent

    def test_empty_spans(self):
        output = format_trace_timeline([])
        assert "No trace data" in output or output.strip() == ""

    def test_multiple_traces(self):
        spans = [
            {
                "trace_id": "traceAAA",
                "span_id": "s1",
                "parent_span_id": "",
                "start_time": 1000000,
                "end_time": 2000000,
                "service_name": "api",
                "operation_name": "op1",
                "span_status": "OK",
                "duration": 1000000,
            },
            {
                "trace_id": "traceBBB",
                "span_id": "s2",
                "parent_span_id": "",
                "start_time": 3000000,
                "end_time": 4000000,
                "service_name": "worker",
                "operation_name": "op2",
                "span_status": "ERROR",
                "duration": 1000000,
            },
        ]
        output = format_trace_timeline(spans)
        assert "traceAAA" in output or "Trace traceA" in output
        assert "traceBBB" in output or "Trace traceB" in output

    def test_unicode_tree_characters(self):
        """format_trace_timeline renders Unicode box-drawing chars (U+251C, U+2514)."""
        spans = [
            {
                "trace_id": "trace_tree",
                "span_id": "root",
                "parent_span_id": "",
                "start_time": 1000000,
                "end_time": 3000000,
                "service_name": "api",
                "operation_name": "GET /v1/chats",
                "span_status": "OK",
                "duration": 2000000,
            },
            {
                "trace_id": "trace_tree",
                "span_id": "child1",
                "parent_span_id": "root",
                "start_time": 1100000,
                "end_time": 1500000,
                "service_name": "directus",
                "operation_name": "get_chats",
                "span_status": "OK",
                "duration": 400000,
            },
            {
                "trace_id": "trace_tree",
                "span_id": "child2",
                "parent_span_id": "root",
                "start_time": 1600000,
                "end_time": 2800000,
                "service_name": "httpx",
                "operation_name": "post app-ai",
                "span_status": "OK",
                "duration": 1200000,
            },
        ]
        output = format_trace_timeline(spans)
        # Must contain Unicode box-drawing: ├ (U+251C) and └ (U+2514)
        assert "\u251c" in output, f"Missing ├ (U+251C) in output:\n{output}"
        assert "\u2514" in output, f"Missing └ (U+2514) in output:\n{output}"

    def test_span_line_shows_service_operation_duration_status(self):
        """Each span line shows service.operation (duration) status format."""
        spans = [
            {
                "trace_id": "trace_fmt",
                "span_id": "root",
                "parent_span_id": "",
                "start_time": 1000000,
                "end_time": 2000000,
                "service_name": "api",
                "operation_name": "GET /v1/chats",
                "span_status": "OK",
                "duration": 1000000,
            },
            {
                "trace_id": "trace_fmt",
                "span_id": "child1",
                "parent_span_id": "root",
                "start_time": 1100000,
                "end_time": 1500000,
                "service_name": "directus",
                "operation_name": "get_chats",
                "span_status": "OK",
                "duration": 400000,
            },
        ]
        output = format_trace_timeline(spans)
        # Child span line must contain service name, operation, duration in ms, and status
        child_lines = [l for l in output.split("\n") if "directus" in l]
        assert len(child_lines) == 1, f"Expected 1 directus line, got {len(child_lines)}"
        line = child_lines[0]
        assert "directus" in line
        assert "get_chats" in line
        assert "400ms" in line
        assert "OK" in line

    def test_trace_header_shows_root_operation(self):
        """Trace header includes root span operation name + total duration + status."""
        spans = [
            {
                "trace_id": "abc123def456789xyz",
                "span_id": "root",
                "parent_span_id": "",
                "start_time": 1000000,
                "end_time": 1234000,
                "service_name": "api",
                "operation_name": "GET /v1/chats",
                "span_status": "OK",
                "duration": 234000,
            },
        ]
        output = format_trace_timeline(spans)
        header = output.split("\n")[0]
        assert "abc123def456" in header  # short trace id
        assert "GET /v1/chats" in header  # root operation name
        assert "234ms" in header  # duration
        assert "OK" in header  # status

    def test_correct_nesting_via_parent_span_id(self):
        """Child spans nest under their parent using span_id/parent_span_id."""
        spans = [
            {
                "trace_id": "trace_nest",
                "span_id": "root",
                "parent_span_id": "",
                "start_time": 1000000,
                "end_time": 5000000,
                "service_name": "api",
                "operation_name": "GET /v1/chats",
                "span_status": "OK",
                "duration": 4000000,
            },
            {
                "trace_id": "trace_nest",
                "span_id": "child1",
                "parent_span_id": "root",
                "start_time": 1100000,
                "end_time": 2000000,
                "service_name": "httpx",
                "operation_name": "post app-ai",
                "span_status": "OK",
                "duration": 900000,
            },
            {
                "trace_id": "trace_nest",
                "span_id": "grandchild1",
                "parent_span_id": "child1",
                "start_time": 1200000,
                "end_time": 1800000,
                "service_name": "celery",
                "operation_name": "ask_skill",
                "span_status": "OK",
                "duration": 600000,
            },
        ]
        output = format_trace_timeline(spans)
        lines = [l for l in output.split("\n") if l.strip()]
        # Find the lines for each span
        httpx_line = [l for l in lines if "httpx" in l][0]
        celery_line = [l for l in lines if "celery" in l][0]
        # Grandchild must be indented deeper than child
        httpx_indent = len(httpx_line) - len(httpx_line.lstrip())
        celery_indent = len(celery_line) - len(celery_line.lstrip())
        assert celery_indent > httpx_indent, (
            f"Grandchild indent ({celery_indent}) should exceed child indent ({httpx_indent})"
        )


# ── parse_args recent subcommand tests ──────────────────────────────────────


class TestParseArgsRecent:
    """Argument parsing for the 'recent' subcommand."""

    def test_recent_subcommand_recognized(self):
        args = parse_args(["recent", "--last", "5m"])
        assert args.command == "recent"
        assert args.last == "5m"

    def test_recent_with_limit(self):
        args = parse_args(["recent", "--last", "1h", "--limit", "10"])
        assert args.command == "recent"
        assert args.limit == 10

    def test_recent_default_limit(self):
        args = parse_args(["recent", "--last", "5m"])
        assert args.limit == 25  # default

    def test_recent_json_flag(self):
        args = parse_args(["recent", "--last", "5m", "--json"])
        assert args.json_output is True

    def test_recent_production_flag(self):
        args = parse_args(["recent", "--last", "5m", "--production"])
        assert args.production is True


# ── _get_full_trace_spans tests ─────────────────────────────────────────────


class TestGetFullTraceSpans:
    """Verify _get_full_trace_spans uses SQL _search API, not /traces/latest."""

    def test_calls_search_api_not_traces_latest(self):
        """_get_full_trace_spans must POST to _search endpoint with SQL query."""
        import importlib
        import httpx as real_httpx

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "hits": [
                {"trace_id": "abc123", "span_id": "s1", "operation_name": "GET /v1/chats"}
            ]
        }

        with patch.object(real_httpx, "post", return_value=mock_response) as mock_post:
            result = _get_full_trace_spans(
                trace_id="abc123",
                start_time_us=1000000,
                end_time_us=9000000,
                base_url="http://localhost:5080",
                auth=("user", "pass"),
            )

            # Must call httpx.post (SQL _search), not httpx.get (traces/latest)
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            url = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
            assert "_search" in url, f"Expected _search in URL, got: {url}"
            assert "traces/latest" not in url, f"Must NOT use traces/latest, got: {url}"

            # Verify SQL contains trace_id filter
            body = call_args[1].get("json", {})
            sql = body.get("query", {}).get("sql", "")
            assert "abc123" in sql, f"SQL must filter by trace_id, got: {sql}"

            assert len(result) == 1
            assert result[0]["trace_id"] == "abc123"
