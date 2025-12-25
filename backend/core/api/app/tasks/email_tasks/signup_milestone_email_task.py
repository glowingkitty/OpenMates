# backend/core/api/app/tasks/email_tasks/signup_milestone_email_task.py
import logging
import asyncio
from datetime import datetime, timezone

# Import the Celery app and Base Task
from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.tasks.base_task import BaseServiceTask

# Import necessary services and utilities
from backend.core.api.app.utils.log_filters import SensitiveDataFilter

# Setup loggers
logger = logging.getLogger(__name__)
sensitive_filter = SensitiveDataFilter()
logger.addFilter(sensitive_filter)
event_logger = logging.getLogger("app.events")
event_logger.addFilter(sensitive_filter)


@app.task(name='app.tasks.email_tasks.signup_milestone_email_task.send_milestone_notification', base=BaseServiceTask, bind=True)
def send_milestone_notification(
    self: BaseServiceTask,
    user_count: int,
    admin_email: str,
    milestone_number: int
) -> bool:
    """
    Celery task to send milestone notification email to admin when user signup milestones are reached.
    
    Args:
        user_count: The current total number of users
        admin_email: The email address of the admin to notify
        milestone_number: The milestone that was reached (1, 2, 3, etc.)
    
    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    logger.info(f"Starting milestone notification task for milestone: {milestone_number}, user count: {user_count}")
    try:
        # Create a new event loop for async operations
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Run the async function and return its result
        result = loop.run_until_complete(
            _async_send_milestone_notification(
                self, user_count, admin_email, milestone_number
            )
        )
        logger.info(f"Milestone notification task completed for milestone: {milestone_number}. Success: {result}")
        return result
    
    except Exception as e:
        logger.error(f"Failed to run milestone notification task for milestone {milestone_number}: {str(e)}", exc_info=True)
        return False
    
    finally:
        # Clean up the loop
        loop.close()


async def _async_send_milestone_notification(
    task: BaseServiceTask,
    user_count: int,
    admin_email: str,
    milestone_number: int
) -> bool:
    """
    Async implementation for sending milestone notification email.
    """
    try:
        # Log the admin email for debugging
        logger.info(f"Admin email for milestone notification: {admin_email[:2]}*** (full address exists: {bool(admin_email)})")
        
        # 1. Initialize all necessary services using the base task class method
        logger.info(f"Initializing services for milestone notification task {milestone_number}...")
        await task.initialize_services()
        logger.info(f"Services initialized for milestone notification task {milestone_number}")
        
        # Verify email_template_service is available
        if not hasattr(task, 'email_template_service') or task.email_template_service is None:
            logger.error(f"email_template_service not available after initialization for milestone {milestone_number}")
            return False
        logger.info(f"email_template_service is available for milestone {milestone_number}")

        # 2. Prepare Email Context
        current_date = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        email_context = {
            "darkmode": False,  # Default to light mode for admin emails
            "user_count": user_count,
            "milestone_date": current_date
        }
        logger.info(f"Prepared email context for milestone notification: {email_context}")

        # 3. Send Milestone Notification Email
        logger.info(f"Attempting to send milestone email to {admin_email[:2]}*** with template 'signup_milestone'")
        email_success = await task.email_template_service.send_email(
            template="signup_milestone",
            recipient_email=admin_email,
            context=email_context,
            lang="en"  # Default to English for admin emails
        )

        if not email_success:
            logger.error(f"Failed to send milestone notification email to {admin_email[:2]}***")
            return False

        logger.info(f"Successfully sent milestone notification email for milestone {milestone_number}")
        return True

    except Exception as e:
        logger.error(f"Error in _async_send_milestone_notification task: {str(e)}", exc_info=True)
        # Re-raise the exception so Celery knows the task failed
        raise e


@app.task(name='app.tasks.email_tasks.signup_milestone_email_task.send_newsletter_milestone_notification', base=BaseServiceTask, bind=True)
def send_newsletter_milestone_notification(
    self: BaseServiceTask,
    subscriber_count: int,
    admin_email: str,
    milestone_number: int
) -> bool:
    """
    Celery task to send newsletter milestone notification email to admin when newsletter signup milestones are reached.

    Args:
        subscriber_count: The current total number of newsletter subscribers
        admin_email: The email address of the admin to notify
        milestone_number: The milestone that was reached (1, 2, 5, etc.)

    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    logger.info(f"Starting newsletter milestone notification task for milestone: {milestone_number}, subscriber count: {subscriber_count}")
    try:
        # Create a new event loop for async operations
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # Run the async function and return its result
        result = loop.run_until_complete(
            _async_send_newsletter_milestone_notification(
                self, subscriber_count, admin_email, milestone_number
            )
        )
        logger.info(f"Newsletter milestone notification task completed for milestone: {milestone_number}. Success: {result}")
        return result

    except Exception as e:
        logger.error(f"Failed to run newsletter milestone notification task for milestone {milestone_number}: {str(e)}", exc_info=True)
        return False

    finally:
        # Clean up the loop
        loop.close()


async def _async_send_newsletter_milestone_notification(
    task: BaseServiceTask,
    subscriber_count: int,
    admin_email: str,
    milestone_number: int
) -> bool:
    """
    Async implementation for sending newsletter milestone notification email.
    """
    try:
        # Log the admin email for debugging
        logger.info(f"Admin email for newsletter milestone notification: {admin_email[:2]}*** (full address exists: {bool(admin_email)})")

        # 1. Initialize all necessary services using the base task class method
        logger.info(f"Initializing services for newsletter milestone notification task {milestone_number}...")
        await task.initialize_services()
        logger.info(f"Services initialized for newsletter milestone notification task {milestone_number}")

        # Verify email_template_service is available
        if not hasattr(task, 'email_template_service') or task.email_template_service is None:
            logger.error(f"email_template_service not available after initialization for newsletter milestone {milestone_number}")
            return False
        logger.info(f"email_template_service is available for newsletter milestone {milestone_number}")

        # 2. Prepare Email Context
        current_date = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        email_context = {
            "darkmode": False,  # Default to light mode for admin emails
            "subscriber_count": subscriber_count,
            "milestone_date": current_date,
            "milestone_type": "newsletter"
        }
        logger.info(f"Prepared email context for newsletter milestone notification: {email_context}")

        # 3. Send Newsletter Milestone Notification Email
        logger.info(f"Attempting to send newsletter milestone email to {admin_email[:2]}*** with template 'newsletter_milestone'")
        email_success = await task.email_template_service.send_email(
            template="newsletter_milestone",
            recipient_email=admin_email,
            context=email_context,
            lang="en"  # Default to English for admin emails
        )

        if not email_success:
            logger.error(f"Failed to send newsletter milestone notification email to {admin_email[:2]}***")
            return False

        logger.info(f"Successfully sent newsletter milestone notification email for milestone {milestone_number}")
        return True

    except Exception as e:
        logger.error(f"Error in _async_send_newsletter_milestone_notification task: {str(e)}", exc_info=True)
        # Re-raise the exception so Celery knows the task failed
        raise e