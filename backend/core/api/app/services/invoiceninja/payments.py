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
                "invoice_id": invoice_id,
                "amount": amount
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


def create_credit_payment(
    service_instance: Any,
    client_id: str,
    amount: float,
    date: str,
    credit_id: str,
    invoice_id: Optional[str] = None,
    payment_type: Optional[str] = None,
    transaction_reference: Optional[str] = None
) -> Optional[str]:
    """
    Creates a payment record in Invoice Ninja for a credit note (refund).
    
    The payment is applied to the credit note using the credits array.
    The payment amount should equal the sum of applied credits amounts.
    The credit note must be marked as "Sent" before this payment can be created.
    
    Args:
        service_instance: The instance of the main service class (InvoiceNinjaService).
        client_id: The hashed ID of the client receiving the refund.
        amount: The refund amount (positive value, e.g., 10.00).
        date: The payment date in "YYYY-MM-DD" format.
        credit_id: The hashed ID of the credit note being refunded.
        invoice_id: Optional invoice ID (not used - payment is applied directly to credit).
        payment_type: Optional name of payment type (Visa Card, MasterCard, American Express, Debit)
        transaction_reference: Optional transaction reference (e.g., from payment gateway).

    Returns:
        The new payment ID if successful, None otherwise.
    """
    logger.info(f"Attempting to create refund payment for client ID {client_id}, credit note ID {credit_id}...")

    # Create payment applied to the credit note
    # The payment amount should equal the credit amount (for full refund)
    # Use positive amount - Invoice Ninja handles the refund direction
    payment_amount = abs(amount)  # Positive amount
    
    # Create payment payload with credits array
    # Use credit_id (not id) as per Invoice Ninja API specification
    payload: dict[str, Any] = {
        "client_id": client_id,
        "amount": str(payment_amount),  # Payment amount equals credit amount
        "date": date,
        # Apply payment to the credit note
        "credits": [
            {
                "credit_id": credit_id,  # Use credit_id (not id) as per API spec
                "amount": payment_amount  # Amount should equal payment.amount
            }
        ],
        # Optional bookkeeping fields
        "private_notes": f"Refund for credit note {credit_id}",
        "is_manual": True  # Mark as manual payment
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

    logger.debug(f"Credit payment payload (applied to credit): {payload}")
    # Use email_receipt=false query parameter to prevent Invoice Ninja from sending payment receipt email
    query_params = {"email_receipt": False}
    response_data = service_instance.make_api_request('POST', '/payments', params=query_params, data=payload)

    if response_data is not None and 'data' in response_data:
        new_payment = response_data['data']
        payment_id = new_payment.get('id')
        if payment_id:
            logger.info(f"Successfully created refund payment: ID={payment_id} (applied to credit note {credit_id})")
            return payment_id
        else:
            logger.error("Credit payment creation response did not contain an ID.")
            return None
    else:
        logger.error("Failed to create credit payment.")
        return None