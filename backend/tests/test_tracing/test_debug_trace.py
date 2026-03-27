"""
Tests for debug_trace.py — the trace CLI subcommand module.

Validates argument parsing for all 6 subcommands (request, errors, task,
session, slow, login), duration parsing, trace ID shortening, and the
indented span timeline formatter. No OpenObserve connection needed.

Bug history this test suite guards against:
  - Initial creation for Phase 06-04 (OTEL distributed trace CLI)
"""

import json
import os
import sys

import pytest

# ── Path bootstrap (mirrors debug_trace.py's own bootstrap) ──────────────────
_SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from debug_trace import (
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
