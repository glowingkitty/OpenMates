#!/usr/bin/env python3
"""Audit deterministic AI observability privacy and propagation invariants.

The audit prevents permissive exporter fallback, inactive WebSocket context,
missing worker tracing initialization, and loss of the required AI phase spans.
It reads source only and requires no credentials or running services.
Contract: architecture.ai-request-observability@1.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def main() -> int:
    failures: list[str] = []
    privacy = _read("backend/shared/python_utils/tracing/privacy_filter.py")
    ws_backend = _read("backend/shared/python_utils/tracing/ws_span_helper.py")
    ws_frontend = _read("frontend/packages/ui/src/services/websocketService.ts")
    worker = _read("backend/core/api/app/tasks/celery_config.py")
    ask_task = _read("backend/apps/ai/tasks/ask_skill_task.py")
    main_processor = _read("backend/apps/ai/processing/main_processor.py")
    stream_consumer = _read("backend/apps/ai/tasks/stream_consumer.py")

    required_privacy_tokens = (
        "DEFAULT_ALLOWED_ATTRS",
        "DIAGNOSTIC_ALLOWED_ATTRS",
        "if key in allowed",
        "def events(self)",
        "def links(self)",
        "def status(self)",
        "OTEL_DIAGNOSTIC_EXPIRES_AT",
    )
    for token in required_privacy_tokens:
        if token not in privacy:
            failures.append(f"privacy filter missing {token}")
    if 'server_env == "dev"' in privacy:
        failures.append("privacy filter must not bypass filtering on dev")
    if 'set_value("current-span"' in ws_backend or "set_span_in_context" not in ws_backend:
        failures.append("WebSocket handler must use standard active OTel span context")
    if "withActiveWsSpan(`send.${type}`" not in ws_frontend:
        failures.append("WebSocket transport must activate a send span before injection")
    if "setup_tracing(service_name=_worker_tracing_service_name())" not in worker:
        failures.append("Celery child process must initialize tracing")
    if 'return "worker-app-ai"' not in worker or 'else "worker-celery"' not in worker:
        failures.append("worker tracing service names must use the reviewed static mapping")
    for phase in ("turn", "preprocess", "main", "postprocess"):
        if f'ai_phase_span("{phase}")' not in ask_task:
            failures.append(f"AI task missing {phase} phase span")
    if 'observe_ai_stream(' not in main_processor or '"main.iteration"' not in main_processor:
        failures.append("main processor missing streamed iteration span")
    if 'ai_phase_span("tool")' not in main_processor:
        failures.append("main processor missing tool execution span")
    for phase in (
        "finalize.billing",
        "finalize.persistence",
        "finalize.validation",
        "finalize.marker",
    ):
        if f'ai_phase_span("{phase}")' not in stream_consumer:
            failures.append(f"stream consumer missing {phase} phase span")

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print("PASS: AI observability privacy and propagation invariants are present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
