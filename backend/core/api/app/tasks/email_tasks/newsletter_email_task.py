"""
Celery task for sending newsletter-related emails.

This module handles:
- Newsletter confirmation request emails
- Newsletter confirmed success emails
"""

import logging
import asyncio
import os
from typing import Dict, Any

# Import the Celery app
from backend.core.api.app.tasks.celery_config import app

# Import necessary services and utilities
from backend.core.api.app.services.email_template import EmailTemplateService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.utils.newsletter_utils import hash_email
from backend.core.api.app.utils.log_filters import SensitiveDataFilter

# Setup loggers
logger = logging.getLogger(__name__)
sensitive_filter = SensitiveDataFilter()
logger.addFilter(sensitive_filter)
event_logger = logging.getLogger("app.events")
event_logger.addFilter(sensitive_filter)


@app.task(name='app.tasks.email_tasks.newsletter_email_task.send_newsletter_confirmation_email', bind=True)
def send_newsletter_confirmation_email(
    self,
    email: str,
    confirmation_token: str,
    language: str = "en",
    darkmode: bool = False
) -> bool:
    """
    Send newsletter confirmation email with confirmation and unsubscribe links.
    
    Uses asyncio.run() which properly handles event loop creation and cleanup.
    """
    logger.info(f"Starting newsletter confirmation email task for {email[:2]}***")
    try:
        result = asyncio.run(
            _async_send_newsletter_confirmation_email(
                email, confirmation_token, language, darkmode
            )
        )
        logger.info(f"Newsletter confirmation email task completed for {email[:2]}***")
        return result
    except Exception as e:
        logger.error(f"Failed to run newsletter confirmation email task for {email[:2]}***: {str(e)}", exc_info=True)
        return False


async def _async_send_newsletter_confirmation_email(
    email: str,
    confirmation_token: str,
    language: str = "en",
    darkmode: bool = False
) -> bool:
    """
    Async implementation of the newsletter confirmation email task
    """
    try:
        # Create standalone services for this task
        secrets_manager = SecretsManager()
        await secrets_manager.initialize()
        email_template_service = EmailTemplateService(secrets_manager=secrets_manager)
        
        # Get webapp URL from shared config loader
        from backend.core.api.app.services.email.config_loader import load_shared_urls
        shared_urls = load_shared_urls()
        
        # Determine environment (development or production)
        is_dev = os.getenv("ENVIRONMENT", "production").lower() in ("development", "dev", "test") or \
                 "localhost" in os.getenv("WEBAPP_URL", "").lower()
        env_name = "development" if is_dev else "production"
        
        # Get webapp URL from shared config
        base_url = shared_urls.get('urls', {}).get('base', {}).get('webapp', {}).get(env_name)
        
        # Fallback to environment variable or default
        if not base_url:
            base_url = os.getenv("WEBAPP_URL", "https://openmates.org" if not is_dev else "http://localhost:5173")
            
        if not base_url.startswith("http"):
            base_url = f"https://{base_url}"
        
        # Build confirmation URL using settings deep link format (like refund links)
        # Format: {base_url}/#settings/newsletter/confirm/{token}
        confirm_url = f"{base_url}/#settings/newsletter/confirm/{confirmation_token}"
        
        # Build block-email URL instead of newsletter unsubscribe URL
        # The "Never message me again" link should block ALL emails, not just unsubscribe from newsletter
        # Format: {base_url}/#settings/email/block/{encoded_email}
        from urllib.parse import quote
        encoded_email = quote(email.lower().strip())
        block_email_url = f"{base_url}/#settings/email/block/{encoded_email}"
        
        # Prepare email context
        context = {
            "confirm_url": confirm_url,
            "unsubscribe_url": block_email_url,  # Use block-email URL instead of newsletter unsubscribe
            "darkmode": darkmode  # Use darkmode setting from user preference
        }
        
        logger.info(f"Sending newsletter confirmation email to {email[:2]}*** - language: {language}")
        success = await email_template_service.send_email(
            template="newsletter-confirmation-request",
            recipient_email=email,
            context=context,
            lang=language
        )
        
        if success:
            logger.info(f"Successfully sent newsletter confirmation email to {email[:2]}***")
            event_logger.info(f"Newsletter confirmation email sent to {email[:2]}***")
        else:
            logger.error(f"Failed to send newsletter confirmation email to {email[:2]}***")
        
        return success
        
    except Exception as e:
        logger.error(f"Error sending newsletter confirmation email to {email[:2]}***: {str(e)}", exc_info=True)
        return False


@app.task(name='app.tasks.email_tasks.newsletter_email_task.send_newsletter_confirmed_email', bind=True)
def send_newsletter_confirmed_email(
    self,
    email: str,
    language: str = "en",
    darkmode: bool = False
) -> bool:
    """
    Send newsletter confirmed success email.
    
    Uses asyncio.run() which properly handles event loop creation and cleanup.
    """
    logger.info(f"Starting newsletter confirmed email task for {email[:2]}***")
    try:
        result = asyncio.run(
            _async_send_newsletter_confirmed_email(
                email, language, darkmode
            )
        )
        logger.info(f"Newsletter confirmed email task completed for {email[:2]}***")
        return result
    except Exception as e:
        logger.error(f"Failed to run newsletter confirmed email task for {email[:2]}***: {str(e)}", exc_info=True)
        return False


async def _async_send_newsletter_confirmed_email(
    email: str,
    language: str = "en",
    darkmode: bool = False
) -> bool:
    """
    Async implementation of the newsletter confirmed email task
    
    This email is sent after a user confirms their newsletter subscription.
    It includes the persistent unsubscribe token that allows users to unsubscribe
    even weeks or months after subscribing.
    """
    try:
        # Create standalone services for this task
        secrets_manager = SecretsManager()
        await secrets_manager.initialize()
        email_template_service = EmailTemplateService(secrets_manager=secrets_manager)
        directus_service = DirectusService()
        
        # Look up the subscriber to get their persistent unsubscribe token
        hashed_email = hash_email(email.lower().strip())
        collection_name = "newsletter_subscribers"
        url = f"{directus_service.base_url}/items/{collection_name}"
        params = {"filter[hashed_email][_eq]": hashed_email}
        
        response = await directus_service._make_api_request("GET", url, params=params)
        
        unsubscribe_url = None
        if response.status_code == 200:
            response_data = response.json()
            items = response_data.get("data", [])
            
            if items:
                # Get the plaintext unsubscribe token (stored in cleartext for direct lookup)
                unsubscribe_token = items[0].get("unsubscribe_token")
                if unsubscribe_token:
                    # Build unsubscribe URL with the plaintext token using settings deep link format
                    # Format: {base_url}/#settings/newsletter/unsubscribe/{token}
                    
                    # Load shared URLs configuration to get webapp URL
                    from backend.core.api.app.services.email.config_loader import load_shared_urls
                    shared_urls = load_shared_urls()

                    # Determine environment (development or production)
                    is_dev = os.getenv("ENVIRONMENT", "production").lower() in ("development", "dev", "test") or \
                             "localhost" in os.getenv("WEBAPP_URL", "").lower()
                    env_name = "development" if is_dev else "production"

                    # Get webapp URL from shared config
                    base_url = shared_urls.get('urls', {}).get('base', {}).get('webapp', {}).get(env_name)

                    # Fallback to environment variable or default
                    if not base_url:
                        base_url = os.getenv("WEBAPP_URL", "https://openmates.org" if not is_dev else "http://localhost:5173")

                    if not base_url.startswith("http"):
                        base_url = f"https://{base_url}"
                        
                    unsubscribe_url = f"{base_url}/#settings/newsletter/unsubscribe/{unsubscribe_token}"
                    logger.debug(f"Generated unsubscribe URL for newsletter confirmed email")
                else:
                    logger.warning(f"No unsubscribe_token found for subscriber: {hashed_email[:16]}...")
        
        # Get social media links (from environment or defaults)
        instagram_url = "https://instagram.com/openmates_official"
        mastodon_url = "https://mastodon.social/@openmates"
        
        # Prepare email context
        context = {
            "instagram_url": instagram_url,
            "mastodon_url": mastodon_url,
            "darkmode": darkmode  # Use darkmode setting from user preference
        }
        
        # Add unsubscribe URL if we successfully retrieved and decrypted the token
        if unsubscribe_url:
            context["unsubscribe_url"] = unsubscribe_url
        else:
            logger.warning(f"Newsletter confirmed email will be sent without unsubscribe link for {email[:2]}***")
        
        logger.info(f"Sending newsletter confirmed email to {email[:2]}*** - language: {language}")
        success = await email_template_service.send_email(
            template="newsletter-confirmed",
            recipient_email=email,
            context=context,
            lang=language
        )
        
        if success:
            logger.info(f"Successfully sent newsletter confirmed email to {email[:2]}***")
            event_logger.info(f"Newsletter confirmed email sent to {email[:2]}***")
        else:
            logger.error(f"Failed to send newsletter confirmed email to {email[:2]}***")
        
        return success
        
    except Exception as e:
        logger.error(f"Error sending newsletter confirmed email to {email[:2]}***: {str(e)}", exc_info=True)
        return False
