# backend/core/api/app/tasks/email_tasks/test_run_started_email_task.py
"""
Celery task for sending a test run started notification email to the admin.

Sent as soon as the test run begins — both for scheduled (Celery Beat) and
manual (admin Settings → Tests panel) triggers. This gives the admin visibility
into when a run kicked off, even before results arrive.

The email contains:
  - How the run was triggered ("Scheduled (daily)" or "Manual (admin)")
  - The current git SHA + branch
  - The UTC timestamp when the run started

Architecture: triggered by:
  1. e2e_test_tasks.run_daily_all_tests (Celery Beat, 03:00 UTC)
  2. POST /v1/admin/tests/run (manual trigger via admin API)
  3. run-tests-daily.sh via _daily_runner_helper.py dispatch-start-email
     (host-side script path, for when the sidecar initiates the run)

See docs/architecture/health-checks.md
"""

import logging
import asyncio

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.utils.log_filters import SensitiveDataFilter

logger = logging.getLogger(__name__)
sensitive_filter = SensitiveDataFilter()
logger.addFilter(sensitive_filter)


@app.task(
    name="app.tasks.email_tasks.test_run_started_email_task.send_test_run_started",
    base=BaseServiceTask,
    bind=True,
)
def send_test_run_started(
    self: BaseServiceTask,
    admin_email: str,
    trigger_type: str,
    git_sha: str,
    git_branch: str,
    started_at: str,
) -> bool:
    """
    Celery task to send a test run started notification email to the admin.

    Args:
        admin_email: Recipient email address (SERVER_OWNER_EMAIL / ADMIN_NOTIFY_EMAIL).
        trigger_type: Human-readable trigger description, e.g.
            "Scheduled (daily)" or "Manual (admin)".
        git_sha: Short git commit SHA the tests are running against.
        git_branch: Git branch name the tests are running against.
        started_at: ISO 8601 UTC timestamp string of when the run began.

    Returns:
        bool: True if the email was sent successfully, False otherwise.
    """
    logger.info(
        f"Starting test run started email task: trigger='{trigger_type}', "
        f"git={git_sha}@{git_branch}, recipient={admin_email}"
    )
    try:
        result = asyncio.run(
            _async_send_test_run_started(
                self,
                admin_email=admin_email,
                trigger_type=trigger_type,
                git_sha=git_sha,
                git_branch=git_branch,
                started_at=started_at,
            )
        )
        if result:
            logger.info(
                f"Test run started email sent: trigger='{trigger_type}', recipient={admin_email}"
            )
        else:
            logger.error(
                f"Test run started email task failed: trigger='{trigger_type}', "
                f"recipient={admin_email} — check logs above for details"
            )
        return result
    except Exception as e:
        logger.error(
            f"Failed to run test run started email task: trigger='{trigger_type}', "
            f"recipient={admin_email}: {e}",
            exc_info=True,
        )
        return False


async def _async_send_test_run_started(
    task: BaseServiceTask,
    admin_email: str,
    trigger_type: str,
    git_sha: str,
    git_branch: str,
    started_at: str,
) -> bool:
    """Async implementation for sending the test run started notification email."""
    from html import escape

    try:
        logger.info("Initializing services for test run started email task...")
        await task.initialize_services()
        logger.info("Services initialized for test run started email task")

        if not hasattr(task, "email_template_service") or task.email_template_service is None:
            logger.error("email_template_service not available after initialization")
            return False

        subject = "Test Run Started"

        email_context = {
            "darkmode": True,  # Admin emails always use dark mode
            "subject": subject,
            "trigger_type": escape(trigger_type) if trigger_type else "Unknown",
            "git_sha": escape(git_sha) if git_sha else "unknown",
            "git_branch": escape(git_branch) if git_branch else "unknown",
            "started_at": escape(started_at) if started_at else "unknown",
        }

        logger.info(
            f"Sending test run started email to {admin_email} "
            f"(trigger='{trigger_type}', git={git_sha}@{git_branch})"
        )

        email_success = await task.email_template_service.send_email(
            template="test_run_started",
            recipient_email=admin_email,
            context=email_context,
            subject=subject,
            lang="en",  # Admin emails always in English
        )

        if not email_success:
            logger.error(
                f"Failed to send test run started email to {admin_email} — "
                f"send_email() returned False. Check email service configuration."
            )
            return False

        logger.info(
            f"Successfully sent test run started email to {admin_email} "
            f"(trigger='{trigger_type}')"
        )
        return True

    except Exception as e:
        logger.error(
            f"Error sending test run started email: {e}",
            exc_info=True,
        )
        return False

    finally:
        try:
            await task.cleanup_services()
            logger.debug("Task services cleaned up successfully")
        except Exception as cleanup_error:
            logger.warning(
                f"Error during task cleanup: {cleanup_error}. Non-critical.",
                exc_info=True,
            )
