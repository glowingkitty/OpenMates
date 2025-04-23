# backend/core/api/app/services/invoiceninja/transactions.py
import logging
from typing import Optional, Any

# Note: This function is intended to be part of the InvoiceNinjaService class.
# It expects 'service_instance' (representing 'self') to provide:
# - service_instance.make_api_request(method, endpoint, params=None, data=None)

logger = logging.getLogger(__name__)


def create_bank_transaction(
        service_instance: Any,
        processor_bank_account_id: str,
        bank_integration_id: int,
        amount: float,
        date_str: str,
        invoice_number: str,
        external_order_id: str,
        base_type: str,
        currency_code: str
        ) -> Optional[str]:
    """
    Creates a bank transaction record in the specified processor bank account.

    Args:
        service_instance: The instance of the main service class.
        processor_bank_account_id: The Invoice Ninja ID of the bank account (e.g., Stripe, Revolut).
        bank_integration_id: The ID of the bank integration associated with the account.
        amount: The transaction amount (positive for deposit).
        date_str: The transaction date in "YYYY-MM-DD" format.
        invoice_number: The related invoice number for the description.
        external_order_id: The external order ID for the description.
        base_type: DEBIT or CREDIT

    Returns:
        The new bank transaction ID if successful, otherwise None.
    """
    logger.info(f"Attempting to create bank transaction in account ID {processor_bank_account_id}...")

    description = f"Payment received - Invoice {invoice_number}, Order {external_order_id}"

    payload = {
        "bank_account_id": processor_bank_account_id, # API uses bank_account_id
        "bank_integration_id": bank_integration_id, # Needs to be passed in or determined via config
        "amount": amount,
        "date": date_str,
        "description": description,
        "base_type": base_type,
        "currency_code": currency_code
    }

    response_data = service_instance.make_api_request('POST', '/bank_transactions', data=payload)

    if response_data is not None and 'data' in response_data:
        new_transaction = response_data['data']
        transaction_id = new_transaction.get('id')
        if transaction_id:
            logger.info(f"Successfully created bank transaction: ID={transaction_id}")
            return transaction_id
        else:
            logger.error("Bank transaction creation response did not contain an ID.")
            return None
    else:
        logger.error("Failed to create bank transaction.")
        return None
        
def match_transaction_to_payment(service_instance: Any, transaction_id: str, payment_id: str) -> bool:
    """
    Matches a bank transaction to an existing payment in Invoice Ninja.

    Args:
        service_instance: The instance of the main service class.
        transaction_id: The HASHED ID of the bank transaction to match.
        payment_id: The HASHED ID of the payment to link the transaction to.

    Returns:
        True if the matching was successful, False otherwise.
    """
    logger.info(f"Attempting to match bank transaction ID {transaction_id} to payment ID {payment_id}...")

    endpoint = '/bank_transactions/match'
    # Assuming the API supports matching via payment_id
    payload = {
        "transactions": [
            {
                "id": transaction_id,
                "payment_id": payment_id # Assuming this key is supported by the API
            }
        ]
    }

    response_data = service_instance.make_api_request('POST', endpoint, data=payload)

    # The match endpoint might return 200 OK with data or just 200/204 on success without specific data
    if response_data is not None:
        # Consider it successful if the API call itself didn't return None (error).
        logger.info(f"Successfully requested matching for transaction {transaction_id} to payment {payment_id}.")
        # Add more specific success checks based on the actual API response if needed.
        return True
    else:
        logger.error(f"Failed to match bank transaction {transaction_id} to payment {payment_id}.")
        return False