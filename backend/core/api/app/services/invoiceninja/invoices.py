# backend/core/api/app/services/invoiceninja/invoices.py
import logging
import os
import json
import requests # Keep requests import for exception handling
from typing import Optional, List, Dict, Any, Tuple

# Note: These functions are intended to be part of the InvoiceNinjaService class.
# They expect 'service_instance' (representing 'self') to provide:
# - service_instance.config (with attributes like INVOICE_NINJA_URL)
# - service_instance.headers
# - service_instance.make_api_request(method, endpoint, params=None, data=None)
# - service_instance._make_file_upload_request(endpoint, file_path) # A dedicated method for file uploads

logger = logging.getLogger(__name__)


def create_invoice(service_instance: Any, client_id: str, invoice_items: List[Dict[str, Any]], external_order_id: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Creates a new invoice using product_keys for items.

    Args:
        service_instance: The instance of the main service class.
        client_id: The ID of the client to create the invoice for.
        invoice_items: A list of dictionaries, each with "product_key" and "quantity".
        external_order_id: The external order ID for reference.

    Returns:
        A tuple containing the new invoice ID and invoice number if successful, otherwise (None, None).
    """
    logger.info(f"Attempting to create invoice for client ID {client_id}...")
    if not invoice_items:
        logger.error("Cannot create invoice without items.")
        return None, None

    # Ensure items use 'product_key' and 'quantity'
    formatted_items = []
    for item in invoice_items:
        if "product_key" not in item or "quantity" not in item:
            logger.error(f"Invoice item missing 'product_key' or 'quantity': {item}")
            return None, None
        # TODO: Add validation for placeholder product keys if needed, potentially using config
        # if not item["product_key"] or "YOUR_KEY_FOR" in item["product_key"]:
        #      logger.error(f"Invalid or placeholder product_key used: {item['product_key']}. Update configuration.")
        #      return None, None
        formatted_items.append({
            "product_key": item["product_key"],
            "quantity": item["quantity"]
            # Cost and notes will be pulled from the Product definition in IN
        })

    payload = {
        "client_id": client_id,
        "invoice_items": formatted_items,
        "private_notes": f"External Order ID: {external_order_id}" # Store order ID in notes too
    }

    response_data = service_instance.make_api_request('POST', '/invoices', data=payload)

    if response_data is not None and 'data' in response_data:
        new_invoice = response_data['data']
        invoice_id = new_invoice.get('id')
        invoice_number = new_invoice.get('number', 'N/A')
        if invoice_id:
            logger.info(f"Successfully created invoice (Draft): ID={invoice_id}, Number={invoice_number}")
            return invoice_id, invoice_number
        else:
            logger.error("Invoice creation response did not contain an ID.")
            return None, None
    else:
        logger.error("Failed to create invoice.")
        return None, None


def mark_invoice_sent(service_instance: Any, invoice_id: str) -> bool:
    """
    Updates the invoice status to mark it as sent (activates it).

    Args:
        service_instance: The instance of the main service class.
        invoice_id: The ID of the invoice to mark as sent.

    Returns:
        True if successful, False otherwise.
    """
    logger.info(f"Attempting to mark invoice ID {invoice_id} as sent...")
    endpoint = f'/invoices/{invoice_id}'
    payload = {"action": "mark_sent"}
    url = f"{service_instance.config.INVOICE_NINJA_URL}/api/v1{endpoint}" # Need full URL for direct requests call

    try:
        # Try PUT first (as per original script logic)
        # Note: Ideally, make_api_request handles method variations, but keeping original logic for now.
        response = requests.put(url, headers=service_instance.headers, data=json.dumps(payload), timeout=15)
        if response.status_code == 405: # Method Not Allowed, try POST
            logger.warning("PUT failed (405) for mark_sent, trying POST...")
            response = requests.post(url, headers=service_instance.headers, data=json.dumps(payload), timeout=15)

        response.raise_for_status()
        logger.info(f"Successfully marked invoice ID {invoice_id} as sent.")
        return True

    except requests.exceptions.HTTPError as http_err:
        logger.error(f"HTTP error occurred updating invoice: {http_err} - Status Code: {http_err.response.status_code}")
        try:
            logger.error(f"Error Details: {json.dumps(http_err.response.json(), indent=2)}")
        except json.JSONDecodeError:
            logger.error(f"Raw Error Response: {http_err.response.text}")
        return False
    except Exception as e:
        logger.exception(f"An unexpected error occurred marking invoice sent: {e}")
        return False


def upload_invoice_document(service_instance: Any, invoice_id: str, pdf_file_path: str) -> bool:
    """
    Uploads a custom PDF document to an existing invoice.

    Args:
        service_instance: The instance of the main service class.
        invoice_id: The ID of the invoice to upload the document to.
        pdf_file_path: The local path to the PDF file.

    Returns:
        True if successful, False otherwise.
    """
    logger.info(f"Attempting to upload document '{pdf_file_path}' to invoice ID {invoice_id}...")
    if not os.path.exists(pdf_file_path):
        logger.error(f"PDF file not found at '{pdf_file_path}'")
        return False

    endpoint = f'/invoices/{invoice_id}/upload'

    # Delegate the actual file upload mechanism to the service instance
    # This allows the service to handle headers and multipart logic correctly.
    # The service method should return True/False based on success.
    # We pass the endpoint and file path.
    success = service_instance._make_file_upload_request(endpoint, pdf_file_path)

    if success:
        logger.info(f"Successfully uploaded document to invoice ID {invoice_id}.")
    else:
        # Error logging should happen within _make_file_upload_request
        logger.error(f"Failed to upload document to invoice ID {invoice_id}.")

    return success