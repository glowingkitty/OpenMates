from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import StreamingResponse
from backend.core.api.app.services.pdf.credit_note import CreditNoteTemplateService
import io

router = APIRouter(
    prefix="/v1/credit-note",
    tags=["credit-note"]
)
credit_note_template_service = CreditNoteTemplateService()

@router.post("/generate")
async def generate_credit_note(request: Request, lang: str = Query("en"), currency: str = Query("eur")):
    try:
        credit_note_data = await request.json()
        pdf_buffer = credit_note_template_service.generate_credit_note(credit_note_data, lang, currency)
        
        # Create a filename based on the credit note number
        credit_note_number = credit_note_data.get('credit_note_number', 'unknown')
        filename = f"openmates_credit_note_{credit_note_number}.pdf"
        
        return StreamingResponse(
            io.BytesIO(pdf_buffer.getvalue()), 
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/preview")
async def preview_credit_note(
    total_credits: int, 
    unused_credits: int, 
    lang: str = Query("en"), 
    currency: str = Query("eur"),
    refund_amount: float = Query(None, description="Optional manual override for the refund amount")
):
    try:
        # Ensure that unused_credits is not greater than total_credits
        if unused_credits > total_credits:
            unused_credits = total_credits
        
        # Validate credits against the pricing tiers
        valid_total_credits = total_credits
        if credit_note_template_service.pricing_tiers:
            valid_tier_credits = [tier.get('credits') for tier in credit_note_template_service.pricing_tiers]
            if total_credits not in valid_tier_credits:
                # Choose the closest valid credits value
                valid_total_credits = min(valid_tier_credits, key=lambda x: abs(x - total_credits))
        
        credit_note_data = {
            "credit_note_number": "CN-475D6855-004",
            "date_of_issue": "2025-03-15",  # ISO format
            "referenced_invoice": "475D6855-004", # The original invoice number
            "receiver_name": "Name Nachname",
            # "receiver_address": "Musterstraße 31",
            # "receiver_city": "10990 Hamburg",
            # "receiver_country": "Germany",
            "receiver_email": "user@domain.com",
            # "receiver_vat": "DE9882931",
            "qr_code_url": "https://openmates.org/settings/usage",
            "total_credits": valid_total_credits,
            "unused_credits": unused_credits,
            "card_name": "Visa",
            "card_last4": "1234"
        }
        
        # Add manual refund amount if provided
        if refund_amount is not None:
            credit_note_data['manual_refund_amount'] = refund_amount
        
        pdf_buffer = credit_note_template_service.generate_credit_note(credit_note_data, lang, currency)
        
        # Create a preview filename using the sample credit note number
        filename = f"openmates-credit-note-2025-03-15-U475D6855-CN001.pdf"
        
        return StreamingResponse(
            io.BytesIO(pdf_buffer.getvalue()),
            media_type="application/pdf",
            headers={"Content-Disposition": f"inline; filename={filename}"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
