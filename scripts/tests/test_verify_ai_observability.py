# scripts/tests/test_verify_ai_observability.py
"""Tests for the aggregate AI observability baseline gate.

Fixtures contain only request-scoped trace identifiers, operation names, and
timestamps. They verify complete-day accounting without querying OpenObserve
or introducing private telemetry fields.
"""
# contract-test-file: tooling

from datetime import datetime, timezone

import scripts.verify_ai_observability as verifier
from scripts.verify_ai_observability import _evaluate_baseline


def _row(day: int, trace_id: str, operation: str) -> dict:
    observed = datetime(2026, 8, day, 12, tzinfo=timezone.utc)
    return {
        "_timestamp": int(observed.timestamp() * 1_000_000),
        "trace_id": trace_id,
        "operation_name": operation,
    }


def test_baseline_passes_only_when_every_day_has_complete_turns():
    required = {
        "ai.turn",
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
    }
    rows = [
        _row(day, f"trace-{day}", operation)
        for day in (22, 23, 24)
        for operation in required
    ]

    result = _evaluate_baseline(
        rows,
        days=3,
        now=datetime(2026, 8, 25, tzinfo=timezone.utc),
    )

    assert result["status"] == "passed"
    assert result["complete_days"] == 3
    assert [day["date"] for day in result["days"]] == [
        "2026-08-22",
        "2026-08-23",
        "2026-08-24",
    ]


def test_baseline_reports_missing_and_incomplete_days_as_pending():
    rows = [
        _row(24, "trace-complete-enough-to-detect", "ai.turn"),
        _row(24, "trace-complete-enough-to-detect", "ai.main"),
    ]

    result = _evaluate_baseline(
        rows,
        days=3,
        now=datetime(2026, 8, 25, tzinfo=timezone.utc),
    )

    assert result["status"] == "pending"
    assert result["complete_days"] == 0
    assert result["days"][-1]["incomplete_turn_count"] == 1


def test_baseline_probe_is_self_contained_for_api_container(monkeypatch):
    commands = []

    def capture(command):
        commands.append(command)
        return "[]"

    monkeypatch.setattr(verifier, "_run", capture)

    result = verifier.verify_baseline(days=7)

    assert result["status"] == "pending"
    assert commands[0][:4] == ["docker", "exec", "api", "python"]
    assert "http://openobserve:5080/api/default/_search?type=traces" in commands[0][-1]
    assert "from scripts" not in commands[0][-1]
