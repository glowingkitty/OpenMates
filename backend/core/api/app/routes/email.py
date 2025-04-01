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
from app.utils.email_context_helpers import prepare_new_device_login_context # Import the new helper

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
    try:
        # --- Get Location Data for Preview ---
        # Call the updated get_location_from_ip (handles localhost internally)
        location_data = get_location_from_ip(ip_address) 
        latitude = location_data.get("latitude")
        longitude = location_data.get("longitude")
        location_name = location_data.get("location_string", "unknown")
        is_localhost = location_name == "localhost" # Determine if it was the localhost case
        logger.info(f"Preview location data: lat={latitude}, lon={longitude}, name={location_name}, is_localhost={is_localhost}")

        # --- Prepare Context using Helper Function ---
        # Pass the determined location data explicitly
        context = await prepare_new_device_login_context(
            user_agent_string=user_agent_string,
            ip_address=ip_address, # Still pass IP for potential logging inside helper
            account_email=account_email,
            language=lang,
            darkmode=darkmode, # Pass darkmode from query param
            translation_service=translation_service, # Use global service instance
            latitude=latitude,         # Pass explicit latitude
            longitude=longitude,       # Pass explicit longitude
            location_name=location_name, # Pass location name string
            is_localhost=is_localhost, # Pass localhost flag
            user_id_for_log="preview"  # Indicate this is for preview logging
        )

        # --- Call Rendering Helper ---
        # Pass the generated context dictionary using **kwargs
        return await _process_email_template(
            request=request,
            template_name="new-device-login",
            lang=lang,
            **context # Unpack the generated context here
            # darkmode is already included in the context dict by the helper
        )
    except Exception as e:
        # Catch potential errors during context preparation or rendering
        logger.error(f"Preview Error: Failed to prepare/render new-device-login: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error generating preview: {str(e)}")