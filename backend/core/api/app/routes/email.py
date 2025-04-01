from fastapi import APIRouter, Query, HTTPException, Request
from fastapi.responses import HTMLResponse
import logging
import os
import base64
import io # Added
# httpx no longer needed here for map image
from datetime import datetime
from urllib.parse import quote_plus
import user_agents
from typing import Optional
from staticmap import StaticMap, CircleMarker # Added

from app.services.email_template import EmailTemplateService
from app.utils.device_fingerprint import get_location_from_ip # Import IP lookup

router = APIRouter(prefix="/v1/email", tags=["email"])
logger = logging.getLogger(__name__)
email_template_service = EmailTemplateService()
translation_service = email_template_service.translation_service # Get instance

# Remove the generic template endpoint and replace with specific template handlers

# Helper function to process email templates with consistent logic
async def _process_email_template(
    request: Request,
    template_name: str,
    lang: str = "en",
    **kwargs
):
    """Internal helper to process email templates with consistent logic"""
    try:
        # Start with empty context
        context = {}
        
        # Add specific parameters to context
        for key, value in kwargs.items():
            if value is not None:
                context[key] = value
        
        # Handle darkmode parameter specifically
        raw_darkmode = request.query_params.get('darkmode', 'false').lower()
        parsed_darkmode = raw_darkmode == 'true'
        context["darkmode"] = parsed_darkmode
        
        # Add any other query parameters that might be needed
        # This part might need adjustment if query params conflict with kwargs
        for key, value in request.query_params.items():
             # Only add if not already set by kwargs or core params
            if key not in ['darkmode', 'lang'] and key not in kwargs:
                context[key] = value
        
        # Log the final context for debugging
        logger.debug(f"Template context: {context}")
        
        # Render the email template
        html_content = email_template_service.render_template(
            template_name=template_name,
            context=context,
            lang=lang
        )
        
        return HTMLResponse(content=html_content)
        
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Email template '{template_name}' not found")
    except Exception as e:
        logger.error(f"Error rendering email template: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error rendering email template: {str(e)}")

@router.get("/confirm-email", response_class=HTMLResponse)
async def preview_confirm_email(
    request: Request,
    lang: str = Query("en", description="Language code for translations"),
    darkmode: bool = Query(False, description="Enable dark mode for the email"),
    code: str = Query("123456", description="Verification code"),
    username: str = Query("User", description="Username to display in the email")
):
    """
    Preview the email confirmation template
    """
    return await _process_email_template(
        request=request,
        template_name="confirm-email",
        lang=lang,
        code=code,
        username=username
    )

@router.get("/purchase-confirmation", response_class=HTMLResponse)
async def preview_purchase_confirmation(
    request: Request,
    lang: str = Query("en", description="Language code for translations"),
    darkmode: bool = Query(False, description="Enable dark mode for the email"),
    username: str = Query("User", description="Username to display in the email"),
    credits: int = Query(21000, description="Number of credits purchased"),
    amount: float = Query(20.0, description="Amount paid"),
    currency: str = Query("EUR", description="Currency of payment"),
    invoice_number: str = Query("INV-001", description="Invoice number")
):
    """
    Preview the purchase confirmation email template
    """
    return await _process_email_template(
        request=request,
        template_name="purchase-confirmation",
        lang=lang,
        username=username,
        credits=credits,
        amount=amount,
        currency=currency,
        invoice_number=invoice_number
    )

@router.get("/new-device-login", response_class=HTMLResponse)
async def preview_new_device_login(
    request: Request,
    lang: str = Query("en", description="Language code for translations"),
    darkmode: bool = Query(False, description="Enable dark mode for the email"),
    # Use a sample User-Agent string for parsing device/OS for preview
    user_agent_string: str = Query("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36", description="User-Agent string to parse"),
    ip_address: str = Query("172.64.154.211", description="IP address to estimate location from (e.g., 8.8.8.8)"),
    account_email: str = Query("preview@example.com", description="Account email address for mailto link"),
):
    """
    Preview the new device login email template. 
    Location is derived from ip_address if provided.
    """

    # --- Determine Location & Coordinates ---
    location_data = {"location_string": "unknown", "latitude": None, "longitude": None}
    if ip_address:
        try:
            # get_location_from_ip now returns a dict
            location_data = get_location_from_ip(ip_address)
        except Exception as loc_exc:
            logger.warning(f"Preview: Failed to get location for IP {ip_address}: {loc_exc}")
            # Keep default location_data

    location_str = location_data.get("location_string", "unknown")
    latitude = location_data.get("latitude")
    longitude = location_data.get("longitude")

    # --- Parse City/Country from location_string ---
    city = "Unknown"
    country = "Unknown"
    if location_str and location_str != "unknown":
        parts = location_str.split(',')
        if len(parts) >= 2:
            city = parts[0].strip()
            country = parts[1].strip()
        elif len(parts) == 1:
            # If only one part, assume it's city or country code
            # Check if it looks like a country code (e.g., 2 letters)
            part = parts[0].strip()
            if len(part) == 2 and part.isalpha():
                 country = part
            else:
                 city = part

    # --- Device & OS Parsing (using provided User-Agent) ---
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
            # Add VR check if needed

            os_family = ua.os.family
            if os_family == "Mac OS X": os_name_key, os_name_raw = "macOS", "macOS"
            elif os_family == "Windows": os_name_key, os_name_raw = "Windows", "Windows"
            elif os_family == "Linux": os_name_key, os_name_raw = "Linux", "Linux"
            elif os_family == "Android": os_name_key, os_name_raw = "Android", "Android"
            elif os_family == "iOS": os_name_key, os_name_raw = "iOS", "iOS"
            elif os_family == "iPadOS": os_name_key, os_name_raw = "iPadOS", "iPadOS"
            # Add VisionOS check if needed
            else: os_name_key = "email.unknown_os.text"
        except Exception as ua_exc:
            logger.warning(f"Preview: Failed to parse User-Agent string '{user_agent_string}': {ua_exc}")
    else:
         logger.warning("Preview: user-agents library not available.")

    device_type_translated = translation_service.get_nested_translation(device_type_key, lang, {})
    if os_name_key == "email.unknown_os.text":
         os_name_translated = translation_service.get_nested_translation(os_name_key, lang, {})
    else:
         os_name_translated = os_name_raw

    # --- Mailto Link Generation ---
    login_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC") 
    mailto_subject_template = translation_service.get_nested_translation("email.email_subject_someone_accessed_my_account.text", lang, {})
    mailto_body_template = translation_service.get_nested_translation("email.email_body_someone_accessed_my_account.text", lang, {})
    mailto_body_formatted = mailto_body_template.format(
        login_time=login_time, device_type=device_type_translated, 
        operating_system=os_name_translated, city=city, country=country, 
        account_email=account_email
    )
    mailto_subject_encoded = quote_plus(mailto_subject_template)
    mailto_body_encoded = quote_plus(mailto_body_formatted)
    support_email = os.getenv("SUPPORT_EMAIL", "support@openmates.org") # Updated fallback
    logout_link = f"mailto:{support_email}?subject={mailto_subject_encoded}&body={mailto_body_encoded}"

    # --- Generate Map Image Data URI using staticmap library ---
    map_image_data_uri = None
    if latitude is not None and longitude is not None:
        if -90 <= latitude <= 90 and -180 <= longitude <= 180:
            try:
                logger.info(f"Preview: Generating static map image for ({latitude}, {longitude})")
                m = StaticMap(600, 250)
                marker = CircleMarker((longitude, latitude), '#0036FF', 12)
                m.add_marker(marker)
                # Render synchronously in the route handler
                image = m.render(zoom=11, center=(longitude, latitude))
                
                buffer = io.BytesIO()
                image.save(buffer, format='PNG')
                image_bytes = buffer.getvalue()
                
                encoded_string = base64.b64encode(image_bytes).decode('utf-8')
                map_image_data_uri = f"data:image/png;base64,{encoded_string}"
                logger.info(f"Preview: Successfully generated and encoded map image.")
                
            except Exception as exc:
                 logger.error(f"Preview: Error generating map image: {exc}", exc_info=True)
        else:
            logger.warning(f"Preview: Invalid coordinates provided: lat={latitude}, lon={longitude}")
    else:
        logger.info(f"Preview: No coordinates provided, skipping map image generation.")

    # --- Call Helper ---
    return await _process_email_template(
        request=request,
        template_name="new-device-login",
        lang=lang,
        # Pass all required context variables for the template
        device_type_translated=device_type_translated,
        os_name_translated=os_name_translated,
        city=city,
        country=country,
        logout_link=logout_link,
        map_image_data_uri=map_image_data_uri # Pass data URI
        # darkmode is handled by _process_email_template
    )