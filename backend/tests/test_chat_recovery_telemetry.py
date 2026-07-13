"""Contracts for sanitized durable chat-recovery timing telemetry.

Recovery latency must be measurable without exposing encryption material or
message content in observability systems. These tests lock the phase allowlist
and the deliberately minimal structured log fields.
"""

from __future__ import annotations

import logging

import pytest

from backend.core.api.app.services import chat_recovery_telemetry


def test_recovery_duration_logs_only_phase_and_duration(caplog, monkeypatch) -> None:
    monkeypatch.setattr(chat_recovery_telemetry.time, "perf_counter", lambda: 3.25)
    with caplog.at_level(logging.INFO):
        duration_ms = chat_recovery_telemetry.record_recovery_duration(
            "durable_preflight",
            3.0,
        )

    assert duration_ms == 250.0
    record = caplog.records[-1]
    assert record.recovery_phase == "durable_preflight"
    assert record.duration_ms == 250.0
    assert "chat" not in record.__dict__
    assert "user" not in record.__dict__
    assert "payload" not in record.__dict__
    assert "key" not in record.__dict__


def test_recovery_duration_rejects_unknown_phase() -> None:
    with pytest.raises(ValueError, match="unsupported recovery timing phase"):
        chat_recovery_telemetry.record_recovery_duration("message", 0.0)


def test_recovery_duration_returns_when_logging_fails(monkeypatch) -> None:
    monkeypatch.setattr(chat_recovery_telemetry.time, "perf_counter", lambda: 3.25)

    def raise_logging_error(*args, **kwargs) -> None:
        raise RuntimeError("logging unavailable")

    monkeypatch.setattr(chat_recovery_telemetry.logger, "info", raise_logging_error)

    assert chat_recovery_telemetry.record_recovery_duration("durable_preflight", 3.0) == 250.0
