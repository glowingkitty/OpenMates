# backend/core/api/app/services/invoiceninja/payments.py
import logging
from typing import Optional, Any

# Note: This function is intended to be part of the InvoiceNinjaService class.
# It expects 'service_instance' (representing 'self') to provide:
# - service_instance.make_api_request(method, endpoint, params=None, data=None)
# - Potentially service_instance.config if payment type IDs are stored there

logger = logging.getLogger(__name__)


def create_payment(
    service_instance: Any,
    client_id: str,
    amount: float,
    date: str,
    invoice_id: str, # Assuming single invoice payment for now based on original structure
    invoice_amount: Optional[float] = None, # Amount specific to this invoice payment
    client_contact_id: Optional[str] = None,
    user_id: Optional[str] = None,
    type_id: Optional[str] = None,
    transaction_reference: Optional[str] = None,
    assigned_user_id: Optional[str] = None,
    private_notes: Optional[str] = None,
    credits: Optional[list[dict[str, str]]] = None,
    payment_number: Optional[str] = None
) -> Optional[str]:
    """
    Creates a payment record in Invoice Ninja based on provided details.

    Args:
        service_instance: The instance of the main service class (InvoiceNinjaService).
        client_id: The hashed ID of the client making the payment.
        amount: The total payment amount (as a string or float).
        date: The payment date in "YYYY-MM-DD" format.
        invoice_id: The hashed ID of the primary invoice being paid.
        invoice_amount: The amount to apply specifically to the invoice_id. Defaults to total amount if None.
        client_contact_id: Optional hashed ID of the client contact.
        user_id: Optional hashed ID of the user creating the payment.
        type_id: Optional enum ID for the payment type.
        transaction_reference: Optional transaction reference (e.g., from payment gateway).
        assigned_user_id: Optional hashed ID of the user assigned to this payment.
        private_notes: Optional private notes for the payment.
        credits: Optional list of credits to apply, each a dict with 'credit_id' and 'amount'.
        payment_number: Optional unique alpha-numeric number for the payment.

    Returns:
        The new payment ID if successful, otherwise None.
    """
    logger.info(f"Attempting to create payment for client ID {client_id}, invoice ID {invoice_id}...")

    # Determine the amount to apply to the specified invoice
    invoice_payment_amount = str(invoice_amount) if invoice_amount is not None else str(amount)

    payload: dict[str, Any] = {
        "client_id": client_id,
        "amount": str(amount), # Total payment amount
        "date": date,
        # Structure for applying payment to specific invoices
        "invoices": [
            {
                "invoice_id": invoice_id,
                "amount": invoice_payment_amount
            }
        ]
    }

    # Add optional fields if they are provided
    if client_contact_id:
        payload["client_contact_id"] = client_contact_id
    if user_id:
        payload["user_id"] = user_id
    if type_id:
        # TODO: Add validation if needed, e.g., check against config values
        payload["type_id"] = str(type_id)
    else:
        logger.warning("Payment Type ID (type_id) is not provided. Creating payment without type.")
    if transaction_reference:
        payload["transaction_reference"] = transaction_reference
    if assigned_user_id:
        payload["assigned_user_id"] = assigned_user_id
    if private_notes:
        payload["private_notes"] = private_notes
    if credits:
        # Ensure credit amounts are strings
        validated_credits = [
            {"credit_id": c.get("credit_id"), "amount": str(c.get("amount"))}
            for c in credits if c.get("credit_id") and c.get("amount") is not None
        ]
        if validated_credits:
            payload["credits"] = validated_credits
    if payment_number:
        payload["number"] = payment_number

    logger.debug(f"Payment payload: {payload}")
    response_data = service_instance.make_api_request('POST', '/payments', data=payload)

    if response_data is not None and 'data' in response_data:
        new_payment = response_data['data']
        payment_id = new_payment.get('id')
        if payment_id:
            logger.info(f"Successfully created payment: ID={payment_id}")
            return payment_id
        else:
            logger.error("Payment creation response did not contain an ID.")
            return None
    else:
        logger.error("Failed to create payment.")
        return None