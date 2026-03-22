# backend/core/api/app/tasks/email_tasks/milestone_checker_task.py
import logging
import os
from typing import Optional

from backend.core.api.app.tasks.celery_config import app

logger = logging.getLogger(__name__)

# Define the milestones we want to track
SIGNUP_MILESTONES = [1, 2, 5, 10, 15, 20, 30, 40, 50, 70, 100, 150, 200, 300]

def _generate_additional_milestones(base_milestones, last_milestone=300, step=100, limit=5000):
    """Generate additional milestones every 100 users starting after 300."""
    additional = []
    current = last_milestone + step
    while current <= limit:
        additional.append(current)
        current += step
    return base_milestones + additional

# Generate the complete milestone list
SIGNUP_MILESTONES = _generate_additional_milestones(SIGNUP_MILESTONES)
NEWSLETTER_MILESTONES = _generate_additional_milestones([1, 2, 5, 10, 15, 20, 30, 40, 50, 70, 100, 150, 200, 300])

def check_user_signup_milestone(total_users: int) -> Optional[int]:
    """
    Check if the current user count has reached a milestone.
    
    Args:
        total_users: The current total number of users
        
    Returns:
        int: The milestone that was reached, or None if no milestone was reached
    """
    # Check if the current count matches any of our milestones
    if total_users in SIGNUP_MILESTONES:
        logger.info(f"User signup milestone reached: {total_users} users")
        return total_users
    return None

def check_newsletter_signup_milestone(total_subscribers: int) -> Optional[int]:
    """
    Check if the current newsletter subscriber count has reached a milestone.

    Args:
        total_subscribers: The current total number of newsletter subscribers

    Returns:
        int: The milestone that was reached, or None if no milestone was reached
    """
    # Check if the current count matches any of our milestones
    if total_subscribers in NEWSLETTER_MILESTONES:
        logger.info(f"Newsletter subscription milestone reached: {total_subscribers} subscribers")
        return total_subscribers
    return None

@app.task(name='app.tasks.email_tasks.milestone_checker_task.check_and_notify_milestone')
def check_and_notify_milestone(total_users: int) -> bool:
    """
    Celery task to check if a milestone was reached and send notification if so.
    
    Args:
        total_users: The current total number of users
        
    Returns:
        bool: True if a milestone was reached and notification sent, False otherwise
    """
    try:
        milestone = check_user_signup_milestone(total_users)
        if milestone:
            # Get admin email from environment variable
            admin_email = os.getenv("ADMIN_NOTIFY_EMAIL", "notify@openmates.org")
            
            # Dispatch the email task
            app.send_task(
                name='app.tasks.email_tasks.signup_milestone_email_task.send_milestone_notification',
                kwargs={
                    "user_count": total_users,
                    "admin_email": admin_email,
                    "milestone_number": milestone
                },
                queue='email'
            )
            logger.info(f"Dispatched milestone notification task for milestone {milestone} to queue 'email'")
            return True
        return False
    except Exception as e:
        logger.error(f"Failed to check/send milestone notification: {str(e)}", exc_info=True)
        return False

@app.task(name='app.tasks.email_tasks.milestone_checker_task.check_and_notify_newsletter_milestone')
def check_and_notify_newsletter_milestone(total_subscribers: int) -> bool:
    """
    Celery task to check if a newsletter milestone was reached and send notification if so.

    Args:
        total_subscribers: The current total number of newsletter subscribers

    Returns:
        bool: True if a milestone was reached and notification sent, False otherwise
    """
    try:
        milestone = check_newsletter_signup_milestone(total_subscribers)
        if milestone:
            # Get admin email from environment variable
            admin_email = os.getenv("ADMIN_NOTIFY_EMAIL", "notify@openmates.org")

            # Dispatch the email task
            app.send_task(
                name='app.tasks.email_tasks.signup_milestone_email_task.send_newsletter_milestone_notification',
                kwargs={
                    "subscriber_count": total_subscribers,
                    "admin_email": admin_email,
                    "milestone_number": milestone
                },
                queue='email'
            )
            logger.info(f"Dispatched newsletter milestone notification task for milestone {milestone} to queue 'email'")
            return True
        return False
    except Exception as e:
        logger.error(f"Failed to check/send newsletter milestone notification: {str(e)}", exc_info=True)
        return False