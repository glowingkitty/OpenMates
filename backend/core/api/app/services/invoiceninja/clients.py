# backend/core/api/app/services/invoiceninja/clients.py
import logging
from typing import Optional, Dict, Any

# Note: These functions are intended to be part of the InvoiceNinjaService class.
# They expect 'service_instance' (representing 'self') to provide:
# - service_instance.config (with attributes like USER_HASH_CUSTOM_FIELD, ORDER_ID_CUSTOM_FIELD)
# - service_instance.make_api_request(method, endpoint, params=None, data=None)

logger = logging.getLogger(__name__)


def find_client_by_hash(service_instance: Any, user_hash: str) -> Optional[str]:
    """
    Searches for an existing client using the hash in the custom field.

    Args:
        service_instance: The instance of the main service class.
        user_hash: The user hash to search for.

    Returns:
        The client ID if found, otherwise None.
    """
    logger.info(f"Searching for client...")
    params = {
        'filter': user_hash,  # Use the broad filter for searching by hash
        'status': 'active'  # Add filter to only search for active clients
    }
    response_data = service_instance.make_api_request('GET', '/clients', params=params)

    if response_data is not None and 'data' in response_data:
        clients = response_data['data']
        if len(clients) > 0:
            client_id = clients[0]['id']
            logger.info(f"Found existing client'")
            return client_id
        else:
            logger.info("Client not found with this hash.")
            return None
    else:
        logger.error("Failed to search for client or unexpected response structure.")
        return None


def create_client(service_instance: Any, user_hash: str, external_order_id: str, client_details: Dict[str, Any]) -> Optional[str]:
    """
    Creates a new client, storing the hash and order ID in custom fields.

    Args:
        service_instance: The instance of the main service class.
        user_hash: The unique hash for the user.
        external_order_id: The external order ID (e.g., from Stripe/Revolut).
        client_details: A dictionary containing client information (e.g., name, contacts).

    Returns:
        The new client ID if successful, otherwise None.
    """
    logger.info(f"Attempting to create new client for hash {user_hash}...")
    # Prepare contact details
    contact = {
        "first_name": client_details.get("first_name", ""),
        "last_name": client_details.get("last_name", ""),
        "email": client_details.get("email", "")
    }
    # Ensure email is added if it's a primary identifier or required
    if "email" in client_details:
        contact["email"] = client_details.get("email")


    payload = {
        "name": client_details.get("name", f"{contact['first_name']} {contact['last_name']}".strip() or f"Client {user_hash[:8]}"),
        "contacts": [contact], # Ensure contacts is a list containing the contact object
        "country_id": client_details.get("country_id"), # Add country_id
        # Add other client details if available, ensuring required fields are present
        # Example: "address1": client_details.get("address1", ""), "city": client_details.get("city", ""), etc.
        service_instance.USER_HASH_CUSTOM_FIELD: user_hash,
        service_instance.ORDER_ID_CUSTOM_FIELD: external_order_id # Store order ID here too
    }
    # Remove country_id if it's None, as the API might require an integer
    if payload["country_id"] is None:
        del payload["country_id"]
        logger.warning(f"country_id not provided for client hash {user_hash}. It's a required field.")

    response_data = service_instance.make_api_request('POST', '/clients', data=payload)

    if response_data is not None and 'data' in response_data:
        new_client = response_data['data']
        client_id = new_client.get('id')
        if client_id:
            logger.info(f"Successfully created client: ID={client_id}")
            return client_id
        else:
            logger.error("Client creation response did not contain an ID.")
            return None
    else:
        logger.error("Failed to create client.")
        return None