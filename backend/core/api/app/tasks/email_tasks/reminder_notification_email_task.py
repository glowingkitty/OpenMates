# backend/core/api/app/tasks/email_tasks/reminder_notification_email_task.py
"""
Celery task for sending reminder notification emails to users.

This module handles sending email notifications when a reminder fires,
allowing users to be notified even when they're not actively using the app.
"""

import logging
import asyncio
import os
from typing import Optional
from html import escape

# Import the Celery app
from backend.core.api.app.tasks.celery_config import app

# Import necessary services and utilities
from backend.core.api.app.services.email_template import EmailTemplateService
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.utils.log_filters import SensitiveDataFilter

# Setup loggers
logger = logging.getLogger(__name__)
sensitive_filter = SensitiveDataFilter()
logger.addFilter(sensitive_filter)


@app.task(name='app.tasks.email_tasks.reminder_notification_email_task.send_reminder_notification', bind=True)
def send_reminder_notification(
    self,
    recipient_email: str,
    reminder_prompt: str,
    trigger_time: str,
    chat_id: str,
    chat_title: Optional[str] = None,
    is_new_chat: bool = True,
    language: str = "en",
    darkmode: bool = False
) -> bool:
    """
    Celery task to send reminder notification email to user.
    
    Uses asyncio.run() which properly handles event loop creation and cleanup.
    
    Args:
        recipient_email: The email address of the user
        reminder_prompt: The reminder message/prompt (plaintext, will be HTML escaped)
        trigger_time: Human-readable trigger time string
        chat_id: The chat ID where the reminder was delivered
        chat_title: Optional title of the chat
        is_new_chat: Whether a new chat was created for this reminder
        language: User's preferred language code
        darkmode: User's dark mode preference
    
    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    logger.info(
        f"Starting reminder notification email task (recipient={recipient_email}, chat_id={chat_id})"
    )
    try:
        result = asyncio.run(
            _async_send_reminder_notification(
                recipient_email=recipient_email,
                reminder_prompt=reminder_prompt,
                trigger_time=trigger_time,
                chat_id=chat_id,
                chat_title=chat_title,
                is_new_chat=is_new_chat,
                language=language,
                darkmode=darkmode
            )
        )
        if result:
            logger.info(
                f"Reminder notification email task completed successfully (recipient={recipient_email})"
            )
        else:
            logger.error(
                f"Reminder notification email task failed (recipient={recipient_email}) - check logs above"
            )
        return result
    except Exception as e:
        logger.error(
            f"Failed to run reminder notification email task: {str(e)} "
            f"(recipient={recipient_email})", 
            exc_info=True
        )
        return False


async def _async_send_reminder_notification(
    recipient_email: str,
    reminder_prompt: str,
    trigger_time: str,
    chat_id: str,
    chat_title: Optional[str] = None,
    is_new_chat: bool = True,
    language: str = "en",
    darkmode: bool = False
) -> bool:
    """
    Async implementation for sending reminder notification email.
    
    IMPORTANT: Uses try/finally to ensure SecretsManager's httpx client is
    properly closed before returning.
    """
    secrets_manager = SecretsManager()
    
    try:
        await secrets_manager.initialize()
        email_template_service = EmailTemplateService(secrets_manager=secrets_manager)
        
        # SECURITY: Sanitize inputs before passing to email template
        sanitized_prompt = escape(reminder_prompt) if reminder_prompt else ""
        sanitized_title = escape(chat_title) if chat_title else None
        
        # Convert newlines to <br/> tags for email display (after escaping)
        sanitized_prompt = sanitized_prompt.replace('\n', '<br/>')

        # Generate chat URL for the button
        # CRITICAL: The frontend uses hash-based routing for chat navigation: /#chat-id={id}
        base_url = os.getenv("FRONTEND_URL", "https://openmates.org")
        chat_url = f"{base_url}/#chat-id={chat_id}"

        # Create a short excerpt of the reminder prompt for the email subject line
        # Strip HTML tags and truncate for subject readability
        plain_prompt = reminder_prompt.replace('<br/>', ' ').strip()
        reminder_excerpt = plain_prompt[:60] + ("..." if len(plain_prompt) > 60 else "")

        # Prepare email context
        email_context = {
            "darkmode": darkmode,
            "reminder_prompt": sanitized_prompt,
            "reminder_excerpt": reminder_excerpt,
            "trigger_time": trigger_time,
            "chat_title": sanitized_title,
            "chat_url": chat_url,
            "is_new_chat": is_new_chat,
        }
        
        logger.info(f"Attempting to send reminder notification email to {recipient_email}")
        
        email_success = await email_template_service.send_email(
            template="reminder-notification",
            recipient_email=recipient_email,
            context=email_context,
            lang=language
        )
        
        if not email_success:
            logger.error(
                f"Failed to send reminder notification email to {recipient_email} - "
                f"send_email() returned False"
            )
            return False
        
        logger.info(f"Successfully sent reminder notification email to {recipient_email}")
        return True
        
    except Exception as e:
        logger.error(f"Error sending reminder notification email: {str(e)}", exc_info=True)
        return False
    finally:
        # CRITICAL: Close the httpx client before asyncio.run() closes the event loop
        await secrets_manager.aclose()
