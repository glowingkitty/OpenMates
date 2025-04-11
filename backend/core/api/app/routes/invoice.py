from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import StreamingResponse
from app.services.pdf.invoice import InvoiceTemplateService
import io

router = APIRouter(
    prefix="/v1/invoice",
    tags=["invoice"]
)
invoice_template_service = InvoiceTemplateService()

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
        
        invoice_data = {
            "invoice_number": "475D6855-004",
            "date_of_issue": "2025-03-15",  # ISO format
            "date_due": "2025-03-15",       # ISO format
            "receiver_name": "Name Nachname",
            # "receiver_address": "Musterstraße 31",
            # "receiver_city": "10990 Hamburg",
            # "receiver_country": "Germany",
            "receiver_email": "user@domain.com",
            # "receiver_vat": "DE9882931",
            "qr_code_url": "https://app.openmates.org/settings/usage",
            "credits": valid_credits,
            "card_name": "Visa",
            "card_last4": "1234"
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