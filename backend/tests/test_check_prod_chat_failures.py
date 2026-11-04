"""Tests for the deterministic production chat-failure classifier."""

import importlib.util
import json
import sys
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "check_prod_chat_failures",
    Path(__file__).resolve().parents[1] / "scripts" / "check_prod_chat_failures.py",
)
checker = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = checker  # dataclasses resolve annotations via sys.modules
SPEC.loader.exec_module(checker)


def _log(service, name, message, level="ERROR"):
    return {"_timestamp": 1_793_600_000_000_000, "service": service,
            "message": json.dumps({"name": name, "level": level, "message": message})}


# contract-test: tooling
def test_trace_terminal_failures_are_impact_and_provider_errors_are_context():
    rows = [
        {"_timestamp": 1, "trace_id": "a" * 32, "ai_terminal_class": "failed_during_main"},
        {"_timestamp": 2, "trace_id": "b" * 32, "ai_phase": "provider", "ai_status_class": "error"},
        {"_timestamp": 3, "trace_id": "c" * 32, "ai_phase": "turn", "ai_status_class": "ok"},
        {"_timestamp": 4, "trace_id": "not-a-trace", "ai_terminal_class": "revoked"},
    ]
    signals = {s.label: s for s in checker.classify_trace_rows(rows).values()}
    assert signals["turn terminal_class=failed_during_main"].kind == "impact"
    assert signals["phase=provider status=error"].kind == "context"
    assert len(signals) == 2  # completed/revoked turns are not failures


# contract-test: tooling
def test_logs_only_count_allowlisted_server_loggers():
    rows = [
        _log("app-ai-worker", "backend.apps.ai.tasks.stream_consumer", "[Task ID: 9e3da64c-175b-42d9-b15b-f8b074e15908] boom 42"),
        _log("app-ai-worker", "backend.apps.ai.tasks.stream_consumer", "[Task ID: 11111111-175b-42d9-b15b-f8b074e15908] boom 7"),
        # User-controlled text logged by another logger must never count, even with marker text.
        _log("api", "backend.core.api.app.middleware.logging_middleware", "[TASK_LIFECYCLE] TASK_FAILED task_name=apps.ai.tasks.skill_ask"),
        _log("app-ai-worker", "backend.apps.ai.llm_providers.groq_client", "Groq API key not found"),
        _log("app-ai-worker", "backend.apps.ai.tasks.stream_consumer", "info line", level="INFO"),
        {"_timestamp": 1, "service": "app-ai-worker", "message": "[TASK_LIFECYCLE] TASK_FAILED raw non-json line"},
    ]
    signals = list(checker.classify_log_rows(rows).values())
    assert len(signals) == 1  # both stream_consumer lines normalize to one fingerprint
    assert signals[0].count == 2
    assert signals[0].samples[0] == "task:9e3da64c-175b-42d9-b15b-f8b074e15908"
    assert "boom" not in json.dumps(signals[0].as_dict())  # message text never leaves the checker


# contract-test: tooling
def test_report_orders_impact_first():
    report = checker.build_report(
        [{"_timestamp": 1, "trace_id": "b" * 32, "ai_phase": "tool", "ai_status_class": "error"}],
        [_log("app-ai-worker", "backend.apps.ai.processing.main_processor", "failed")],
        70,
    )
    assert report["ok"] is True
    assert [s["kind"] for s in report["signals"]] == ["impact", "context"]
    assert report["impact_count"] == 1
