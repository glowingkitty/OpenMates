from fastapi import APIRouter, Query, HTTPException, Request
from fastapi.responses import HTMLResponse
import logging

from app.services.email_template import EmailTemplateService

router = APIRouter(prefix="/v1/email", tags=["email"])
logger = logging.getLogger(__name__)
email_template_service = EmailTemplateService()

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
        for key, value in request.query_params.items():
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