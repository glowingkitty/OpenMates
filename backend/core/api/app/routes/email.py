from fastapi import APIRouter, Query, HTTPException, Request
from fastapi.responses import HTMLResponse
import logging
# httpx no longer needed here for map image
from datetime import datetime, timezone

from backend.core.api.app.services.email_template import EmailTemplateService
from backend.core.api.app.services.translations import TranslationService # Import TranslationService
from backend.core.api.app.utils.device_fingerprint import generate_device_fingerprint_hash
from backend.core.api.app.utils.email_context_helpers import prepare_new_device_login_context, generate_report_access_mailto_link

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
        
        # Render the email template using the service from backend.core.api.app.state
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
    username: str = Query("User", description="Username to display in the email"),
    email: str = Query("preview@example.com", description="Email address for blocklist link")
):
    """
    Preview the email confirmation template
    """
    return await _process_email_template(
        request=request,
        template_name="confirm-email",
        lang=lang,
        code=code,
        username=username,
        recipient_email=email  # Use recipient_email as it's the standard field name for blocklist URL generation
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
        # Note: generate_device_fingerprint_hash extracts IP from request headers primarily.
        # The ip_address query param is less reliable but kept for potential logging/context.
        # We'll use the fingerprint object for location data.
        # For preview, we don't have a user_id, so use a placeholder.
        device_hash, connection_hash, os_name, country_code, city, region, latitude, longitude = generate_device_fingerprint_hash(request, user_id="preview_user")
        
        # Construct location name similar to how it's done in auth_2fa_verify
        location_name = f"{city}, {country_code}" if city and country_code else country_code or "Unknown"
        is_localhost = country_code == "Local" and city == "Local Network"
        logger.info(f"Preview fingerprint location data: lat={latitude}, lon={longitude}, name={location_name}, is_localhost={is_localhost}")

        # --- Prepare Context using Helper Function ---
        # Pass the determined location data explicitly
        context = await prepare_new_device_login_context(
            user_agent_string=user_agent_string,
            ip_address=ip_address, # Still pass IP for potential logging inside helper
            account_email=account_email,
            language=lang,
            darkmode=darkmode, # Pass darkmode from query param
            translation_service=request.app.state.email_template_service.translation_service, # Use service from backend.core.api.app.state
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
        local_translation_service = translation_service # Use the one from backend.core.api.app.state for preview

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


@router.get("/recovery-key-used", response_class=HTMLResponse)
async def preview_recovery_key_used(
    request: Request,
    lang: str = Query("en", description="Language code for translations"),
    darkmode: bool = Query(False, description="Enable dark mode for the email"),
    account_email: str = Query("preview@example.com", description="Account email address for mailto link")
):
    """
    Preview the recovery code used email template.
    Generates the mailto link dynamically for the preview.
    Note: No actual recovery code is displayed in the email for security reasons.
    """
    # Access services from request.app.state for consistency
    translation_service: TranslationService = request.app.state.email_template_service.translation_service

    try:
        # Use the translation service from app.state for preview
        local_translation_service = translation_service

        # Prepare details for the mailto link helper
        login_time_str = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S %Z')
        report_details = {
            "login_time": login_time_str,
            "recovery_key": "****"  # Don't include actual code for security
        }

        # Generate the mailto link using the helper
        logout_link = await generate_report_access_mailto_link(
            translation_service=local_translation_service,
            language=lang,
            account_email=account_email,  # Use email from query param
            report_type='recovery_key',
            details=report_details
        )

        if not logout_link:
            logger.error("Failed to generate mailto link for recovery code used")
            raise HTTPException(status_code=500, detail="Failed to generate mailto link")

        # Call the main rendering helper, accessing services via request
        return await _process_email_template(
            request=request,  # Pass request to access app.state inside helper
            template_name="recovery-key-was-used",
            lang=lang,
            logout_link=logout_link  # Pass the generated mailto link
            # darkmode is handled by _process_email_template
            # No code parameter since we don't display it
        )
    except Exception as e:
        logger.error(f"Preview Error: Failed to prepare/render recovery-key-used: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error generating preview: {str(e)}")


@router.get("/newsletter-confirmation-request", response_class=HTMLResponse)
async def preview_newsletter_confirmation_request(
    request: Request,
    lang: str = Query("en", description="Language code for translations"),
    darkmode: bool = Query(False, description="Enable dark mode for the email"),
    confirmation_token: str = Query("sample-token-12345", description="Confirmation token for the subscription link"),
    email: str = Query("preview@example.com", description="Email address for block-email link")
):
    """
    Preview the newsletter confirmation request email template.
    """
    import os
    from urllib.parse import quote
    
    try:
        # Get base URL for confirmation links from shared config
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
        encoded_email = quote(email.lower().strip())
        block_email_url = f"{base_url}/#settings/email/block/{encoded_email}"
        
        return await _process_email_template(
            request=request,
            template_name="newsletter-confirmation-request",
            lang=lang,
            confirm_url=confirm_url,
            unsubscribe_url=block_email_url  # Use block-email URL instead of newsletter unsubscribe
        )
    except Exception as e:
        logger.error(f"Preview Error: Failed to prepare/render newsletter-confirmation-request: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error generating preview: {str(e)}")


@router.get("/newsletter-confirmed", response_class=HTMLResponse)
async def preview_newsletter_confirmed(
    request: Request,
    lang: str = Query("en", description="Language code for translations"),
    darkmode: bool = Query(False, description="Enable dark mode for the email")
):
    """
    Preview the newsletter confirmed email template.
    """
    import os
    
    try:
        # Get social media links (from environment or defaults)
        instagram_url = "https://instagram.com/openmates_official"
        mastodon_url = "https://mastodon.social/@openmates"
        
        return await _process_email_template(
            request=request,
            template_name="newsletter-confirmed",
            lang=lang,
            instagram_url=instagram_url,
            mastodon_url=mastodon_url
        )
    except Exception as e:
        logger.error(f"Preview Error: Failed to prepare/render newsletter-confirmed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error generating preview: {str(e)}")
