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
import re
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
    not_started: int,
    suites: List[Dict[str, Any]],
    failed_tests: List[Dict[str, Any]],
    environment: str = "development",
    all_tests: List[Dict[str, Any]] = None,
    opencode_chat_url: str = None,
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
        not_started: Number of tests not started due to earlier failure.
        suites: List of suite summary dicts with keys:
            name, total, passed, failed, status
        failed_tests: List of failed test dicts with keys:
            suite, name, error (truncated snippet)
        environment: Server environment, "development" or "production".
        all_tests: Optional list of all individual test dicts with keys:
            suite, name, status, duration_seconds. When provided, the email
            shows every test with pass/fail/skip icons.

    Returns:
        bool: True if the email was sent successfully, False otherwise.
    """
    if all_tests is None:
        all_tests = []
    logger.info(
        f"Starting test run summary email task: run_id='{run_id}', "
        f"environment='{environment}', total={total}, passed={passed}, "
        f"failed={failed}, recipient={admin_email}, "
        f"all_tests_count={len(all_tests)}"
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
                not_started=not_started,
                suites=suites,
                failed_tests=failed_tests,
                environment=environment,
                all_tests=all_tests,
                opencode_chat_url=opencode_chat_url,
            )
        )
        if result:
            logger.info(
                f"Test run summary email sent successfully: run_id='{run_id}', "
                f"environment='{environment}', failed={failed}, recipient={admin_email}"
            )
        else:
            logger.error(
                f"Test run summary email task failed: run_id='{run_id}', "
                f"environment='{environment}', recipient={admin_email} — check logs above for details"
            )
        return result
    except Exception as e:
        logger.error(
            f"Failed to run test run summary email task: run_id='{run_id}', "
            f"environment='{environment}', recipient={admin_email}: {e}",
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
    not_started: int,
    suites: List[Dict[str, Any]],
    failed_tests: List[Dict[str, Any]],
    environment: str = "development",
    all_tests: List[Dict[str, Any]] = None,
    opencode_chat_url: str = None,
) -> bool:
    """
    Async implementation for sending the daily test run summary email.

    Initializes BaseServiceTask services, builds the email context, then sends
    via EmailTemplateService (Brevo/Mailjet). Subject line varies by outcome:
    - "All tests successful" when failed == 0
    - "Warning: X of Y tests failed!" when failed > 0
    """
    from html import escape

    if all_tests is None:
        all_tests = []

    try:
        logger.info("Initializing services for test run summary email task...")
        await task.initialize_services()
        logger.info("Services initialized for test run summary email task")

        if not hasattr(task, "email_template_service") or task.email_template_service is None:
            logger.error("email_template_service not available after initialization")
            return False

        environment_label = "Production" if environment == "production" else "Development"

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

        # Sanitize failed test entries and truncate error snippets.
        # Strip ANSI escape codes first — Playwright/pytest output frequently
        # contains terminal color codes (e.g. \x1b[31m). These control chars
        # cause mjml2html() to fail with a misleading "unable to load included
        # template" error, even after html.escape() has been applied.
        _ansi_re = re.compile(r"\x1b\[[0-9;]*[mKHJABCDsuGfFnRh]")
        sanitized_failed = []
        for ft in failed_tests:
            error_raw = ft.get("error", "") or ""
            error_raw = _ansi_re.sub("", error_raw)  # strip ANSI before HTML-escaping
            if len(error_raw) > MAX_ERROR_SNIPPET_LENGTH:
                error_raw = error_raw[:MAX_ERROR_SNIPPET_LENGTH] + "... [truncated]"
            sanitized_failed.append({
                "suite": escape(str(ft.get("suite", ""))),
                "name": escape(str(ft.get("name", ""))),
                "error": escape(error_raw) if error_raw else None,
            })

        # Build all_tests grouped by suite for the full test list in the email.
        # Each entry gets a status icon and sanitized name.
        sanitized_all_tests_by_suite: Dict[str, List[Dict[str, Any]]] = {}
        for t in all_tests:
            suite_name = escape(str(t.get("suite", "unknown")))
            status_raw = str(t.get("status", "unknown"))
            test_name = escape(str(t.get("name", "")))
            duration_s = t.get("duration_seconds", 0)

            # Choose status icon
            if status_raw == "passed":
                icon = "✅"
            elif status_raw == "failed":
                icon = "❌"
            elif status_raw == "skipped":
                icon = "⏭️"
            elif status_raw == "not_started":
                icon = "⏸️"
            else:
                icon = "❓"

            entry = {
                "name": test_name,
                "status": status_raw,
                "icon": icon,
                "duration_seconds": duration_s,
            }

            if suite_name not in sanitized_all_tests_by_suite:
                sanitized_all_tests_by_suite[suite_name] = []
            sanitized_all_tests_by_suite[suite_name].append(entry)

        # Sanitize the opencode chat URL — only allow https://opencode.ai/s/... links
        sanitized_chat_url = None
        if opencode_chat_url and opencode_chat_url.startswith("https://opencode.ai/s/"):
            sanitized_chat_url = escape(opencode_chat_url)

        email_context = {
            "darkmode": True,  # Admin emails always use dark mode
            "subject": subject,
            "environment": environment_label,
            "run_id": sanitized_run_id,
            "git_sha": sanitized_git_sha,
            "git_branch": sanitized_git_branch,
            "duration_minutes": duration_minutes,
            "duration_remainder_seconds": duration_remainder_seconds,
            "total": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "not_started": not_started,
            "suites": sanitized_suites,
            "failed_tests": sanitized_failed,
            "all_tests_by_suite": sanitized_all_tests_by_suite,
            "has_all_tests": len(all_tests) > 0,
            "opencode_chat_url": sanitized_chat_url,  # AI analysis session link (None if no failures or analysis unavailable)
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
