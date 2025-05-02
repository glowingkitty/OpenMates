from fastapi import APIRouter, Query, HTTPException, Request
from fastapi.responses import HTMLResponse
import logging
# httpx no longer needed here for map image
from datetime import datetime, timezone

from app.services.email_template import EmailTemplateService
from app.services.translations import TranslationService # Import TranslationService
from app.utils.device_fingerprint import generate_device_fingerprint, DeviceFingerprint # Import new fingerprint utils
from app.utils.email_context_helpers import prepare_new_device_login_context, generate_report_access_mailto_link

router = APIRouter(
    prefix="/v1/email",
    tags=["email"] # Removed admin access key dependency
)
logger = logging.getLogger(__name__)

# Remove the generic template endpoint and replace with specific template handlers

# Helper function to process email templates with consistent logic
async def _process_email_template(
    request: Request,
    template_name: str,
    lang: str = "en",
    **kwargs
) -> HTMLResponse: # Add return type hint
    """Internal helper to process email templates with consistent logic"""
    # Access services from request.app.state
    email_template_service: EmailTemplateService = request.app.state.email_template_service
    
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
        
        # Render the email template using the service from app.state
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
        # --- Generate Fingerprint and Get Location Data for Preview ---
        # Note: generate_device_fingerprint extracts IP from request headers primarily.
        # The ip_address query param is less reliable but kept for potential logging/context.
        # We'll use the fingerprint object for location data.
        fingerprint: DeviceFingerprint = generate_device_fingerprint(request)
        latitude = fingerprint.latitude
        longitude = fingerprint.longitude
        # Construct location name similar to how it's done in auth_2fa_verify
        location_name = f"{fingerprint.city}, {fingerprint.country_code}" if fingerprint.city and fingerprint.country_code else fingerprint.country_code or "unknown"
        is_localhost = fingerprint.country_code == "Local" and fingerprint.city == "Local Network"
        logger.info(f"Preview fingerprint location data: lat={latitude}, lon={longitude}, name={location_name}, is_localhost={is_localhost}")

        # --- Prepare Context using Helper Function ---
        # Pass the determined location data explicitly
        context = await prepare_new_device_login_context(
            user_agent_string=user_agent_string,
            ip_address=ip_address, # Still pass IP for potential logging inside helper
            account_email=account_email,
            language=lang,
            darkmode=darkmode, # Pass darkmode from query param
            translation_service=request.app.state.email_template_service.translation_service, # Use service from app.state
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


@router.get("/backup-code-used", response_class=HTMLResponse)
async def preview_backup_code_used(
    request: Request,
    lang: str = Query("en", description="Language code for translations"),
    darkmode: bool = Query(False, description="Enable dark mode for the email"),
    code: str = Query("ABCD-0123-****", description="Anonymized backup code used"),
    account_email: str = Query("preview@example.com", description="Account email address for mailto link") # Added account_email query param
):
    """
    Preview the backup code used email template.
    Generates the mailto link dynamically for the preview.
    """
    # Access services from request.app.state for consistency, even though mailto link needs its own
    # email_template_service: EmailTemplateService = request.app.state.email_template_service
    translation_service: TranslationService = request.app.state.email_template_service.translation_service

    try:
        # NOTE: Mailto link generation might still need its own translation instance
        # if it relies on specific context not available globally.
        # For preview, using the global one should be fine.
        local_translation_service = translation_service # Use the one from app.state for preview

        # Prepare details for the mailto link helper
        login_time_str = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S %Z')
        report_details = {
            "login_time": login_time_str,
            "backup_code": code # Use the code from query param
        }

        # Generate the mailto link using the helper
        logout_link = await generate_report_access_mailto_link(
            translation_service=local_translation_service,
            language=lang,
            account_email=account_email, # Use email from query param
            report_type='backup_code',
            details=report_details
        )

        if not logout_link:
             logger.error("Failed to generate mailto link for backup code used")
             raise HTTPException(status_code=500, detail="Failed to generate mailto link")

        # Call the main rendering helper, accessing services via request
        return await _process_email_template(
            request=request, # Pass request to access app.state inside helper
            template_name="backup-code-was-used",
            lang=lang,
            code=code, # Pass the code for display in the template
            logout_link=logout_link # Pass the generated mailto link
            # darkmode is handled by _process_email_template
        )
    except Exception as e:
        logger.error(f"Preview Error: Failed to prepare/render backup-code-used: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error generating preview: {str(e)}")