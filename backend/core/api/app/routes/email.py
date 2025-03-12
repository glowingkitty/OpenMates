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
):
    """
    Preview an email template with specified parameters
    
    Args:
        template_name: Name of the email template to render
        lang: Language code for translations
        darkmode: Whether to use dark mode styling
        code: Verification code or token to include in the email
        
    Returns:
        Rendered HTML email
    """
    try:
        # Start with empty context
        context = {}
        
        # Add specific parameters to context
        context["code"] = code
        
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
            if key not in ['darkmode', 'code', 'lang']:
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
