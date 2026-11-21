# Daily admin summary of technical chat failures on the official dev server.
# Dev records failures in Redis instead of emailing each one (see
# chat_failure_email_task); this task sends one email around 08:00 Berlin, grouped
# by stage/category with a count, the newest example and its chat id. No failures
# in the last 24 hours means no email. Production is untouched: it keeps one
# instant email per failure.
# Architecture: docs/architecture/core/chat-failure-notifications.md.

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.tasks.email_tasks.chat_failure_email_task import DEV_FAILURE_LOG_KEY
from backend.shared.python_utils.chat_failure_notifications import notification_environment

logger = logging.getLogger(__name__)
SUMMARY_TASK = "app.tasks.email_tasks.chat_failure_summary_task.send_dev_chat_failure_summary"
SUMMARY_WINDOW = timedelta(hours=24)
SUMMARY_TIMEZONE = ZoneInfo("Europe/Berlin")
SUMMARY_HOUR = 8


def summarize_failures(raw_entries: list[bytes | str]) -> list[dict]:
    """Group recorded failures by stage and category, most frequent first."""
    groups: dict[tuple[str, str], dict] = {}
    for raw in raw_entries:
        try:
            entry = json.loads(raw)
            key = (entry["stage"], entry["category"])
            ts = float(entry["ts"])
        except (ValueError, KeyError, TypeError):
            logger.error("[CHAT_FAILURE_SUMMARY] unreadable_entry")
            continue
        group = groups.setdefault(key, {"stage": key[0], "category": key[1], "count": 0, "newest_ts": 0.0, "newest_ref": None})
        group["count"] += 1
        if ts >= group["newest_ts"]:
            group["newest_ts"] = ts
            group["newest_ref"] = entry.get("ref")
    ordered = sorted(groups.values(), key=lambda g: (-g["count"], -g["newest_ts"]))
    for group in ordered:
        newest = datetime.fromtimestamp(group.pop("newest_ts"), timezone.utc)
        group["newest_at"] = newest.astimezone(SUMMARY_TIMEZONE).strftime("%Y-%m-%d %H:%M %Z")
        group["newest_ref"] = group["newest_ref"] or "unavailable"
    return ordered


async def deliver_dev_failure_summary(now: datetime | None = None, force: bool = False) -> str:
    from backend.core.api.app.services.cache import CacheService
    from backend.core.api.app.services.email_template import EmailTemplateService
    from backend.core.api.app.utils.secrets_manager import SecretsManager

    if notification_environment() != "development":
        return "not_development"
    now = now or datetime.now(timezone.utc)
    if not force and now.astimezone(SUMMARY_TIMEZONE).hour != SUMMARY_HOUR:
        # Beat fires at 06:00 and 07:00 UTC so that one of them is 08:00 Berlin all year.
        return "outside_summary_hour"
    recipient = os.getenv("SERVER_OWNER_EMAIL") or os.getenv("ADMIN_NOTIFY_EMAIL")
    if not recipient:
        logger.error("[CHAT_FAILURE_SUMMARY] missing_admin_email")
        return "missing_admin_email"
    cache = CacheService()
    secrets = None
    try:
        try:
            redis = await cache.client
            raw = await redis.zrangebyscore(DEV_FAILURE_LOG_KEY, (now - SUMMARY_WINDOW).timestamp(), "+inf")
        except Exception:
            logger.error("[CHAT_FAILURE_SUMMARY] failure_log_unavailable")
            return "failure_log_unavailable"
        groups = summarize_failures(raw)
        if not groups:
            return "no_failures"
        secrets = SecretsManager()
        await secrets.initialize()
        total = sum(g["count"] for g in groups)
        accepted = await EmailTemplateService(secrets_manager=secrets).send_email(
            template="chat-failure-daily-summary", recipient_email=recipient,
            subject=f"OpenMates development: {total} chat processing failure{'s' if total != 1 else ''} in the last 24 hours",
            context={"darkmode": True, "environment": "development", "total": total, "groups": groups},
            lang="en",
        )
        outcome = "accepted" if accepted else "rejected"
        logger.log(logging.INFO if accepted else logging.ERROR, "[CHAT_FAILURE_SUMMARY] %s failures=%s", outcome, total)
        return outcome
    finally:
        for resource in (secrets, cache):
            if resource is not None:
                try:
                    await (resource.aclose() if resource is secrets else resource.close())
                except Exception:
                    logger.error("[CHAT_FAILURE_SUMMARY] cleanup_failed")


@app.task(name=SUMMARY_TASK, ignore_result=True)
def send_dev_chat_failure_summary() -> str:
    """Beat entry point: one summary email per day on dev, nothing on other editions."""
    return asyncio.run(deliver_dev_failure_summary())
