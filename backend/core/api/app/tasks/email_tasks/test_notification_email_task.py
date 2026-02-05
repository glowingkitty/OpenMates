# backend/core/api/app/tasks/email_tasks/test_notification_email_task.py
"""
Celery task for sending E2E test failure notification emails to server owner/admin.

This module handles sending notifications when automated Playwright E2E tests fail,
alerting the operations team to potential issues with the application.
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


@app.task(name='app.tasks.email_tasks.test_notification_email_task.send_test_failure_notification', base=BaseServiceTask, bind=True)
def send_test_failure_notification(
    self: BaseServiceTask,
    admin_email: str,
    environment: str = "development",
    test_file: str = "",
    test_name: str = "",
    status: str = "failed",
    timestamp: str = "",
    duration_seconds: float = 0.0,
    error_message: Optional[str] = None,
    console_logs: Optional[str] = None,
    network_activities: Optional[str] = None
) -> bool:
    """
    Celery task to send E2E test failure notification email to server owner/admin.

    Args:
        admin_email: The email address of the admin/server owner to notify
        environment: The environment where the test ran (e.g., "development", "production")
        test_file: The name of the test file that failed
        test_name: The name of the specific test that failed
        status: The test status (e.g., "failed", "timedout", "passed")
        timestamp: Timestamp when the test ran (formatted string)
        duration_seconds: How long the test took to run in seconds
        error_message: The error message or stack trace from the test failure
        console_logs: Console logs captured during the test (last 20 entries)
        network_activities: Network request/response logs captured during the test (last 20 entries)

    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    logger.info(
        f"Starting test failure notification email task for test: '{test_name}' "
        f"(task_id={self.request.id if hasattr(self.request, 'id') else 'unknown'}, "
        f"status={status}, environment={environment}, recipient={admin_email})"
    )
    try:
        # Use asyncio.run() which handles loop creation and cleanup properly
        result = asyncio.run(
            _async_send_test_failure_notification(
                self, admin_email, environment, test_file, test_name,
                status, timestamp, duration_seconds, error_message,
                console_logs, network_activities
            )
        )
        if result:
            logger.info(
                f"Test failure notification email task completed successfully for test: '{test_name}' "
                f"(status={status}, environment={environment}, recipient={admin_email})"
            )
        else:
            logger.error(
                f"Test failure notification email task failed for test: '{test_name}' "
                f"(status={status}, environment={environment}, recipient={admin_email}) - check logs above for details"
            )
        return result
    except Exception as e:
        logger.error(
            f"Failed to run test failure notification email task for test '{test_name}': {str(e)} "
            f"(status={status}, environment={environment}, recipient={admin_email})",
            exc_info=True
        )
        return False


async def _async_send_test_failure_notification(
    task: BaseServiceTask,
    admin_email: str,
    environment: str = "development",
    test_file: str = "",
    test_name: str = "",
    status: str = "failed",
    timestamp: str = "",
    duration_seconds: float = 0.0,
    error_message: Optional[str] = None,
    console_logs: Optional[str] = None,
    network_activities: Optional[str] = None
) -> bool:
    """
    Async implementation for sending test failure notification email.

    Note: This function ensures proper cleanup of async resources (like httpx clients)
    before the event loop closes to prevent "Event loop is closed" errors.
    """
    try:
        # Initialize services using the base task class method
        logger.info("Initializing services for test failure notification email task...")
        await task.initialize_services()
        logger.info("Services initialized for test failure notification email task")

        # Verify email_template_service is available
        if not hasattr(task, 'email_template_service') or task.email_template_service is None:
            logger.error("email_template_service not available after initialization")
            return False
        logger.info("email_template_service is available")

        # SECURITY: Sanitize inputs before passing to email template
        from html import escape

        # HTML escape all text inputs
        sanitized_test_file = escape(test_file) if test_file else "Unknown"
        sanitized_test_name = escape(test_name) if test_name else "Unknown"
        sanitized_environment = escape(environment) if environment else "Unknown"
        sanitized_status = escape(status) if status else "Unknown"

        # Truncate and escape error message to prevent huge emails
        sanitized_error = None
        if error_message:
            # Limit error message to 5000 chars
            truncated_error = error_message[:5000]
            if len(error_message) > 5000:
                truncated_error += "\n... [truncated]"
            sanitized_error = escape(truncated_error)

        # Truncate and escape logs
        sanitized_console_logs = None
        if console_logs:
            truncated_logs = console_logs[:3000]
            if len(console_logs) > 3000:
                truncated_logs += "\n... [truncated]"
            sanitized_console_logs = escape(truncated_logs)

        sanitized_network = None
        if network_activities:
            truncated_network = network_activities[:3000]
            if len(network_activities) > 3000:
                truncated_network += "\n... [truncated]"
            sanitized_network = escape(truncated_network)

        # Prepare email context with sanitized data
        email_context = {
            "darkmode": True,  # Default to dark mode for admin emails
            "environment": sanitized_environment,
            "test_file": sanitized_test_file,
            "test_name": sanitized_test_name,
            "status": sanitized_status,
            "timestamp": timestamp,
            "duration_seconds": round(duration_seconds, 2),
            "error_message": sanitized_error,
            "console_logs": sanitized_console_logs,
            "network_activities": sanitized_network
        }
        logger.info("Prepared email context for test failure notification")

        # Send test failure notification email
        logger.info(
            f"Attempting to send test failure notification email to {admin_email} "
            f"with template 'test_failure_notification' (test: '{test_name}', status: '{status}')"
        )
        email_success = await task.email_template_service.send_email(
            template="test_failure_notification",
            recipient_email=admin_email,
            context=email_context,
            lang="en"  # Default to English for admin emails
        )

        if not email_success:
            logger.error(
                f"Failed to send test failure notification email to {admin_email} - "
                f"send_email() returned False. Check email service configuration and logs."
            )
            return False

        logger.info(
            f"Successfully sent test failure notification email to {admin_email} "
            f"(test: '{test_name}', status: '{status}', environment: '{environment}')"
        )
        return True

    except Exception as e:
        logger.error(f"Error sending test failure notification email: {str(e)}", exc_info=True)
        return False

    finally:
        # CRITICAL: Close async resources (like httpx clients) before the event loop closes
        # This prevents "Event loop is closed" errors during cleanup
        try:
            await task.cleanup_services()
            logger.debug("Task services cleaned up successfully")
        except Exception as cleanup_error:
            # Log but don't raise - we're in cleanup and don't want to mask the original error
            logger.warning(
                f"Error during task cleanup: {str(cleanup_error)}. "
                f"This is non-critical but should be investigated.",
                exc_info=True
            )
