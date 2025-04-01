import logging
import os
# Removed base64, io imports
from datetime import datetime
from urllib.parse import quote_plus
from typing import Dict, Any, Optional

# Assuming user-agents is installed
try:
    import user_agents
except ImportError:
    user_agents = None

# Removed StaticMap, CircleMarker, get_location_from_ip imports

from app.services.translations import TranslationService
# from app.utils.device_fingerprint import get_location_from_ip # No longer needed here
from app.utils.log_filters import SensitiveDataFilter
from .image_generation import generate_combined_map_preview # Import the new utility function

logger = logging.getLogger(__name__)
logger.addFilter(SensitiveDataFilter()) # Apply filter

async def prepare_new_device_login_context(
    user_agent_string: str,
    ip_address: str,
    account_email: str,
    language: str,
    darkmode: bool,
    translation_service: TranslationService,
    latitude: Optional[float], # Now required (can be None)
    longitude: Optional[float], # Now required (can be None)
    location_name: str, # Now required
    is_localhost: bool, # Now required
    user_id_for_log: str = "unknown" # Optional user ID for logging context
) -> Dict[str, Any]:
    """
    Prepares the context dictionary for the 'new-device-login' email template.
    Consolidates logic for device/OS parsing, map generation, and mailto link using provided location data.
    """
    log_prefix = f"User {user_id_for_log[:6]}... - " if user_id_for_log != "unknown" else ""
    logger.info(f"{log_prefix}Preparing new device login context with provided location data...")

    # --- Use Provided Location Data ---
    # Location lookup and localhost handling is now done before calling this helper
    final_latitude = latitude
    final_longitude = longitude
    final_location_name = location_name if location_name else "unknown" # Ensure we have a string

    # Determine if location is known (either localhost or valid coords provided)
    location_known = is_localhost or (final_latitude is not None and final_longitude is not None)
    logger.info(f"{log_prefix}Location known: {location_known} (is_localhost={is_localhost}, lat={final_latitude}, lon={final_longitude})")

    # --- Parse City/Country from final_location_name ---
    city = "Unknown"
    country = "Unknown"
    if final_location_name and final_location_name != "unknown" and final_location_name != "localhost":
        parts = final_location_name.split(',')
        if len(parts) >= 2:
            city = parts[0].strip()
            country = parts[1].strip()
        elif len(parts) == 1:
            part = parts[0].strip()
            # Basic check if it looks like a country code vs a city name
            if len(part) == 2 and part.isalpha() and part.isupper():
                 country = part
            else:
                 city = part # Assume city otherwise
    elif final_location_name == "localhost":
        city = "Localhost" # Use specific city/country for localhost if desired, or keep Unknown
        country = ""

    # --- Device & OS Parsing ---
    device_type_key = "email.unknown_device.text"
    os_name_key = "email.unknown_os.text"
    os_name_raw = "Unknown OS"

    if user_agents:
        try:
            ua = user_agents.parse(user_agent_string)
            os_name_raw = ua.os.family or os_name_raw

            if ua.is_pc: device_type_key = "email.computer.text"
            elif ua.is_tablet: device_type_key = "email.tablet.text"
            elif ua.is_mobile: device_type_key = "email.phone.text"
            # Add VR/VisionOS checks if needed based on library capabilities

            os_family = ua.os.family
            if os_family == "Mac OS X": os_name_key, os_name_raw = "macOS", "macOS"
            elif os_family == "Windows": os_name_key, os_name_raw = "Windows", "Windows"
            elif os_family == "Linux": os_name_key, os_name_raw = "Linux", "Linux"
            elif os_family == "Android": os_name_key, os_name_raw = "Android", "Android"
            elif os_family == "iOS": os_name_key, os_name_raw = "iOS", "iOS"
            elif os_family == "iPadOS": os_name_key, os_name_raw = "iPadOS", "iPadOS"
            # Add VisionOS check if needed
            else: os_name_key = "email.unknown_os.text"

            logger.info(f"{log_prefix}Parsed UA: OS={os_name_raw}, TypeKey={device_type_key}")

        except Exception as ua_exc:
            logger.warning(f"{log_prefix}Failed to parse User-Agent string '{user_agent_string}': {ua_exc}")
    else:
         logger.warning(f"{log_prefix}user-agents library not available. Using default device/OS keys.")

    device_type_translated = translation_service.get_nested_translation(device_type_key, language, {})
    if os_name_key == "email.unknown_os.text":
         os_name_translated = translation_service.get_nested_translation(os_name_key, language, {})
    else:
         os_name_translated = os_name_raw # Use the mapped raw name

    # --- Mailto Link Generation ---
    login_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    mailto_subject_template = translation_service.get_nested_translation("email.email_subject_someone_accessed_my_account.text", language, {})
    mailto_body_template = translation_service.get_nested_translation("email.email_body_someone_accessed_my_account.text", language, {})

    mailto_body_formatted = mailto_body_template.format(
        login_time=login_time,
        device_type=device_type_translated,
        operating_system=os_name_translated,
        city=city, # Use parsed city
        country=country, # Use parsed country
        account_email=account_email
    )

    mailto_subject_encoded = quote_plus(mailto_subject_template)
    mailto_body_encoded = quote_plus(mailto_body_formatted)
    support_email = os.getenv("SUPPORT_EMAIL", "support@openmates.org")
    logout_link = f"mailto:{support_email}?subject={mailto_subject_encoded}&body={mailto_body_encoded}"

    # --- Combined Map Preview Image Generation ---
    combined_map_preview_uri = None
    unknown_location_text = None
    map_alt_text = ""

    if location_known:
        # Generate alt text using the translation key, replacing <br>
        # Use final_location_name if city/country parsing failed but location is known (e.g., localhost)
        display_city = city if city != "Unknown" else final_location_name
        display_country = country if country != "Unknown" else ""
        map_alt_text = translation_service.get_nested_translation("email.area_around.text", language, {}).format(city=display_city, country=display_country).replace("<br>", " ").strip()
        
        # Ensure coordinates are valid floats before generating image
        if isinstance(final_latitude, (int, float)) and isinstance(final_longitude, (int, float)) and \
           -90 <= final_latitude <= 90 and -180 <= final_longitude <= 180:
            
            logger.info(f"{log_prefix}Generating combined map preview for known location: {final_location_name}")
            combined_map_preview_uri = generate_combined_map_preview(
                latitude=final_latitude,
                longitude=final_longitude,
                city=city, # Pass parsed city/country to image generator
                country=country,
                darkmode=darkmode,
                lang=language
            )
            if not combined_map_preview_uri:
                 logger.error(f"{log_prefix}Failed to generate combined map preview image.")
        else:
             logger.warning(f"{log_prefix}Coordinates are invalid or not numbers (lat={final_latitude}, lon={final_longitude}). Skipping map image generation.")
             location_known = False # Treat as unknown if coords invalid
             unknown_location_text = translation_service.get_nested_translation("email.from_unknown_location.text", language, {})

    else:
        logger.info(f"{log_prefix}Location is unknown. Getting 'unknown location' text.")
        unknown_location_text = translation_service.get_nested_translation("email.from_unknown_location.text", language, {})


    # --- Prepare Final Context ---
    context = {
        "device_type_translated": device_type_translated,
        "os_name_translated": os_name_translated,
        "location_name": final_location_name, # Pass the determined location name
        "logout_link": logout_link,
        "location_known": location_known, # Pass the flag
        "final_latitude": final_latitude, # Pass coordinates for link
        "final_longitude": final_longitude, # Pass coordinates for link
        "combined_map_preview_uri": combined_map_preview_uri, # Pass image URI (or None)
        "map_alt_text": map_alt_text, # Pass alt text (or empty string)
        "unknown_location_text": unknown_location_text, # Pass unknown text (or None)
        "darkmode": darkmode
    }

    logger.info(f"{log_prefix}Finished preparing new device login context. Location known: {location_known}")
    return context