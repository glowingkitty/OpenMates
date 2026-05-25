# backend/core/api/app/tasks/email_tasks/daily_issue_digest_task.py
"""
Daily issue digest for production/dev reliability triage.

Collects the top backend error clusters, privacy-safe client diagnostic clusters,
and latest daily test failures, then writes durable handoff artifacts and emails
SERVER_OWNER_EMAIL. The generated OpenCode prompt lets the owner approve a
follow-up investigation/fix session without exposing raw user content.
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Any

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.tasks.email_tasks.error_digest_task import _aggregate, _query_prod, _top_n
from backend.core.api.app.utils.log_filters import SensitiveDataFilter
from backend.core.api.app.utils.newsletter_utils import hash_email

logger = logging.getLogger(__name__)
logger.addFilter(SensitiveDataFilter())

TOP_N = 10
REPO_ROOT = Path(os.getenv("OPENMATES_REPO_ROOT", "/app"))
DIGEST_DIR = REPO_ROOT / "test-results" / "daily-issue-digests"
PROMPT_PATH = REPO_ROOT / "scripts" / ".tmp" / "daily-issue-opencode-prompt.md"
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mKHJABCDsuGfFnRh]")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _clean_text(value: Any, limit: int) -> str:
    text = str(value or "")
    text = _ANSI_RE.sub("", text)
    text = _CONTROL_RE.sub("", text)
    return text[:limit]


@app.task(
    name="app.tasks.email_tasks.daily_issue_digest_task.send_daily_issue_digest",
    bind=True,
)
def send_daily_issue_digest(self) -> bool:
    """Entry point for Celery beat and manual dispatch."""
    logger.info("[DAILY_ISSUE_DIGEST] Starting daily issue digest")
    try:
        return asyncio.run(_async_send_daily_issue_digest())
    except Exception as exc:
        logger.error(f"[DAILY_ISSUE_DIGEST] Task failed: {exc}", exc_info=True)
        return False


async def _async_send_daily_issue_digest() -> bool:
    admin_email = os.getenv("SERVER_OWNER_EMAIL")
    if not admin_email:
        logger.error("[DAILY_ISSUE_DIGEST] SERVER_OWNER_EMAIL is not configured")
        return False

    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=24)

    dev_errors, client_errors = await _query_dev_issue_sources(start, now)
    prod_errors = await _query_prod(start)
    failed_tests = _read_failed_tests()

    digest = {
        "generated_at": now.isoformat(),
        "window": "last_24h",
        "prod_top_errors": _top_n(prod_errors)[:TOP_N],
        "dev_top_errors": _top_n(dev_errors)[:TOP_N],
        "client_top_errors": _top_n(client_errors)[:TOP_N],
        "failed_tests": failed_tests[:TOP_N],
    }

    _write_digest_artifacts(digest)
    return await _send_digest_email(admin_email, digest)


async def _query_dev_issue_sources(
    start: datetime,
    end: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Query local OpenObserve for backend and client diagnostic clusters."""
    try:
        from backend.core.api.app.services.openobserve_log_collector import openobserve_log_collector as oo

        backend_sql = (
            "SELECT message, service, level, COUNT(*) as cnt "
            "FROM \"default\" "
            "WHERE level IN ('WARNING', 'ERROR', 'CRITICAL') "
            "GROUP BY message, service, level "
            "ORDER BY cnt DESC "
            f"LIMIT {TOP_N * 5}"
        )
        backend_hits = await oo._search("default", backend_sql, start_time=start, end_time=end) or []

        client_sql = (
            "SELECT message, level, COUNT(*) as cnt "
            "FROM \"client_console_ephemeral\" "
            "WHERE level IN ('warn', 'error') "
            "GROUP BY message, level "
            "ORDER BY cnt DESC "
            f"LIMIT {TOP_N * 5}"
        )
        client_hits = await oo._search("client_console_ephemeral", client_sql, start_time=start, end_time=end) or []
        client_groups = _aggregate(client_hits, count_field="cnt")
        for group in client_groups:
            group["service"] = "client"
        return _aggregate(backend_hits, count_field="cnt"), client_groups
    except Exception as exc:
        logger.warning(f"[DAILY_ISSUE_DIGEST] Dev/client query failed: {exc}", exc_info=True)
        return [], []


def _read_failed_tests() -> list[dict[str, Any]]:
    """Read latest local daily test failures if present."""
    path = REPO_ROOT / "test-results" / "last-failed-tests.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        tests = data.get("failed_tests") or data.get("tests") or []
        result = []
        for item in tests:
            result.append({
                "suite": _clean_text(item.get("suite", item.get("project", "unknown")), 80),
                "name": _clean_text(item.get("name", item.get("test", "unknown")), 160),
                "error": _clean_text(item.get("error", item.get("message", "")), 300),
            })
        return result
    except Exception as exc:
        logger.warning(f"[DAILY_ISSUE_DIGEST] Failed to read test failures: {exc}")
        return []


def _write_digest_artifacts(digest: dict[str, Any]) -> None:
    DIGEST_DIR.mkdir(parents=True, exist_ok=True)
    PROMPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    (DIGEST_DIR / "latest.json").write_text(json.dumps(digest, indent=2), encoding="utf-8")

    markdown = _render_markdown(digest)
    (DIGEST_DIR / "latest.md").write_text(markdown, encoding="utf-8")
    PROMPT_PATH.write_text(_render_opencode_prompt(digest), encoding="utf-8")


def _render_markdown(digest: dict[str, Any]) -> str:
    lines = [
        "# Daily Issue Digest",
        "",
        f"Generated: {digest['generated_at']}",
        "Window: last 24h",
        "",
    ]
    for title, key in [
        ("Production Errors", "prod_top_errors"),
        ("Development Errors", "dev_top_errors"),
        ("Client Diagnostics", "client_top_errors"),
    ]:
        lines.extend([f"## {title}", ""])
        rows = digest.get(key, [])
        if not rows:
            lines.extend(["No issues found.", ""])
            continue
        for row in rows:
            lines.append(f"- {row.get('count', 0)}x `{row.get('service', '')}`: {row.get('message', '')}")
        lines.append("")

    lines.extend(["## Failed Tests", ""])
    for test in digest.get("failed_tests", []):
        lines.append(f"- `{test.get('suite', 'unknown')}` {test.get('name', 'unknown')}: {test.get('error', '')}")
    if not digest.get("failed_tests"):
        lines.append("No failed tests found.")
    lines.append("")
    return "\n".join(lines)


def _render_opencode_prompt(digest: dict[str, Any]) -> str:
    return (
        "Investigate and fix the top OpenMates reliability issues from this daily digest. "
        "Start with the highest-impact production errors, then client diagnostics, then failed tests. "
        "Do not expose raw user content; use sanitized logs and existing debug tooling.\n\n"
        + _render_markdown(digest)
    )


async def _send_digest_email(admin_email: str, digest: dict[str, Any]) -> bool:
    try:
        from backend.core.api.app.services.email_template import EmailTemplateService
        from backend.core.api.app.utils.secrets_manager import SecretsManager

        secrets = SecretsManager()
        await secrets.initialize()
        email_svc = EmailTemplateService(secrets)

        context = {
            "darkmode": True,
            "generated_at": escape(digest["generated_at"]),
            "prod_top_errors": _sanitize_rows(digest["prod_top_errors"]),
            "dev_top_errors": _sanitize_rows(digest["dev_top_errors"]),
            "client_top_errors": _sanitize_rows(digest["client_top_errors"]),
            "failed_tests": [
                {
                    "suite": escape(str(item.get("suite", ""))),
                    "name": escape(str(item.get("name", ""))),
                    "error": escape(str(item.get("error", ""))),
                }
                for item in digest["failed_tests"]
            ],
            "opencode_prompt_path": str(PROMPT_PATH),
        }
        ok = await email_svc.send_email(
            template="daily_issue_digest",
            recipient_email=admin_email,
            context=context,
            lang="en",
        )
        if ok:
            logger.info(f"[DAILY_ISSUE_DIGEST] Sent to {hash_email(admin_email)[:8]}")
        return bool(ok)
    except Exception as exc:
        logger.error(f"[DAILY_ISSUE_DIGEST] Failed to send email: {exc}", exc_info=True)
        return False


def _sanitize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "count": int(row.get("count", 0)),
            "service": escape(str(row.get("service", ""))),
            "message": escape(str(row.get("message", ""))),
        }
        for row in rows
    ]
