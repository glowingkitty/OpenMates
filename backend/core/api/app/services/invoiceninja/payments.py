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
    invoice_id: str,
    payment_type: Optional[str] = None,
    transaction_reference: Optional[str] = None
) -> Optional[str]:
    """
    Creates a payment record in Invoice Ninja based on provided details.

    Args:
        service_instance: The instance of the main service class (InvoiceNinjaService).
        client_id: The hashed ID of the client making the payment.
        amount: The total payment amount (as a string or float).
        date: The payment date in "YYYY-MM-DD" format.
        invoice_id: The hashed ID of the primary invoice being paid.
        payment_type: Optional name of payment type (Visa Card, MasterCard, American Express, Debit)
        transaction_reference: Optional transaction reference (e.g., from payment gateway).

    Returns:
        The new payment ID if successful, otherwise None.
    """
    logger.info(f"Attempting to create payment for client ID {client_id}, invoice ID {invoice_id}...")

    payload: dict[str, Any] = {
        "client_id": client_id,
        "amount": str(amount), # Total payment amount
        "date": date,
        # Structure for applying payment to specific invoices
        "invoices": [
            {
                "invoice_id": invoice_id
            }
        ]
    }

    # Add optional fields if they are provided
    payment_types = {
        "American Express": 7,
        "Visa Card": 5,
        "MasterCard": 6,
        "Debit": 3
    }
    if payment_type:
        payload["type_id"] = payment_types[payment_type]
    else:
        logger.warning("Payment Type ID (type_id) is not provided. Creating payment without type.")
    if transaction_reference:
        payload["transaction_reference"] = transaction_reference
    if credits:
        # Ensure credit amounts are strings
        validated_credits = [
            {"credit_id": c.get("credit_id"), "amount": str(c.get("amount"))}
            for c in credits if c.get("credit_id") and c.get("amount") is not None
        ]
        if validated_credits:
            payload["credits"] = validated_credits

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