# backend/core/api/app/tasks/email_tasks/ai_response_notification_email_task.py
"""
Celery task for sending AI response notification emails to users.

This module handles sending email notifications when an AI assistant completes a response
while the user is offline (no active WebSocket connections).

Architecture:
- The WebSocket handler (websockets.py) detects when a user is offline using
  ConnectionManager.is_user_active() with retry logic (3 attempts, 5 seconds apart)
- Only after confirming the user is truly offline, this task is queued
- This task simply sends the email - all eligibility checks are done before queuing
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


@app.task(name='app.tasks.email_tasks.ai_response_notification_email_task.send_ai_response_notification', bind=True)
def send_ai_response_notification(
    self,
    recipient_email: str,
    response_preview: str,
    chat_id: str,
    chat_title: Optional[str] = None,
    language: str = "en",
    darkmode: bool = False,
    user_id: Optional[str] = None,
    task_queued_timestamp: Optional[int] = None
) -> bool:
    """
    Celery task to send AI response notification email to user.
    
    This task is queued by the WebSocket handler AFTER it has verified the user
    is offline using ConnectionManager.is_user_active() with retry logic.
    
    Args:
        recipient_email: The email address of the user (decrypted)
        response_preview: A preview/excerpt of the AI response (plaintext, will be HTML escaped)
        chat_id: The chat ID where the response was delivered
        chat_title: Optional title of the chat
        language: User's preferred language code
        darkmode: User's dark mode preference
        user_id: User ID (for logging purposes)
        task_queued_timestamp: Unix timestamp when task was queued (for logging)
    
    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    logger.info(
        f"[EMAIL_NOTIFICATION] Sending AI response notification email "
        f"(recipient={recipient_email}, chat_id={chat_id}, user_id={user_id})"
    )
    try:
        result = asyncio.run(
            _async_send_ai_response_notification(
                recipient_email=recipient_email,
                response_preview=response_preview,
                chat_id=chat_id,
                chat_title=chat_title,
                language=language,
                darkmode=darkmode
            )
        )
        if result:
            logger.info(
                f"[EMAIL_NOTIFICATION] AI response notification email sent successfully "
                f"(recipient={recipient_email}, chat_id={chat_id})"
            )
        else:
            logger.error(
                f"[EMAIL_NOTIFICATION] AI response notification email failed "
                f"(recipient={recipient_email}, chat_id={chat_id}) - check logs above"
            )
        return result
    except Exception as e:
        logger.error(
            f"[EMAIL_NOTIFICATION] Failed to run AI response notification email task: {str(e)} "
            f"(recipient={recipient_email}, chat_id={chat_id})",
            exc_info=True
        )
        return False


async def _async_send_ai_response_notification(
    recipient_email: str,
    response_preview: str,
    chat_id: str,
    chat_title: Optional[str] = None,
    language: str = "en",
    darkmode: bool = False
) -> bool:
    """
    Async implementation for sending AI response notification email.
    
    NOTE: All offline checks are done BEFORE this task is queued (in websockets.py).
    This function simply sends the email - no additional eligibility checks needed.
    
    IMPORTANT: Uses try/finally to ensure SecretsManager's httpx client is
    properly closed before returning.
    """
    secrets_manager = SecretsManager()
    
    try:
        await secrets_manager.initialize()
        
        email_template_service = EmailTemplateService(secrets_manager=secrets_manager)
        
        # SECURITY: Sanitize inputs before passing to email template
        # Truncate preview to reasonable length and escape HTML
        max_preview_length = 500  # Characters
        if response_preview:
            truncated_preview = response_preview[:max_preview_length]
            if len(response_preview) > max_preview_length:
                truncated_preview += "..."
            sanitized_preview = escape(truncated_preview)
            # Convert newlines to <br/> tags for email display (after escaping)
            sanitized_preview = sanitized_preview.replace('\n', '<br/>')
        else:
            sanitized_preview = ""
        
        sanitized_title = escape(chat_title) if chat_title else None

        # Generate chat URL for the button
        base_url = os.getenv("FRONTEND_URL", "https://openmates.org")
        chat_url = f"{base_url}/chat/{chat_id}"

        # Prepare email context
        email_context = {
            "darkmode": darkmode,
            "response_preview": sanitized_preview,
            "chat_title": sanitized_title,
            "chat_url": chat_url,
        }
        
        logger.info(
            f"[EMAIL_NOTIFICATION] Attempting to send AI response notification email "
            f"to {recipient_email} for chat {chat_id}"
        )
        
        email_success = await email_template_service.send_email(
            template="ai-response-notification",
            recipient_email=recipient_email,
            context=email_context,
            lang=language
        )
        
        if not email_success:
            logger.error(
                f"[EMAIL_NOTIFICATION] Failed to send AI response notification email to {recipient_email} - "
                f"send_email() returned False"
            )
            return False
        
        logger.info(
            f"[EMAIL_NOTIFICATION] Successfully sent AI response notification email to {recipient_email}"
        )
        return True
        
    except Exception as e:
        logger.error(
            f"[EMAIL_NOTIFICATION] Error sending AI response notification email: {str(e)}",
            exc_info=True
        )
        return False
    finally:
        # CRITICAL: Close the httpx client before asyncio.run() closes the event loop
        await secrets_manager.aclose()
