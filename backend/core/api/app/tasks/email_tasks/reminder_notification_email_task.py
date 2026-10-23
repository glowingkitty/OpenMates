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
from urllib.parse import quote, urlsplit

from backend.core.api.app.services.reminder_preview_renderer import reminder_datetime_label

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
    darkmode: bool = False,
    notification_context: Optional[dict] = None,
    target_embed_id: Optional[str] = None,
    preview_url: Optional[str] = None,
    reminder_id: Optional[str] = None,
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
                darkmode=darkmode,
                notification_context=notification_context,
                target_embed_id=target_embed_id,
                preview_url=preview_url,
                reminder_id=reminder_id,
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
            "Failed to run reminder notification email task (%s)", type(e).__name__
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
    darkmode: bool = False,
    notification_context: Optional[dict] = None,
    target_embed_id: Optional[str] = None,
    preview_url: Optional[str] = None,
    reminder_id: Optional[str] = None,
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
        
        email_context = build_reminder_email_context(
            reminder_prompt=reminder_prompt, trigger_time=trigger_time,
            chat_id=chat_id, chat_title=chat_title, is_new_chat=is_new_chat,
            language=language, darkmode=darkmode,
            notification_context=notification_context, target_embed_id=target_embed_id,
            preview_url=preview_url,
        )

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
        
        if email_context.get("preview_url") and reminder_id:
            await _refresh_preview_expiry_after_delivery(reminder_id)
        logger.info(f"Successfully sent reminder notification email to {recipient_email}")
        return True
        
    except Exception as e:
        logger.error("Error sending reminder notification email (%s)", type(e).__name__)
        return False
    finally:
        # CRITICAL: Close the httpx client before asyncio.run() closes the event loop
        await secrets_manager.aclose()


async def _refresh_preview_expiry_after_delivery(reminder_id: str) -> None:
    """Renew only a mailed capability; renewal failure cannot undo accepted mail."""
    from time import time
    from backend.core.api.app.services.directus import DirectusService
    from backend.core.api.app.services.reminder_notification_context import PREVIEW_RETENTION_SECONDS

    directus = None
    try:
        directus = DirectusService()
        if not await directus.reminder.update_reminder(reminder_id, {
            "notification_preview_expires_at": int(time()) + PREVIEW_RETENTION_SECONDS,
        }):
            logger.warning("Reminder preview expiry renewal failed")
    except Exception as error:
        logger.warning("Reminder preview expiry renewal failed (%s)", type(error).__name__)
    finally:
        if directus is not None:
            try:
                await directus.close()
            except Exception as error:
                logger.warning("Reminder preview renewal cleanup failed (%s)", type(error).__name__)


def build_reminder_email_context(
    *, reminder_prompt: str, trigger_time: str, chat_id: str,
    chat_title: Optional[str] = None, is_new_chat: bool = True,
    language: str = "en", darkmode: bool = False,
    notification_context: Optional[dict] = None,
    target_embed_id: Optional[str] = None, preview_url: Optional[str] = None,
) -> dict:
    """Prepare escaped text and one canonical destination for image and button.

    Legacy jobs retain their saved prompt. Dispatch redacts by passing no prompt,
    title, context or image; the resulting subject and body contain generic copy.
    """
    from backend.shared.python_utils.frontend_url import get_frontend_base_url

    def text(value: object, limit: int) -> str:
        return value[:limit] if isinstance(value, str) else ""

    def html(value: object, limit: int) -> str:
        return escape(text(value, limit)).replace("\n", "<br/>")

    context = notification_context if isinstance(notification_context, dict) else {}
    kind = context.get("kind") if context.get("kind") in {"chat", "event", "appointment", "travel_connection", "travel_stay", "home_listing", "embed"} else "chat"
    title = text(context.get("title"), 200) or text(chat_title, 200)
    prompt = text(reminder_prompt, 4000)
    excerpt = " ".join((title or prompt).split())[:160]
    # The existing subject formatter owns the localized prefix. An empty excerpt
    # uses the localized header so explicit redaction has a meaningful subject.
    if not excerpt:
        from backend.core.api.app.services.translations import TranslationService
        excerpt = TranslationService().get_nested_translation("email.reminder_notification.header", language, {})
    base_url = get_frontend_base_url().rstrip("/")
    chat_url = f"{base_url}/#chat-id={quote(text(chat_id, 128), safe='')}" if chat_id else ""
    if target_embed_id:
        fragment = f"embed-id={quote(text(target_embed_id, 128), safe='')}"
        chat_url = f"{chat_url}&{fragment}" if chat_url else f"{base_url}/#{fragment}"
    # Preview URLs are generated by first-party dispatch. Refuse active/non-HTTPS
    # schemes at this final HTML boundary; never embed private data or CID URLs.
    try:
        parsed_preview = urlsplit(preview_url) if isinstance(preview_url, str) else None
    except ValueError:
        parsed_preview = None
    isolated_loopback_preview = bool(
        parsed_preview and parsed_preview.scheme == "http"
        and parsed_preview.hostname in {"localhost", "127.0.0.1", "api"}
        and os.environ.get("CI") == "true"
        and os.environ.get("OPENMATES_CI_ISOLATED") == "1"
        and os.environ.get("OPENMATES_CI_MAIL_CAPTURE") == "1"
    )
    safe_preview = preview_url if parsed_preview and (parsed_preview.scheme == "https" or isolated_loopback_preview) and parsed_preview.hostname and not parsed_preview.username and not parsed_preview.password and context and title and chat_url else None
    facts = context.get("facts") if isinstance(context.get("facts"), list) else []
    description = text(context.get("description"), 2000)
    summary = text(context.get("summary"), 500)
    return {
        "darkmode": darkmode, "is_new_chat": is_new_chat,
        "notification_icon_url": f"{base_url}/images/email/reminder-notification.png",
        "reminder_prompt": html(prompt, 4000), "reminder_excerpt": excerpt,
        "trigger_time": html(trigger_time, 200), "chat_title": html(title, 200),
        "target_title": html(title, 200), "target_kind": kind,
        "chat_url": escape(chat_url), "preview_url": escape(safe_preview) if safe_preview else None,
        "description": html(description or summary, 2000),
        "event_time": html(reminder_datetime_label(context, language), 300),
        "location": html(context.get("location"), 1000),
        "facts": [{"label": html(fact.get("label"), 80), "value": html(fact.get("value"), 512)} for fact in facts[:8] if isinstance(fact, dict) and fact.get("value")],
        "show_prompt": bool(prompt and prompt.strip() != description.strip()),
        "has_rich_context": bool(context and title),
        "heading_key": ("header_" + kind if kind in {"chat", "event", "appointment"} else "header") if context and title else "header_task" if is_new_chat and prompt else "header",
        "button_key": "open_" + kind + "_button" if kind in {"chat", "event", "appointment"} else "open_item_button",
    }
