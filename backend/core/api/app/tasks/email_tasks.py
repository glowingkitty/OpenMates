import logging
import random
import os # Re-added os import
import base64
import io # Added for image saving
from typing import Dict, Any, Optional
import asyncio
# httpx no longer needed here for map image
from datetime import datetime, timezone # Added timezone
from urllib.parse import quote_plus # Re-added quote_plus import
from staticmap import StaticMap, CircleMarker # Added staticmap imports

# Assuming user-agents is installed (add to requirements.txt later)
try:
    import user_agents
except ImportError:
    user_agents = None # Handle gracefully if not installed

from celery import shared_task
from app.services.email_template import EmailTemplateService
from app.services.cache import CacheService # Needed for verification email task
from app.utils.secrets_manager import SecretsManager # Import SecretsManager
from app.utils.log_filters import SensitiveDataFilter  # Import the filter
from app.services.directus import DirectusService # Needed to get user details like email
# Import the new mailto link helper and the existing context helper
from app.utils.email_context_helpers import prepare_new_device_login_context, generate_report_access_mailto_link

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
        secrets_manager = SecretsManager() # Instantiate SecretsManager
        await secrets_manager.initialize() # Initialize SecretsManager
        email_template_service = EmailTemplateService(secrets_manager=secrets_manager) # Pass SecretsManager
        
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
    email_address: str, # Changed from user_id
    user_agent_string: str,
    # location: Optional[str], # Removed old location string
    ip_address: str, # For logging/context
    latitude: Optional[float], # Keep explicit coords
    longitude: Optional[float], # Keep explicit coords
    location_name: str, # Add location name string
    is_localhost: bool, # Add localhost flag
    language: str = "en",
    darkmode: bool = False
) -> bool:
    """
    Celery task wrapper to send a 'new device login' notification email.
    """
    # Updated log message to use email address
    logger.info(f"Starting new device login email task for email: {email_address[:2]}***") 
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # Pass new location arguments and email_address to the async function
        result = loop.run_until_complete(_async_send_new_device_email(
            email_address=email_address, # Pass email_address instead of user_id
            user_agent_string=user_agent_string,
            ip_address=ip_address,
            latitude=latitude,
            longitude=longitude, 
            location_name=location_name, # Pass location name
            is_localhost=is_localhost, # Pass localhost flag
            language=language,
            darkmode=darkmode
        ))
        # Updated log message
        logger.info(f"New device login email task completed for email: {email_address[:2]}***")
        return result
    except Exception as e:
        # Updated log message
        logger.error(f"Failed to run new device login email task for email {email_address[:2]}...: {str(e)}", exc_info=True)
        return False
    finally:
        loop.close()

async def _async_send_new_device_email(
    email_address: str, # Changed from user_id
    user_agent_string: str,
    ip_address: str,
    latitude: Optional[float], # Keep explicit coords
    longitude: Optional[float], # Keep explicit coords
    location_name: str, # Add location name string
    is_localhost: bool, # Add localhost flag
    language: str = "en",
    darkmode: bool = False
) -> bool:
    """
    Async implementation for sending the new device login email.
    """
    try:
        secrets_manager = SecretsManager() # Instantiate SecretsManager
        await secrets_manager.initialize() # Initialize SecretsManager
        email_template_service = EmailTemplateService(secrets_manager=secrets_manager) # Pass SecretsManager

        # --- Prepare Context using Helper Function ---
        try:
            # Use email_address directly instead of account_email
            # Remove user_id_for_log as it's no longer available here
            context = await prepare_new_device_login_context(
                user_agent_string=user_agent_string,
                ip_address=ip_address, # Still useful for context/debugging
                account_email=email_address, # Use passed email_address
                language=language,
                darkmode=darkmode,
                translation_service=email_template_service.translation_service, # Pass the service instance
                latitude=latitude, # Pass coord
                longitude=longitude, # Pass coord
                location_name=location_name, # Pass location name
                is_localhost=is_localhost
            )
        except Exception as context_exc:
             # Updated log message
             logger.error(f"Error preparing email context for email {email_address[:2]}...: {context_exc}", exc_info=True)
             return False # Fail the task if context preparation fails

        # --- Send Email ---
        # Updated log message
        logger.info(f"Sending new device login email to {email_address[:2]}*** - lang: {language}")

        success = await email_template_service.send_email(
            template="new-device-login",
            recipient_email=email_address,
            context=context,
            lang=language
        )

        if not success:
            # Updated log message
            logger.error(f"Failed to send new device login email for email {email_address[:2]}...")
            return False

        # Updated log message
        logger.info(f"New device login email sent successfully for email {email_address[:2]}...")
        return True

    except Exception as e:
        # Updated log message
        logger.error(f"Error in _async_send_new_device_email task for email {email_address[:2]}...: {str(e)}", exc_info=True)
        return False


# --- Backup Code Used Email Task ---

@app.task(name='app.tasks.email_tasks.send_backup_code_used_email', bind=True)
def send_backup_code_used_email(
    self,
    email_address: str,
    anonymized_code: str,
    language: str = "en",
    darkmode: bool = False
) -> bool:
    """
    Celery task wrapper to send a 'backup code used' notification email.
    """
    logger.info(f"Starting backup code used email task for email: {email_address[:2]}***")
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        result = loop.run_until_complete(_async_send_backup_code_used_email(
            email_address=email_address,
            anonymized_code=anonymized_code,
            language=language,
            darkmode=darkmode
        ))
        logger.info(f"Backup code used email task completed for email: {email_address[:2]}***")
        return result
    except Exception as e:
        logger.error(f"Failed to run backup code used email task for email {email_address[:2]}...: {str(e)}", exc_info=True)
        return False
    finally:
        loop.close()

async def _async_send_backup_code_used_email(
    email_address: str,
    anonymized_code: str,
    language: str = "en",
    darkmode: bool = False
) -> bool:
    """
    Async implementation for sending the backup code used email.
    """
    try:
        secrets_manager = SecretsManager() # Instantiate SecretsManager
        await secrets_manager.initialize() # Initialize SecretsManager
        email_template_service = EmailTemplateService(secrets_manager=secrets_manager) # Pass SecretsManager
        translation_service = email_template_service.translation_service # Get translation service instance

        # --- Prepare Mailto Link using Helper ---
        login_time_str = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S %Z') # e.g., 2025-04-02 13:10:00 UTC
        
        report_details = {
            "login_time": login_time_str,
            "backup_code": anonymized_code # Pass the anonymized code to the helper
            # account_email is passed directly to the helper
        }

        logout_link = await generate_report_access_mailto_link(
            translation_service=translation_service,
            language=language,
            account_email=email_address,
            report_type='backup_code', # Specify the report type
            details=report_details
        )
        
        if not logout_link:
             logger.error(f"Failed to generate mailto link for backup code used email for {email_address[:2]}...")
             # Decide if task should fail or continue without link
             # For now, let's allow it to continue but log the error prominently
             logout_link = "" # Set to empty string to avoid template errors

        # --- Prepare Template Context ---
        # Context now only needs the code, darkmode, and the generated mailto link
        context = {
            "code": anonymized_code, # The anonymized code itself for display in the email
            "darkmode": darkmode,
            "logout_link": logout_link # The generated mailto link
        }
        logger.debug(f"Prepared template context for backup code used email: {context}")

        # --- Send Email ---
        logger.info(f"Sending backup code used email to {email_address[:2]}*** - lang: {language}")

        success = await email_template_service.send_email(
            template="backup-code-was-used", # Use the correct template name
            recipient_email=email_address,
            context=context,
            lang=language
        )

        if not success:
            logger.error(f"Failed to send backup code used email for email {email_address[:2]}...")
            return False

        logger.info(f"Backup code used email sent successfully for email {email_address[:2]}...")
        return True

    except Exception as e:
        logger.error(f"Error in _async_send_backup_code_used_email task for email {email_address[:2]}...: {str(e)}", exc_info=True)
        return False