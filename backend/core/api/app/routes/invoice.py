from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import StreamingResponse
from backend.core.api.app.services.pdf.invoice import InvoiceTemplateService
from backend.core.api.app.utils.secrets_manager import SecretsManager
import io

router = APIRouter(
    prefix="/v1/invoice",
    tags=["invoice"]
)

# Create a single SecretsManager instance
secrets_manager = SecretsManager()
invoice_template_service = InvoiceTemplateService(secrets_manager=secrets_manager)

@router.post("/generate")
async def generate_invoice(request: Request, lang: str = Query("en"), currency: str = Query("eur")):
    try:
        invoice_data = await request.json()
        pdf_buffer = invoice_template_service.generate_invoice(invoice_data, lang, currency)
        
        # Create a filename based on the invoice number
        invoice_number = invoice_data.get('invoice_number', 'unknown')
        filename = f"openmates_invoice_{invoice_number}.pdf"
        
        return StreamingResponse(
            io.BytesIO(pdf_buffer.getvalue()), 
            media_type="application/pdf",
            headers={"Content-Disposition": f"inline; filename={filename}"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/preview")
async def preview_invoice(credits: int, lang: str = Query("en"), currency: str = Query("eur")):
    try:
        # Validate credits against the pricing tiers
        valid_credits = credits
        if invoice_template_service.pricing_tiers:
            valid_tier_credits = [tier.get('credits') for tier in invoice_template_service.pricing_tiers]
            if credits not in valid_tier_credits:
                # Choose the closest valid credits value
                valid_credits = min(valid_tier_credits, key=lambda x: abs(x - credits))
        
        # Dummy sender details for preview (in production, these come from secrets manager)
        invoice_data = {
            "invoice_number": "475D6855-004",
            "date_of_issue": "2025-03-15",  # ISO format
            "date_due": "2025-03-15",       # ISO format
            # Sender details (dummy data for preview)
            "sender_addressline1": "OpenMates GmbH",
            "sender_addressline2": "Musterstraße 123",
            "sender_addressline3": "12345 Berlin",
            "sender_country": "Germany",
            "sender_email": "support@openmates.org",
            "sender_vat": "DE123456789",
            # Receiver details (dummy data for preview)
            "receiver_account_id": "ACC-12345678",
            "receiver_name": "John Doe",
            "receiver_address": "Sample Street 45",
            "receiver_city": "10115 Berlin",
            "receiver_country": "Germany",
            "receiver_email": "user@example.com",
            # Invoice details
            "credits": valid_credits,
            "card_name": "Visa",
            "card_last4": "1234",
            # Note: qr_code_url removed - view usage section is hidden until usage settings menu is implemented
        }
        
        pdf_buffer = invoice_template_service.generate_invoice(invoice_data, lang, currency)
        
        # Create a preview filename using the sample invoice number
        filename = f"openmates-invoice-2025-03-15-U475D6855-I001.pdf"
        
        return StreamingResponse(
            io.BytesIO(pdf_buffer.getvalue()),
            media_type="application/pdf",
            headers={"Content-Disposition": f"inline; filename={filename}"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
