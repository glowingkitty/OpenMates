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

# Removed StaticMap, CircleMarker imports

from app.services.translations import TranslationService
from app.utils.device_fingerprint import get_location_from_ip
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
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    user_id_for_log: str = "unknown" # Optional user ID for logging context
) -> Dict[str, Any]:
    """
    Prepares the context dictionary for the 'new-device-login' email template.
    Consolidates logic for location, device/OS parsing, map generation, and mailto link.
    """
    log_prefix = f"User {user_id_for_log[:6]}... - " if user_id_for_log != "unknown" else ""
    logger.info(f"{log_prefix}Preparing new device login context...")

    # --- Determine Location & Coordinates ---
    location_data = {"location_string": "unknown", "latitude": None, "longitude": None}
    # Use provided coords if available, otherwise lookup by IP
    if latitude is not None and longitude is not None:
         # Basic validation
        if -90 <= latitude <= 90 and -180 <= longitude <= 180:
            location_data["latitude"] = latitude
            location_data["longitude"] = longitude
            # Attempt to get location string anyway for city/country, but prioritize provided coords for map
            try:
                ip_loc_data = get_location_from_ip(ip_address)
                location_data["location_string"] = ip_loc_data.get("location_string", "unknown")
            except Exception as loc_exc:
                logger.warning(f"{log_prefix}Failed to get location string for IP {ip_address} even with coords provided: {loc_exc}")
        else:
             logger.warning(f"{log_prefix}Invalid coordinates provided: lat={latitude}, lon={longitude}. Attempting IP lookup.")
             # Fallback to IP lookup if provided coords are invalid
             try:
                 location_data = get_location_from_ip(ip_address)
             except Exception as loc_exc:
                 logger.warning(f"{log_prefix}Failed to get location for IP {ip_address} after invalid coords: {loc_exc}")

    elif ip_address: # If no coords provided, lookup by IP
        try:
            location_data = get_location_from_ip(ip_address)
        except Exception as loc_exc:
            logger.warning(f"{log_prefix}Failed to get location for IP {ip_address}: {loc_exc}")

    location_str = location_data.get("location_string", "unknown")
    final_latitude = location_data.get("latitude")
    final_longitude = location_data.get("longitude")

    # --- Parse City/Country from location_string ---
    city = "Unknown"
    country = "Unknown"
    if location_str and location_str != "unknown":
        parts = location_str.split(',')
        if len(parts) >= 2:
            city = parts[0].strip()
            country = parts[1].strip()
        elif len(parts) == 1:
            part = parts[0].strip()
            if len(part) == 2 and part.isalpha() and part.isupper(): # Check for likely country code
                 country = part
            else:
                 city = part # Assume city otherwise

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
        city=city,
        country=country,
        account_email=account_email
    )

    mailto_subject_encoded = quote_plus(mailto_subject_template)
    mailto_body_encoded = quote_plus(mailto_body_formatted)
    support_email = os.getenv("SUPPORT_EMAIL", "support@openmates.org")
    logout_link = f"mailto:{support_email}?subject={mailto_subject_encoded}&body={mailto_body_encoded}"

    # --- Combined Map Preview Image Generation ---
    combined_map_preview_uri = None
    # Generate alt text using the translation key, replacing <br>
    map_alt_text = translation_service.get_nested_translation("email.area_around.text", language, {}).format(city=city, country=country).replace("<br>", " ")

    if final_latitude is not None and final_longitude is not None:
        # Check coords are still valid
        if -90 <= final_latitude <= 90 and -180 <= final_longitude <= 180:
            # Call the image generation utility function
            combined_map_preview_uri = generate_combined_map_preview(
                latitude=final_latitude,
                longitude=final_longitude,
                city=city,
                country=country,
                darkmode=darkmode,
                lang=language
            )
            if not combined_map_preview_uri:
                 logger.error(f"{log_prefix}Failed to generate combined map preview image.")
        else:
             logger.warning(f"{log_prefix}Final coordinates invalid after lookup/validation: lat={final_latitude}, lon={final_longitude}. Skipping image generation.")
    else:
        logger.info(f"{log_prefix}No valid coordinates available, skipping combined map preview image generation.")


    # --- Prepare Final Context ---
    context = {
        "device_type_translated": device_type_translated,
        "os_name_translated": os_name_translated,
        "city": city, # Keep for mailto link and potentially other uses
        "country": country, # Keep for mailto link and potentially other uses
        "logout_link": logout_link,
        "combined_map_preview_uri": combined_map_preview_uri, # Use the new combined image URI
        "map_alt_text": map_alt_text, # Add alt text
        "darkmode": darkmode
        # Removed "map_image_data_uri"
    }

    logger.info(f"{log_prefix}Finished preparing new device login context.")
    return context