# backend/core/api/app/tasks/email_tasks/community_share_email_task.py
"""
Celery task for sending community share notification emails to admin.

This module handles sending notifications when a user shares a chat with the community,
notifying the admin that a new chat has been suggested for community sharing.
"""

import logging
import asyncio
from typing import Optional

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
event_logger = logging.getLogger("app.events")
event_logger.addFilter(sensitive_filter)


@app.task(name='app.tasks.email_tasks.community_share_email_task.send_community_share_notification', bind=True)
def send_community_share_notification(
    self,
    admin_email: str,
    chat_title: str,
    chat_summary: Optional[str],
    chat_id: str,
    demo_chat_id: str,
    category: Optional[str] = None,
    icon: Optional[str] = None
) -> bool:
    """
    Celery task to send community share notification email to admin.
    
    Uses asyncio.run() which properly handles event loop creation and cleanup.
    
    IMPORTANT: No share_link parameter - community shares follow zero-knowledge architecture.
    The server never receives the user's chat encryption key. Admin accesses the demo
    through the admin interface, not via the original user's share link.
    
    Args:
        admin_email: The email address of the admin to notify
        chat_title: The title of the shared chat
        chat_summary: Optional summary/description of the chat
        chat_id: The original chat ID (for reference only)
        demo_chat_id: UUID of the pending demo_chat entry
        category: Optional category
        icon: Optional icon name
    
    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    logger.info(
        f"Starting community share notification email task for chat: '{chat_title[:50]}...' "
        f"(recipient={admin_email})"
    )
    try:
        # Use asyncio.run() which handles loop creation and cleanup properly
        result = asyncio.run(
            _async_send_community_share_notification(
                admin_email, chat_title, chat_summary, chat_id, demo_chat_id, category, icon
            )
        )
        if result:
            logger.info(
                f"Community share notification email task completed successfully for chat: '{chat_title[:50]}...' "
                f"(recipient={admin_email})"
            )
        else:
            logger.error(
                f"Community share notification email task failed for chat: '{chat_title[:50]}...' "
                f"(recipient={admin_email}) - check logs above for details"
            )
        return result
    except Exception as e:
        logger.error(
            f"Failed to run community share notification email task for chat '{chat_title[:50]}...': {str(e)} "
            f"(recipient={admin_email})", 
            exc_info=True
        )
        return False


async def _async_send_community_share_notification(
    admin_email: str,
    chat_title: str,
    chat_summary: Optional[str],
    chat_id: str,
    demo_chat_id: str,
    category: Optional[str] = None,
    icon: Optional[str] = None
) -> bool:
    """
    Async implementation for sending community share notification email.
    
    IMPORTANT: Uses try/finally to ensure SecretsManager's httpx client is
    properly closed before returning. This prevents "Event loop is closed" 
    errors when asyncio.run() closes the event loop in Celery tasks.
    
    ZERO-KNOWLEDGE ARCHITECTURE: No share_link parameter. The server never receives
    the user's chat encryption key. Admin accesses the pending demo through the
    admin interface at /settings/server/community-suggestions
    """
    # Create services outside try block so they're available in finally
    secrets_manager = SecretsManager()
    
    try:
        await secrets_manager.initialize()
        email_template_service = EmailTemplateService(secrets_manager=secrets_manager)
        
        # SECURITY: Sanitize inputs before passing to email template
        # HTML escape title and summary to prevent XSS
        from html import escape
        
        sanitized_title = escape(chat_title) if chat_title else "Untitled Chat"
        sanitized_summary = escape(chat_summary) if chat_summary else ""
        
        # Convert newlines to <br/> tags for email display (after escaping)
        # This is safe because we've already escaped all HTML tags
        sanitized_summary = sanitized_summary.replace('\n', '<br/>')

        # Generate demo chat approval URL for admin
        # This deep-links to the community suggestions settings page where admin can approve/reject
        import os
        base_url = os.getenv("FRONTEND_URL", "https://openmates.org")
        demo_chat_url = f"{base_url}/settings/server/community-suggestions?demo_chat_id={demo_chat_id}"
        
        # Add metadata as URL parameters for preview in email
        import urllib.parse
        if sanitized_title:
            demo_chat_url += f"&title={urllib.parse.quote(sanitized_title[:200])}"
        if sanitized_summary:
            demo_chat_url += f"&summary={urllib.parse.quote(sanitized_summary[:200])}"
        if category:
            demo_chat_url += f"&category={urllib.parse.quote(category)}"
        if icon:
            demo_chat_url += f"&icon={urllib.parse.quote(icon)}"

        # Prepare email context with sanitized data
        email_context = {
            "darkmode": True,  # Default to dark mode for admin emails
            "chat_title": sanitized_title,
            "chat_summary": sanitized_summary,
            "demo_chat_url": demo_chat_url
        }
        logger.info("Prepared email context for community share notification")
        
        # Send community share notification email
        logger.info(
            f"Attempting to send community share notification email to {admin_email} with template 'community_share_notification' "
            f"(title: '{chat_title[:50]}...')"
        )
        email_success = await email_template_service.send_email(
            template="community_share_notification",
            recipient_email=admin_email,
            context=email_context,
            lang="en"  # Default to English for admin emails
        )
        
        if not email_success:
            logger.error(
                f"Failed to send community share notification email to {admin_email} - "
                f"send_email() returned False. Check email service configuration and logs."
            )
            return False
        
        logger.info(
            f"Successfully sent community share notification email to {admin_email} "
            f"(subject: 'New chat suggested for community: {chat_title[:50]}...')"
        )
        event_logger.info(f"Community share notification email sent to {admin_email}")
        return True
        
    except Exception as e:
        logger.error(f"Error sending community share notification email: {str(e)}", exc_info=True)
        return False
    finally:
        # CRITICAL: Close the httpx client before asyncio.run() closes the event loop
        # This prevents "Event loop is closed" errors during httpx cleanup
        await secrets_manager.aclose()

