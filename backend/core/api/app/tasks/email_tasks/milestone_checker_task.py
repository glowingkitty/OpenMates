# backend/core/api/app/tasks/email_tasks/milestone_checker_task.py
import logging
import os
from typing import Optional

from backend.core.api.app.tasks.celery_config import app

logger = logging.getLogger(__name__)

# Define the milestones we want to track
SIGNUP_MILESTONES = [1, 2, 3, 4, 5, 10, 20, 50, 100, 500, 1000]

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
            admin_email = os.getenv("ADMIN_EMAIL", "notify@openmates.org")
            
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