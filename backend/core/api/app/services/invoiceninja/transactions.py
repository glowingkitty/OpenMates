# backend/core/api/app/services/invoiceninja/transactions.py
import logging
from typing import Optional, Any

# Note: This function is intended to be part of the InvoiceNinjaService class.
# It expects 'service_instance' (representing 'self') to provide:
# - service_instance.make_api_request(method, endpoint, params=None, data=None)

logger = logging.getLogger(__name__)


def create_bank_transaction(service_instance: Any, processor_bank_account_id: str, bank_integration_id: int, amount: float, date_str: str, invoice_number: str, external_order_id: str) -> Optional[str]:
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

    Returns:
        The new bank transaction ID if successful, otherwise None.
    """
    logger.info(f"Attempting to create bank transaction in account ID {processor_bank_account_id}...")
    # TODO: Add validation for processor_bank_account_id if needed, potentially using config
    # if not processor_bank_account_id or "YOUR_" in processor_bank_account_id:
    #      logger.error("Invalid or placeholder Processor Bank Account ID provided. Cannot create bank transaction.")
    #      return None

    description = f"Payment received - Invoice {invoice_number}, Order {external_order_id}"

    payload = {
        "bank_account_id": processor_bank_account_id, # API uses bank_account_id
        "bank_integration_id": bank_integration_id, # Needs to be passed in or determined via config
        "amount": str(amount), # Positive for deposit
        "date": date_str,
        "description": description,
        # Note: The original script incorrectly used 'id' instead of 'bank_account_id' in the payload. Corrected here.
        # Note: The original script hardcoded STRIPE_BANK_INTEGRATION_ID. This should be dynamic.
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