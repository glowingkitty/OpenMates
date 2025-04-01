import logging
import random
import os
from typing import Dict, Any, Optional
import asyncio

# Assuming user-agents is installed (add to requirements.txt later)
try:
    import user_agents
except ImportError:
    user_agents = None # Handle gracefully if not installed

from celery import shared_task
from app.services.email_template import EmailTemplateService
from app.services.cache import CacheService # Needed for verification email task
from app.utils.log_filters import SensitiveDataFilter  # Import the filter
from app.services.directus import DirectusService # Needed to get user details like email

# Import the Celery app directly 
from app.tasks.celery_config import app
# Import settings if needed for URLs
# from app.core.config import settings 

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
        logger.error(f"Error in _async_generate_and_send_verification_email task: {str(e)}", exc_info=True)
        return False


# --- New Device Login Email Task ---

@app.task(name='app.tasks.email_tasks.send_new_device_email', bind=True)
def send_new_device_email(
    self,
    user_id: str,
    user_agent_string: str,
    location: Optional[str], # e.g., "Berlin, DE" or "unknown"
    ip_address: str, # For logging/context
    language: str = "en",
    darkmode: bool = False
) -> bool:
    """
    Celery task wrapper to send a 'new device login' notification email.
    """
    logger.info(f"Starting new device login email task for user_id: {user_id[:6]}...")
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        result = loop.run_until_complete(_async_send_new_device_email(
            user_id, user_agent_string, location, ip_address, language, darkmode
        ))
        logger.info(f"New device login email task completed for user_id: {user_id[:6]}...")
        return result
    except Exception as e:
        logger.error(f"Failed to run new device login email task for user_id {user_id[:6]}...: {str(e)}", exc_info=True)
        return False
    finally:
        loop.close()

async def _async_send_new_device_email(
    user_id: str,
    user_agent_string: str,
    location: Optional[str],
    ip_address: str, # Included for potential future use or richer context
    language: str = "en",
    darkmode: bool = False
) -> bool:
    """
    Async implementation for sending the new device login email.
    """
    try:
        email_template_service = EmailTemplateService()
        directus_service = DirectusService() # Need to fetch user email

        # Fetch user email
        success, user_data, msg = await directus_service.get_user_profile(user_id, fields=['email'])
        if not success or not user_data or not user_data.get('email'):
            logger.error(f"Failed to fetch email for user {user_id} for new device notification: {msg}")
            return False
        
        recipient_email = user_data['email']
        logger.info(f"Fetched email for user {user_id[:6]}...: {recipient_email[:2]}***")

        # Parse User-Agent
        device_type = "Device" # Default
        os_name = "Unknown OS" # Default
        if user_agents:
            try:
                ua = user_agents.parse(user_agent_string)
                os_name = ua.os.family or os_name
                if ua.is_mobile or ua.is_tablet:
                    device_type = "Mobile/Tablet"
                elif ua.is_pc:
                    device_type = "Computer"
                logger.info(f"Parsed UA for {user_id[:6]}...: OS={os_name}, Type={device_type}")
            except Exception as ua_exc:
                logger.warning(f"Failed to parse User-Agent string '{user_agent_string}' for user {user_id[:6]}...: {ua_exc}")
        else:
             logger.warning("user-agents library not available. Using default device/OS.")


        # Prepare context for the email template
        # Image URLs removed - embedding handled by EmailTemplateService based on MJML src
        # TODO: Get base URL from config/settings
        base_url = os.getenv("FRONTEND_URL", "http://localhost:5173") 
        security_link_url_placeholder = f"{base_url}/settings/security" 

        context = {
            "device_type": device_type,
            "os_name": os_name,
            "location": location or "Unknown Location",
            "security_link_url": security_link_url_placeholder,
            "darkmode": darkmode # Pass darkmode preference
        }
        
        logger.info(f"Sending new device login email to {recipient_email[:2]}*** - lang: {language}")
        
        success = await email_template_service.send_email(
            template="new-device-login", # Use the new template name
            recipient_email=recipient_email,
            context=context,
            lang=language
        )
        
        if not success:
            logger.error(f"Failed to send new device login email for user {user_id[:6]}...")
            return False
            
        logger.info(f"New device login email sent successfully for user {user_id[:6]}...")
        return True
        
    except Exception as e:
        logger.error(f"Error in _async_send_new_device_email task for user {user_id[:6]}...: {str(e)}", exc_info=True)
        return False