# backend/core/api/app/tasks/email_tasks/error_digest_task.py
"""
Weekly error digest email sent every Monday at 08:00 UTC.

Queries OpenObserve for ERROR/CRITICAL log entries from the last 7 days,
aggregates by (message, service), strips UUIDs and timestamps from messages
so identical errors are grouped even if they carry different IDs in the text,
then sends a single HTML summary email to SERVER_OWNER_EMAIL via Brevo.

Two sections:
  - Production errors  (queries the prod admin /errors/logs endpoint via HTTP,
                        requires PROD_API_URL + PROD_ADMIN_API_KEY env vars)
  - Dev errors         (queries local OpenObserve directly)

If PROD_API_URL is not set the production section is skipped silently.

Also surfaces any `candidate_key_promoted` events from the encryption fallback
system (see ChatKeyManager.tryDecryptWithCandidates) as a highlighted section
so encryption regressions appear in the weekly review.

Architecture: docs/architecture/core/encryption-root-causes.md
"""

import asyncio
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Any

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.utils.log_filters import SensitiveDataFilter
from backend.core.api.app.utils.newsletter_utils import hash_email

logger = logging.getLogger(__name__)
logger.addFilter(SensitiveDataFilter())

# Maximum errors per environment shown in the email
TOP_N = 20
# Message pattern: strip UUIDs, ISO timestamps, hex IDs, and numbers so identical
# errors with different IDs group together (e.g. "chat abc-123" → "chat <id>").
_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_HEX_RE = re.compile(r"\b[0-9a-f]{8,}\b", re.I)
_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}")
_NUM_RE = re.compile(r"\b\d{4,}\b")
_MSG_TRUNCATE = 120


def _normalise(msg: str) -> str:
    """Strip volatile tokens so distinct occurrences of the same error cluster."""
    msg = _UUID_RE.sub("<id>", msg)
    msg = _TS_RE.sub("<ts>", msg)
    msg = _HEX_RE.sub("<hex>", msg)
    msg = _NUM_RE.sub("<n>", msg)
    return msg.strip()[:_MSG_TRUNCATE]


@app.task(
    name="app.tasks.email_tasks.error_digest_task.send_weekly_error_digest",
    bind=True,
)
def send_weekly_error_digest(self) -> bool:
    """Entry point for the Celery beat schedule."""
    logger.info("[ERROR_DIGEST] Starting weekly error digest")
    try:
        return asyncio.run(_async_send_weekly_error_digest())
    except Exception as exc:
        logger.error(f"[ERROR_DIGEST] Task failed: {exc}", exc_info=True)
        return False


async def _async_send_weekly_error_digest() -> bool:
    admin_email = os.getenv("SERVER_OWNER_EMAIL")
    if not admin_email:
        logger.error("[ERROR_DIGEST] Recipient not configured — check env vars")
        return False

    now = datetime.now(timezone.utc)
    week_start = now - timedelta(days=7)
    week_label = f"{week_start.strftime('%b %d')} – {now.strftime('%b %d, %Y')}"

    dev_errors, dev_fallbacks = await _query_dev(week_start, now)
    prod_errors = await _query_prod(week_start)

    total_errors = sum(e["count"] for e in dev_errors) + sum(e["count"] for e in prod_errors)
    key_fallback_events = dev_fallbacks

    # Build de-duplicated top lists
    dev_top = _top_n(dev_errors)
    prod_top = _top_n(prod_errors)

    try:
        from backend.core.api.app.services.email_template import EmailTemplateService
        from backend.core.api.app.utils.secrets_manager import SecretsManager

        secrets = SecretsManager()
        await secrets.initialize()

        email_svc = EmailTemplateService(secrets)

        context = {
            "darkmode": True,
            "week_label": escape(week_label),
            "generated_at": escape(now.strftime("%Y-%m-%d %H:%M")),
            "total_errors": total_errors,
            "prod_errors": sum(e["count"] for e in prod_errors),
            "dev_errors": sum(e["count"] for e in dev_errors),
            "key_fallback_events": key_fallback_events,
            "prod_top_errors": [
                {"count": e["count"], "service": escape(e["service"]), "message": escape(e["message"])}
                for e in prod_top
            ],
            "dev_top_errors": [
                {"count": e["count"], "service": escape(e["service"]), "message": escape(e["message"])}
                for e in dev_top
            ],
        }

        ok = await email_svc.send_email(
            template="error_digest_weekly",
            recipient_email=admin_email,
            context=context,
            lang="en",
        )
        if ok:
            logger.info(
                f"[ERROR_DIGEST] Sent to recipient {hash_email(admin_email)[:8]}: "
                f"dev={len(dev_top)} groups, prod={len(prod_top)} groups, fallbacks={key_fallback_events}"
            )
        else:
            logger.error("[ERROR_DIGEST] Delivery failed — check outbound transport config")
        return bool(ok)

    except Exception as exc:
        logger.error(f"[ERROR_DIGEST] Failed to send: {exc}", exc_info=True)
        return False


async def _query_dev(
    start: datetime, end: datetime
) -> tuple[list[dict[str, Any]], int]:
    """Query local OpenObserve. Returns (error_groups, candidate_key_promotion_count)."""
    try:
        from backend.core.api.app.services.openobserve_log_collector import openobserve_log_collector as oo

        error_sql = (
            "SELECT message, service, level, COUNT(*) as cnt "
            "FROM \"default\" "
            "WHERE (level = 'ERROR' OR level = 'CRITICAL') "
            "GROUP BY message, service, level "
            "ORDER BY cnt DESC "
            f"LIMIT {TOP_N * 5}"  # over-fetch so normalisation can merge duplicates
        )
        hits = await oo._search("default", error_sql, start_time=start, end_time=end) or []

        # Count candidate_key_promoted events separately
        fallback_sql = (
            "SELECT COUNT(*) as cnt FROM \"default\" "
            "WHERE message LIKE '%candidate_key_promoted%'"
        )
        fallback_hits = await oo._search("default", fallback_sql, start_time=start, end_time=end) or []
        fallback_count = int(fallback_hits[0].get("cnt", 0)) if fallback_hits else 0

        groups = _aggregate(hits, count_field="cnt")
        return groups, fallback_count

    except Exception as exc:
        logger.warning(f"[ERROR_DIGEST] Dev OpenObserve query failed: {exc}", exc_info=True)
        return [], 0


async def _query_prod(start: datetime) -> list[dict[str, Any]]:
    """
    Query prod via the admin /v1/admin/debug/errors/logs endpoint.
    Requires PROD_API_URL and PROD_ADMIN_API_KEY env vars.
    Returns empty list if either is missing.
    """
    prod_url = os.getenv("PROD_API_URL", "").rstrip("/")
    prod_key = os.getenv("PROD_ADMIN_API_KEY", "")
    if not prod_url or not prod_key:
        return []

    try:
        import aiohttp
        url = f"{prod_url}/v1/admin/debug/errors/logs?since_minutes=10080&top={TOP_N * 5}"
        headers = {"Authorization": f"Bearer {prod_key}"}
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    logger.warning(f"[ERROR_DIGEST] Prod query returned {resp.status}")
                    return []
                data = await resp.json()
                raw = data.get("entries", [])
                # Prod endpoint already returns {message, service, count} dicts
                return _top_n([
                    {"message": _normalise(e.get("message", "")), "service": e.get("service", ""), "count": e.get("count", 1)}
                    for e in raw
                ])
    except Exception as exc:
        logger.warning(f"[ERROR_DIGEST] Prod query failed: {exc}", exc_info=True)
        return []


def _aggregate(hits: list[dict[str, Any]], count_field: str = "count") -> list[dict[str, Any]]:
    """Normalise messages, merge duplicates, sort by count descending."""
    merged: dict[str, dict[str, Any]] = {}
    for h in hits:
        raw_msg = h.get("message", "")
        # Strip JSON wrapper that OpenObserve sometimes returns
        if isinstance(raw_msg, str) and raw_msg.startswith("{"):
            try:
                import json
                inner = json.loads(raw_msg)
                raw_msg = inner.get("message", raw_msg)
            except Exception:
                pass
        key = _normalise(raw_msg)
        cnt = int(h.get(count_field, 1))
        if key in merged:
            merged[key]["count"] += cnt
        else:
            merged[key] = {
                "message": key,
                "service": h.get("service", ""),
                "count": cnt,
            }
    return sorted(merged.values(), key=lambda x: x["count"], reverse=True)


def _top_n(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return groups[:TOP_N]
