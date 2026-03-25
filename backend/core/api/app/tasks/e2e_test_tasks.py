# backend/core/api/app/tasks/e2e_test_tasks.py
"""
Celery tasks for processing individual E2E test results reported by Playwright.

The Playwright custom API reporter (frontend/apps/web_app/tests/api-reporter.ts)
POSTs individual test results to the internal API, which dispatches this task
to send failure notification emails.

Daily test scheduling is handled by a system crontab (see `crontab -l`)
that runs scripts/run-tests-daily.sh directly on the host — no Celery
involvement for scheduling or orchestration.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from backend.core.api.app.tasks.celery_config import app
from celery import Task

logger = logging.getLogger(__name__)


class E2ETestTask(Task):
    """Base task class for E2E test result processing."""
    abstract = True


def _send_failure_notifications(
    environment: str,
    test_file: str,
    test_name: str,
    status: str,
    timestamp: str,
    duration_seconds: float,
    error_message: Optional[str] = None,
    console_logs: Optional[str] = None,
    network_activities: Optional[str] = None
) -> bool:
    """
    Send failure notification via Celery email task.

    This dispatches an email notification task for a failed test.

    Returns:
        bool: True if notification was dispatched successfully
    """
    admin_email = os.getenv("SERVER_OWNER_EMAIL")
    if not admin_email:
        logger.error("SERVER_OWNER_EMAIL not set, cannot send failure notifications")
        return False

    try:
        app.send_task(
            name='app.tasks.email_tasks.test_notification_email_task.send_test_failure_notification',
            args=[
                admin_email,
                environment,
                test_file,
                test_name,
                status,
                timestamp,
                duration_seconds,
                error_message,
                console_logs,
                network_activities
            ],
            queue='email'
        )
        logger.info(f"Dispatched failure notification for test: {test_name}")
        return True
    except Exception as e:
        logger.error(f"Failed to dispatch notification for {test_name}: {e}")
        return False


@app.task(name='e2e_tests.process_test_result', base=E2ETestTask, bind=True)
def process_test_result(
    self,
    environment: str,
    test_file: str,
    test_name: str,
    status: str,
    duration_seconds: float,
    error_message: Optional[str] = None,
    console_logs: Optional[str] = None,
    network_activities: Optional[str] = None
) -> Dict[str, Any]:
    """
    Process a test result and send notification if the test failed.

    This task is called by the Playwright reporter (via the internal API)
    when a test completes. It only sends notifications for failed tests.

    Args:
        environment: The environment where the test ran
        test_file: The test file name
        test_name: The test name
        status: The test status ("passed", "failed", "timedout", etc.)
        duration_seconds: How long the test took
        error_message: Error details if the test failed
        console_logs: Console logs captured during the test
        network_activities: Network activity logs captured during the test

    Returns:
        Dictionary with processing result
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    if status == "passed":
        logger.info(f"Test passed: {test_name} ({test_file}) in {duration_seconds:.1f}s")
        return {
            "status": "success",
            "notification_sent": False,
            "reason": "Test passed, no notification needed"
        }

    logger.warning(
        f"Test {status}: {test_name} ({test_file}) in {duration_seconds:.1f}s - "
        f"Error: {error_message[:200] if error_message else 'N/A'}..."
    )

    # Send notification for failed test
    notification_sent = _send_failure_notifications(
        environment=environment,
        test_file=test_file,
        test_name=test_name,
        status=status,
        timestamp=timestamp,
        duration_seconds=duration_seconds,
        error_message=error_message,
        console_logs=console_logs,
        network_activities=network_activities
    )

    return {
        "status": "processed",
        "notification_sent": notification_sent,
        "test_status": status,
        "test_name": test_name,
        "test_file": test_file
    }
