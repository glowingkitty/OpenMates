# backend/core/api/app/tasks/email_tasks/free_testing_budget_email_task.py
#
# Sends internal server-owner alerts for the Free testing credits promotion.
# This is an operational admin email, not a user-facing notification; user
# signup grant notifications are sent over the existing translated in-app
# notification channel.

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


@app.task(
    name="app.tasks.email_tasks.free_testing_budget_email_task.send_free_testing_budget_exhausted_email",
    bind=True,
)
def send_free_testing_budget_exhausted_email(
    self,
    admin_email: str,
    total_budget_credits: int,
    used_budget_credits: int,
    per_user_grant_credits: int,
) -> bool:
    """Send a one-time exhausted-budget alert to the configured server owner."""
    try:
        return asyncio.run(
            _async_send_free_testing_budget_exhausted_email(
                admin_email=admin_email,
                total_budget_credits=total_budget_credits,
                used_budget_credits=used_budget_credits,
                per_user_grant_credits=per_user_grant_credits,
            )
        )
    except Exception as exc:
        logger.error("Failed to run Free testing budget exhausted email task: %s", exc, exc_info=True)
        return False


async def _async_send_free_testing_budget_exhausted_email(
    *,
    admin_email: str,
    total_budget_credits: int,
    used_budget_credits: int,
    per_user_grant_credits: int,
) -> bool:
    secrets_manager = SecretsManager()
    try:
        await secrets_manager.initialize()
        email_template_service = EmailTemplateService(secrets_manager=secrets_manager)
        remaining_budget_credits = max(0, int(total_budget_credits or 0) - int(used_budget_credits or 0))
        context = {
            "darkmode": True,
            "total_budget_credits": escape(str(total_budget_credits)),
            "used_budget_credits": escape(str(used_budget_credits)),
            "remaining_budget_credits": escape(str(remaining_budget_credits)),
            "per_user_grant_credits": escape(str(per_user_grant_credits)),
        }
        return await email_template_service.send_email(
            template="free-testing-budget-exhausted",
            recipient_email=admin_email,
            subject="Free testing credits budget exhausted",
            context=context,
            lang="en",
        )
    finally:
        await secrets_manager.aclose()
