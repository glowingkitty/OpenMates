# backend/core/api/app/tasks/email_tasks/health_status_alert_email_task.py
# Sends internal server-owner health transition alerts.
# These emails are operational notifications for provider, app, and external
# service outages or recoveries, not user-facing notification emails.
# The payload is deliberately sanitized before reaching the template so provider
# diagnostics and secrets are never exposed through email.

from __future__ import annotations

import asyncio
import logging
from html import escape

from backend.core.api.app.services.email_template import EmailTemplateService
from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.utils.log_filters import SensitiveDataFilter
from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)
logger.addFilter(SensitiveDataFilter())

MAX_EMAIL_FIELD_LENGTH = 255


def _email_field(value: object, *, fallback: str = "unknown") -> str:
    text = str(value if value is not None else fallback).strip() or fallback
    return escape(text[:MAX_EMAIL_FIELD_LENGTH])


@app.task(
    name="app.tasks.email_tasks.health_status_alert_email_task.send_health_status_alert_email",
    bind=True,
)
def send_health_status_alert_email(
    self,
    admin_email: str,
    service_type: str,
    service_id: str,
    previous_status: str | None,
    new_status: str,
    error_message: str | None = None,
    response_time_ms: float | None = None,
    duration_seconds: int | None = None,
    occurred_at: str | None = None,
    environment: str | None = None,
) -> bool:
    """Send one server-owner email for a health status transition."""
    try:
        return asyncio.run(
            _async_send_health_status_alert_email(
                admin_email=admin_email,
                service_type=service_type,
                service_id=service_id,
                previous_status=previous_status,
                new_status=new_status,
                error_message=error_message,
                response_time_ms=response_time_ms,
                duration_seconds=duration_seconds,
                occurred_at=occurred_at,
                environment=environment,
            )
        )
    except Exception as exc:
        logger.error("Failed to run health status alert email task: %s", exc, exc_info=True)
        return False


async def _async_send_health_status_alert_email(
    *,
    admin_email: str,
    service_type: str,
    service_id: str,
    previous_status: str | None,
    new_status: str,
    error_message: str | None = None,
    response_time_ms: float | None = None,
    duration_seconds: int | None = None,
    occurred_at: str | None = None,
    environment: str | None = None,
) -> bool:
    secrets_manager = SecretsManager()
    try:
        await secrets_manager.initialize()
        email_template_service = EmailTemplateService(secrets_manager=secrets_manager)
        safe_service_type = _email_field(service_type)
        safe_service_id = _email_field(service_id)
        safe_previous = _email_field(previous_status, fallback="initial")
        safe_new = _email_field(new_status)
        safe_environment = _email_field(environment, fallback="unknown")
        subject = (
            f"OpenMates {safe_environment} health: "
            f"{safe_service_type}/{safe_service_id} {safe_previous} -> {safe_new}"
        )

        context = {
            "darkmode": True,
            "environment": safe_environment,
            "service_type": safe_service_type,
            "service_id": safe_service_id,
            "previous_status": safe_previous,
            "new_status": safe_new,
            "error_message": _email_field(error_message, fallback="none"),
            "response_time_ms": _email_field(
                round(response_time_ms, 2) if response_time_ms is not None else None,
                fallback="n/a",
            ),
            "duration_seconds": _email_field(duration_seconds, fallback="n/a"),
            "occurred_at": _email_field(occurred_at, fallback="unknown"),
        }
        return await email_template_service.send_email(
            template="health-status-alert",
            recipient_email=admin_email,
            subject=subject,
            context=context,
            lang="en",
        )
    finally:
        await secrets_manager.aclose()
