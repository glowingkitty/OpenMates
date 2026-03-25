# backend/core/api/app/tasks/email_tasks/cron_session_email_task.py
"""
Celery task for sending cron job session notification emails to admin.

Notifies the admin when an automated Claude Code session completes (or fails),
so cron job results are visible without checking log files manually.

Architecture: cron script → _claude_utils.py → POST /internal/dispatch-cron-session-email
→ this task → EmailTemplateService (Brevo/Mailjet).
See docs/architecture/infrastructure/cronjobs.md
"""

import logging
import asyncio
from typing import Optional

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.utils.log_filters import SensitiveDataFilter

logger = logging.getLogger(__name__)
sensitive_filter = SensitiveDataFilter()
logger.addFilter(sensitive_filter)

MAX_CONTEXT_LENGTH = 3000


@app.task(
    name="app.tasks.email_tasks.cron_session_email_task.send_cron_session_notification",
    base=BaseServiceTask,
    bind=True,
)
def send_cron_session_notification(
    self: BaseServiceTask,
    admin_email: str,
    job_type: str,
    job_name: str,
    status: str,
    session_id: Optional[str] = None,
    duration_seconds: Optional[int] = None,
    context_summary: Optional[str] = None,
    exit_code: Optional[int] = None,
) -> bool:
    """
    Celery task to send a cron job session notification email.

    Args:
        admin_email: Admin email address.
        job_type: Category — "audit", "security", "redteam", "dependabot",
                  "dead-code", "deploy-fix", "test-analysis", "issues", "workflow-review".
        job_name: Human-readable session title (e.g. "security-audit: top 5 issues 2026-03-24").
        status: "completed", "failed", or "timeout".
        session_id: Claude Code session UUID (resumable via --resume).
        duration_seconds: How long the session ran.
        context_summary: Brief description of what happened (e.g. "3 alerts processed").
        exit_code: Process exit code (0 = success).

    Returns:
        bool: True if email was sent successfully.
    """
    logger.info(
        f"Starting cron session notification: job_type={job_type}, "
        f"status={status}, recipient={admin_email}"
    )
    try:
        result = asyncio.run(
            _async_send(
                self, admin_email, job_type, job_name, status,
                session_id, duration_seconds, context_summary, exit_code,
            )
        )
        if result:
            logger.info(f"Cron session notification sent: job_type={job_type}, recipient={admin_email}")
        else:
            logger.error(f"Cron session notification failed: job_type={job_type}, recipient={admin_email}")
        return result
    except Exception as e:
        logger.error(f"Cron session notification error: job_type={job_type}: {e}", exc_info=True)
        return False


async def _async_send(
    task: BaseServiceTask,
    admin_email: str,
    job_type: str,
    job_name: str,
    status: str,
    session_id: Optional[str],
    duration_seconds: Optional[int],
    context_summary: Optional[str],
    exit_code: Optional[int],
) -> bool:
    """Async implementation for the cron session notification email."""
    from html import escape

    try:
        await task.initialize_services()

        if not hasattr(task, "email_template_service") or task.email_template_service is None:
            logger.error("email_template_service not available after initialization")
            return False

        # Format duration as human-readable
        duration_str = None
        if duration_seconds is not None:
            mins, secs = divmod(duration_seconds, 60)
            if mins > 0:
                duration_str = f"{mins}m {secs}s"
            else:
                duration_str = f"{secs}s"

        # Map status to display values
        status_color = {
            "completed": "#4CAF50",  # green
            "failed": "#F44336",     # red
            "timeout": "#FF9800",    # orange
        }.get(status, "#2196F3")

        # Map job_type to icon and display name
        job_display = {
            "audit": "Codebase Audit",
            "security": "Security Audit",
            "redteam": "Red Team Probe",
            "dependabot": "Dependabot Fix",
            "dead-code": "Dead Code Removal",
            "deploy-fix": "Deploy Failure Fix",
            "test-analysis": "Test Failure Analysis",
            "issues": "Issue Investigation",
            "workflow-review": "Workflow Review",
        }.get(job_type, job_type.replace("-", " ").title())

        # Sanitize all inputs
        sanitized_context = None
        if context_summary:
            truncated = context_summary[:MAX_CONTEXT_LENGTH]
            if len(context_summary) > MAX_CONTEXT_LENGTH:
                truncated += "\n... [truncated]"
            sanitized_context = escape(truncated)

        email_context = {
            "darkmode": True,
            "job_type": escape(job_type),
            "job_display": escape(job_display),
            "job_name": escape(job_name),
            "status": escape(status),
            "status_color": status_color,
            "session_id": escape(session_id) if session_id else None,
            "duration": duration_str,
            "context_summary": sanitized_context,
            "exit_code": exit_code,
        }

        email_success = await task.email_template_service.send_email(
            template="cron_session_notification",
            recipient_email=admin_email,
            context=email_context,
            lang="en",
        )

        if not email_success:
            logger.error(f"Failed to send cron session email to {admin_email}")
            return False

        return True

    except Exception as e:
        logger.error(f"Error sending cron session email: {e}", exc_info=True)
        return False
