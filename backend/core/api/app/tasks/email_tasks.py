import logging
import random
import os
from typing import Dict, Any
import asyncio

from celery import shared_task
from app.services.email_template import EmailTemplateService
from app.services.cache import CacheService
from app.utils.log_filters import SensitiveDataFilter  # Import the filter

# Import the Celery app directly 
from app.tasks.celery_config import app

logger = logging.getLogger(__name__)
# Add filter to email tasks logger
sensitive_filter = SensitiveDataFilter()
logger.addFilter(sensitive_filter)

event_logger = logging.getLogger("app.events")
# Also ensure event_logger has the filter
event_logger.addFilter(sensitive_filter)

@app.task(name='app.tasks.email_tasks.generate_and_send_verification_email', bind=True)
def generate_and_send_verification_email(
    self,
    email: str, 
    invite_code: str,
    language: str = "en",
    darkmode: bool = False
) -> bool:
    """
    Generate a verification code, store it in cache, and send email
    """
    logger.info(f"Starting email verification task")
    try:
        # Create a new event loop for async operations
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Run the async function and return its result
        result = loop.run_until_complete(_async_generate_and_send_verification_email(
            email, invite_code, language, darkmode
        ))
        logger.info(f"Email verification task completed")
        return result
    except Exception as e:
        logger.error(f"Failed to run email verification task: {str(e)}", exc_info=True)
        return False
    finally:
        # Clean up
        loop.close()

async def _async_generate_and_send_verification_email(
    email: str, 
    invite_code: str,
    language: str = "en",
    darkmode: bool = False
) -> bool:
    """
    Async implementation of the email verification task
    """
    try:
        # Create a standalone cache service for this task
        cache_service = CacheService()
        email_template_service = EmailTemplateService()
        
        # Generate a 6-digit code
        verification_code = ''.join(random.choices('0123456789', k=6))
        logger.info(f"Generated verification code")
        
        # Store the code in cache with 20 minute expiration
        cache_key = f"email_verification:{email}"
        cache_result = await cache_service.set(cache_key, verification_code, ttl=1200)  # 1200 seconds = 20 minutes
        if not cache_result:
            logger.error(f"Failed to store verification code in cache")
            return False
            
        logger.info(f"Stored verification code in cache")
        
        # Save invite code in cache for use during registration completion
        invite_cache_key = f"invite_code:{email}"
        invite_cache_result = await cache_service.set(invite_cache_key, invite_code, ttl=1200)
        if not invite_cache_result:
            logger.warning(f"Failed to store invite code in cache, but continuing")
        
        # Send the email using the email template service
        context = {
            "code": verification_code,
            "darkmode": darkmode
        }
        
        logger.info(f"Sending verification email - language: {language}")
        success = await email_template_service.send_email(
            template="confirm-email",
            recipient_email=email,
            context=context,
            lang=language
        )
        
        if not success:
            logger.error(f"Failed to send verification email")
            return False
            
        logger.info(f"Verification email sent successfully")
        return True
        
    except Exception as e:
        logger.error(f"Error in generate_and_send_verification_email task: {str(e)}", exc_info=True)
        return False
