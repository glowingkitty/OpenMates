from fastapi import APIRouter, Query, HTTPException, Request
from fastapi.responses import HTMLResponse
import logging

from app.services.email_template import EmailTemplateService

router = APIRouter(prefix="/v1/email", tags=["email"])
logger = logging.getLogger(__name__)
email_template_service = EmailTemplateService()

@router.get("/{template_name}", response_class=HTMLResponse)
async def preview_email_template(
    request: Request,
    template_name: str,
    lang: str = Query("en", description="Language code for translations"),
    darkmode: bool = Query(False, description="Enable dark mode for the email"),
    code: str = Query(None, description="Verification code or token"),
    refund_link: str = Query(None, description="Custom refund link URL"),
    mailto_link_report_email: str = Query(None, description="Custom report email link"),
    device: str = Query(None, description="Device type"),
    os_with_version: str = Query(None, description="Operating system with version"),
    count: str = Query(None, description="Count of items"),
    logout_link_delete_invite_codes: str = Query(None, description="Logout and delete invite codes link"),
):
    """
    Preview an email template with specified parameters
    
    Args:
        template_name: Name of the email template to render
        lang: Language code for translations
        darkmode: Whether to use dark mode styling
        code: Verification code or token to include in the email (optional)
        refund_link: Custom refund link (defaults to support email if not provided)
        mailto_link_report_email: Custom report email link (defaults to support email if not provided)
        device: Device type (optional)
        os_with_version: Operating system version (optional)
        count: Count of items (optional)
        logout_link_delete_invite_codes: Logout and delete invite codes link (optional)
        
    Returns:
        Rendered HTML email
    """
    try:
        # Start with empty context
        context = {}
        
        # Add specific parameters to context
        context["code"] = code
        context["refund_link"] = refund_link
        context["mailto_link_report_email"] = mailto_link_report_email
        context["device"] = device
        context["os_with_version"] = os_with_version
        context["count"] = count
        context["logout_link_delete_invite_codes"] = logout_link_delete_invite_codes
        
        # Handle darkmode parameter specifically
        # Get the raw query param value to check what was actually passed
        raw_darkmode = request.query_params.get('darkmode', 'false').lower()
        logger.debug(f"Raw darkmode value: {raw_darkmode}")
        
        # Convert string to boolean
        parsed_darkmode = raw_darkmode == 'true'
        logger.debug(f"Parsed darkmode value: {parsed_darkmode}")
        
        # Use the parsed value in the context
        context["darkmode"] = parsed_darkmode
        
        # Add any other query parameters that might be needed
        for key, value in request.query_params.items():
            if key not in ['darkmode', 'code', 'lang', 'refund_link', 
                          'mailto_link_report_email', 'device', 
                          'os_with_version', 'count', 
                          'logout_link_delete_invite_codes']:
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
