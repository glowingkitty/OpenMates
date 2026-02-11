# backend/core/api/app/tasks/e2e_test_tasks.py
"""
Celery tasks for running automated E2E tests and reporting failures.

This module provides:
1. Scheduled tasks that trigger E2E test runs
2. Email notification dispatch for test failures
3. Configuration for development vs production testing

ARCHITECTURE:
- Tests are run via a separate Playwright Docker container (docker-compose.playwright.yml)
- The Playwright container uses a custom reporter that POSTs results to our internal API
- The internal API dispatches email notification tasks via Celery

To enable automated testing:
1. Set the required environment variables (test account credentials, Mailosaur keys)
2. Ensure docker-compose.playwright.yml is configured correctly
3. The hourly scheduled task will trigger test runs

For manual test execution, use:
  docker compose -f docker-compose.playwright.yml run --rm playwright
"""

import logging
import os
import asyncio
import httpx
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from backend.core.api.app.tasks.celery_config import app
from celery import Task

logger = logging.getLogger(__name__)


# Configuration
E2E_TEST_CONFIG = {
    "development": {
        "base_url": os.getenv("E2E_TEST_DEV_BASE_URL", "https://app.dev.openmates.org"),
        "enabled": os.getenv("E2E_TEST_DEV_ENABLED", "true").lower() == "true",
    },
    "production": {
        "base_url": os.getenv("E2E_TEST_PROD_BASE_URL", "https://openmates.org"),
        "enabled": os.getenv("E2E_TEST_PROD_ENABLED", "false").lower() == "true",
    }
}

# Test files to run - can be overridden via environment variable
DEFAULT_TEST_FILES = [
    "chat-flow.spec.ts",  # Login + send message (uses existing test account)
]

# Tests that require signup resources (Mailosaur, etc.) - run less frequently
SIGNUP_TEST_FILES = [
    "signup-flow.spec.ts",
    "signup-flow-passkey.spec.ts",
]


class E2ETestTask(Task):
    """Base task class for E2E test execution."""
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


async def _trigger_playwright_run_async(
    test_files: List[str],
    environment: str,
    base_url: str
) -> Dict[str, Any]:
    """
    Trigger a Playwright test run via HTTP to the test runner service.
    
    This is an async function that can be called from Celery tasks.
    
    NOTE: This approach requires a separate test runner service that:
    1. Accepts HTTP requests to trigger test runs
    2. Runs Playwright tests
    3. Reports results back to our internal API
    
    For now, we'll log a message indicating manual test execution is required.
    """
    logger.info(
        f"E2E test run requested for {environment} environment. "
        f"Tests: {test_files}, Base URL: {base_url}"
    )
    
    # Check if test runner endpoint is configured
    test_runner_url = os.getenv("E2E_TEST_RUNNER_URL")
    
    if not test_runner_url:
        logger.warning(
            "E2E_TEST_RUNNER_URL not configured. "
            "To enable automated testing, either:\n"
            "1. Set up an external test runner service and configure E2E_TEST_RUNNER_URL\n"
            "2. Run tests manually: docker compose -f docker-compose.playwright.yml run --rm playwright"
        )
        return {
            "status": "manual_required",
            "message": "Automated test runner not configured. Run tests manually.",
            "environment": environment,
            "test_files": test_files,
            "base_url": base_url
        }
    
    # If we have a test runner URL, trigger the test run
    try:
        internal_token = os.getenv("INTERNAL_API_SHARED_TOKEN", "")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{test_runner_url}/run",
                json={
                    "test_files": test_files,
                    "environment": environment,
                    "base_url": base_url
                },
                headers={
                    "X-Internal-Service-Token": internal_token
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"Test run triggered successfully: {result}")
                return {
                    "status": "triggered",
                    "result": result,
                    "environment": environment,
                    "test_files": test_files
                }
            else:
                logger.error(f"Test runner returned error: {response.status_code} - {response.text}")
                return {
                    "status": "error",
                    "error": f"Test runner returned {response.status_code}",
                    "environment": environment,
                    "test_files": test_files
                }
                
    except httpx.TimeoutException:
        logger.error("Timeout connecting to test runner service")
        return {
            "status": "timeout",
            "error": "Timeout connecting to test runner",
            "environment": environment,
            "test_files": test_files
        }
    except Exception as e:
        logger.error(f"Error triggering test run: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
            "environment": environment,
            "test_files": test_files
        }


def _trigger_playwright_run(
    test_files: List[str],
    environment: str,
    base_url: str
) -> Dict[str, Any]:
    """Synchronous wrapper for async test trigger function."""
    return asyncio.run(_trigger_playwright_run_async(test_files, environment, base_url))


@app.task(name='e2e_tests.run_dev_tests', base=E2ETestTask, bind=True)
def run_dev_e2e_tests(self, test_files: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Run E2E tests against the development environment.
    
    This task is scheduled to run hourly via Celery Beat.
    
    Args:
        test_files: Optional list of test files to run. Defaults to DEFAULT_TEST_FILES.
        
    Returns:
        Dictionary with test trigger results
    """
    config = E2E_TEST_CONFIG["development"]
    
    if not config["enabled"]:
        logger.info("Development E2E tests are disabled")
        return {"status": "disabled", "environment": "development"}
    
    test_files = test_files or DEFAULT_TEST_FILES
    
    logger.info(f"Starting scheduled E2E tests for development: {test_files}")
    
    return _trigger_playwright_run(
        test_files=test_files,
        environment="development",
        base_url=config["base_url"]
    )


@app.task(name='e2e_tests.run_prod_tests', base=E2ETestTask, bind=True)
def run_prod_e2e_tests(self, test_files: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Run E2E tests against the production environment.
    
    This task can be scheduled via Celery Beat or triggered manually.
    By default, production tests are disabled for safety.
    
    Args:
        test_files: Optional list of test files to run. Defaults to DEFAULT_TEST_FILES.
        
    Returns:
        Dictionary with test trigger results
    """
    config = E2E_TEST_CONFIG["production"]
    
    if not config["enabled"]:
        logger.info("Production E2E tests are disabled (set E2E_TEST_PROD_ENABLED=true to enable)")
        return {"status": "disabled", "environment": "production"}
    
    # For production, only run safe tests (no signup tests that create real accounts)
    test_files = test_files or DEFAULT_TEST_FILES
    
    # Filter out signup tests for production
    safe_tests = [f for f in test_files if f not in SIGNUP_TEST_FILES]
    if len(safe_tests) < len(test_files):
        logger.warning(f"Filtered out signup tests for production. Running: {safe_tests}")
    
    if not safe_tests:
        logger.warning("No safe tests to run in production after filtering")
        return {"status": "no_safe_tests", "environment": "production"}
    
    logger.info(f"Starting scheduled E2E tests for production: {safe_tests}")
    
    return _trigger_playwright_run(
        test_files=safe_tests,
        environment="production",
        base_url=config["base_url"]
    )


@app.task(name='e2e_tests.run_signup_tests', base=E2ETestTask, bind=True)
def run_signup_e2e_tests(self, environment: str = "development") -> Dict[str, Any]:
    """
    Run signup E2E tests. These are run less frequently as they consume
    Mailosaur credits and create real (then deleted) accounts.
    
    Args:
        environment: "development" only (signup tests should never run in production)
        
    Returns:
        Dictionary with test trigger results
    """
    if environment != "development":
        logger.warning("Signup tests should only run in development environment")
        return {"status": "wrong_environment", "environment": environment}
    
    config = E2E_TEST_CONFIG["development"]
    
    if not config["enabled"]:
        logger.info("Development E2E tests are disabled")
        return {"status": "disabled", "environment": "development"}
    
    logger.info(f"Starting signup E2E tests for development: {SIGNUP_TEST_FILES}")
    
    return _trigger_playwright_run(
        test_files=SIGNUP_TEST_FILES,
        environment="development",
        base_url=config["base_url"]
    )


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
