# backend/core/api/app/tasks/email_tasks/test_run_summary_email_task.py
"""
Celery task for sending a daily automated test run summary email to the admin.

This module sends a SINGLE summary email after each daily automated test run,
covering all test suites (vitest, pytest unit, pytest integration, Playwright E2E).
It replaces the per-test failure emails for the daily run scenario.

The email subject is:
  - "All tests successful" when all tests pass
  - "Warning: X of Y tests failed!" when failures exist

Architecture: run-tests-daily.sh → dispatches this task via celery_dispatch_task.py
→ EmailTemplateService (Brevo/Mailjet). See docs/architecture/health-checks.md
"""

import logging
import asyncio
from typing import List, Dict, Any

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.utils.log_filters import SensitiveDataFilter

logger = logging.getLogger(__name__)
sensitive_filter = SensitiveDataFilter()
logger.addFilter(sensitive_filter)

# Maximum error snippet length per failed test to keep email readable
MAX_ERROR_SNIPPET_LENGTH = 400


@app.task(
    name="app.tasks.email_tasks.test_run_summary_email_task.send_test_run_summary",
    base=BaseServiceTask,
    bind=True,
)
def send_test_run_summary(
    self: BaseServiceTask,
    admin_email: str,
    run_id: str,
    git_sha: str,
    git_branch: str,
    duration_seconds: int,
    total: int,
    passed: int,
    failed: int,
    skipped: int,
    suites: List[Dict[str, Any]],
    failed_tests: List[Dict[str, Any]],
) -> bool:
    """
    Celery task to send a single daily test run summary email to the admin.

    Args:
        admin_email: Recipient email address (SERVER_OWNER_EMAIL).
        run_id: ISO timestamp string identifying this test run.
        git_sha: Short git commit SHA the tests ran against.
        git_branch: Git branch name the tests ran against.
        duration_seconds: Total wall-clock duration of the full test run.
        total: Total number of individual tests that ran.
        passed: Number of tests that passed.
        failed: Number of tests that failed.
        skipped: Number of tests that were skipped.
        suites: List of suite summary dicts with keys:
            name, total, passed, failed, status
        failed_tests: List of failed test dicts with keys:
            suite, name, error (truncated snippet)

    Returns:
        bool: True if the email was sent successfully, False otherwise.
    """
    logger.info(
        f"Starting test run summary email task: run_id='{run_id}', "
        f"total={total}, passed={passed}, failed={failed}, recipient={admin_email}"
    )
    try:
        result = asyncio.run(
            _async_send_test_run_summary(
                self,
                admin_email=admin_email,
                run_id=run_id,
                git_sha=git_sha,
                git_branch=git_branch,
                duration_seconds=duration_seconds,
                total=total,
                passed=passed,
                failed=failed,
                skipped=skipped,
                suites=suites,
                failed_tests=failed_tests,
            )
        )
        if result:
            logger.info(
                f"Test run summary email sent successfully: run_id='{run_id}', "
                f"failed={failed}, recipient={admin_email}"
            )
        else:
            logger.error(
                f"Test run summary email task failed: run_id='{run_id}', "
                f"recipient={admin_email} — check logs above for details"
            )
        return result
    except Exception as e:
        logger.error(
            f"Failed to run test run summary email task: run_id='{run_id}', "
            f"recipient={admin_email}: {e}",
            exc_info=True,
        )
        return False


async def _async_send_test_run_summary(
    task: BaseServiceTask,
    admin_email: str,
    run_id: str,
    git_sha: str,
    git_branch: str,
    duration_seconds: int,
    total: int,
    passed: int,
    failed: int,
    skipped: int,
    suites: List[Dict[str, Any]],
    failed_tests: List[Dict[str, Any]],
) -> bool:
    """
    Async implementation for sending the daily test run summary email.

    Initializes BaseServiceTask services, builds the email context, then sends
    via EmailTemplateService (Brevo/Mailjet). Subject line varies by outcome:
    - "All tests successful" when failed == 0
    - "Warning: X of Y tests failed!" when failed > 0
    """
    from html import escape

    try:
        logger.info("Initializing services for test run summary email task...")
        await task.initialize_services()
        logger.info("Services initialized for test run summary email task")

        if not hasattr(task, "email_template_service") or task.email_template_service is None:
            logger.error("email_template_service not available after initialization")
            return False

        # Build email subject — matches the user-requested subject format exactly
        if failed == 0:
            subject = "All tests successful"
        else:
            subject = f"Warning: {failed} of {total} tests failed!"

        # Duration breakdown for human-readable display
        duration_minutes = duration_seconds // 60
        duration_remainder_seconds = duration_seconds % 60

        # Sanitize git fields
        sanitized_git_sha = escape(git_sha) if git_sha else "unknown"
        sanitized_git_branch = escape(git_branch) if git_branch else "unknown"
        sanitized_run_id = escape(run_id) if run_id else "unknown"

        # Sanitize suite summaries
        sanitized_suites = []
        for suite in suites:
            sanitized_suites.append({
                "name": escape(str(suite.get("name", ""))),
                "total": int(suite.get("total", 0)),
                "passed": int(suite.get("passed", 0)),
                "failed": int(suite.get("failed", 0)),
                "status": escape(str(suite.get("status", "unknown"))),
            })

        # Sanitize failed test entries and truncate error snippets
        sanitized_failed = []
        for ft in failed_tests:
            error_raw = ft.get("error", "") or ""
            if len(error_raw) > MAX_ERROR_SNIPPET_LENGTH:
                error_raw = error_raw[:MAX_ERROR_SNIPPET_LENGTH] + "... [truncated]"
            sanitized_failed.append({
                "suite": escape(str(ft.get("suite", ""))),
                "name": escape(str(ft.get("name", ""))),
                "error": escape(error_raw) if error_raw else None,
            })

        email_context = {
            "darkmode": True,  # Admin emails always use dark mode
            "subject": subject,
            "run_id": sanitized_run_id,
            "git_sha": sanitized_git_sha,
            "git_branch": sanitized_git_branch,
            "duration_minutes": duration_minutes,
            "duration_remainder_seconds": duration_remainder_seconds,
            "total": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "suites": sanitized_suites,
            "failed_tests": sanitized_failed,
        }

        logger.info(
            f"Sending test run summary email to {admin_email} "
            f"(subject='{subject}', failed={failed}/{total})"
        )

        email_success = await task.email_template_service.send_email(
            template="test_run_summary",
            recipient_email=admin_email,
            context=email_context,
            subject=subject,
            lang="en",  # Admin emails always in English
        )

        if not email_success:
            logger.error(
                f"Failed to send test run summary email to {admin_email} — "
                f"send_email() returned False. Check email service configuration."
            )
            return False

        logger.info(
            f"Successfully sent test run summary email to {admin_email} "
            f"(run_id='{run_id}', failed={failed}/{total})"
        )
        return True

    except Exception as e:
        logger.error(
            f"Error sending test run summary email: {e}",
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
