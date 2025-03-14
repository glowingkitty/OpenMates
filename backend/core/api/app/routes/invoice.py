from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import StreamingResponse
from app.services.invoice_template import InvoiceTemplateService
import io

router = APIRouter(prefix="/v1/invoice", tags=["invoice"])
invoice_template_service = InvoiceTemplateService()

@router.post("/generate")
async def generate_invoice(request: Request, lang: str = Query("en")):
    try:
        invoice_data = await request.json()
        pdf_buffer = invoice_template_service.generate_invoice(invoice_data, lang)
        return StreamingResponse(io.BytesIO(pdf_buffer.getvalue()), media_type="application/pdf")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/preview")
async def preview_invoice(credits: int, lang: str = Query("en")):
    try:
        invoice_data = {
            "invoice_number": "475D6855-004",
            "date_of_issue": "2025-03-15",  # ISO format
            "date_due": "2025-03-15",       # ISO format
            "receiver_name": "Name Nachname",
            "receiver_address": "Musterstraße 31",
            "receiver_city": "10990 Hamburg",
            "receiver_country": "Germany",
            "receiver_email": "user@domain.com",
            "receiver_vat": "DE9882931",
            "qr_code_url": "https://app.openmates.org/settings/usage",
            "credits": credits,
            "unit_price": credits / 1000,
            "total_price": credits / 1000,
            "card_name": "Visa",
            "card_last4": "XXXX"
        }
        pdf_buffer = invoice_template_service.generate_invoice(invoice_data, lang)
        return StreamingResponse(io.BytesIO(pdf_buffer.getvalue()), media_type="application/pdf")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
