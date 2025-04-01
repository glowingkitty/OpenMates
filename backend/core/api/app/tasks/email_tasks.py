import logging
import random
import os
import base64
import io # Added for image saving
from typing import Dict, Any, Optional
import asyncio
# httpx no longer needed here for map image
from datetime import datetime
from urllib.parse import quote_plus
from staticmap import StaticMap, CircleMarker # Added staticmap imports

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
    location: Optional[str], # e.g., "Berlin, Germany" or "unknown"
    ip_address: str, # For logging/context
    latitude: Optional[float] = None, # Added
    longitude: Optional[float] = None, # Added
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
    ip_address: str, # Added ip_address here as it was missing but passed from wrapper
    latitude: Optional[float] = None, # Added
    longitude: Optional[float] = None, # Added
    language: str = "en",
    darkmode: bool = False
) -> bool:
    """
    Async implementation for sending the new device login email.
    """
    try:
        email_template_service = EmailTemplateService()
        directus_service = DirectusService() # Need to fetch user email
        translation_service = email_template_service.translation_service # Use existing instance

        # Fetch user email
        success, user_data, msg = await directus_service.get_user_profile(user_id, fields=['email'])
        if not success or not user_data or not user_data.get('email'):
            logger.error(f"Failed to fetch email for user {user_id} for new device notification: {msg}")
            return False
        
        account_email = user_data['email']
        logger.info(f"Fetched email for user {user_id[:6]}...: {account_email[:2]}***")

        # --- Device & OS Parsing ---
        device_type_key = "email.unknown_device.text" # Default key
        os_name_key = "email.unknown_os.text" # Default key
        os_name_raw = "Unknown OS" # Default raw name

        if user_agents:
            try:
                ua = user_agents.parse(user_agent_string)
                os_name_raw = ua.os.family or os_name_raw # Store raw OS name for mailto link

                # Determine Device Type Key
                # Add more specific checks if needed (e.g., ua.device.family for 'Oculus')
                if ua.is_pc:
                    device_type_key = "email.computer.text"
                elif ua.is_tablet: # Check tablet before mobile
                    device_type_key = "email.tablet.text"
                elif ua.is_mobile:
                    device_type_key = "email.phone.text"
                # Add VR headset check if possible/needed based on ua library capabilities
                # elif "VR" in ua.device.family or "Oculus" in ua.device.family: 
                #    device_type_key = "email.vr_headset.text"

                # Determine OS Name Key / Raw Name
                os_family = ua.os.family
                if os_family == "Mac OS X":
                    os_name_key = "macOS"
                    os_name_raw = "macOS"
                elif os_family == "Windows":
                    os_name_key = "Windows"
                    os_name_raw = "Windows"
                elif os_family == "Linux":
                    os_name_key = "Linux"
                    os_name_raw = "Linux"
                elif os_family == "Android":
                    os_name_key = "Android"
                    os_name_raw = "Android"
                elif os_family == "iOS":
                    os_name_key = "iOS"
                    os_name_raw = "iOS"
                elif os_family == "iPadOS": # Specific check for iPadOS
                     os_name_key = "iPadOS"
                     os_name_raw = "iPadOS"
                # Add VisionOS check if possible/needed
                # elif os_family == "VisionOS":
                #     os_name_key = "VisionOS"
                #     os_name_raw = "VisionOS"
                else: # Use translated unknown
                    os_name_key = "email.unknown_os.text"
                    
                logger.info(f"Parsed UA for {user_id[:6]}...: OS={os_name_raw}, TypeKey={device_type_key}")

            except Exception as ua_exc:
                logger.warning(f"Failed to parse User-Agent string '{user_agent_string}' for user {user_id[:6]}...: {ua_exc}")
        else:
             logger.warning("user-agents library not available. Using default device/OS keys.")

        # Get translated device type and OS name (or key if translation missing)
        device_type_translated = translation_service.get_nested_translation(device_type_key, language, {})
        # For OS, use the raw name if it's a known one, otherwise translate "unknown"
        if os_name_key == "email.unknown_os.text":
             os_name_translated = translation_service.get_nested_translation(os_name_key, language, {})
        else:
             os_name_translated = os_name_raw # Use the mapped raw name like "macOS", "Windows"

        # --- Location Parsing ---
        city = "Unknown"
        country = "Unknown"
        if location and location != "unknown":
            parts = location.split(',')
            if len(parts) >= 2:
                city = parts[0].strip()
                country = parts[1].strip()
            elif len(parts) == 1:
                # Assume it's either city or country, difficult to distinguish reliably
                # For simplicity, assign to city, or could try further checks
                city = parts[0].strip() 
                country = "Unknown" # Or leave as Unknown

        # --- Mailto Link Generation ---
        login_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC") # Current time as login time
        
        # Fetch mailto subject and body templates
        mailto_subject_template = translation_service.get_nested_translation("email.email_subject_someone_accessed_my_account.text", language, {})
        mailto_body_template = translation_service.get_nested_translation("email.email_body_someone_accessed_my_account.text", language, {})

        # Replace placeholders in the body template
        # Use the translated device type and OS name for the mailto body
        mailto_body_formatted = mailto_body_template.format(
            login_time=login_time,
            device_type=device_type_translated, 
            operating_system=os_name_translated, 
            city=city,
            country=country,
            account_email=account_email
        )

        # URL-encode subject and body
        mailto_subject_encoded = quote_plus(mailto_subject_template)
        mailto_body_encoded = quote_plus(mailto_body_formatted)

        # Construct the mailto link
        # Assuming the recipient is a support email address from config/env
        support_email = os.getenv("SUPPORT_EMAIL", "support@openmates.org") # Updated fallback
        logout_link = f"mailto:{support_email}?subject={mailto_subject_encoded}&body={mailto_body_encoded}"

        # --- Static Map Image Data URI Generation using staticmap library ---
        map_image_data_uri = None
        if latitude is not None and longitude is not None:
            # Basic validation for coordinates
            if -90 <= latitude <= 90 and -180 <= longitude <= 180:
                try:
                    logger.info(f"Generating static map image for user {user_id[:6]}... at ({latitude}, {longitude})")
                    # Create StaticMap object (width, height)
                    m = StaticMap(600, 250)
                    # Add marker (coordinates, color, size)
                    marker = CircleMarker((longitude, latitude), '#0036FF', 12) # Blue marker
                    m.add_marker(marker)
                    # Render the map (center coordinates, zoom level)
                    # Note: Rendering might block the async event loop if it's CPU-intensive or performs sync I/O (like tile fetching)
                    # Consider running this in a thread pool executor if it causes performance issues
                    image = m.render(zoom=11, center=(longitude, latitude))
                    
                    # Save image to bytes buffer
                    buffer = io.BytesIO()
                    image.save(buffer, format='PNG')
                    image_bytes = buffer.getvalue()
                    
                    # Encode as base64 data URI
                    encoded_string = base64.b64encode(image_bytes).decode('utf-8')
                    map_image_data_uri = f"data:image/png;base64,{encoded_string}"
                    logger.info(f"Successfully generated and encoded map image for user {user_id[:6]}...")
                    
                except Exception as exc:
                     # Catch potential errors during map generation/rendering (e.g., tile fetching)
                     logger.error(f"Error generating map image for user {user_id[:6]}...: {exc}", exc_info=True)
            else:
                logger.warning(f"Invalid coordinates provided for user {user_id[:6]}...: lat={latitude}, lon={longitude}")
        else:
            logger.info(f"No coordinates provided for user {user_id[:6]}..., skipping map image generation.")

        # --- Prepare Context for MJML Template ---
        context = {
            "device_type_translated": device_type_translated, # Pass translated device type
            "os_name_translated": os_name_translated,       # Pass translated/mapped OS name
            "city": city,
            "country": country,
            "logout_link": logout_link, # Pass the generated mailto link
            "map_image_data_uri": map_image_data_uri, # Pass the generated map data URI (or None)
            "darkmode": darkmode
        }

        logger.info(f"Sending new device login email to {account_email[:2]}*** - lang: {language}")
        
        success = await email_template_service.send_email(
            template="new-device-login", # Use the new template name
            recipient_email=account_email,
            context=context,
            lang=language
            # Subject is derived automatically by EmailTemplateService based on template name + lang
        )
        
        if not success:
            logger.error(f"Failed to send new device login email for user {user_id[:6]}...")
            return False
            
        logger.info(f"New device login email sent successfully for user {user_id[:6]}...")
        return True
        
    except Exception as e:
        logger.error(f"Error in _async_send_new_device_email task for user {user_id[:6]}...: {str(e)}", exc_info=True)
        return False