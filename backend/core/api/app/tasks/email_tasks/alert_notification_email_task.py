# backend/core/api/app/tasks/email_tasks/alert_notification_email_task.py
"""
Celery task for sending Prometheus alert notification emails to server owner/admin.

This module handles sending notifications when Alertmanager fires or resolves
alerts, routing them through the existing Brevo/Mailjet email infrastructure
instead of requiring a separate SMTP configuration.

Architecture: Alertmanager webhook → POST /internal/alerts/webhook → this task
→ EmailTemplateService (Brevo/Mailjet). Alertmanager still handles grouping,
throttling and inhibition; only the delivery path is changed.
See docs/architecture/logging-and-monitoring.md
"""

import logging
import asyncio
from typing import Optional

# Import the Celery app and Base Task
from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.tasks.base_task import BaseServiceTask

# Import necessary services and utilities
from backend.core.api.app.utils.log_filters import SensitiveDataFilter

# Setup loggers
logger = logging.getLogger(__name__)
sensitive_filter = SensitiveDataFilter()
logger.addFilter(sensitive_filter)

# Maximum character lengths for alert fields to prevent oversized emails
MAX_DESCRIPTION_LENGTH = 2000
MAX_LABELS_LENGTH = 1000


@app.task(
    name="app.tasks.email_tasks.alert_notification_email_task.send_alert_notification",
    base=BaseServiceTask,
    bind=True,
)
def send_alert_notification(
    self: BaseServiceTask,
    admin_email: str,
    alertname: str,
    status: str,
    severity: str,
    summary: str,
    starts_at: str,
    description: Optional[str] = None,
    ends_at: Optional[str] = None,
    labels: Optional[str] = None,
) -> bool:
    """
    Celery task to send a Prometheus alert notification email to the server owner/admin.

    Args:
        admin_email: The email address of the admin/server owner to notify.
        alertname: The Prometheus alert name (e.g. "HighErrorRate").
        status: Alert status from Alertmanager: "firing" or "resolved".
        severity: Alert severity label (e.g. "critical", "warning").
        summary: Short summary annotation from the alert rule.
        starts_at: ISO-8601 timestamp when the alert started firing.
        description: Optional longer description annotation from the alert rule.
        ends_at: ISO-8601 timestamp when the alert was resolved (only for resolved alerts).
        labels: Optional formatted string of all alert labels for debugging context.

    Returns:
        bool: True if email was sent successfully, False otherwise.
    """
    logger.info(
        f"Starting alert notification email task: alertname='{alertname}', "
        f"status={status}, severity={severity}, recipient={admin_email}, "
        f"task_id={self.request.id if hasattr(self.request, 'id') else 'unknown'}"
    )
    try:
        result = asyncio.run(
            _async_send_alert_notification(
                self,
                admin_email,
                alertname,
                status,
                severity,
                summary,
                starts_at,
                description,
                ends_at,
                labels,
            )
        )
        if result:
            logger.info(
                f"Alert notification email task completed successfully: "
                f"alertname='{alertname}', status={status}, recipient={admin_email}"
            )
        else:
            logger.error(
                f"Alert notification email task failed: "
                f"alertname='{alertname}', status={status}, recipient={admin_email} "
                f"— check logs above for details"
            )
        return result
    except Exception as e:
        logger.error(
            f"Failed to run alert notification email task: "
            f"alertname='{alertname}', status={status}, recipient={admin_email}: {e}",
            exc_info=True,
        )
        return False


async def _async_send_alert_notification(
    task: BaseServiceTask,
    admin_email: str,
    alertname: str,
    status: str,
    severity: str,
    summary: str,
    starts_at: str,
    description: Optional[str] = None,
    ends_at: Optional[str] = None,
    labels: Optional[str] = None,
) -> bool:
    """
    Async implementation for sending the Prometheus alert notification email.

    Initializes the BaseServiceTask services, sanitizes inputs, then sends
    the email via EmailTemplateService (Brevo/Mailjet).
    """
    from html import escape

    try:
        logger.info("Initializing services for alert notification email task...")
        await task.initialize_services()
        logger.info("Services initialized for alert notification email task")

        if not hasattr(task, "email_template_service") or task.email_template_service is None:
            logger.error("email_template_service not available after initialization")
            return False

        # SECURITY: HTML-escape all string inputs before passing to the template.
        sanitized_alertname = escape(alertname) if alertname else "Unknown"
        sanitized_status = escape(status) if status else "unknown"
        sanitized_severity = escape(severity) if severity else "unknown"
        sanitized_summary = escape(summary) if summary else ""
        sanitized_starts_at = escape(starts_at) if starts_at else ""

        sanitized_description = None
        if description:
            truncated = description[:MAX_DESCRIPTION_LENGTH]
            if len(description) > MAX_DESCRIPTION_LENGTH:
                truncated += "\n... [truncated]"
            sanitized_description = escape(truncated)

        sanitized_ends_at = None
        if ends_at:
            sanitized_ends_at = escape(ends_at)

        sanitized_labels = None
        if labels:
            truncated_labels = labels[:MAX_LABELS_LENGTH]
            if len(labels) > MAX_LABELS_LENGTH:
                truncated_labels += "\n... [truncated]"
            sanitized_labels = escape(truncated_labels)

        email_context = {
            "darkmode": True,  # Admin emails always use dark mode
            "alertname": sanitized_alertname,
            "status": sanitized_status,
            "severity": sanitized_severity,
            "summary": sanitized_summary,
            "starts_at": sanitized_starts_at,
            "description": sanitized_description,
            "ends_at": sanitized_ends_at,
            "labels": sanitized_labels,
        }
        logger.info(
            f"Sending alert notification email to {admin_email} "
            f"(alertname='{alertname}', status={status})"
        )

        email_success = await task.email_template_service.send_email(
            template="prometheus_alert",
            recipient_email=admin_email,
            context=email_context,
            lang="en",  # Admin emails always use English
        )

        if not email_success:
            logger.error(
                f"Failed to send alert notification email to {admin_email} — "
                f"send_email() returned False. Check email service configuration."
            )
            return False

        logger.info(
            f"Successfully sent alert notification email to {admin_email} "
            f"(alertname='{alertname}', status={status})"
        )
        return True

    except Exception as e:
        logger.error(
            f"Error sending alert notification email: {e}",
            exc_info=True,
        )
        return False
