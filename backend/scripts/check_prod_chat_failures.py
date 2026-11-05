#!/usr/bin/env python3
"""
Deterministic detector for real chat-processing failures on production.

Runs on the dev server inside the ``api`` container (which holds the Admin
Debug API key in Vault) and queries production OpenObserve through
``/v1/admin/debug/o2/search``. It prints one JSON document that the host-side
``scripts/claude_dispatch.py prod-errors`` consumes to decide whether to open
an investigation chat.

Why this cannot be triggered by prompt injection:
- Trace signals use structured span attributes (``ai_phase``,
  ``ai_status_class``, ``ai_terminal_class``) that server code sets from
  reviewed enums (backend/shared/python_utils/tracing/ai_observability.py);
  user or model text never becomes an attribute value.
- Log signals use only the server-set JSON ``name`` (logger) and ``level`` of
  lines emitted by allowlisted chat-pipeline loggers on allowlisted services.
  Free-text matching is never used, because request query strings and other
  user-controlled text are logged verbatim elsewhere.
- Log message text is reduced to a one-way fingerprint and never emitted, so
  the downstream Claude prompt contains no attacker-controlled text.

A failed or partial query exits 2 instead of reporting "no failures".

Usage:
  docker exec api python /app/backend/scripts/check_prod_chat_failures.py --since-minutes 70
Architecture: docs/architecture/infrastructure/claude-dispatch.md
Tests: backend/tests/test_check_prod_chat_failures.py
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

TRACE_STREAM = "default"
LOG_STREAM = "default"

# Phases whose error status means the user saw a failed or missing answer.
IMPACT_PHASES = frozenset({
    "turn", "queue", "setup", "prepare", "preprocess", "pre_main", "main",
    "main.response_finalize", "postprocess", "postprocess.delivery",
    "finalize.marker", "finalize.billing", "finalize.validation", "finalize.persistence",
})
# Recoverable sub-steps (provider fallback, retried iterations, tool calls).
CONTEXT_PHASES = frozenset({"provider", "main.iteration", "tool"})
FAILED_TERMINAL_CLASSES = frozenset({
    "failed_before_main", "failed_during_main", "billing_failed", "soft_limited", "worker_interrupted",
})

CHAT_SERVICES = frozenset({"app-ai-worker", "app-ai-routing-worker", "api"})
# (service set, logger-name prefix). The API only counts for chat dispatch handlers.
CHAT_LOGGERS: tuple[tuple[frozenset[str], str], ...] = (
    (frozenset({"app-ai-worker", "app-ai-routing-worker"}), "backend.apps.ai.tasks."),
    (frozenset({"app-ai-worker", "app-ai-routing-worker"}), "backend.apps.ai.processing."),
    (frozenset({"app-ai-worker", "app-ai-routing-worker"}), "backend.apps.ai.skills.ask_skill"),
    (frozenset({"app-ai-worker", "app-ai-routing-worker"}), "backend.core.api.app.tasks.celery_config"),
    (frozenset({"api"}), "backend.core.api.app.routes.handlers.websocket_handlers.message_received_handler"),
)

_NORMALIZE_RE = re.compile(r"[0-9a-fA-F]{8,}(?:-[0-9a-fA-F]{4,})*|\d+")
_QUOTED_RE = re.compile(r"'[^']*'|\"[^\"]*\"")
_TASK_ID_RE = re.compile(r"\[Task ID: ([0-9a-fA-F-]{36})")
_TRACE_ID_RE = re.compile(r"^[0-9a-f]{32}$")


@dataclass
class Signal:
    fingerprint: str
    source: str  # "trace" | "log"
    kind: str  # "impact" | "context"
    label: str  # server-defined identifier only (phase/class or logger name)
    count: int = 0
    first_seen_us: int = 0
    last_seen_us: int = 0
    samples: list[str] = field(default_factory=list)

    def add(self, timestamp_us: int, sample: str | None) -> None:
        self.count += 1
        self.first_seen_us = min(self.first_seen_us or timestamp_us, timestamp_us)
        self.last_seen_us = max(self.last_seen_us, timestamp_us)
        if sample and sample not in self.samples and len(self.samples) < 5:
            self.samples.append(sample)

    def as_dict(self) -> dict[str, Any]:
        def iso(us: int) -> str:
            return datetime.fromtimestamp(us / 1_000_000, tz=timezone.utc).isoformat() if us else ""
        return {
            "fingerprint": self.fingerprint, "source": self.source, "kind": self.kind,
            "label": self.label, "count": self.count, "first_seen": iso(self.first_seen_us),
            "last_seen": iso(self.last_seen_us), "samples": self.samples,
        }


def _fingerprint(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def classify_trace_rows(rows: Iterable[dict[str, Any]]) -> dict[str, Signal]:
    signals: dict[str, Signal] = {}
    for row in rows:
        phase = str(row.get("ai_phase") or "")
        status = str(row.get("ai_status_class") or "")
        terminal = str(row.get("ai_terminal_class") or "")
        if terminal in FAILED_TERMINAL_CLASSES:
            label, kind = f"turn terminal_class={terminal}", "impact"
        elif status == "error" and phase in IMPACT_PHASES:
            label, kind = f"phase={phase} status=error", "impact"
        elif status == "error" and phase in CONTEXT_PHASES:
            label, kind = f"phase={phase} status=error", "context"
        else:
            continue
        key = _fingerprint("trace", label)
        signal = signals.setdefault(key, Signal(key, "trace", kind, label))
        trace_id = str(row.get("trace_id") or "")
        signal.add(int(row.get("_timestamp") or 0), trace_id if _TRACE_ID_RE.match(trace_id) else None)
    return signals


def _allowed_logger(service: str, logger_name: str) -> bool:
    return any(service in services and logger_name.startswith(prefix) for services, prefix in CHAT_LOGGERS)


def classify_log_rows(rows: Iterable[dict[str, Any]]) -> dict[str, Signal]:
    signals: dict[str, Signal] = {}
    for row in rows:
        service = str(row.get("service") or "")
        try:
            line = json.loads(str(row.get("message") or ""))
        except json.JSONDecodeError:
            continue  # Raw (non-JSON-formatter) lines carry no trustworthy logger name.
        if not isinstance(line, dict):
            continue
        logger_name = str(line.get("name") or "")
        level = str(line.get("level") or "")
        if level not in {"ERROR", "CRITICAL"} or not _allowed_logger(service, logger_name):
            continue
        text = str(line.get("message") or "")
        shape = _NORMALIZE_RE.sub("#", _QUOTED_RE.sub("'…'", text))[:80]
        key = _fingerprint("log", service, logger_name, shape)
        signal = signals.setdefault(key, Signal(key, "log", "impact", f"{service} {level} {logger_name}"))
        match = _TASK_ID_RE.search(text)
        signal.add(int(row.get("_timestamp") or 0), f"task:{match.group(1)}" if match else None)
    return signals


def build_report(trace_rows: list[dict[str, Any]], log_rows: list[dict[str, Any]], since_minutes: int) -> dict[str, Any]:
    signals = {**classify_trace_rows(trace_rows), **classify_log_rows(log_rows)}
    ordered = sorted(signals.values(), key=lambda s: (s.kind != "impact", -s.count))
    return {
        "ok": True,
        "environment": "production",
        "since_minutes": since_minutes,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "impact_count": sum(s.count for s in ordered if s.kind == "impact"),
        "signals": [s.as_dict() for s in ordered],
    }


TRACE_SQL = (
    f'SELECT _timestamp, trace_id, ai_phase, ai_status_class, ai_terminal_class FROM "{TRACE_STREAM}" '
    "WHERE ai_status_class = 'error' OR ai_terminal_class IN ("
    + ",".join(f"'{c}'" for c in sorted(FAILED_TERMINAL_CLASSES))
    + ") ORDER BY _timestamp DESC LIMIT 1000"
)
LOG_SQL = (
    f'SELECT _timestamp, service, message FROM "{LOG_STREAM}" '
    "WHERE level IN ('ERROR','CRITICAL') AND service IN ("
    + ",".join(f"'{s}'" for s in sorted(CHAT_SERVICES))
    + ") ORDER BY _timestamp DESC LIMIT 2000"
)


async def _query(client: Any, base_url: str, headers: dict[str, str], sql: str, stream_type: str, since_minutes: int) -> list[dict[str, Any]]:
    response = await client.get(
        f"{base_url}/o2/search",
        params={"sql": sql, "since_minutes": since_minutes, "stream_type": stream_type},
        headers=headers,
    )
    if response.status_code != 200:
        raise RuntimeError(f"{stream_type} query failed with HTTP {response.status_code}: {response.text[:300]}")
    body = response.json()
    if not body.get("success"):
        raise RuntimeError(f"{stream_type} query was not successful: {str(body)[:300]}")
    return list(body.get("hits") or [])


async def run(since_minutes: int, target: str) -> dict[str, Any]:
    import httpx

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from debug_utils import _admin_debug_api_headers, get_admin_debug_api_key, get_base_url

    api_key = await get_admin_debug_api_key(target)
    if not api_key:
        raise RuntimeError(f"No admin debug API key for {target} in Vault")
    headers = _admin_debug_api_headers(api_key)
    base_url = get_base_url(use_dev=target == "dev")
    async with httpx.AsyncClient(timeout=60.0) as client:
        traces = await _query(client, base_url, headers, TRACE_SQL, "traces", since_minutes)
        logs = await _query(client, base_url, headers, LOG_SQL, "logs", since_minutes)
    report = build_report(traces, logs, since_minutes)
    report["environment"] = "production" if target == "prod" else "development"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--since-minutes", type=int, default=70)
    parser.add_argument("--target", choices=("prod", "dev"), default="prod")
    args = parser.parse_args()
    import httpx

    try:
        report = asyncio.run(run(args.since_minutes, args.target))
    except (RuntimeError, OSError, httpx.HTTPError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
