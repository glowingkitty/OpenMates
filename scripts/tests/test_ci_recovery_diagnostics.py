# contract-test-file: infrastructure
"""Failed recovery cases retain bounded worker evidence without public payloads."""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

from scripts import ci_environment


def _runner(monkeypatch):
    monkeypatch.setitem(sys.modules, "ci_environment", ci_environment)
    path = Path(__file__).resolve().parents[1] / "ci_run_tests.py"
    spec = importlib.util.spec_from_file_location("_recovery_diagnostic_runner", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _report(status="failed", start="2026-10-03T20:49:47.292Z", duration=120000):
    return {"suites": [{"specs": [{"tests": [{"results": [{
        "status": status, "startTime": start, "duration": duration,
    }]}]}]}]}


def test_recovery_log_window_is_exact_and_public_summary_has_no_payload(tmp_path, monkeypatch):
    runner = _runner(monkeypatch)
    monkeypatch.setattr(runner, "RESULTS", tmp_path)
    calls = []
    private_value = "private-synthetic-ciphertext-token"

    def fake_compose(*args, **_kwargs):
        calls.append(args)
        return SimpleNamespace(stdout=(
            "ai-worker | Traceback (most recent call last):\n"
            "ai-worker |   File \"/app/backend/apps/ai/processing/worker.py\", line 123, in dispatch\n"
            f"ai-worker | RuntimeError: {private_value}\n"
        ))

    monkeypatch.setattr(runner, "compose", fake_compose)
    summary = runner.capture_recovery_ai_diagnostics(_report(), 0)
    assert summary == [{"exception_class": "RuntimeError", "function": "dispatch", "line": 123}]
    assert private_value not in str(summary)
    assert calls[0][:2] == ("logs", "--no-color")
    assert calls[0][-1] == "ai-worker"
    assert "--since" in calls[0] and "--until" in calls[0]
    assert (tmp_path / "ci-private/recovery-ai-spec-0-result-0.log").read_text().endswith(private_value)


def test_recovery_log_bytes_and_lines_are_bounded(tmp_path, monkeypatch):
    runner = _runner(monkeypatch)
    monkeypatch.setattr(runner, "RESULTS", tmp_path)
    monkeypatch.setattr(runner, "compose", lambda *_args, **_kwargs: SimpleNamespace(
        stdout=("ai-worker | synthetic-log-line" + "x" * 180 + "\n") * 4000
    ))
    summary = runner.capture_recovery_ai_diagnostics(_report(), 1)
    retained = tmp_path / "ci-private/recovery-ai-spec-1-result-0.log"
    assert summary == [{"exception_class": "none", "function": "none", "line": 0}]
    assert retained.stat().st_size <= 200_000
    assert len(retained.read_text().splitlines()) <= 2000


def test_recovery_diagnostics_ignore_passes_and_reject_bad_case_windows(tmp_path, monkeypatch):
    runner = _runner(monkeypatch)
    monkeypatch.setattr(runner, "RESULTS", tmp_path)
    monkeypatch.setattr(runner, "compose", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("AI logs should not be requested")
    ))
    assert runner.capture_recovery_ai_diagnostics(_report(status="passed"), 0) == []
    assert runner.capture_recovery_ai_diagnostics(_report(start="bad-time"), 0) == [
        {"exception_class": "ValueError", "function": "none", "line": 0}
    ]
