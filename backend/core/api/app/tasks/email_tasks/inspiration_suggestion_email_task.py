# backend/core/api/app/tasks/email_tasks/inspiration_suggestion_email_task.py
"""
Celery task for notifying admin when a user suggests a YouTube video
as a default Daily Inspiration.

Follows the same pattern as community_share_email_task.py.
"""

import logging
import asyncio
import os
import urllib.parse
from html import escape
from typing import Optional

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.services.email_template import EmailTemplateService
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.utils.log_filters import SensitiveDataFilter

logger = logging.getLogger(__name__)
sensitive_filter = SensitiveDataFilter()
logger.addFilter(sensitive_filter)


@app.task(
    name="app.tasks.email_tasks.inspiration_suggestion_email_task.send_inspiration_suggestion_notification",
    bind=True,
)
def send_inspiration_suggestion_notification(
    self,
    admin_email: str,
    video_id: str,
    video_title: str,
    video_channel_name: str,
    inspiration_id: str,
) -> bool:
    """
    Celery task to notify admin that a new video has been suggested as a Daily Inspiration.

    Args:
        admin_email: Admin email address to notify
        video_id: YouTube video ID
        video_title: Video title
        video_channel_name: YouTube channel name
        inspiration_id: UUID of the created suggested_daily_inspirations record

    Returns:
        bool: True if email sent successfully, False otherwise
    """
    logger.info(
        f"[InspirationEmail] Starting notification task for inspiration_id={inspiration_id} "
        f"(video_id={video_id}, recipient={admin_email})"
    )
    try:
        result = asyncio.run(
            _async_send_inspiration_suggestion_notification(
                admin_email=admin_email,
                video_id=video_id,
                video_title=video_title,
                video_channel_name=video_channel_name,
                inspiration_id=inspiration_id,
            )
        )
        if result:
            logger.info(
                f"[InspirationEmail] Notification task completed for inspiration_id={inspiration_id}"
            )
        else:
            logger.error(
                f"[InspirationEmail] Notification task failed for inspiration_id={inspiration_id}"
            )
        return result
    except Exception as e:
        logger.error(
            f"[InspirationEmail] Failed to run notification task for inspiration_id={inspiration_id}: {e}",
            exc_info=True,
        )
        return False


async def _async_send_inspiration_suggestion_notification(
    admin_email: str,
    video_id: str,
    video_title: str,
    video_channel_name: str,
    inspiration_id: str,
) -> bool:
    """
    Async implementation. Sends admin notification email for a new inspiration suggestion.

    Uses try/finally to ensure SecretsManager's httpx client is properly closed
    before asyncio.run() closes the event loop (same pattern as community_share_email_task).
    """
    secrets_manager = SecretsManager()

    try:
        await secrets_manager.initialize()
        email_service = EmailTemplateService(secrets_manager=secrets_manager)

        # Sanitize inputs to prevent XSS
        safe_title = escape(video_title) if video_title else "Unknown"
        safe_channel = escape(video_channel_name) if video_channel_name else "Unknown"
        youtube_url = f"https://www.youtube.com/watch?v={video_id}"

        # Deep-link to the admin panel for this suggestion
        base_url = os.getenv("FRONTEND_URL", "https://openmates.org")
        admin_url = f"{base_url}/settings/server/default-inspirations?inspiration_id={urllib.parse.quote(inspiration_id)}"

        # Build the email context to reuse the community_share_notification template
        # which has the same structure: darkmode, title, summary, action URL
        email_context = {
            "darkmode": True,
            "chat_title": f"YouTube: {safe_title}",
            "chat_summary": (
                f"Channel: {safe_channel}<br/>"
                f"Video: <a href='{youtube_url}'>{youtube_url}</a>"
            ),
            "demo_chat_url": admin_url,
        }

        success = await email_service.send_email(
            template="community_share_notification",
            recipient_email=admin_email,
            context=email_context,
            lang="en",
        )

        if not success:
            logger.error(
                f"[InspirationEmail] send_email() returned False for inspiration_id={inspiration_id}"
            )
            return False

        logger.info(
            f"[InspirationEmail] Sent notification to {admin_email} for inspiration_id={inspiration_id}"
        )
        return True

    except Exception as e:
        logger.error(
            f"[InspirationEmail] Error sending notification for inspiration_id={inspiration_id}: {e}",
            exc_info=True,
        )
        return False
    finally:
        # CRITICAL: close the httpx client before asyncio.run() closes the event loop
        await secrets_manager.aclose()
