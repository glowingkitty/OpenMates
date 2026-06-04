# backend/core/api/app/services/degraded_services_report.py
#
# Builds the weekday Discord degraded-services digest from OpenObserve logs.
# This module is intentionally lightweight and import-safe for unit tests: it
# does not import Celery, Redis, or task packages. The Celery task in
# health_check_tasks.py only orchestrates these helpers.

import json
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

DEGRADED_SERVICES_REPORT_LOOKBACK_HOURS = 24
DEGRADED_SERVICES_REPORT_MIN_OCCURRENCES = 3
DEGRADED_SERVICES_REPORT_QUERY_LIMIT = 1000
DEGRADED_SERVICES_REPORT_TOP_MESSAGES = 12
DEGRADED_SERVICES_DISCORD_LIMIT = 1900
DEGRADED_SERVICES_DISCORD_TIMEOUT_SECONDS = 10.0


def extract_exact_log_message(raw_message: str) -> tuple[str, str]:
    """Return logger name and inner log message from JSON log payloads."""
    try:
        payload = json.loads(raw_message)
        if isinstance(payload, dict):
            name = str(payload.get("name") or "unknown")
            message = str(payload.get("message") or raw_message)
            return name, message
    except (TypeError, ValueError):
        pass

    return "unknown", str(raw_message or "")


def is_degraded_report_candidate(level: str, exact_message: str) -> bool:
    level_upper = level.upper()
    if level_upper in {"ERROR", "CRITICAL"}:
        return True

    lowered = exact_message.lower()
    return any(
        marker in lowered
        for marker in (
            " is degraded",
            " is unhealthy",
            "failed",
            "timeout",
            "no active celery workers found",
        )
    )


def build_degraded_issue_report(
    log_rows: list[dict[str, Any]],
    *,
    min_occurrences: int = DEGRADED_SERVICES_REPORT_MIN_OCCURRENCES,
    top_messages: int = DEGRADED_SERVICES_REPORT_TOP_MESSAGES,
) -> list[dict[str, Any]]:
    grouped: Counter[tuple[str, str, str, str]] = Counter()

    for row in log_rows:
        raw_message = str(row.get("message") or "")
        service = str(row.get("service") or row.get("container") or "unknown")
        level = str(row.get("level") or "UNKNOWN").upper()
        logger_name, exact_message = extract_exact_log_message(raw_message)

        if not exact_message or "[ADMIN_LOG_QUERY]" in exact_message:
            continue
        if not is_degraded_report_candidate(level, exact_message):
            continue

        grouped[(service, level, logger_name, exact_message)] += 1

    issues = [
        {
            "service": service,
            "level": level,
            "logger": logger_name,
            "message": exact_message,
            "count": count,
        }
        for (service, level, logger_name, exact_message), count in grouped.items()
        if count >= min_occurrences
    ]
    issues.sort(
        key=lambda item: (item["count"], item["level"] == "CRITICAL", item["level"] == "ERROR"),
        reverse=True,
    )
    return issues[:top_messages]


def truncate_discord_message(message: str, limit: int = DEGRADED_SERVICES_DISCORD_LIMIT) -> str:
    if len(message) <= limit:
        return message
    suffix = "\n...truncated; see OpenObserve for the full 24h report."
    return message[: max(0, limit - len(suffix))].rstrip() + suffix


def format_degraded_report_message(
    *,
    environment: str,
    issues: list[dict[str, Any]],
    lookback_hours: int = DEGRADED_SERVICES_REPORT_LOOKBACK_HOURS,
) -> str:
    header = f"OpenMates {environment} degraded services report ({lookback_hours}h)"
    if not issues:
        return f"{header}\nNo repeated degraded API/container errors found."

    lines = [header, f"Repeated issues (>= {DEGRADED_SERVICES_REPORT_MIN_OCCURRENCES} occurrences):"]
    for issue in issues:
        exact_message = str(issue["message"]).replace("```", "'''")
        lines.append(
            f"- {issue['count']}x [{issue['level']}] {issue['service']} / {issue['logger']}\n"
            f"  ```{exact_message[:700]}```"
        )
    return truncate_discord_message("\n".join(lines))


def select_degraded_report_webhook_url(environment: str) -> Optional[str]:
    explicit = os.getenv("DISCORD_WEBHOOK_DEGRADED_SERVICES", "").strip()
    if explicit:
        return explicit

    env_lower = environment.lower()
    if env_lower in {"production", "prod"}:
        return os.getenv("DISCORD_WEBHOOK_PROD_SMOKE", "").strip() or None
    return os.getenv("DISCORD_WEBHOOK_DEV_SMOKE", "").strip() or None


async def send_discord_degraded_report(content: str, webhook_url: str) -> None:
    async with httpx.AsyncClient(timeout=DEGRADED_SERVICES_DISCORD_TIMEOUT_SECONDS) as client:
        response = await client.post(webhook_url, json={"content": content})
        response.raise_for_status()


async def collect_recent_degraded_log_rows(
    lookback_hours: int = DEGRADED_SERVICES_REPORT_LOOKBACK_HOURS,
) -> list[dict[str, Any]]:
    from backend.core.api.app.services.openobserve_log_collector import OpenObserveLogCollectorService

    start_time = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    collector = OpenObserveLogCollectorService()
    sql = (
        'SELECT _timestamp, service, container, level, message FROM "default" '
        "WHERE level IN ('WARNING', 'ERROR', 'CRITICAL') "
        "ORDER BY _timestamp DESC "
        f"LIMIT {DEGRADED_SERVICES_REPORT_QUERY_LIMIT}"
    )
    return await collector._search("default", sql, start_time=start_time) or []
