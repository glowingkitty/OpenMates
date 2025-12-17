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


def find_payment_by_invoice(
    service_instance: Any,
    invoice_id: str,
    client_id: Optional[str] = None
) -> Optional[str]:
    """
    Finds a payment in Invoice Ninja by invoice ID.
    
    When a payment is created, it's applied to an invoice. This function searches for
    the payment that was applied to the specified invoice.
    
    Args:
        service_instance: The instance of the main service class (InvoiceNinjaService).
        invoice_id: The hashed ID of the invoice to find the payment for.
        client_id: Optional client ID to narrow the search.
        
    Returns:
        The payment ID if found, None otherwise.
    """
    logger.info(f"Searching for payment by invoice ID: {invoice_id}")
    
    # Search for payments by invoice_id
    # Invoice Ninja API: GET /payments?invoice_id={invoice_id}
    search_params = {
        "invoice_id": invoice_id
    }
    
    # Optionally filter by client_id if provided
    if client_id:
        search_params["client_id"] = client_id
    
    response_data = service_instance.make_api_request('GET', '/payments', params=search_params)
    
    if response_data and 'data' in response_data:
        payments = response_data['data']
        if payments and len(payments) > 0:
            # Get the first matching payment (should be the original payment)
            # Payments are typically returned in reverse chronological order
            payment_id = payments[0].get('id')
            if payment_id:
                logger.info(f"Found payment: ID={payment_id} for invoice ID: {invoice_id}")
                return payment_id
            else:
                logger.warning(f"Payment found but missing ID for invoice ID: {invoice_id}")
        else:
            logger.warning(f"No payments found for invoice ID: {invoice_id}")
    else:
        logger.warning(f"Failed to search for payments by invoice ID: {invoice_id}")
    
    return None


def find_payment_by_transaction_reference(
    service_instance: Any,
    transaction_reference: str,
    client_id: Optional[str] = None
) -> Optional[str]:
    """
    Finds a payment in Invoice Ninja by transaction reference (external_order_id).
    
    When a payment is created, we store the external_order_id in the transaction_reference field.
    This function searches for the payment using that reference.
    
    Args:
        service_instance: The instance of the main service class (InvoiceNinjaService).
        transaction_reference: The external order ID (transaction reference) to search for.
        client_id: Optional client ID to narrow the search.
        
    Returns:
        The payment ID if found, None otherwise.
    """
    logger.info(f"Searching for payment by transaction reference: {transaction_reference}")
    
    # Search for payments by transaction_reference
    # Invoice Ninja API: GET /payments?transaction_reference={transaction_reference}
    search_params = {
        "transaction_reference": transaction_reference
    }
    
    # Optionally filter by client_id if provided
    if client_id:
        search_params["client_id"] = client_id
    
    response_data = service_instance.make_api_request('GET', '/payments', params=search_params)
    
    if response_data and 'data' in response_data:
        payments = response_data['data']
        if payments and len(payments) > 0:
            # Get the first matching payment
            payment_id = payments[0].get('id')
            if payment_id:
                logger.info(f"Found payment: ID={payment_id} for transaction reference: {transaction_reference}")
                return payment_id
            else:
                logger.warning(f"Payment found but missing ID for transaction reference: {transaction_reference}")
        else:
            logger.warning(f"No payments found for transaction reference: {transaction_reference}")
    else:
        logger.warning(f"Failed to search for payments by transaction reference: {transaction_reference}")
    
    return None


def find_payment_by_invoice_and_transaction_reference(
    service_instance: Any,
    invoice_id: str,
    transaction_reference: str,
    client_id: Optional[str] = None
) -> Optional[str]:
    """
    Finds a payment in Invoice Ninja by both invoice ID and transaction reference.
    
    This is the most reliable way to find the specific payment created for an invoice,
    as it matches both the invoice and the order ID (transaction_reference).
    
    Args:
        service_instance: The instance of the main service class (InvoiceNinjaService).
        invoice_id: The hashed ID of the invoice.
        transaction_reference: The external order ID (transaction reference) to search for.
        client_id: Optional client ID to narrow the search.
        
    Returns:
        The payment ID if found, None otherwise.
    """
    logger.info(f"Searching for payment by invoice ID: {invoice_id} and transaction reference: {transaction_reference}")
    
    # First, get all payments for the invoice
    search_params = {
        "invoice_id": invoice_id
    }
    
    if client_id:
        search_params["client_id"] = client_id
    
    response_data = service_instance.make_api_request('GET', '/payments', params=search_params)
    
    if response_data and 'data' in response_data:
        payments = response_data['data']
        if payments:
            # Filter payments to find the one with matching transaction_reference
            for payment in payments:
                payment_transaction_ref = payment.get('transaction_reference')
                if payment_transaction_ref == transaction_reference:
                    payment_id = payment.get('id')
                    if payment_id:
                        logger.info(f"Found payment: ID={payment_id} matching both invoice ID: {invoice_id} and transaction reference: {transaction_reference}")
                        return payment_id
                    else:
                        logger.warning(f"Payment found but missing ID for invoice ID: {invoice_id} and transaction reference: {transaction_reference}")
            
            logger.warning(f"No payment found matching both invoice ID: {invoice_id} and transaction reference: {transaction_reference}")
        else:
            logger.warning(f"No payments found for invoice ID: {invoice_id}")
    else:
        logger.warning(f"Failed to search for payments by invoice ID: {invoice_id}")
    
    return None


def refund_payment(
    service_instance: Any,
    payment_id: str,
    refund_amount: float,
    refund_date: str,
    invoice_id: str,
    email_receipt: bool = False
) -> bool:
    """
    Refunds a payment in Invoice Ninja using the /payments/refund endpoint.
    
    This is the correct way to process refunds in Invoice Ninja - it actually refunds the payment,
    returning money to the client, rather than just modifying the payment record.
    
    The endpoint is /payments/refund and the payment ID goes in the request body along with
    the invoice details.
    
    Args:
        service_instance: The instance of the main service class (InvoiceNinjaService).
        payment_id: The hashed ID of the payment to refund.
        refund_amount: The amount to refund (positive value, e.g., 10.00).
        refund_date: The refund date in "YYYY-MM-DD" format.
        invoice_id: The hashed ID of the invoice the payment was applied to.
        email_receipt: Whether to send an email notification to the client (default: False).
        
    Returns:
        True if successful, False otherwise.
    """
    logger.info(f"Attempting to refund payment ID: {payment_id}, Amount: {refund_amount}, Date: {refund_date}")
    
    # Invoice Ninja refund endpoint: POST /api/v1/payments/refund
    # The payment ID and invoice details go in the request body
    # Format matches what the Invoice Ninja UI sends:
    # {
    #   "id": "payment_id",
    #   "date": "2025-12-17",
    #   "invoices": [{"amount": 2, "invoice_id": "invoice_id", "id": ""}]
    # }
    payload: dict[str, Any] = {
        "id": payment_id,
        "date": refund_date,
        "invoices": [
            {
                "amount": refund_amount,
                "invoice_id": invoice_id,
                "id": ""  # Empty string as shown in the client request
            }
        ]
    }
    
    logger.debug(f"Refund payload: {payload}")
    
    # The endpoint is /payments/refund (not /payments/{id}/refund)
    # Add email_receipt query parameter if False (to prevent sending email)
    query_params = {}
    if not email_receipt:
        query_params["email_receipt"] = "false"
    
    response_data = service_instance.make_api_request('POST', '/payments/refund', params=query_params, data=payload)
    
    if response_data is not None:
        # The refund endpoint returns details of the refund
        logger.info(f"Successfully refunded payment: ID={payment_id}, Amount: {refund_amount}")
        return True
    else:
        logger.error(f"Failed to refund payment: ID={payment_id}")
        return False


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
    
    NOTE: This function is deprecated for refunds. Use refund_payment() instead to refund
    the original payment. This function may still be used for other credit note scenarios.
    
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