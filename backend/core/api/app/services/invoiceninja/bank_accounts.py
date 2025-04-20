# backend/core/api/app/services/invoiceninja/bank_accounts.py
import logging
from typing import Optional, Any, List, Dict

# Note: This function is intended to be part of the InvoiceNinjaService class.
# It expects 'service_instance' (representing 'self') to provide:
# - service_instance.make_api_request(method, endpoint, params=None, data=None)

logger = logging.getLogger(__name__)


def get_bank_integrations(service_instance: Any, params: Optional[Dict[str, Any]] = None) -> Optional[List[Dict[str, Any]]]:
    """
    Retrieves a list of bank integrations from Invoice Ninja.

    Docs:
    https://api-docs.invoicing.co/#tag/bank_integrations

    Corresponds to GET /api/v1/bank_integrations

    Args:
        service_instance: The instance of the main service class.
        params: Optional dictionary of query parameters for the API request (e.g., filtering).

    Returns:
        A list of bank integration dictionaries if successful, otherwise None.
        Returns an empty list if no integrations are found but the request was successful.

        The structure of each dictionary in the returned list (within the 'data' key of the response):
        [
            {
                "id": "string",  # The bank integration hashed id
                "user_id": "string",  # The user hashed id
                "provider_bank_name": "string",  # The provider's bank name
                "bank_account_id": "string",  # The bank account id
                "bank_account_name": "string",  # The name of the account
                "bank_account_number": "string",  # The account number
                "bank_account_status": "string",  # The status of the bank account
                "bank_account_type": "string",  # The type of account
                "balance": "number",  # The current bank balance if available
                "currency": "string",  # ISO 3166-3 code
            },
            ...
        ]
        The full response also includes a 'meta' object with pagination details.
    """
    logger.info("Attempting to retrieve bank integrations...")
    response_data = service_instance.make_api_request('GET', '/bank_integrations', params=params)

    if response_data is not None and 'data' in response_data:
        integrations = response_data['data']
        logger.info(f"Successfully retrieved {len(integrations)} bank integration(s).")
        return integrations # Will be an empty list if none found
    else:
        logger.error("Failed to retrieve bank integrations or unexpected response structure.")
        return None